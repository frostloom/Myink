"""Retrospective projection of independently accepted finite manager runs.

No candidate imports, model requests, adoption or ledger transactions occur here.
The host owns the acceptance receipt; audit_only is never execution authority.
"""
from datetime import datetime,timezone
from hashlib import sha256
import os
from pathlib import Path
from ops.pi.audit import AuditStore,_path,_plain,digest,hash_value,name,require,strict_json,validate_record

FIXED_FILES=('bundle/selection-output/result.json','development-output/result.json',
             'development-output/phase-verification.json','development-output/check-2-receipt.json','development-entry-review.json')


def _read(root,relative):
    p=_path(root/relative);_plain(p)
    require(p.stat().st_size<=1048576,'bounded import receipt required')
    raw=p.read_bytes();require(len(raw)<=1048576)
    value=strict_json(raw);require(isinstance(value,dict),'object receipt required')
    return value,sha256(raw).hexdigest()


def _count(value):return type(value) is int and value>=0


def import_manager_run(state,billing,task_id,job_root,audit_path,clock=None):
    from ops.pi import manager
    from ops.pi.development_inputs import ledger_snapshot
    state,billing,job_root,audit_path=map(_path,(state,billing,job_root,audit_path))
    require(name(task_id) and state!=billing and audit_path not in (state,billing) and not audit_path.is_relative_to(job_root),'separate audit target required')
    for source in (state,billing):_plain(source)
    _,_,rows,tasks,before_manager=manager._snapshot(state,billing,'ACTUAL')
    before_fee=ledger_snapshot(billing)
    task=next((t for t in tasks if t['payload']['task_id']==task_id),None)
    require(task is not None and task['status']=='done','registered manager run required')
    dispatch=rows.get(task['operation_id']+':dispatch');require(dispatch and dispatch['status']=='done','completed dispatch required')
    e=dispatch['evidence']
    require(e.get('verified') is True and e.get('mode')=='ACTUAL' and e.get('released') is False,'actual nonrelease receipt required')
    cycle,cycle_sha=_read(job_root,'bundle/cycle-output/result.json')
    require(digest(cycle)==e['cycle_result_sha256'] and cycle.get('status')=='done' and cycle.get('schema_version')==1,'cycle binding mismatch')
    ce=cycle.get('evidence',{})
    require(ce.get('verified') is True and ce.get('mode')=='ACTUAL' and ce.get('released') is False,'unverified cycle')
    review,review_sha=_read(job_root,'final-acceptance-review.json')
    require(review.get('schema')=='pi-server-owner-acceptance-review-v1' and review.get('source')=='independent_review'
            and review.get('verified') is True and review.get('result')=='approved' and review.get('task_id')==task_id,'independent acceptance required')
    require(review.get('product_adoption') is False and type(review.get('dispatch_count')) is int and review['dispatch_count']==1
            and review.get('dispatch_elapsed_ms')==e.get('elapsed_ms'),'dispatch identity mismatch')
    require(all(review.get(k) is True for k in ('containers_absent','policy_restored','original_history_unchanged')),'incomplete acceptance')
    require(all(_count(review.get(k)) for k in ('tests','baseline_failures','new_unknown','new_model_attempts','new_known_cost_microyuan'))
            and review['new_unknown']==0,'unresolved or invalid acceptance count')
    require(all(hash_value(review.get(k),40 if k=='source_commit' else 64) for k in ('source_commit','source_sha256','gold_sha256','candidate_sha256')),'unknown accepted source')
    files={};hashes={}
    for relative in FIXED_FILES:
        files[relative],hashes[relative]=_read(job_root,relative)
        require(review.get('evidence_sha256',{}).get(relative)==hashes[relative],'stale accepted artifact')
    selection=files[FIXED_FILES[0]];development=files[FIXED_FILES[1]];phase=files[FIXED_FILES[2]];check=files[FIXED_FILES[3]]
    require(selection.get('verified') is True and development.get('verified') is True and development.get('candidate_sha256')==review['candidate_sha256'],'candidate acceptance mismatch')
    require(ce.get('result')==development,'cycle development mismatch')
    for key in ('new_attempts','new_unknown','known_cost_microyuan'):
        require(all(_count(x.get(key)) for x in (selection,development)),'invalid phase count')
    require(selection['new_unknown']==development['new_unknown']==0 and selection['new_attempts']+development['new_attempts']==review['new_model_attempts']
        and selection['known_cost_microyuan']+development['known_cost_microyuan']==review['new_known_cost_microyuan'],'phase accounting mismatch')
    require(phase.get('verified') is True and phase.get('mode')=='ACTUAL','actual phase verification required')
    require(check.get('passed') is True and all(_count(check.get(k)) for k in ('tests','failures','errors','skipped'))
        and check['tests']==review['tests'] and check['failures']==check['errors']==check['skipped']==0,'unverified final checks')
    tool_snapshot=ledger_snapshot(job_root/'development-output/tools.sqlite')
    tool_rows={x['operation_id']:x for x in tool_snapshot['operations'] if x['kind']=='controlled_tool'}
    ordered=[]
    for event in tool_snapshot['events']:
        if event['kind']=='intent':
            value=manager.Ledger._decode(event['payload']);operation=value['operation_id']
            if operation in tool_rows:ordered.append(tool_rows[operation])
    require(len(ordered)==len(tool_rows) and len({x['operation_id'] for x in ordered})==len(ordered),'tool order mismatch')
    verified=phase.get('verified_tool_calls')
    require(isinstance(verified,list) and all(name(x) for x in verified) and len(set(verified))==len(verified)
        and set(verified)=={x['operation_id'].rsplit(':',1)[-1] for x in ordered},'tool verification mismatch')
    source=job_root/'package/source';candidate=job_root/'development-output/candidate'
    changes=snapshot_changes(source,candidate,review) if source.exists() or candidate.exists() else []
    version=dict(source_commit=review['source_commit'],base_commit=review['source_commit'],candidate_sha256=review['candidate_sha256'])
    evidence=[dict(kind='independent_acceptance',sha256=review_sha,verified=True,evidence_domain='real_provider_fixed_input')]
    def record(kind,status,summary,details=None,proof=None):
        return dict(kind=kind,status=status,run_id=task_id,occurred_at=None,summary=summary,details=details or {},version=version,changes=[],evidence=evidence+(proof or []),followups=[],mode='ACTUAL',evidence_domain='real_provider_fixed_input')
    records=[('analysis',record('analysis','passed',selection.get('proposal',{}).get('reason','Accepted fixed-input selection'),dict(decision='selected_fixed_input_repair'))),
             ('review',record('review','passed','Independent acceptance verified for frozen source, candidate and fixed tests.'))]
    for index,row in enumerate(ordered):
        payload=manager.Ledger._decode(row['payload']);receipt=manager.Ledger._decode(row['evidence']) if row['evidence'] else {}
        tool=payload.get('tool')
        from ops.pi.tools import TOOL_NAMES
        require(tool in TOOL_NAMES and row['status'] in ('done','blocked','failed','uncertain') and all(payload.get(k)==receipt.get(k) for k in ('tool','binding','input_hash')),'invalid tool receipt')
        feedback=receipt.get('check_feedback',{})
        result_summary='Receipt preserved; source text and raw patch are private.'
        if isinstance(feedback,dict) and feedback.get('verified') is True and feedback.get('mode')=='ACTUAL':
            cases=feedback.get('failed_cases',[])
            if isinstance(cases,list) and all(isinstance(case,str) for case in cases):result_summary='Failed cases: '+', '.join(cases)
        records.append(('tool-'+str(index),record('tool','passed' if row['status']=='done' else row['status'],tool+' returned '+row['status'],dict(tool_name=tool,operation_id=row['operation_id'],reason=receipt.get('reason'),request_summary='Frozen typed tool request; raw input retained privately.',result_summary=result_summary))))
    records.extend([
       ('development',record('development','candidate_ready','Real provider fixed-input repair accepted; no product adoption.',dict(model_requests=review['new_model_attempts'],tool_calls=len(ordered),known_cost_microyuan=review['new_known_cost_microyuan'],duration_ms=e['elapsed_ms']))),
       ('test',record('test','passed','Frozen checker passed; this is not an online improvement measurement.',dict(test_total=check['tests'],test_failures=0,test_errors=0,test_skipped=0,baseline_failures=review['baseline_failures']))),
       ('release',record('deployment','no_release','Candidate retained privately; not merged or deployed.',dict(decision='no_release'))),
    ])
    for _,value in records:
        if value['kind'] in ('development','test'):value['changes']=changes
        validate_record(value)
    # Validate all input receipts before creating any audit data.
    require(ledger_snapshot(billing)==before_fee and manager._snapshot(state,billing,'ACTUAL')[-1]==before_manager,'canonical state changed during import')
    audit=AuditStore(audit_path,clock=clock)
    for key,value in records:audit.append(task_id+':'+key,value)
    require(ledger_snapshot(billing)==before_fee and manager._snapshot(state,billing,'ACTUAL')[-1]==before_manager,'canonical state changed during export')
    return dict(schema_version=1,authority='audit_only',run_id=task_id,event_count=len(records),canonical_unchanged=True,
                acceptance_sha256=review_sha,cycle_sha256=cycle_sha,model_requests=review['new_model_attempts'],tool_calls=len(ordered),tests=check['tests'],known_cost_microyuan=review['new_known_cost_microyuan'])


