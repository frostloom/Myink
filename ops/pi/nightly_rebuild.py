"""Explicit model-free operator rebuild; scheduled entry points cannot call it."""
from pathlib import Path
from collections import Counter
import os,stat,fcntl
from .audit import _path,_plain,require,strict_json,digest,hash_value,validate_record
from .nightly_gate import BASE
from .nightly_bundle import verify,prepare
from .nightly_image import image_id,probe_image
from .nightly_deployment import _run,PRODUCTION
from .product_commands import DockerCommands,_write,_sync
from .development_inputs import file_hash,ledger_snapshot
from . import manager_completion

FILES={'src/myink/config.py','src/myink/observability.py','src/myink/workflow/nodes.py'}
FIELDS=set('schema mode issuer cycle_id package_sha256 parent_image_id image_id parent_package_sha256 package_map_sha256 patch_sha256 changes'.split())


def _json(path):
    path=_path(path);_plain(path);require(path.stat().st_size<=65536,'bounded operator input required');return strict_json(path.read_bytes())


def _product(commands,parent):
    ids=_run(commands,['ps','--quiet','--filter','label=com.docker.compose.project=myink']).decode().split();require(0<len(ids)<=32,'bounded current product census required')
    rows=strict_json(_run(commands,['container','inspect',*ids]));selected=[r for r in rows if r['Config'].get('Labels',{}).get('com.docker.compose.service') in ('myink-api','myink-worker')]
    require(Counter(r['Config']['Labels']['com.docker.compose.service'] for r in selected)==Counter({'myink-api':1,'myink-worker':2}),'fixed API/worker cohort required')
    require(all(r['Image']==parent and r['State']['Running'] is True and not r['State'].get('OOMKilled') and r['State'].get('Health',{}).get('Status','healthy')=='healthy' for r in selected),'compatibility parent is not the healthy current product')
    return digest([dict(id=r['Id'],image=r['Image'],started_at=r['State'].get('StartedAt'),pid=r['State'].get('Pid'),config=r['Config'],host=r.get('HostConfig',{}),mounts=r.get('Mounts',[])) for r in sorted(selected,key=lambda r:r['Id'])])


def verify_base(gate,cycle,report,root):
    require(gate.mode=='ACTUAL' and os.geteuid()==0,'fixed actual base verifier required');root.mkdir(mode=0o700);(root/'commands').mkdir(mode=0o700);commands=DockerCommands(Path('/usr/bin/docker'),'unix:///var/run/docker.sock',root/'commands')
    require(_run(commands,['info','--format','{{.ID}}']).decode().strip()==PRODUCTION,'original product daemon changed')
    before=_product(commands,report['parent_image_id']);probes=[]
    for key in ('parent_image_id','image_id'):
        image=report[key];rows=strict_json(_run(commands,['image','inspect',image]));require(len(rows)==1 and rows[0]['Id']==image and rows[0]['Os']=='linux' and rows[0]['Config']['User']=='10001' and rows[0]['Config']['WorkingDir']=='/app' and rows[0]['Config'].get('OnBuild') in (None,[]),'fixed nonroot application image required')
        probes.append(probe_image(commands,image,cycle,active=lambda:gate.require_preparation(cycle,gate.status()['task_id'],report['image_id'])))
    parent,target=probes;require(parent['package']==target['package'] and digest(parent['files'])==report['parent_package_sha256'] and digest(target['files'])==report['package_map_sha256'],'compatibility package digest changed')
    require(all(parent['files'].get(f)==v['before'] for f,v in report['changes'].items()) and target['files']==dict(parent['files'],**{f:v['after'] for f,v in report['changes'].items()}),'base changed outside approved telemetry files')
    require(_product(commands,report['parent_image_id'])==before,'product changed during base verification')
    result=dict(verified=True,image_id=report['image_id'],package_sha256=report['package_map_sha256']);_write(root/'receipt.json',result);return result


