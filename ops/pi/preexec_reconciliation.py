"""Root reconciliation only for retained, terminal setpriv failures before exec.

No old receipt is changed and no phase is retried. A root-owned certificate
retains input hashes; subsequent legitimate ledger growth does not revoke it.
"""
from pathlib import Path
from datetime import datetime,timezone
import os,stat,fcntl
from .audit import _path,_plain,digest,require,strict_json,AuditStore
from .development_inputs import file_hash,ledger_snapshot
from .product_commands import _write
from .nightly_gate import BASE

COMPONENTS=('investigation','coordinator_audit')
ERRORS={b'setpriv: setresuid failed: Operation not permitted\n',b'setpriv: setgroups failed: Operation not permitted\n'}
FILES=('intent.json','receipt.json','ledger-before-private.json')+tuple('phase-'+c+'/'+n for c in COMPONENTS for n in ('intent.json','receipt.json','capture.json','pid.json','stdout-private.log','stderr-private.log'))


def _json(path):
    _plain(path);require(path.stat().st_size<=67108864,'bounded original preexec evidence required');return strict_json(path.read_bytes())


def _claim(claim,mode):
    claim=_path(claim);require(mode in ('ACTUAL','SIMULATED') and claim.is_dir() and stat.S_IMODE(claim.stat().st_mode)==0o700 and len(claim.name)==64 and all(c in '0123456789abcdef' for c in claim.name),'private original claim required')
    if mode=='ACTUAL':require(os.geteuid()==0 and claim.parent==BASE/'autonomy','fixed root original claim required')
    else:require(not claim.is_relative_to(BASE),'isolated reconciliation required')
    return claim


def verified(claim,mode):
    claim=_claim(claim,mode);path=claim/'preexec-reconciliation.json'
    if not path.exists():return False
    value=_json(path);info=path.stat()
    require(info.st_uid==(0 if mode=='ACTUAL' else os.geteuid()) and stat.S_IMODE(info.st_mode)==0o600,'root reconciliation certificate required')
    require(set(value)=={'schema','mode','claim','issued_at','proof','proof_sha256'} and value['schema']=='pi-autonomy-preexec-reconciliation-v1' and value['mode']==mode and value['claim']==str(claim),'original reconciliation identity required')
    proof=value['proof'];require(digest(proof)==value['proof_sha256'] and proof['model_requests']==0 and proof['classification']=='launcher_failed_before_exec' and set(proof['inputs'])==set(FILES),'closed no-effect certificate required')
    require(all(file_hash(claim/name)==pin for name,pin in proof['inputs'].items()),'reconciled evidence changed')
    return True


def inspect(claim,state,billing,*,mode):
    claim=_claim(claim,mode);state=_path(state);billing=_path(billing)
    if mode=='ACTUAL':require(state==BASE/'state/actual-manager.sqlite' and billing==BASE/'state/ledger.sqlite','original accounting required')
    receipt=_json(claim/'receipt.json');intent=_json(claim/'intent.json');fee=ledger_snapshot(billing);manager=ledger_snapshot(state)
    from .autonomy_coordinator import RESULT
    require(set(receipt)==RESULT and receipt['schema']=='pi-autonomy-coordinator-result-v1' and receipt['mode']==mode and receipt['status']=='uncertain' and receipt['research_fingerprint']==claim.name==intent['research_fingerprint'] and receipt['profile_sha256']==intent['profile_sha256'],'original uncertain coordinator required')
    require(receipt['model_requests']==0 and receipt['before_fee_sha256']==receipt['after_fee_sha256']==fee['sha256'] and _json(claim/'ledger-before-private.json')==fee,'unchanged original fee evidence required')
    require(all(receipt[k] is None for k in ('manifest_sha256','handoff_request_sha256','cycle_sha256')) and receipt['pending_file_hashes']=={} and set(receipt['phases'])==set(COMPONENTS),'pre-admission failure required')
    for component in COMPONENTS:
        phase=claim/('phase-'+component);r=_json(phase/'receipt.json');capture=_json(phase/'capture.json')
        require(file_hash(phase/'receipt.json')==receipt['phases'][component] and r['component']==component and r['status']=='uncertain' and r['model_requests'] is None and r['result_sha256'] is None and _json(phase/'intent.json')['component']==component,'original unexecuted phase required')
        require(capture==dict(returncode=127,interrupted=False,reason=None) and not (phase/'result-private.json').exists(),'terminal launcher failure required')
        _plain(phase/'stdout-private.log');_plain(phase/'stderr-private.log')
        require((phase/'stdout-private.log').stat().st_size==0 and (phase/'stderr-private.log').read_bytes() in ERRORS,'known fixed preexec failure required')
    base=claim.parent.parent;task='auto-'+claim.name[:32]
    require(not any((base/name).exists() for name in ('inbox/'+task+'.task.json','handoffs/request-'+claim.name+'.json','handoffs/handoff-'+claim.name,'investigations/research-'+claim.name)),'phase or admission outputs exist')
    require(not any(task in str(row) for rows in (manager['operations'],manager['events']) for row in rows),'original manager work exists')
    return dict(classification='launcher_failed_before_exec',model_requests=0,before_fee_sha256=fee['sha256'],manager_sha256=manager['sha256'],inputs={name:file_hash(claim/name) for name in FILES})


