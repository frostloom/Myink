"""Closed ordinary-user manager entry; complete autonomous receipts precede payment."""
from pathlib import Path
from threading import Event
import os,re,signal
from .audit import _path,_plain,hash_value,require,digest
from .development_inputs import file_hash,read_json
from .review_lease import _read,load_policy
from .autonomy_coordinator import RESULT
from .manager_handoff import BASE
from . import manager

FIELDS=set('schema mode state_path billing_path inbox autonomy_root handoff_root'.split())
PHASES={'investigation','reproducer','sdk_review','manager_handoff','coordinator_audit'}


def _ready(c,task_id,request_path,request_pin,manifest_pin,clock):
    if not task_id.startswith('auto-'):return
    require(re.fullmatch('auto-[0-9a-f]{32}',task_id),'reserved autonomous task identity invalid');cycle=_path(request_path)
    require(cycle.name=='cycle.json' and cycle.parent.name=='bundle' and cycle.parent.parent.parent==_path(c['handoff_root']),'autonomous cycle custody drift')
    fp=cycle.parent.parent.name.removeprefix('handoff-');require(hash_value(fp) and cycle.parent.parent.name=='handoff-'+fp and task_id=='auto-'+fp[:32],'autonomous fingerprint drift')
    claim=_path(c['autonomy_root'])/fp;r=_read(claim/'receipt.json')[0];intent=_read(claim/'intent.json')[0]
    require(isinstance(r,dict) and set(r)==RESULT and r['schema']=='pi-autonomy-coordinator-result-v1' and r['mode']==c['mode'] and r['status']=='admitted' and r['research_fingerprint']==fp and r['profile_sha256']==intent['profile_sha256'] and r['cycle_sha256']==request_pin==file_hash(cycle),'complete autonomous coordinator required')
    require(manifest_pin is None or r['manifest_sha256']==manifest_pin,'autonomous admission manifest drift')
    require(set(r['phases'])==PHASES,'complete phase chain required');results={}
    for component,pin in r['phases'].items():
        root=claim/('phase-'+component);phase,sha=_read(root/'receipt.json');require(sha==pin and phase['schema']=='pi-autonomy-phase-receipt-v1' and phase['mode']==c['mode'] and phase['status']=='done','autonomous phase incomplete')
        result,rpin=_read(root/'result-private.json');require(rpin==phase['result_sha256'] and result['schema']=='pi-autonomy-worker-result-v1' and result['mode']==c['mode'] and result['component']==component and result['status']=='done','autonomous phase result drift');results[component]=result
    cp=_path(c['handoff_root'])/('request-'+fp+'.json');require(file_hash(cp)==r['handoff_request_sha256'],'autonomous handoff request drift');q=read_json(cp)
    require(q['task_id']==task_id and q['mode']==c['mode'] and _path(q['root'])==cycle.parent.parent,'handoff identity drift')
    handoff=_read(cycle.parent.parent/'receipt.json')[0]
    require(digest(handoff)==digest(results['manager_handoff']['outcome']) and handoff['manifest_sha256']==r['manifest_sha256'] and handoff['cycle_sha256']==request_pin,'completed handoff receipt drift')
    p,_=load_policy(q['issuer_policy_path'],q['issuer_policy_sha256'],clock);require(p['mode']==c['mode'],'issuer mode drift')


def run(config_path,pin,*,cancel=None,executor=None,clock=None):
    cp=_path(config_path);_plain(cp);require(cp.stat().st_size<=65536 and file_hash(cp)==pin,'closed manager config drift');c=read_json(cp)
    require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-closed-manager-host-v1' and c['mode'] in ('ACTUAL','SIMULATED'),'fixed manager host config required')
    if c['mode']=='ACTUAL':
        from .autonomy_worker import _identity
        require(executor is None and clock is None and cp.stat().st_uid==0 and cp.stat().st_mode&0o777==0o640 and cp.parent.stat().st_uid==0 and cp.parent.stat().st_mode&0o777==0o750,'root ACTUAL manager config required');_identity()
        require(all(_path(c[k])==v for k,v in dict(state_path=BASE/'state/actual-manager.sqlite',billing_path=BASE/'state/ledger.sqlite',inbox=BASE/'inbox',autonomy_root=BASE/'autonomy',handoff_root=BASE/'handoffs').items()),'original actual manager roots required')
    else:require(callable(executor) and _path(c['billing_path'])!=BASE/'state/ledger.sqlite' and cp.stat().st_mode&0o777==0o600,'explicit isolated manager simulation required')
    cancel=cancel if cancel is not None else Event();previous={}
    def stop(*_):cancel.set()
    try:
        for signum in (signal.SIGTERM,signal.SIGINT):previous[signum]=signal.signal(signum,stop)
        require(not cancel.is_set(),'manager cancelled before admission')
        _,_,rows,tasks,_=manager._snapshot(Path(c['state_path']),Path(c['billing_path']),c['mode'])
        manifests=sorted(_path(c['inbox']).glob('*.task.json'));require(len(manifests)<=manager.MAX_TASKS,'bounded manager inbox required')
        for manifest in manifests:
            m=_read(manifest,1048576)[0];key='manager:task:'+m['task_id']
            if key+':dispatch' in rows or key+':cancel' in rows:continue
            _ready(c,m['task_id'],m['request_path'],m['request_sha256'],file_hash(manifest),clock)
        for task in tasks:
            if task['operation_id']+':dispatch' in rows or task['operation_id']+':cancel' in rows:continue
            q=task['payload'];_ready(c,q['task_id'],q['request_path'],q['request_sha256'],None,clock)
        require(not cancel.is_set() and file_hash(cp)==pin,'manager config revoked before dispatch')
        return manager.run(c['state_path'],c['billing_path'],max_tasks=1,seconds=2100,idle_seconds=0,inbox=c['inbox'],mode=c['mode'],executor=executor,cancel=cancel)
    finally:
        for signum,handler in previous.items():signal.signal(signum,handler)
