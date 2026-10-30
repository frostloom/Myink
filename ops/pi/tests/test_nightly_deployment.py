"""Only a human-approved, physically running candidate unlocks observation."""
from pathlib import Path
from datetime import timedelta
import json,uuid
import pytest
from ops.pi.audit import digest
from ops.pi.tests.test_nightly_bundle import bundle_case,finished,stopped,completed,config_file,Image,prepare

FILES={'src/myink/frozen.py':'1'*64}


@pytest.fixture
def deployed_case(bundle_case,monkeypatch):
    original=Image.build
    def image(self,*args):
        value=original(self,*args);value['package_sha256']=digest(FILES);p=self.root/'receipt.json';p.write_text(json.dumps(value));return value
    monkeypatch.setattr(Image,'build',image);prepare(bundle_case)
    g,cycle,root,task,finished,now=bundle_case;packet=json.loads((root/'bundle/manifest.json').read_bytes())
    p=root/'approval.json';value=dict(schema='pi-nightly-human-approval-v1',mode='SIMULATED',issuer='human_operator',cycle_id=cycle,package_sha256=digest(packet),approved_actions=['deploy'],issued_at=now[0].isoformat(),expires_at=(now[0]+timedelta(hours=1)).isoformat());p.write_text(json.dumps(value));p.chmod(0o600)
    from ops.pi.development_inputs import file_hash
    g.approve(cycle,p,file_hash(p));calls=[]
    return bundle_case,calls


class Docker:
    def __init__(self,root,case,calls,fault):self.root=root;self.case=case;self.calls=calls;self.fault=fault
    def run(self,args,**kwargs):
        self.calls.append(args);value=b'';g,cycle,root,task,finished,now=self.case
        if args[:1]==['info']:value=b'fixture-daemon'
        elif args[:1]==['ps']:value=('\n'.join(ch*64 for ch in 'abc')).encode()
        elif args[:2]==['container','inspect']:
            rows=[]
            for i,ch in enumerate('abc'):
                rows.append(dict(Id=ch*64,Image='sha256:'+(('6' if self.fault=='old_image' and i else '7')*64),State=dict(Running=True,OOMKilled=False,StartedAt=now[0].isoformat(),Health=dict(Status='starting' if self.fault=='health' and i==0 else 'healthy')),Config=dict(User='10001',WorkingDir='/app',Entrypoint=None,Cmd=['myink-api' if i==0 else 'myink-worker'],Env=['JWT_SECRET=private-not-for-receipt']+(['PYTHONPATH=/wrong'] if self.fault=='env' else []),Labels={'com.docker.compose.project':'myink','com.docker.compose.service':'myink-api' if i==0 else 'myink-worker'}),HostConfig=dict(Privileged=False),Mounts=[]))
            value=json.dumps(rows).encode()
        elif args[:1]==['exec']:
            files=FILES if self.fault!='source' else {'src/myink/frozen.py':'2'*64};value=json.dumps(dict(package='/usr/local/lib/python3.12/site-packages/myink',files=files)).encode()
        else:raise AssertionError(args)
        name=str(uuid.uuid4());folder=self.root/name;folder.mkdir();(folder/'stdout.bin').write_bytes(value)
        return dict(status='done',returncode=0,command_id=name)


def confirm(case,fault=None):
    from ops.pi.nightly_deployment import confirm
    bundle_case,calls=case;g,cycle,root,*_=bundle_case
    return confirm(g,cycle,root/'bundle',Path('/bin/echo'),'unix:///fixture.sock','fixture-daemon',transport_factory=lambda p:Docker(p,bundle_case,calls,fault))


def test_approved_but_not_deployed_remains_waiting_without_observation(deployed_case):
    r=confirm(deployed_case,'old_image');g=deployed_case[0][0]
    assert r['status']=='awaiting_deployment' and g.status()['phase']=='awaiting_deployment'
    with pytest.raises(ValueError):g.require_action(deployed_case[0][1],'observe_metrics')


def test_actual_image_cohort_source_and_health_produce_separate_receipt(deployed_case):
    result=confirm(deployed_case);g,cycle,root,*_=deployed_case[0]
    assert result['status']=='observing' and result['model_requests']==0
    g.require_action(cycle,'observe_metrics')
    receipt=json.loads(Path(result['deployment_receipt_path']).read_bytes())
    assert receipt['issuer']=='trusted_deployment_verifier' and receipt['image_id']=='sha256:'+'7'*64
    assert 'JWT_SECRET' not in json.dumps(receipt) and 'private-not-for-receipt' not in json.dumps(receipt)
    assert not any(a[0] in ('run','build','push','start','stop') for a in deployed_case[1])


@pytest.mark.parametrize('fault',['env','source'])
def test_mismatched_runtime_does_not_unlock_observation(deployed_case,fault):
    with pytest.raises(ValueError):confirm(deployed_case,fault)
    assert deployed_case[0][0].status()['phase']=='awaiting_deployment'


def test_starting_health_waits_without_claiming_deployment(deployed_case):
    assert confirm(deployed_case,'health')['status']=='awaiting_deployment'
    assert deployed_case[0][0].status()['phase']=='awaiting_deployment'


def test_no_approval_never_reads_docker(bundle_case):
    prepare(bundle_case);g,cycle,root,*_=bundle_case
    from ops.pi.nightly_deployment import confirm
    with pytest.raises(ValueError):confirm(g,cycle,root/'bundle',Path('/bin/echo'),'unix:///fixture.sock','fixture-daemon',transport_factory=lambda p:pytest.fail('unapproved runtime read'))
