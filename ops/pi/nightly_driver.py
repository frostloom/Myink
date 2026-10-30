"""Single-round host driver; original coordinator and manager remain executors.

The old seven timers stay disabled. A root-owned nightly timer may call this
entry repeatedly: sealed/approved/blocked rounds return before intake, model,
metrics or build work. Unfinished external intents block instead of replaying.
"""
from datetime import datetime,timezone
from pathlib import Path
import fcntl,os,stat,subprocess,uuid,time
from .audit import _path,_plain,require,strict_json,digest,utc,SHANGHAI
from .development_inputs import file_hash
from .nightly_gate import ApprovalGate,BASE
from .product_commands import _write
from . import manager_completion
from .nightly_bundle import prepare

FIELDS=set('schema mode state_path billing_path gate_path root lock_path inherit_task_id base_image_id docker endpoint daemon_id autonomy_profile'.split())


def _load(path,pin,callbacks,clock):
    path=_path(path);_plain(path);require(path.stat().st_size<=65536 and file_hash(path)==pin,'nightly driver config drift');c=strict_json(path.read_bytes())
    require(isinstance(c,dict) and FIELDS<=set(c)<=FIELDS|{'observation_config','observation_template','source_template'} and not ('observation_config' in c and 'observation_template' in c) and c['schema']=='pi-nightly-driver-v1' and c['mode'] in ('ACTUAL','SIMULATED'),'closed nightly driver config required')
    for key in ('root','lock_path','state_path','billing_path','gate_path'):_path(c[key])
    require(Path(c['root']).is_dir() and stat.S_IMODE(Path(c['root']).stat().st_mode)==0o700,'private nightly root required');_plain(Path(c['lock_path']))
    if c['mode']=='ACTUAL':
        require(not any(v is not None for v in callbacks) and clock is None and os.geteuid()==0 and path==BASE/'config/nightly-driver.json' and path.stat().st_uid==0 and stat.S_IMODE(path.stat().st_mode)==0o640 and path.parent.stat().st_uid==0 and stat.S_IMODE(path.parent.stat().st_mode)==0o750,'root-issued fixed ACTUAL nightly driver required')
        require(all(Path(c[k])==v for k,v in dict(root=BASE/'nightly',lock_path=BASE/'control/nightly.lock',state_path=BASE/'state/actual-manager.sqlite',billing_path=BASE/'state/ledger.sqlite',gate_path=BASE/'state/nightly-approval.sqlite').items()),'original ACTUAL manager and fee roots required')
        require(c['docker']=='/usr/bin/docker' and c['endpoint']=='unix:///var/run/docker.sock' and c['daemon_id']=='0f90c176-9c45-4708-8103-37b5ff2464f1','original product Docker daemon required')
    else:require(stat.S_IMODE(path.stat().st_mode)==0o600 and not Path(c['root']).is_relative_to(BASE),'isolated private driver simulation required')
    profile=c['autonomy_profile'];require(profile is None or isinstance(profile,dict) and set(profile)=={'path','sha256'},'one fixed optional original source profile required')
    if profile is not None and c['mode']=='ACTUAL':require(_path(profile['path'])==BASE/'config/autonomy-profile.json','original finite source profile required')
    return c


def _read(path):
    _plain(path);require(path.stat().st_size<=1048576 and stat.S_IMODE(path.stat().st_mode)==0o600,'private bounded driver receipt required');return strict_json(path.read_bytes())


def _response(gate,status,**extra):return dict(gate.status(),status=status,**extra)


def _admit(c):
    from .autonomy_coordinator import serve
    p=c['autonomy_profile'];require(file_hash(p['path'])==p['sha256'],'original source profile drift');return serve(p['path'],p['sha256'])


def _review_scope(task):
    path=BASE/'config/review-worker-registry.json';_plain(path);require(path.stat().st_size<=65536 and path.stat().st_uid==0 and stat.S_IMODE(path.stat().st_mode)==0o640,'root original worker registry required')
    entries=strict_json(path.read_bytes())['entries'];require(isinstance(entries,list) and 0<len(entries)<=16,'one finite worker scope required')
    for e in entries:
        request=_path(e['request_path']);require(request.is_relative_to(BASE/'handoffs') and file_hash(request)==e['request_sha256'] and strict_json(request.read_bytes())['task_id']==task,'review worker must serve only this bound task')


def _manager_state():
    r=subprocess.run(['/usr/bin/systemctl','show','myink-pi-manager.service','--property=ActiveState','--property=Result'],check=True,capture_output=True,timeout=30)
    values=dict(line.split('=',1) for line in r.stdout.decode().splitlines() if '=' in line)
    require(values.get('ActiveState') in ('activating','active','reloading','deactivating','inactive','failed') and 'Result' in values,'known original manager unit state required')
    return dict(active=values['ActiveState'] not in ('inactive','failed'),unit_result=values['Result'])