def _reconcile(claim,state,billing,*,mode):
    claim=_claim(claim,mode)
    if verified(claim,mode):return _json(claim/'preexec-reconciliation.json')
    proof=inspect(claim,state,billing,mode=mode)
    if mode=='ACTUAL':
        audit=BASE/'audit/state/events.sqlite';export=BASE/'audit/export'
    else:
        parent=claim/'reconciliation-audit';parent.mkdir(mode=0o700,exist_ok=True);audit=parent/'events.sqlite';export=parent/'export'
    now=datetime.now(timezone.utc).isoformat()
    event=dict(kind='plan',status='failed',run_id='auto-'+claim.name[:32],occurred_at=now,summary='Verified launcher failure before Python execution; original uncertain history retained. No replay or fee release.',details=dict(reference='autonomy.preexec_reconciliation.v1',decision='reconciled_no_execution',next_action='fresh_evidence_only',model_requests=0,known_cost_microyuan=0),version={},changes=[],evidence=[dict(kind='preexec_no_effect_proof',sha256=digest(proof),verified=True,evidence_domain='offline' if mode=='ACTUAL' else 'synthetic')],followups=[],mode=mode,evidence_domain='offline' if mode=='ACTUAL' else 'synthetic')
    intent_path=claim/'preexec-reconciliation-intent.json'
    if intent_path.exists():
        packet=_json(intent_path);info=intent_path.stat()
        require(info.st_uid==(0 if mode=='ACTUAL' else os.geteuid()) and stat.S_IMODE(info.st_mode)==0o600,'owned recovery intent required')
        require(set(packet)=={'schema','mode','claim','proof','event'} and packet['schema']=='pi-preexec-reconciliation-intent-v1' and packet['mode']==mode and packet['claim']==str(claim) and packet['proof']==proof,'original recovery publication intent changed')
        event=packet['event'];require(event['run_id']=='auto-'+claim.name[:32] and event['mode']==mode and event['details']['model_requests']==0,'original recovery audit identity required')
        now=event['occurred_at']
    else:_write(intent_path,dict(schema='pi-preexec-reconciliation-intent-v1',mode=mode,claim=str(claim),proof=proof,event=event))
    store=AuditStore(audit);store.append(claim.name+':preexec-reconciled',event);store.export(export)
    if mode=='ACTUAL':
        from .nightly_binding import _audit_outputs,_ordinary
        for path in _audit_outputs(dict(audit_path=str(audit),export_root=str(export))):_ordinary(path,mode)
    require(inspect(claim,state,billing,mode=mode)==proof,'preexec evidence changed during audit')
    value=dict(schema='pi-autonomy-preexec-reconciliation-v1',mode=mode,claim=str(claim),issued_at=now,proof=proof,proof_sha256=digest(proof));_write(claim/'preexec-reconciliation.json',value);verified(claim,mode);return value


def reconcile(claim,state,billing,*,mode):
    claim=_claim(claim,mode)
    lock=BASE/'control/maintenance.lock' if mode=='ACTUAL' else claim.parent.parent/'maintenance.lock'
    if mode=='SIMULATED' and not lock.exists():lock.touch(mode=0o600)
    _plain(lock)
    with lock.open('rb') as held:
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _reconcile(claim,state,billing,mode=mode)
