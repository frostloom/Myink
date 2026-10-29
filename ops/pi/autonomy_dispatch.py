"""Once-only fixed phase execution; paid kernels run as ordinary ubuntu."""
from pathlib import Path
from threading import Event
import os,signal,stat,subprocess,time
from .audit import _path,_plain,require,strict_json
from .development_inputs import file_hash,read_json
from .review_lease import _read,_new,_sync,_directory
from .autonomy_profile import _owner,write
from .autonomy_worker import SCHEMAS
from .manager_handoff import BASE

ENVELOPE=set('schema component mode status model_requests outcome'.split())


def command(p,component,stage):
    require(p['mode']=='ACTUAL' and component in SCHEMAS,'fixed ACTUAL phase command required')
    argv=['/usr/bin/setpriv','--reuid=ubuntu','--regid=ubuntu','--groups=docker','--no-new-privs','--bounding-set=-all','--inh-caps=-all','--ambient-caps=-all','--pdeathsig=TERM','/usr/bin/python3','-I','-S','-B',p['worker_entry_path'],'--component',component,'--config',stage['config_path'],'--config-sha256',stage['config_sha256']]
    env=dict(PATH='/usr/bin:/bin',HOME='/home/ubuntu',USER='ubuntu',LOGNAME='ubuntu',LANG='C.UTF-8',DOCKER_CONFIG='/nonexistent',PYTHONDONTWRITEBYTECODE='1',PI_OBSERVER_RUNTIME_SHA256=p['controller_sha256'])
    return argv,env


def _owned_signal(process,signum):
    if process.poll() is None:
        require(os.getpgid(process.pid)==process.pid,'owned phase process group changed')
        try:os.killpg(process.pid,signum)
        except ProcessLookupError:pass


