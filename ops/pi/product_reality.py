"""Fixed read-only product inventory. Observations confer no release authority."""
from datetime import datetime,timezone
from pathlib import Path
import os,pwd,re,stat,subprocess,time,uuid
from hashlib import sha256
from .audit import _path,_plain,require,digest,encoded,strict_json,utc
from .audit_export import _publish

BASE=Path('/home/ubuntu/myink-pi-managed')


def file_hash(path):return sha256(Path(path).read_bytes()).hexdigest()


def _directory(value):
    path=_path(value);require(path.is_dir() and stat.S_IMODE(path.stat().st_mode)==0o700,'private observer directory required');return path


def _new(path,value):_publish(path,encoded(value),immutable=True)


def _sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def _disjoint(a,b):require(not a.is_relative_to(b) and not b.is_relative_to(a),'observer resources overlap')

FIELDS=set('schema mode docker endpoint daemon_id root audit_path export_root worker_replicas'.split())
ROW=set('id image_id running status healthy project service'.split())
META=set('maintenance_control maintenance_executions maintenance_lock_function task_provenance agent_run_provenance'.split())
SERVICES={'myink-api':1,'myink-worker':None,'myink-caddy':1,'myink-pg':1,'myink-redis':1,'myink-rabbitmq':1}
METADATA_SQL="""BEGIN READ ONLY;SET LOCAL statement_timeout='3s';
SELECT json_build_object(
'maintenance_control',to_regclass('public.maintenance_control') IS NOT NULL,
'maintenance_executions',to_regclass('public.maintenance_executions') IS NOT NULL,
'maintenance_lock_function',to_regprocedure('public.myink_lock_maintenance()') IS NOT NULL,
 'task_provenance',EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='tasks' AND column_name='run_provenance'),
 'agent_run_provenance',EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='agent_runs' AND column_name='run_provenance'));
ROLLBACK;"""
CONTAINER_FORMAT='{"id":{{json .Id}},"image_id":{{json .Image}},"running":{{json .State.Running}},"status":{{json .State.Status}},"healthy":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}}}'
IMAGE_FORMAT='{"id":{{json .Id}},"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}}}'


def _hex(value):return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None

def _image(value):return isinstance(value,str) and re.fullmatch('sha256:[0-9a-f]{64}',value) is not None


def _load(cp,pin,runner,clock):
    cp=_path(cp);_plain(cp);require(cp.stat().st_size<=65536 and file_hash(cp)==pin,'product config pin drift');c=strict_json(cp.read_bytes())
    require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-product-observer-v1' and c['mode'] in ('ACTUAL','SIMULATED'),'fixed product observer config required')
    if c['mode']=='ACTUAL':
        require(runner is None and clock is None,'ACTUAL forbids injected product observation')
        require(cp==BASE/'config/product-observer.json' and cp.stat().st_uid==0 and stat.S_IMODE(cp.stat().st_mode)==0o640 and cp.parent.stat().st_uid==0 and stat.S_IMODE(cp.parent.stat().st_mode)==0o750,'canonical root product config required')
        require(os.geteuid()==pwd.getpwnam('ubuntu').pw_uid and os.geteuid()!=0,'ordinary product observer identity required')
        require(c['docker']=='/usr/bin/docker' and c['endpoint']=='unix:///var/run/docker.sock' and c['root']==str(BASE/'product-observations') and c['audit_path']==str(BASE/'audit/state/events.sqlite') and c['export_root']==str(BASE/'audit/export'),'original product resources required')
        _plain(Path(c['docker']));require(Path(c['docker']).stat().st_uid==0 and not Path(c['docker']).stat().st_mode&0o022,'trusted fixed Docker required')
    else:require(callable(runner) and stat.S_IMODE(cp.stat().st_mode)==0o600 and stat.S_IMODE(cp.parent.stat().st_mode)==0o700 and all(not _path(value).is_relative_to(BASE) for value in (cp,c['root'],c['audit_path'],c['export_root'])),'isolated private product simulation required')
    require(type(c['worker_replicas']) is int and 1<=c['worker_replicas']<=8 and isinstance(c['daemon_id'],str) and re.fullmatch('[A-Za-z0-9:_-]{1,128}',c['daemon_id']),'bounded product topology required')
    require(_path(c['docker']).is_absolute() and isinstance(c['endpoint'],str) and re.fullmatch(r'unix:///[^\s?,#\x00]+',c['endpoint']),'fixed local Docker socket required')
    root=_directory(c['root']);audit=_path(c['audit_path']);export=_path(c['export_root'])
    for item in (cp,audit,export):_disjoint(root,item)
    _disjoint(audit,export);require(stat.S_IMODE(audit.parent.stat().st_mode)==0o700,'private existing audit parent required')
    if c['mode']=='ACTUAL':
        require(root.stat().st_uid==os.geteuid(),'ordinary observer must own outputs');_plain(audit)
        require(audit.stat().st_uid==os.geteuid() and stat.S_IMODE(audit.stat().st_mode)==0o600,'existing ordinary private audit required')
        import sqlite3
        from contextlib import closing
        from .audit import _schema
        with closing(sqlite3.connect(audit.as_uri()+'?mode=ro',uri=True)) as db:_schema(db)
    return c


