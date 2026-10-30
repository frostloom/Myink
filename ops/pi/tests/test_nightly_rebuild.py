"""Explicit operator packaging reuses completed work and never grants release."""
from pathlib import Path
from datetime import timedelta
import json,uuid
import pytest
from ops.pi.tests.test_nightly_bundle import bundle_case,finished,stopped,completed,config_file,Image,prepare
from ops.pi.audit import digest
from ops.pi.development_inputs import file_hash,ledger_snapshot


@pytest.fixture
def rebuild_case(bundle_case):
    prepare(bundle_case);g,old,root,task,finished,now=bundle_case;new=str(uuid.uuid4());manifest=json.loads((root/'bundle/manifest.json').read_bytes())
    changes={f:dict(before=None if f.endswith('observability.py') else 'a'*64,after='b'*64) for f in ('src/myink/config.py','src/myink/observability.py','src/myink/workflow/nodes.py')}
    report=dict(schema='pi-nightly-compatible-base-v1',mode='SIMULATED',issuer='trusted_compatibility_builder',cycle_id=old,package_sha256=digest(manifest),parent_image_id='sha256:'+'6'*64,image_id='sha256:'+'9'*64,parent_package_sha256='c'*64,package_map_sha256='d'*64,patch_sha256='e'*64,changes=changes)
    rp=root/'compatibility.json';rp.write_text(json.dumps(report));rp.chmod(0o600)
    value=dict(schema='pi-nightly-human-rebuild-v1',mode='SIMULATED',issuer='human_operator',action='prepare_same_candidate',cycle_id=old,package_sha256=digest(manifest),new_cycle_id=new,night='2026-11-01',base_image_id=report['image_id'],compatibility_sha256=file_hash(rp),issued_at=now[0].isoformat(),expires_at=(now[0]+timedelta(hours=2)).isoformat())
    permission=root/'rebuild.json';permission.write_text(json.dumps(value));permission.chmod(0o600);lock=root.parent/'nightly.lock';lock.touch(mode=0o600)
    calls=[]
    def verify(gate,cycle,r,folder):calls.append('verify');return dict(verified=True,image_id=r['image_id'],package_sha256=r['package_map_sha256'])
    return bundle_case,new,permission,rp,lock,calls,verify


def run(case,**kwargs):
    from ops.pi.nightly_rebuild import run
    original,new,permission,rp,lock,calls,verify=case;g,old,*_=original
    def check(e,*a):calls.append('checker');return dict(passed=True,tests=len(e['test_cases']),failures=0,errors=0,skipped=0,cleanup=[dict(removed=True)])
    return run(g,old,permission,file_hash(permission),rp,lock,verifier=kwargs.get('verifier',verify),image_factory=Image,check=kwargs.get('check',check))


def test_operator_rebuild_retains_old_bundle_and_original_ledgers_then_waits(rebuild_case):
    case,new,permission,rp,lock,calls,verify=rebuild_case;g,old,root,task,finished,now=case;before=ledger_snapshot(g.state),ledger_snapshot(g.billing);oldfiles={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()};count=len(Image.calls)
    result=run(rebuild_case)
    assert result['status']=='awaiting_approval' and result['cycle_id']==new and calls==['verify','checker'] and len(Image.calls)==count+1
    assert (ledger_snapshot(g.state),ledger_snapshot(g.billing))==before and all(Path(p).read_bytes()==v for p,v in oldfiles.items())
    assert run(rebuild_case)==result and calls==['verify','checker'] and len(Image.calls)==count+1
    for action in ('github_push','registry_push','deploy','observe_metrics'):
        with pytest.raises(ValueError):g.require_action(new,action)


@pytest.mark.parametrize('fault',['human','report','verifier'])
def test_invalid_permission_or_base_cannot_build(rebuild_case,fault):
    case,new,permission,rp,lock,calls,verify=rebuild_case;g,old,root,*_=case;count=len(Image.calls)
    if fault=='human':v=json.loads(permission.read_bytes());v['issuer']='model';permission.write_text(json.dumps(v))
    elif fault=='report':v=json.loads(rp.read_bytes());v['image_id']='sha256:'+'8'*64;rp.write_text(json.dumps(v))
    with pytest.raises(ValueError):run(rebuild_case,verifier=(lambda *a:dict(verified=False)) if fault=='verifier' else verify)
    assert len(Image.calls)==count
    if fault!='verifier':assert g.status()['cycle_id']==old
    else:assert g.status()['phase']=='blocked' and g.status()['cycle_id']==new


def test_interrupted_operator_claim_has_no_automatic_replay(rebuild_case):
    case,new,permission,rp,lock,calls,verify=rebuild_case;g,old,root,*_=case;g.begin_rebuild(old,permission,file_hash(permission));out=root.parent/new;out.mkdir(mode=0o700);(out/'rebuild-intent.json').write_text('{}');count=len(Image.calls)
    with pytest.raises(ValueError):run(rebuild_case)
    assert calls==[] and len(Image.calls)==count and g.status()['phase']=='blocked'