def _capture(argv,env,root,seconds,cancel,owner):
    root=_directory(root);require(type(seconds) in (int,float) and 0<seconds<=240,'bounded phase subprocess required')
    logs=[];process=None;interrupted=False;reason=None;started=time.monotonic();grace=None
    try:
        for name in ('stdout-private.log','stderr-private.log'):
            fd=os.open(root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            if os.geteuid()==0:os.fchown(fd,*owner)
            logs.append(os.fdopen(fd,'wb'))
        require(not cancel.is_set(),'phase cancelled before process creation')
        process=subprocess.Popen(argv,env=env,stdin=subprocess.DEVNULL,stdout=logs[0],stderr=logs[1],start_new_session=True,close_fds=True)
        _new(root/'pid.json',dict(pid=process.pid,process_group=process.pid))
        if os.geteuid()==0:os.chown(root/'pid.json',*owner)
        while True:
            sizes=[(root/name).stat().st_size for name in ('stdout-private.log','stderr-private.log')]
            current=time.monotonic();live=process.poll() is None
            trigger='capture_limit' if sizes[0]>1048576 or sizes[1]>65536 else 'cancelled' if cancel.is_set() else 'deadline' if current-started>=seconds else None
            if trigger and not interrupted:
                interrupted=True;reason=trigger;grace=current+60;_owned_signal(process,signal.SIGTERM)
            if not live:break
            if interrupted and current>=grace:_owned_signal(process,signal.SIGKILL)
            try:process.wait(timeout=.1)
            except subprocess.TimeoutExpired:pass
        return dict(returncode=process.returncode,interrupted=interrupted,reason=reason)
    finally:
        if process is not None and process.poll() is None:
            _owned_signal(process,signal.SIGTERM)
            try:process.wait(timeout=60)
            except subprocess.TimeoutExpired:_owned_signal(process,signal.SIGKILL);process.wait(timeout=5)
        for out in logs:out.flush();os.fsync(out.fileno());out.close()
        _sync(root)


def run(p,component,stage,claim_path,*,cancel=None,runner=None):
    cancel=cancel if cancel is not None else Event();require(component in SCHEMAS and p['mode'] in ('ACTUAL','SIMULATED') and not cancel.is_set(),'fixed uncancelled phase required')
    if p['mode']=='ACTUAL':
        require(runner is None and os.geteuid()==0 and _path(p['host']['ledger_path'])==BASE/'state/ledger.sqlite','ACTUAL fixed root dispatch required')
        from .deploy.observer_entry import verify_release
        entry=_path(p['worker_entry_path']);require(entry.name=='entry.py' and entry.is_relative_to(BASE/'releases'));verify_release(entry.parent,p['controller_sha256'])
        launcher=_path('/usr/bin/setpriv');_plain(launcher);require(launcher.stat().st_uid==0 and not launcher.stat().st_mode&0o022,'trusted fixed privilege dropper required')
    else:require(callable(runner) and _path(p['host']['ledger_path'])!=BASE/'state/ledger.sqlite','isolated explicit simulation required')
    claim=_directory(claim_path);require(claim.parent==_path(p['root']),'original phase claim required');fp=claim.name
    paths=dict(investigation=claim/'research-config.json',reproducer=_path(p['permit_root'])/('reproducer-'+fp+'.json'),sdk_review=_path(p['handoff_root'])/('review-config-'+fp+'.json'),manager_handoff=_path(p['handoff_root'])/('request-'+fp+'.json'),coordinator_audit=claim/'coordinator-audit.json',coordinator_withdrawal=claim/'coordinator-withdrawal-audit.json')
    cp=_path(stage['config_path']);require(cp==paths[component] and file_hash(cp)==stage['config_sha256'],'generated phase input pin required');c=read_json(cp)
    require(c['schema']==SCHEMAS[component] and c['mode']==p['mode'],'phase schema/mode drift')
    root=claim/('phase-'+component);require(not root.exists(),'phase intent exists; no replay');root.mkdir(mode=0o700)
    if p['mode']=='ACTUAL':os.chown(root,*_owner(p))
    _sync(root.parent);write(p,root/'intent.json',dict(component=component,config_path=str(cp),config_sha256=stage['config_sha256']))
    capture=None;result=None;failure=None
    try:
        require(not cancel.is_set() and file_hash(cp)==stage['config_sha256'],'phase revoked before dispatch')
        if runner is not None:result=runner(component,cp,stage['config_sha256'],cancel)
        else:
            seconds=dict(investigation=p['limits']['investigation_seconds']+60,reproducer=p['limits']['checker_seconds']+60,sdk_review=p['limits']['review_seconds']+60,manager_handoff=60,coordinator_audit=30,coordinator_withdrawal=30)[component]
            argv,env=command(p,component,stage);capture=_capture(argv,env,root,seconds,cancel,_owner(p));write(p,root/'capture.json',capture)
            out=root/'stdout-private.log';require(out.stat().st_size<=1048576,'bounded worker envelope required');result=strict_json(out.read_bytes())
        require(isinstance(result,dict) and set(result)==ENVELOPE and result['schema']=='pi-autonomy-worker-result-v1' and result['component']==component and result['mode']==p['mode'] and result['status'] in ('done','failed','blocked') and type(result['model_requests']) is int and 0<=result['model_requests']<=1 and isinstance(result['outcome'],dict),'verified fixed phase envelope required')
        if capture is not None:require(capture['returncode']==(0 if result['status']=='done' else 1),'worker exit/envelope mismatch')
        write(p,root/'result-private.json',result)
    except Exception as error:
        failure=type(error).__name__;write(p,root/'failure.json',dict(failure_class=failure))
    state='uncertain' if failure or capture and capture['interrupted'] else result['status']
    receipt=dict(schema='pi-autonomy-phase-receipt-v1',component=component,mode=p['mode'],status=state,model_requests=result.get('model_requests') if isinstance(result,dict) and type(result.get('model_requests')) is int else None,config_sha256=stage['config_sha256'],result_sha256=file_hash(root/'result-private.json') if (root/'result-private.json').exists() else None)
    write(p,root/'receipt.json',receipt)
    return dict(receipt,outcome=result['outcome'] if result and not failure else None,receipt_path=str(root/'receipt.json'),receipt_sha256=file_hash(root/'receipt.json'))