def snapshot_changes(source,candidate,expected):
    from difflib import SequenceMatcher
    from ops.pi.development_inputs import tree_hash
    source,candidate=map(_path,(source,candidate))
    before=tree_hash(source);after=tree_hash(candidate)
    require(before==expected['source_sha256'] and after==expected['candidate_sha256'],'frozen audit trees changed')
    names={p.relative_to(root).as_posix() for root in (source,candidate) for p in root.rglob('*') if p.is_file()}
    result=[]
    for relative in sorted(names):
        contents=[]
        for root in (source,candidate):
            p=root/relative
            if not p.exists():contents.append(b'');continue
            require(p.stat().st_size<=1048576,'changed source file exceeds audit diff bound')
            contents.append(p.read_bytes())
        if contents[0]==contents[1]:continue
        try:
            old,new=(v.decode('utf-8').splitlines() for v in contents)
            opcodes=SequenceMatcher(None,old,new,autojunk=False).get_opcodes()
            added=sum(j2-j1 for tag,i1,i2,j1,j2 in opcodes if tag!='equal')
            deleted=sum(i2-i1 for tag,i1,i2,j1,j2 in opcodes if tag!='equal')
        except UnicodeError:added=deleted=None
        parts=Path(relative).parts
        category='test' if 'tests' in parts or Path(relative).name.startswith('test_') else 'docs' if Path(relative).suffix in ('.md','.rst') else 'config' if Path(relative).suffix in ('.json','.yaml','.yml','.toml','.ini') else 'production'
        result.append(dict(path=relative,category=category,added=added,deleted=deleted))
    require(tree_hash(source)==before and tree_hash(candidate)==after,'audit source changed during diff')
    return result