def _native(argv,seconds):
    p=subprocess.run(argv,stdin=subprocess.DEVNULL,capture_output=True,timeout=seconds,env=dict(PATH='/usr/bin:/bin',HOME='/nonexistent',DOCKER_CONFIG='/nonexistent',LANG='C.UTF-8'))
    return dict(returncode=p.returncode,stdout=p.stdout.decode('utf-8'),stderr=p.stderr.decode('utf-8',errors='replace'))


def _inventory(rows,ids,replicas):
    require(isinstance(rows,list) and len(rows)==len(ids) and {r.get('id') for r in rows}==set(ids),'complete product census required');counts={k:0 for k in SERVICES};active=[];excluded=[]
    for row in rows:
        require(isinstance(row,dict) and set(row)==ROW and _hex(row['id']) and _image(row['image_id']) and type(row['running']) is bool and row['project']=='myink' and row['healthy'] in (None,'healthy','unhealthy','starting'),'typed original product container required')
        service=row['service'];require(service in SERVICES or service=='myink-migrate','unreviewed Compose service')
        if not row['running']:
            require(service=='myink-migrate' and row['status']=='exited','missing running product service');excluded.append(dict(id=row['id'],service=service,image_id=row['image_id'],reason='not_running_migration'));continue
        require(service!='myink-migrate' and row['status']=='running','migration still running');counts[service]+=1;active.append(dict(id=row['id'],service=service,image_id=row['image_id'],healthy=row['healthy']))
    require(all(value==(replicas if role=='myink-worker' else SERVICES[role]) for role,value in counts.items()),'product replica census mismatch')
    python={r['image_id'] for r in active if r['service'] in ('myink-api','myink-worker')};require(len(python)==1,'mixed Python product versions')
    return sorted(active,key=lambda r:r['id']),sorted(excluded,key=lambda r:r['id'])


