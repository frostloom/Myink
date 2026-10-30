"""Read-only physical deployment attestation, separate from human approval.

No push/start/stop/build occurs here. Only the exact approved image across the
API and both workers, healthy and with matching installed code, can produce a
root-issued deployment receipt. Docker command material remains private.
"""
from pathlib import Path
import os,pwd,stat,uuid
from .audit import _path,require,strict_json,digest,utc,hash_value
from .nightly_gate import BASE
from .nightly_bundle import verify
from .nightly_image import PROBE
from .product_commands import DockerCommands,_write

PRODUCTION='0f90c176-9c45-4708-8103-37b5ff2464f1'


def _run(commands,args,*,timeout=30):
    r=commands.run(args,timeout=timeout,output_limit=4194304);require(r['status']=='done' and r['returncode']==0,'deployment identity read unconfirmed')
    return (commands.root/r['command_id']/'stdout.bin').read_bytes()


def _identity(env,image):
    values={}
    for item in env:
        key,sep,value=item.partition('=');require(sep and key not in values,'unique runtime environment required');values[key]=value
    generation=values.get('DEPLOYMENT_GENERATION','');require(generation.isdecimal() and len(generation)<=10,'known product generation required')
    identity=dict(deployment_id=values.get('DEPLOYMENT_ID'),generation=int(generation),owner=values.get('DEPLOYMENT_OWNER'),image_ids=strict_json(values.get('DEPLOYMENT_IMAGE_IDS','null')),commit_sha=values.get('DEPLOYMENT_COMMIT_SHA'),schema_id=values.get('OBSERVATION_SCHEMA_ID'),config_hash=values.get('OBSERVATION_CONFIG_ID'))
    from .live_observer import _identity as validate
    validate(identity)
    require(all(v is not None for v in identity.values()) and hash_value(identity['commit_sha'],40) and hash_value(identity['config_hash']) and identity['image_ids'].get('python')==image,'complete deployed product provenance required')
    return identity


def _cohort(commands,image,package_sha256,now):
    ids=_run(commands,['ps','--quiet','--filter','label=com.docker.compose.project=myink']).decode().split()
    require(0<len(ids)<=32,'bounded live product census required');rows=strict_json(_run(commands,['container','inspect',*ids]))
    selected=[r for r in rows if r['Config'].get('Labels',{}).get('com.docker.compose.service') in ('myink-api','myink-worker')]
    roles=[r['Config']['Labels']['com.docker.compose.service'] for r in selected]
    if roles.count('myink-api')!=1 or roles.count('myink-worker')!=2 or any(r['Image']!=image for r in selected):return None,'approved_image_not_running'
    snapshots=[]
    for row in sorted(selected,key=lambda r:r['Id']):
        state=row['State'];c=row['Config'];role=c['Labels']['com.docker.compose.service']
        if state['Running'] is not True or state.get('OOMKilled') or state.get('Health',{}).get('Status','healthy')!='healthy':return None,'runtime_not_healthy'
        require(c['User']=='10001' and c['WorkingDir']=='/app' and c.get('Entrypoint') in (None,[]) and c['Cmd']==['myink-api' if role=='myink-api' else 'myink-worker'],'fixed application commands required')
        keys={v.partition('=')[0] for v in c.get('Env',[])}
        require(not keys&{'PYTHONPATH','PYTHONHOME','LD_PRELOAD'} and not row.get('HostConfig',{}).get('Privileged'),'runtime interpreter override rejected')
        require(all(not m['Destination'].startswith(('/usr/local','/app/src')) for m in row.get('Mounts',[])),'installed package mount override rejected')
        identity=_identity(c.get('Env',[]),image)
        started=utc(state['StartedAt']);require(started<=now,'runtime start is in the future')
        probe=strict_json(_run(commands,['exec','--user','10001:10001',row['Id'],'python','-I','-S','-B','-c',PROBE]))
        require(set(probe)=={'package','files'} and digest(probe['files'])==package_sha256,'running installed package differs from frozen image')
        snapshots.append(dict(container_id=row['Id'],image_id=row['Image'],role=role,started_at=started.isoformat(),identity=identity,config_sha256=digest(dict(config=c,host=row.get('HostConfig',{}),mounts=row.get('Mounts',[])))))
    require(all(r['identity']==snapshots[0]['identity'] for r in snapshots),'mixed deployed product provenance')
    return snapshots,None


