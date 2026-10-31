"""Ordinary no-model projection of original manager-bound stopped development."""
from pathlib import Path
import re
from .audit import AuditStore,_path,_plain,require,digest,validate_record
from .development_inputs import read_json,file_hash,ledger_snapshot
from .manager_completion import inspect
from .tools import TOOL_NAMES
from .local_cycle import _disjoint

FIELDS=set('schema mode manager_state ledger_path task_id request_path request_sha256 audit_path export_root controller_sha256 profile_sha256 source_commit'.split())


def emit(config_path,pin):
    cp=_path(config_path);_plain(cp);require(cp.stat().st_size<=65536 and file_hash(cp)==pin,'development projection config drift');c=read_json(cp)
    require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-development-audit-v1' and c['mode'] in ('ACTUAL','SIMULATED'),'fixed development projection required')
    if c['mode']=='ACTUAL':
        from .autonomy_worker import _identity
        _identity()
    proof=inspect(c['manager_state'],c['ledger_path'],c['task_id'],c['request_path'],c['request_sha256'],mode=c['mode']);d=proof['development'];dc=d['config'];view=d['dossier']['model_view']
    require(len(d['tools'])<=dc['max_tools'],'bounded original tool flow required')
    for out in (c['audit_path'],c['export_root']):
        for src in (cp,c['manager_state'],c['ledger_path'],c['request_path'],dc['root'],dc['source_path']):_disjoint(_path(out),_path(src))
    domain='real_provider_fixed_input' if c['mode']=='ACTUAL' else 'synthetic'
    version=dict(candidate_sha256=d['candidate_sha256'],controller_sha256=c['controller_sha256'],policy_sha256=c['profile_sha256'],sdk_version='1.1.0',source_commit=c['source_commit'])
    common=dict(run_id=c['task_id'],occurred_at=None,version=version,changes=[],followups=[],mode=c['mode'],evidence_domain=domain)
    evidence=[dict(kind=kind,sha256=sha,verified=True,evidence_domain=domain) for kind,sha in (('manager_binding',digest(proof['manager_binding'])),('stopped_tool_history',d['tools_sha256']),('development_result',view['development_result_sha256']))]
    def event(kind,status,summary,details,changes=None,extra=None):return dict(common,kind=kind,status=status,summary=summary,details=details,changes=changes or [],evidence=evidence+(extra or []))
    records=[]
    for index,row in enumerate(d['tools']):
        tool=row['payload']['tool'];require(tool in TOOL_NAMES and row['status'] in ('done','blocked','failed','uncertain'),'fixed terminal tool required')
        receipt=row['evidence'];feedback=receipt.get('check_feedback',{});cases=feedback.get('failed_cases',[]) if isinstance(feedback,dict) else []
        require(isinstance(cases,list),'bounded feedback cases required')
        cases=[case for case in cases if isinstance(case,str) and re.fullmatch(r'fixed_development_tests\.[A-Za-z0-9_.]{1,180}',case)]
        details=dict(reference='development.tool_flow.v1',tool_name=tool,operation_id=row['operation_id'],request_summary='Frozen typed request; arguments and source remain private.',result_summary='Failed fixed cases: '+','.join(cases[:4]) if cases else 'Terminal typed receipt retained privately.',reason=row['status'])
        records.append(('tool-'+str(index),event('tool','passed' if row['status']=='done' else row['status'],tool+' returned '+row['status'],details,extra=[dict(kind='controlled_tool_receipt',sha256=digest(row),verified=True,evidence_domain=domain)])))
    final=view['final_check'];baseline=view['baseline'];changes=view['changes']
    baseline_failures=baseline['reproduction']['failures'] if baseline.get('evidence_domain')=='code_regression' else baseline.get('failures')
    records.extend([
        ('development',event('development','candidate_ready','Stopped original development; independent candidate review and product adoption remain separate.',dict(reference='development.completed.v1',model_requests=d['model_requests'],tool_calls=len(d['tools']),known_cost_microyuan=d['known_cost_microyuan']),changes)),
        ('test',event('test','passed','Complete frozen final regression, matching candidate and cleanup.',dict(reference='development.final_check.v1',test_total=final['tests'],test_failures=final['failures'],test_errors=final['errors'],test_skipped=final['skipped'],baseline_failures=baseline_failures),changes)),
        ('release',event('deployment','no_release','Private candidate retained; no main adoption or product release.',dict(reference='development.no_release.v1',decision='no_release'))),
    ])
    for _,record in records:validate_record(record)
    require(file_hash(cp)==pin and ledger_snapshot(c['ledger_path'])==d['fee'],'development projection input/fee drift')
    store=AuditStore(c['audit_path'])
    for key,record in records:store.append(c['task_id']+':development-flow-v1:'+key,record)
    store.export(c['export_root']);return dict(model_requests=0,records=len(records),development_model_requests=d['model_requests'])