def observe(config_path,config_sha256,*,runner=None,clock=None):
    c=_load(config_path,config_sha256,runner,clock);now=lambda:utc((clock or (lambda:datetime.now(timezone.utc)))());started=now();deadline=time.monotonic()+45
    root=Path(c['root'])/('observation-'+uuid.uuid4().hex);root.mkdir(mode=0o700);_sync(root.parent);_new(root/'intent.json',dict(schema='pi-product-observation-intent-v1',config_sha256=config_sha256,mode=c['mode'],started_at=started.isoformat()))
    result=dict(schema='pi-product-observation-v1',mode=c['mode'],authority='none',release_allowed=False,model_requests=0,run_id='product-'+root.name.removeprefix('observation-'),observer_config_sha256=config_sha256,observed_at=started.isoformat(),status='blocked',containers=[],excluded=[],images={},metadata=None,metadata_status='unknown',command_proofs=[],deployment_id=None,generation=None,owner=None,source_commit=None,source_sha256=None,config_sha256=None,maintenance_epoch=None,cohort_sha256=None)
    stage='info'
    def command(args):
        remaining=deadline-time.monotonic();require(remaining>0 and file_hash(config_path)==config_sha256,'product observation deadline or config revoked');value=(runner or _native)([c['docker'],'--host',c['endpoint'],*args],remaining)
        require(isinstance(value,dict) and set(value)=={'returncode','stdout','stderr'} and type(value['returncode']) is int and isinstance(value['stdout'],str) and isinstance(value['stderr'],str) and len(value['stdout'].encode())<=1048576 and len(value['stderr'].encode())<=65536,'bounded product command receipt required')
        result['command_proofs'].append(dict(stage=stage,returncode=value['returncode'],stdout_sha256=sha256(value['stdout'].encode()).hexdigest(),stderr_sha256=sha256(value['stderr'].encode()).hexdigest()))
        require(time.monotonic()<deadline and file_hash(config_path)==config_sha256 and value['returncode']==0,'product command/config unconfirmed');return value['stdout']
    def census():
        values=command(['ps','--all','--no-trunc','--filter','label=com.docker.compose.project=myink','--format','{{.ID}}']).splitlines();require(0<len(values)<=128 and len(set(values))==len(values) and all(_hex(v) for v in values),'bounded unique product IDs required');return values
    def inspect(ids):return [strict_json(line) for line in command(['inspect','--format',CONTAINER_FORMAT,*ids]).splitlines()]
    try:
        info=strict_json(command(['info','--format','{{json .}}']));require(isinstance(info,dict) and info.get('ID')==c['daemon_id'],'original Docker daemon mismatch')
        stage='census_before';ids=census();stage='containers_before';before=inspect(ids);active,excluded=_inventory(before,ids,c['worker_replicas']);result.update(containers=active,excluded=excluded)
        stage='images';image_ids=sorted({row['image_id'] for row in before});raw=[strict_json(line) for line in command(['image','inspect','--format',IMAGE_FORMAT,*image_ids]).splitlines()]
        require(len(raw)==len(image_ids) and all(isinstance(r,dict) and set(r)=={'id','revision'} and _image(r['id']) for r in raw) and {r['id'] for r in raw}==set(image_ids),'exact product image inventory required');images={r['id']:r for r in raw}
        for role,service in (('python','myink-api'),('frontend','myink-caddy'),('postgres','myink-pg'),('redis','myink-redis'),('rabbitmq','myink-rabbitmq')):
            iid=next(row['image_id'] for row in active if row['service']==service);claim=images[iid]['revision'];result['images'][role]=dict(image_id=iid,revision_claim=claim if isinstance(claim,str) and re.fullmatch('[0-9a-f]{40}',claim) else None,source_attested=False)
        stage='catalog';pg=next(row['id'] for row in active if row['service']=='myink-pg')
        try:
            text=command(['exec',pg,'psql','-X','-A','-t','-w','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c',METADATA_SQL]);values=[strict_json(line) for line in text.splitlines() if line.startswith('{')];require(len(values)==1 and isinstance(values[0],dict) and set(values[0])==META and all(type(v) is bool for v in values[0].values()),'catalog boolean availability required');result.update(metadata=values[0],metadata_status='observed')
        except (ValueError,OSError,subprocess.SubprocessError):pass  # Unavailable is never "absent".
        stage='census_after';after_ids=census();stage='containers_after';after=inspect(after_ids)
        if set(ids)!=set(after_ids) or digest(sorted(before,key=lambda r:r['id']))!=digest(sorted(after,key=lambda r:r['id'])):result['status']='confounded'
        else:
            _inventory(after,after_ids,c['worker_replicas']);result.update(status='observed',cohort_sha256=digest(dict(containers=active,images=result['images'])))
    except (ValueError,OSError,subprocess.SubprocessError,KeyError,TypeError) as error:result.update(status='blocked',failure_class=type(error).__name__,failure_stage=stage)
    result['completed_at']=now().isoformat();result['observation_sha256']=digest(result);_new(root/'outcome.json',result);return dict(result,observation_path=str(root))