def confirm(gate,cycle,bundle,docker,endpoint,daemon_id,*,transport_factory=None):
    gate.require_action(cycle,'deploy');bundle=_path(bundle);packet=verify(gate,bundle)
    if gate.mode=='ACTUAL':require(os.geteuid()==0 and transport_factory is None and _path(docker)==Path('/usr/bin/docker') and endpoint=='unix:///var/run/docker.sock' and daemon_id==PRODUCTION and bundle==BASE/'nightly'/cycle/'bundle','fixed ACTUAL deployment verifier required')
    else:require(daemon_id!=PRODUCTION and not bundle.is_relative_to(BASE),'isolated deployment verification required')
    with gate._connection() as c:
        row=gate._row(c,cycle);approval=gate._approval(row)
    parent=bundle.parent/'deployment-checks'
    if not parent.exists():parent.mkdir(mode=0o700)
    require(parent.resolve()==parent and stat.S_IMODE(parent.stat().st_mode)==0o700,'private deployment evidence directory required')
    attempt=parent/str(uuid.uuid4());attempt.mkdir(mode=0o700);commands_root=attempt/'commands';commands_root.mkdir(mode=0o700)
    commands=transport_factory(commands_root) if transport_factory else DockerCommands(docker,endpoint,commands_root)
    require(_run(commands,['info','--format','{{.ID}}']).decode().strip()==daemon_id,'original Docker daemon drift')
    context,reason=_cohort(commands,packet['manifest']['image_id'],packet['image']['package_sha256'],utc(gate.clock()))
    if context is None:return dict(status='awaiting_deployment',verified=False,reason=reason,model_requests=0)
    issued=utc(approval['packet']['issued_at']);require(all(utc(r['started_at'])>=issued for r in context),'running cohort predates human approval')
    deployed=max(utc(r['started_at']) for r in context)
    deployment_id=context[0]['identity']['deployment_id']
    _write(attempt/'context.json',dict(schema='pi-nightly-deployed-cohort-v1',cycle_id=cycle,deployment_id=deployment_id,cohort_sha256=digest(context),containers=context))
    receipt=dict(schema='pi-nightly-deployment-receipt-v1',mode=gate.mode,issuer='trusted_deployment_verifier',cycle_id=cycle,package_sha256=digest(packet['manifest']),approval_sha256=approval['sha256'],image_id=packet['manifest']['image_id'],source_sha256=packet['manifest']['source_sha256'],comparison_sha256=packet['manifest']['comparison_sha256'],deployment_id=deployment_id,deployed_at=deployed.isoformat())
    folder=BASE/'config/deployment-receipts' if gate.mode=='ACTUAL' else bundle.parent/'deployment-receipts'
    if not folder.exists():
        folder.mkdir(mode=0o750 if gate.mode=='ACTUAL' else 0o700)
        if gate.mode=='ACTUAL':os.chmod(folder,0o750);os.chown(folder,0,pwd.getpwnam('ubuntu').pw_gid)
    path=folder/(cycle+'.json');require(not path.exists(),'existing deployment receipt cannot be replaced');_write(path,receipt)
    if gate.mode=='ACTUAL':os.chmod(path,0o640);os.chown(path,0,pwd.getpwnam('ubuntu').pw_gid)
    _write(bundle.parent/'deployment-context.json',dict(schema='pi-nightly-deployed-context-v1',cycle_id=cycle,deployment_receipt_sha256=digest(receipt),cohort_sha256=digest(context),containers=context))
    result=gate.deployed(cycle,path,digest(receipt));return dict(status=result['phase'],verified=True,deployment_receipt_path=str(path),model_requests=0)