def test_failed_compatible_image_gold_stops_without_release(rebuild_case):
    with pytest.raises(ValueError):run(rebuild_case,check=lambda *a:dict(passed=False,tests=1,failures=1,errors=0,skipped=0,cleanup=[dict(removed=True)]))
    assert rebuild_case[0][0].status()['phase']=='blocked'


def test_cached_rebuild_requires_unchanged_new_checker_receipt(rebuild_case):
    result=run(rebuild_case);root=rebuild_case[0][2].parent/result['cycle_id'];path=root/'rebuild-check/result.json';v=json.loads(path.read_bytes());v['failures']=1;path.write_text(json.dumps(v))
    with pytest.raises(ValueError):run(rebuild_case)


def test_crash_during_new_image_check_leaves_no_approvable_package(rebuild_case):
    g=rebuild_case[0][0]
    def crash(*a):
        assert g.status()['phase']=='preparing'
        raise KeyboardInterrupt('simulated hard interruption')
    with pytest.raises(KeyboardInterrupt):run(rebuild_case,check=crash)
    new=rebuild_case[1]
    assert g.status()['phase']=='preparing'
    with g._connection() as c:assert g._row(c,new)['package'] is None
    with pytest.raises(ValueError):g.require_action(new,'deploy')


@pytest.mark.parametrize('fault',[None,'outside','parent_not_current','cleanup','healthy_log'])
def test_actual_verifier_checks_maps_current_parent_and_owned_cleanup(tmp_path,monkeypatch,fault):
    from types import SimpleNamespace
    from ops.pi import nightly_rebuild as module
    from ops.pi.nightly_image import LABEL
    from ops.pi.nightly_deployment import PRODUCTION
    before={'src/myink/config.py':'a'*64,'src/myink/workflow/nodes.py':'a'*64,'src/myink/workflow/short_parse.py':'f'*64};after=dict(before,**{p:'b'*64 for p in module.FILES})
    if fault=='outside':after['src/myink/unrelated.py']='c'*64
    report=dict(parent_image_id='sha256:'+'6'*64,image_id='sha256:'+'9'*64,parent_package_sha256=digest(before),package_map_sha256=digest(after),changes={p:dict(before=before.get(p),after='b'*64) for p in module.FILES});cycle=str(uuid.uuid4());calls=[]
    class Commands:
        def __init__(self,docker,endpoint,root):self.root=root;self.probes={};self.census=0
        def run(self,args,**kwargs):
            calls.append(args)
            if args[0]=='info':value=PRODUCTION.encode()
            elif args[0]=='ps':value=(' '.join(c*64 for c in 'abc')).encode()
            elif args[:2]==['image','inspect']:value=json.dumps([dict(Id=args[2],Os='linux',Config=dict(User='10001',WorkingDir='/app',OnBuild=None))]).encode()
            elif args[0]=='create':cid=uuid.uuid4().hex*2;self.probes[cid]=args[args.index('--entrypoint')+2];value=cid.encode()
            elif args[0]=='start':value=json.dumps(dict(package='/usr/local/lib/python3.12/site-packages/myink',files=before if self.probes[args[-1]]==report['parent_image_id'] else after)).encode()
            elif args[:2]==['container','inspect']:
                if args[-1] in self.probes:value=json.dumps([dict(Id=args[-1],State=dict(Running=False),Config=dict(Labels={LABEL:'wrong' if fault=='cleanup' else cycle}))]).encode()
                else:
                    self.census+=1
                    value=json.dumps([dict(Id=c*64,Image='sha256:'+'8'*64 if fault=='parent_not_current' else report['parent_image_id'],State=dict(Running=True,Health=dict(Status='healthy',Log=[dict(End=self.census if fault=='healthy_log' else 0)])),Config=dict(Labels={'com.docker.compose.service':'myink-api' if i==0 else 'myink-worker'})) for i,c in enumerate('abc')]).encode()
            elif args[:2]==['container','rm']:value=b''
            else:raise AssertionError(args)
            folder=self.root/uuid.uuid4().hex;folder.mkdir();(folder/'stdout.bin').write_bytes(value);return dict(status='done',returncode=0,command_id=folder.name)
    monkeypatch.setattr(module,'DockerCommands',Commands);monkeypatch.setattr(module.os,'geteuid',lambda:0)
    gate=SimpleNamespace(mode='ACTUAL',status=lambda:dict(task_id='original'),require_preparation=lambda *a:None)
    if fault not in (None,'healthy_log'):
        with pytest.raises(ValueError):module.verify_base(gate,cycle,report,tmp_path/'verify')
    else:
        assert module.verify_base(gate,cycle,report,tmp_path/'verify')['verified'] is True
        assert sum(a[:2]==['container','rm'] for a in calls)==2
        assert all(a[0] not in ('build','push','run','stop') for a in calls)
