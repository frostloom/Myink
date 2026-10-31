"""Readonly reauthentication of finished SDK/tool/fee facts, never task authority.

The root completion controller must additionally bind the original completed
manager dispatch/cycle before it can issue a finite candidate-review permit.
"""
from dataclasses import asdict
from pathlib import Path
from .audit import digest,require,strict_json
from .candidate_dossier import compile_evidence
from .development_inputs import file_hash,ledger_snapshot,OWNER
from .review_lease import _read
from .review_issuer import _snapshot
from .diagnosis_launcher import _unknown
from .development_launcher import worker_receipt
from .policy import load_policy
from .plans import Plan,validate_plan
from .tools import ToolCapability,digest as tool_digest
from .trial_runtime import verify_stopped_phase

CANONICAL=Path('/home/ubuntu/myink-pi-managed/state/ledger.sqlite')


class _StoppedTools:
    """Only the three readonly methods used by verify_stopped_phase; no Ledger."""
    def __init__(self,c,plan,snapshot):
        candidate=Path(c['root'])/'candidate';self.capability=ToolCapability(c['run_id'],c['run_id'],candidate,c['source_sha256'],OWNER,1,'develop',plan.files,plan)
        self.rows={r['operation_id']:r for r in snapshot['operations']};self.c=c
        self.binding=tool_digest(dict(session=c['run_id'],candidate_id=c['run_id'],base=c['source_sha256'],owner=OWNER,generation=1,phase='develop',root=str(candidate),plan_hash=plan.plan_hash))
        source_binding=tool_digest(dict(candidate_id=c['run_id'],base=c['source_sha256'],owner=OWNER,generation=1,root=str(candidate),paths=plan.files))
        row=self.rows.get('tool-source-base:'+source_binding)
        require(row and row['kind']=='tool_source_base' and row['status']=='done' and strict_json(row['evidence'])==dict(sources={p:(Path(c['source_path'])/p).read_text() for p in plan.files}),'original tool-source base drift')
        approval=self.rows.get('tool-approval:'+self.binding+':'+plan.plan_hash);review_id=c['run_id']+':review';review=self.rows.get(review_id)
        require(approval and approval['kind']=='tool_approval' and approval['status']=='done' and strict_json(approval['payload'])==dict(plan_hash=plan.plan_hash,binding=self.binding,review_id=review_id),'missing original tool approval')
        original_review=_read(c['review_path'])[0];require(review and review['kind']=='independent_review' and review['status']=='done' and digest(strict_json(review['evidence']))==digest(original_review),'tool review differs from frozen FileReview')
        rules=asdict(validate_plan(plan,_read(c['baseline_path'])[0],load_policy(Path(c['policy_path']))))
        require(digest(strict_json(approval['evidence']))==digest(dict(rules=rules,review_id=review_id)),'original tool approval rules drift')

    def candidate_hash(self):return tool_digest({p:file_hash(Path(self.c['root'])/'candidate'/p) for p in self.capability.tracked_paths})

    def lookup(self,call_id,name,args,result):
        row=self.rows.get('tool:'+self.c['run_id']+':'+call_id)
        return bool(row and row['kind']=='controlled_tool' and row['status']!='pending'
            and strict_json(row['payload'])==dict(tool=name,input_hash=tool_digest(args),binding=self.binding)
            and isinstance(result,dict) and digest(result)==digest(dict(operation_id=row['operation_id'],status=row['status'],evidence=strict_json(row['evidence']),schema_version=1)))