def _manager_start(task):
    _review_scope(task)
    subprocess.run(['/usr/bin/systemctl','start','myink-pi-manager.service'],check=True,capture_output=True,timeout=30)
    deadline=time.monotonic()+2400
    while True:
        state=_manager_state()
        if not state['active']:return dict(status='started',task_id=task,**state)
        require(time.monotonic()<deadline,'original manager completion unconfirmed; no replay')
        _review_scope(task)
        subprocess.run(['/usr/bin/systemctl','start','myink-pi-review-worker.service'],check=True,capture_output=True,timeout=35)
        time.sleep(5)


def _window(clock):
    from .maintenance_window import budget
    try:budget(utc(clock()),2100);return True
    except ValueError:return False


def _used(gate,pending):
    pin=pending['cycle_result']['evidence']['result']['candidate_sha256']
    with gate._connection() as c:
        return any(strict_json(r[0])['source_sha256']==pin for r in c.execute("SELECT package FROM approval_cycles WHERE phase='completed' AND package IS NOT NULL"))


def run(config_path,pin,*,clock=None,admit=None,manager_trigger=None,image_factory=None,deployment_confirm=None,assessor=None,source_prepare=None):
    c=_load(config_path,pin,(admit,manager_trigger,image_factory,deployment_confirm,assessor,source_prepare),clock);clock=clock or (lambda:datetime.now(timezone.utc))
    gate=ApprovalGate(c['gate_path'],c['state_path'],c['billing_path'],mode=c['mode'],clock=clock if c['mode']=='SIMULATED' else None)
    with Path(c['lock_path']).open('rb') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return _response(gate,'lock_busy')
        state=gate.status()
        if state['phase']=='awaiting_deployment':
            require(c['mode']=='ACTUAL' or callable(deployment_confirm),'explicit simulated deployment verifier required')
            if deployment_confirm is None:
                from .nightly_deployment import confirm as deployment_confirm
            result=deployment_confirm(gate,state['cycle_id'],Path(c['root'])/state['cycle_id']/'bundle',Path(c['docker']),c['endpoint'],c['daemon_id'])
            return _response(gate,'observing' if result['status']=='observing' else 'waiting_human',confirmation_status=result['status'])
        if state['phase']=='observing':
            observer=c.get('observation_config')
            if c.get('observation_template') is not None:
                from .nightly_binding import bind
                template=c['observation_template'];require(isinstance(template,dict) and set(template)=={'path','sha256'},'one pinned observer template required')
                observer=bind(gate,state['cycle_id'],Path(c['root'])/state['cycle_id']/'bundle',template['path'],template['sha256'])
            if observer is None:return _response(gate,'observation_not_configured')
            require(isinstance(observer,dict) and set(observer)=={'path','sha256'},'one pinned observation config required')
            require(c['mode']=='ACTUAL' or callable(assessor),'explicit simulated assessment required')
            if assessor is None:
                from .nightly_observation import assess as assessor
            result=assessor(gate,state['cycle_id'],Path(c['root'])/state['cycle_id']/'bundle',observer['path'],observer['sha256'])
            return _response(gate,result['status'],assessed_cycle_id=state['cycle_id'])
        if state['phase'] not in ('idle','preparing'):return _response(gate,'waiting_human')
        cycle=state['cycle_id'];root=None
        try:
            if state['phase']=='idle':
                inherited=None
                if c['inherit_task_id'] is not None:
                    inherited=manager_completion.request(gate.state,gate.billing,c['inherit_task_id'],mode=gate.mode)
                    require(inherited['status']=='candidate_ready','configured inherited candidate is not complete')
                    if _used(gate,inherited):inherited=None
                if inherited is None and c['autonomy_profile'] is None:
                    if c.get('source_template') is None:return _response(gate,'source_not_configured')
                    with gate._connection() as db:confirmed=db.execute("SELECT 1 FROM approval_cycles WHERE phase='completed' AND package IS NOT NULL AND deployment IS NOT NULL LIMIT 1").fetchone()
                    if confirmed is None:return _response(gate,'source_requires_confirmed_deployment')
                from .maintenance_window import budget
                try:budget(utc(clock()),2100)
                except ValueError:return _response(gate,'outside_window')
                cycle=str(uuid.uuid4());claim=gate.begin(cycle,utc(clock()).astimezone(SHANGHAI).date().isoformat())
                if not claim['claimed']:return _response(gate,'already_claimed')
                root=Path(c['root'])/cycle;root.mkdir(mode=0o700)
                _write(root/'start.json',dict(schema='pi-nightly-start-v1',cycle_id=cycle,config_sha256=pin,created_at=utc(clock()).isoformat()))
                if inherited is not None:
                    gate.bind_task(cycle,c['inherit_task_id']);_write(root/'selected.json',dict(task_id=c['inherit_task_id'],origin='completed_original_manager'))
            root=Path(c['root'])/cycle
            require(root.is_dir() and stat.S_IMODE(root.stat().st_mode)==0o700,'existing private single-cycle root required')
            require(_read(root/'start.json')['config_sha256']==pin,'nightly source configuration changed during preparation')
            selected=root/'selected.json'
            if not selected.exists():
                intent=root/'admission-intent.json';receipt=root/'admission.json'
                if intent.exists() and not receipt.exists():raise ValueError('interrupted original source admission; no model replay')
                if not receipt.exists():
                    if not _window(clock):return _response(gate,'waiting_next_window')
                    require(c['autonomy_profile'] is not None or c.get('source_template') is not None,'original source profile or confirmed source template required');_write(intent,dict(config_sha256=pin,profile=c['autonomy_profile'],source_template=c.get('source_template')))
                    effective=c
                    if c.get('source_template') is not None:
                        from .nightly_source import prepare as prepare_source
                        template=c['source_template'];require(isinstance(template,dict) and set(template)=={'path','sha256'},'one pinned source template required')
                        require(c['mode']=='ACTUAL' or callable(source_prepare),'explicit simulated source preparation required')
                        stage=(source_prepare or prepare_source)(gate,cycle,root,template['path'],template['sha256']);require(stage['cycle_id']==cycle,'source stage belongs to another round')
                        if not (root/'source-stage.json').exists():_write(root/'source-stage.json',stage)
                        require(_read(root/'source-stage.json')==stage,'source stage receipt drift');effective=dict(c,autonomy_profile=stage['profile'])
                    require(c['mode']=='ACTUAL' or callable(admit),'SIMULATED source requires an explicit callback')
                    admitted=(admit or _admit)(effective);_write(receipt,admitted)
                result=_read(receipt)
                disposition=result['status']
                if disposition=='cached':require(result.get('previous_status') in ('no_task','not_reproduced'),'cached prior admission or failure needs reconciliation')
                if disposition in ('no_task','not_reproduced','no_evidence','outside_window','lock_busy','cached'):
                    record=dict(schema='pi-nightly-no-release-v1',cycle_id=cycle,status='no_release',reason=disposition,admission_receipt_sha256=file_hash(receipt),model_requests=result.get('model_requests',0),deployed=False)
                    _write(root/'no-release.json',record);gate.no_release(cycle,disposition,digest(record));return _response(gate,'no_release',reason=disposition)
                require(disposition=='admitted','original source did not admit a task')
                fp=result['research_fingerprint'];require(isinstance(fp,str) and len(fp)==64 and all(ch in '0123456789abcdef' for ch in fp),'original source fingerprint required')
                task='auto-'+fp[:32];gate.bind_task(cycle,task);_write(selected,dict(task_id=task,origin='original_source_coordinator'))
            choice=_read(selected);task=choice['task_id'];require(gate.status()['task_id']==task,'original task binding drift')
            if choice['origin']=='original_source_coordinator':
                intent=root/'manager-intent.json';receipt=root/'manager-start.json'
                if intent.exists() and not receipt.exists():raise ValueError('interrupted original manager notification; no replay')
                if not receipt.exists():
                    if not _window(clock):return _response(gate,'waiting_next_window')
                    require(c['mode']=='ACTUAL' or callable(manager_trigger),'SIMULATED manager requires an explicit callback')
                    _write(intent,dict(task_id=task));started=(manager_trigger or _manager_start)(task);require(started['status']=='started','original manager not notified');_write(receipt,started)
            pending=manager_completion.request(gate.state,gate.billing,task,mode=gate.mode)
            if pending['status'] in ('not_registered','waiting_manager'):
                if choice['origin']=='original_source_coordinator':
                    started=_read(root/'manager-start.json')
                    if c['mode']=='ACTUAL':require(_manager_state()['active'],'original manager exited without completion; no restart')
                    elif 'active' in started:require(started['active'],'original manager exited without completion; no restart')
                return _response(gate,'waiting_original_manager')
            require(pending['status']=='candidate_ready','original manager stopped without a completed candidate')
            if not _window(clock):return _response(gate,'waiting_next_window')
            require(not (root/'bundle').exists(),'interrupted package preparation; no rebuild or reseal')
            require(file_hash(config_path)==pin,'nightly config revoked before preparation')
            base=_read(root/'source-stage.json')['base_image_id'] if (root/'source-stage.json').exists() else c['base_image_id']
            prepare(gate,cycle,root/'bundle',task,base,Path(c['docker']),c['endpoint'],c['daemon_id'],image_factory=image_factory)
            return _response(gate,'waiting_human')
        except Exception as error:
            if cycle is not None:
                gate.block(cycle,'nightly_preparation_'+type(error).__name__)
                if root is not None and root.is_dir() and not (root/'failure.json').exists():_write(root/'failure.json',dict(status='blocked',failure_class=type(error).__name__,model_replay=False))
            return _response(gate,'blocked',failure_class=type(error).__name__)