def run(gate,old_cycle,permission_path,permission_pin,compatibility_path,lock_path,*,verifier=None,image_factory=None,check=None):
    lock_path=_path(lock_path);_plain(lock_path)
    if gate.mode=='ACTUAL':require(os.geteuid()==0 and verifier is None and image_factory is None and check is None and lock_path==BASE/'control/nightly.lock','root fixed operator rebuild required')
    else:require(callable(verifier) and callable(image_factory) and callable(check),'explicit isolated operator verifier/image/checker required')
    with lock_path.open('rb') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return dict(status='lock_busy',model_requests=0)
        permission=gate._trusted(permission_path,permission_pin,'rebuild');new=permission['new_cycle_id']
        old_root=BASE/'nightly'/old_cycle if gate.mode=='ACTUAL' else lock_path.parent/old_cycle
        packet=verify(gate,old_root/'bundle');compatibility_path=_path(compatibility_path);report=_json(compatibility_path)
        require(file_hash(compatibility_path)==permission['compatibility_sha256'] and set(report)==FIELDS and report['schema']=='pi-nightly-compatible-base-v1' and report['mode']==gate.mode and report['issuer']=='trusted_compatibility_builder' and report['cycle_id']==old_cycle and report['package_sha256']==digest(packet['manifest']) and report['image_id']==permission['base_image_id'],'human-bound compatible base report required')
        image_id(report['parent_image_id']);image_id(report['image_id']);require(all(hash_value(report[k]) for k in ('parent_package_sha256','package_map_sha256','patch_sha256')) and isinstance(report['changes'],dict) and set(report['changes'])==FILES,'fixed compatibility file scope required')
        require(all(isinstance(v,dict) and set(v)=={'before','after'} and (v['before'] is None or hash_value(v['before'])) and hash_value(v['after']) for v in report['changes'].values()),'compatibility file digests required')
        if gate.mode=='ACTUAL':require(compatibility_path==BASE/'config/compatible-bases'/(report['image_id'][7:]+'.json') and compatibility_path.stat().st_uid==0 and stat.S_IMODE(compatibility_path.stat().st_mode)==0o640 and compatibility_path.parent.stat().st_uid==0 and stat.S_IMODE(compatibility_path.parent.stat().st_mode)==0o750,'root compatibility report required')
        with gate._connection() as c:task=gate._row(c,old_cycle)['task_id']
        before=ledger_snapshot(gate.state),ledger_snapshot(gate.billing)
        manager_completion.inspect(gate.state,gate.billing,task,old_root/'bundle/request.json',file_hash(old_root/'bundle/request.json'),mode=gate.mode)
        gate.begin_rebuild(old_cycle,permission_path,permission_pin);root=old_root.parent/new
        try:
            if (root/'rebuild-receipt.json').exists():
                result=_json(root/'rebuild-receipt.json');current=verify(gate,root/'bundle')
                require(result['cycle_id']==new and result['permission_sha256']==permission_pin and result['compatibility_sha256']==file_hash(compatibility_path) and result['package_sha256']==digest(current['manifest']) and result['test_result_sha256']==digest(_json(root/'rebuild-check/result.json')),'operator rebuild receipt drift');return result
            require(not root.exists(),'interrupted operator rebuild retained; no replay');root.mkdir(mode=0o700);_write(root/'rebuild-intent.json',dict(previous_cycle_id=old_cycle,permission_sha256=permission_pin,compatibility_sha256=file_hash(compatibility_path)))
            result=(verifier or verify_base)(gate,new,report,root/'base-verification');require(result.get('verified') is True and result.get('image_id')==report['image_id'] and result.get('package_sha256')==report['package_map_sha256'],'physical compatible base unconfirmed')
            docker=Path('/usr/bin/docker') if gate.mode=='ACTUAL' else Path('/bin/echo');endpoint='unix:///var/run/docker.sock' if gate.mode=='ACTUAL' else 'unix:///fixture.sock';daemon=PRODUCTION if gate.mode=='ACTUAL' else 'fixture-daemon'
            prepare(gate,new,root/'bundle',task,report['image_id'],docker,endpoint,daemon,image_factory=image_factory,seal=False);fresh=verify(gate,root/'bundle',staged=True);comparison=fresh['comparison']
            directory=root/'rebuild-check';directory.mkdir(mode=0o700)
            if check is None:
                from .followup import _isolated_check
                check=_isolated_check
            e=dict(candidate_path=str(root/'bundle/candidate'),test_path=str(root/'bundle/regression.py'),test_sha256=comparison['test_sha256'],test_cases=comparison['test_cases'],checker=dict(docker=str(docker),endpoint=endpoint,daemon_id=daemon,checker_image_id=fresh['manifest']['image_id']))
            tested=check(e,directory,lambda name,value:_write(directory/name,value));_write(directory/'result.json',tested)
            require(tested.get('passed') is True and tested.get('tests')==len(comparison['test_cases']) and all(tested.get(k)==0 for k in ('failures','errors','skipped')) and tested.get('cleanup') and all(r.get('removed') is True for r in tested['cleanup']),'compatible image regression or cleanup failed')
            require((ledger_snapshot(gate.state),ledger_snapshot(gate.billing))==before,'original accounting changed during operator rebuild')
            evaluation=dict(fresh['evaluation'],rebuild_check_sha256=digest(tested),rebuild_compatibility_sha256=file_hash(compatibility_path));manifest=dict(fresh['manifest'],evaluation_sha256=digest(evaluation))
            for name,value in (('evaluation.json',evaluation),('manifest.json',manifest)):
                temporary=root/'bundle'/('final-'+name);_write(temporary,value);os.replace(temporary,root/'bundle'/name)
            _sync(root/'bundle');fresh=verify(gate,root/'bundle',staged=True);gate.ready(new,fresh['manifest'])
            result=dict(schema='pi-nightly-operator-rebuild-result-v1',status='awaiting_approval',cycle_id=new,previous_cycle_id=old_cycle,permission_sha256=permission_pin,compatibility_sha256=file_hash(compatibility_path),package_sha256=digest(fresh['manifest']),test_result_sha256=digest(tested),model_requests=0,known_cost_microyuan=0,pushed=False,deployed=False)
            event=dict(kind='version',status='no_release',run_id=task,occurred_at=gate.clock().isoformat(),summary='Same original candidate rebuilt on the human-approved compatibility base; no publication.',details=dict(reference='nightly.operator_rebuild.v1',operation_id=new,model_requests=0,known_cost_microyuan=0,next_action='review_exact_package'),version=dict(candidate_sha256=fresh['manifest']['source_sha256'],image_ids=dict(python=fresh['manifest']['image_id'])),changes=fresh['changes'],evidence=[dict(kind='human_rebuild_permission',sha256=permission_pin,verified=True,evidence_domain='offline' if gate.mode=='ACTUAL' else 'synthetic')],followups=[],mode=gate.mode,evidence_domain='offline' if gate.mode=='ACTUAL' else 'synthetic');validate_record(event)
            _write(root/'rebuild-audit.json',dict(schema='pi-nightly-rebuild-audit-v1',records=[dict(record_key=task+':rebuild:'+new,event=event)]));_write(root/'rebuild-receipt.json',result);return result
        except Exception:
            gate.block(new,'operator_rebuild_stopped');raise