def inspect(request_path,request_sha256):
    dossier=compile_evidence(request_path,request_sha256);q=_read(request_path)[0];c=_read(q['config_path'])[0];root=Path(c['root']);pins=dict(dossier['artifact_pins'])
    def read(name):
        value,pin=_read(root/name);pins[str(root/name)]=pin;return value
    result=read('result.json');saved=read('phase-verification.json');frame=read('worker-frame-private.json')
    require(frame.get('type')=='result' and frame.get('network_denied') is True,'stopped network-denied SDK frame required')
    receipt=worker_receipt(frame['receipt']);e=receipt.evidence
    require(e.get('engine')=='pi' and e.get('phase','develop')=='develop' and not e.get('protocol_failed') and not e.get('errors')
        and type(e.get('owned_pid')) is int and e['owned_pid']>0 and type(e.get('returncode')) is int and e['returncode']==0,'SDK failed or still running')
    # PiAdapter receipts bind the administrator context, not a phase field.
    # The phase is independently bound by the original Plan/tool ledger and
    # stopped-session reconciliation below. Reject contradictory context.
    if q['mode']=='ACTUAL' or 'phase' not in e or 'administrator_role' in e:
        require(e.get('administrator_role')=='myink-administrator' and e.get('experiment_id')=='local-trial-1' and e.get('budget_scope_id')=='local-trial-1' and e.get('plan_id')==dossier['model_view']['plan_hash'] and e.get('accepted') is True and e.get('disposition')=='started' and e.get('settled') is True and e.get('aborted') is False and e.get('process_exited') is True,'original Pi administrator/plan/session identity required')
    tools_path=root/'tools.sqlite';tools=ledger_snapshot(tools_path)
    raw_plan=dossier['model_view']['plan'];plan=Plan(**{k:tuple(v) if isinstance(v,list) else v for k,v in raw_plan.items()});broker=_StoppedTools(c,plan,tools)
    require(isinstance(frame['session'],str) and isinstance(frame['transcript'],str),'bounded stopped SDK artifacts required')
    checked=verify_stopped_phase(broker,receipt,frame['session'].encode(),frame['transcript'].encode(),stopped=dict(verified=True,mode='ACTUAL',pid=e['owned_pid'],tree_empty=True,returncode=0),source_before=c['source_sha256'],source_after=dossier['candidate_sha256'])
    require(checked.get('verified') is True and digest(checked)==digest(saved),'stopped development SDK/tool reconciliation failed')
    rows={r['operation_id']:r for r in tools['operations'] if r['kind']=='controlled_tool'};ordered=[]
    for event in tools['events']:
        if event['kind']=='intent':
            operation=strict_json(event['payload'])['operation_id']
            if operation in rows:ordered.append(rows[operation])
    require(len(ordered)==len(rows) and len({r['operation_id'] for r in ordered})==len(rows)
        and set(saved['verified_tool_calls'])=={r['operation_id'].rsplit(':',1)[-1] for r in ordered},'tool history/session mismatch')
    before=read('ledger-before-private.json');after=read('ledger-after-private.json');current=ledger_snapshot(c['ledger_path']);old=_snapshot(before);new=_snapshot(after);now=_snapshot(current)
    require(before['sha256']==c['ledger_sha256'] and before['limits']==after['limits']==current['limits']
        and after['events'][:len(before['events'])]==before['events'] and current['events'][:len(after['events'])]==after['events']
        and all(new.get(k)==v for k,v in old.items()) and all(now.get(k)==v for k,v in new.items())
        and _unknown(before)==_unknown(after)==_unknown(current),'original fee prefix/history or unknown scope drift')
    require(q['mode']!='SIMULATED' or Path(c['ledger_path'])!=CANONICAL,'SIMULATED requires isolated fees')
    if q['mode']=='ACTUAL':require(Path(c['ledger_path'])==CANONICAL and current['limits']['budget_microyuan']==50000000 and len(_unknown(current))==9,'original50CNY/nineholds required')
    added={k:v for k,v in new.items() if k not in old};posts=result['model_posts'];require(isinstance(posts,list) and len(posts)==len(added)==result['new_attempts'] and len({p['attempt_id'] for p in posts})==len(posts)
        and all(p.get('status')==200 for p in posts) and {p['attempt_id'] for p in posts}==set(added),'development paid request linkage drift')
    cost=0
    for row in added.values():
        evidence=strict_json(row['evidence'] or '{}');require(row['kind']=='model-attempt' and row['status']=='done' and evidence.get('usage_known') is True and type(evidence.get('charged_microyuan')) is int and evidence['charged_microyuan']>=0,'known development settlement required');cost+=evidence['charged_microyuan']
    require(cost==result['known_cost_microyuan'],'development fee total drift')
    require(ledger_snapshot(tools_path)==tools and ledger_snapshot(c['ledger_path'])==current and all(file_hash(p)==pin for p,pin in pins.items()),'development evidence changed while inspecting')
    return dict(authority='completed_development_only',mode=q['mode'],config=c,candidate_sha256=dossier['candidate_sha256'],dossier=dossier,tools=[dict(r,payload=strict_json(r['payload']),evidence=strict_json(r['evidence'])) for r in ordered],model_requests=len(added),known_cost_microyuan=cost,fee=current,artifact_pins=pins,tools_sha256=tools['sha256'])
