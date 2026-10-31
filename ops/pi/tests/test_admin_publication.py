"""Publication source identity is a real local Git object, not a base label."""
from pathlib import Path
from hashlib import sha256
import os
import subprocess
import pytest
from ops.pi.audit import digest


def git(root,*args,stdin=None):
    return subprocess.run(['/usr/bin/git','-C',str(root),*args],input=stdin,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout


@pytest.fixture
def repository(tmp_path):
    root=tmp_path/'repository';root.mkdir();git(root,'init','--quiet');git(root,'config','user.name','Fixture');git(root,'config','user.email','fixture@example.test')
    source=root/'src/myink';source.mkdir(parents=True);(source/'__init__.py').write_text('');(source/'budget.py').write_text('budget = 1\n')
    git(root,'add','.');git(root,'commit','--quiet','-m','base');commit=git(root,'rev-parse','HEAD').decode().strip()
    candidate=tmp_path/'candidate/src/myink';candidate.mkdir(parents=True);(candidate/'budget.py').write_text('budget = 2\n')
    files={'src/myink/__init__.py':sha256(b'').hexdigest(),'src/myink/budget.py':sha256(b'budget = 2\n').hexdigest()}
    work=tmp_path/'publication';work.mkdir(mode=0o700)
    return root,commit,candidate.parents[1],files,work


def test_exact_candidate_gets_a_real_commit_without_changing_or_pushing_main(repository):
    from ops.pi.admin_publication import candidate_commit, package_files
    root,base,candidate,files,work=repository;before=git(root,'status','--porcelain')
    result=candidate_commit(root/'.git',base,candidate,digest(files),work)
    assert len(result)==40 and result!=base and package_files(root/'.git',result)==files
    assert git(root,'show',result+':src/myink/budget.py')==b'budget = 2\n'
    assert git(root,'rev-parse','HEAD').decode().strip()==base and git(root,'status','--porcelain')==before
    assert git(root,'show','-s','--format=%P',result).decode().strip()==base


def test_git_source_mismatch_cannot_be_used_as_candidate_provenance(repository):
    from ops.pi.admin_publication import candidate_commit
    root,base,candidate,files,work=repository
    with pytest.raises(ValueError):candidate_commit(root/'.git',base,candidate,'0'*64,work)
    assert git(root,'rev-parse','HEAD').decode().strip()==base


def test_candidate_cannot_add_non_python_scope_to_publication(repository):
    from ops.pi.admin_publication import candidate_commit
    root,base,candidate,files,work=repository;(candidate/'startup.sh').write_text('arbitrary shell')
    with pytest.raises(ValueError):candidate_commit(root/'.git',base,candidate,digest(files),work)


def test_git_source_cannot_follow_a_source_file_symlink(repository):
    from ops.pi.admin_publication import package_files
    root,base,candidate,files,work=repository;(root/'src/myink/budget.py').unlink();os.symlink('/etc/passwd',root/'src/myink/budget.py');git(root,'add','.');git(root,'commit','--quiet','-m','symlink fixture');bad=git(root,'rev-parse','HEAD').decode().strip()
    with pytest.raises(ValueError):package_files(root/'.git',bad)


from ops.pi.tests.test_nightly_gate import case


@pytest.fixture
def native_case(repository,case,monkeypatch):
    import json, shutil, uuid
    from ops.pi import admin_publication as module, nightly_deployment, nightly_rebuild, nightly_image
    from ops.pi.development_inputs import file_hash, ledger_snapshot
    root,base,candidate,files,work=repository;gate=case[0](True);cycle=str(uuid.uuid4());gate.begin(cycle,'2026-10-31');gate.ready(cycle,case[2]);bundle=work/'bundle';bundle.mkdir(mode=0o700);shutil.copytree(candidate,bundle/'candidate');image=case[2]['image_id'];base_image='sha256:'+'6'*64
    packet=dict(manifest=case[2],image=dict(base_image_id=base_image,package_sha256=digest(files)))
    compose=root/'docker-compose.yml';compose.write_text('synthetic fixture only');config_path=root/'publication.json';config_path.write_text(json.dumps(dict(schema='pi-admin-publication-v1',mode='SIMULATED',source_repository=str(root/'.git'),compose_files=[str(compose)])));config_path.chmod(0o600)
    environment=dict(DEPLOYMENT_ID='fixture-base',DEPLOYMENT_GENERATION='1',DEPLOYMENT_OWNER='fixture-owner',DEPLOYMENT_IMAGE_IDS=json.dumps({'python':base_image}),DEPLOYMENT_COMMIT_SHA=base,OBSERVATION_SCHEMA_ID='myink-run-provenance-v1',OBSERVATION_CONFIG_ID='5'*64)
    identity=nightly_deployment._identity([k+'='+v for k,v in environment.items()],base_image)
    class Transport:
        def __init__(self,folder):self.root=folder
        def run(self,args,**kwargs):
            holder.calls.append(args)
            if args[:1]==['info']:body=b'simulation-console-daemon'
            elif args[:1]==['ps']:body=b'postgres' if any('myink-pg' in a for a in args) else b'rabbit' if any('myink-rabbitmq' in a for a in args) else b'api worker1 worker2'
            elif args[:2]==['container','inspect']:
                body=json.dumps([dict(Config=dict(Labels={'com.docker.compose.service':role,'com.docker.compose.config-hash':'7'*64},Cmd=[role],Env=[k+'='+v for k,v in dict(environment,JWT_SECRET='PRIVATE_KEEP').items()]),Mounts=[]) for role in ('myink-api','myink-worker','myink-worker')]).encode()
            elif args[:2]==['image','ls']:body=b''
            elif args[:2]==['image','tag']:holder.alias=args[-1];body=b''
            elif args[:2]==['image','inspect']:body=json.dumps([{'Id':base_image if args[-1]==base_image else 'sha256:'+'0'*64 if holder.alias_drift else image,'Config':{'Env':[]}}]).encode()
            elif args[:1]==['exec'] and args[1]=='postgres':
                sql=args[-1]
                if 'UPDATE public.maintenance_control' in sql:
                    import re
                    value=json.loads(re.search(r"WITH desired AS \(SELECT '((?:[^']|'')*)'::jsonb AS value",sql).group(1).replace("''", "'"))
                    if value['admission_closed'] and not holder.control_closed:holder.control_updates.append('closed')
                    elif value['admission_closed']:holder.control_updates.append('identity')
                    else:holder.control_updates.append('opened')
                    holder.control=value;holder.control_closed=value['admission_closed'];body=json.dumps(value).encode()
                elif 'active_tasks' in sql:body=json.dumps({'active_tasks':int(holder.inflight),'executions':0,'pending_admissions':0,'pending_handoffs':0}).encode()
                else:body=json.dumps(holder.control).encode()
            elif args[:1]==['exec']:body=('queue:tasks\t'+('1' if holder.busy else '0')+'\t0\nqueue:tasks:vip\t0\t0\n').encode()
            elif args[:1]==['compose'] and '--hash' in args:body=(args[-1]+' '+('8' if holder.config_drift else '7')*64+'\n').encode()
            elif args[:1]==['compose'] and 'config' in args:
                value={'services':{k:dict(image=base_image,command=[k],environment=dict(environment,JWT_SECRET='PRIVATE_KEEP'),volumes=[]) for k in ('myink-api','myink-worker')}}
                if holder.config_drift:value['services']['myink-api']['environment']['JWT_SECRET']='CHANGED_PRIVATE'
                inputs=[args[i+1] for i,x in enumerate(args[:-1]) if x=='-f']
                if inputs[-1].endswith('compose.override.json'):
                    override=json.loads(Path(inputs[-1]).read_bytes())
                    for k,v in override['services'].items():value['services'][k].update({n:x for n,x in v.items() if n!='environment'});value['services'][k]['environment'].update(v['environment'])
                body=json.dumps(value).encode()
            elif args[:1]==['compose'] and 'up' in args:
                if holder.compose_failed:raise ValueError('fixture compose failure')
                holder.deployed=True;inputs=[args[i+1] for i,x in enumerate(args[:-1]) if x=='-f'];env=json.loads(Path(inputs[-1]).read_bytes())['services']['myink-api']['environment'];holder.deployed_identity=nightly_deployment._identity([k+'='+v for k,v in env.items()],image);body=b''
            else:raise AssertionError(args)
            identity=str(uuid.uuid4());folder=self.root/identity;folder.mkdir(mode=0o700);(folder/'stdout.bin').write_bytes(body);return dict(status='done',returncode=0,command_id=identity)
    from types import SimpleNamespace
    holder=SimpleNamespace(calls=[],busy=False,product_drift=False,config_drift=False,alias_drift=False,deployed=False,deployed_identity=None,inflight=False,control_closed=False,control_updates=[],compose_failed=False)
    holder.control=dict(id=1,epoch='original-epoch',deployment_id=identity['deployment_id'],generation=identity['generation'],owner=identity['owner'],image_ids=identity['image_ids'],deadline=None,admission_closed=False,consumer_blocked=False)
    def product(commands,expected):
        if holder.product_drift:raise ValueError('fixture base drift')
        return '9'*64
    def cohort(commands,expected,*args):return ([dict(identity=holder.deployed_identity if holder.deployed else identity)]*3,None)
    monkeypatch.setattr(nightly_rebuild,'_product',product);monkeypatch.setattr(nightly_deployment,'_cohort',cohort);monkeypatch.setattr(nightly_image,'probe_image',lambda *a,**k:{'files':files})
    def confirm(g,c,b):
        from ops.pi.tests.test_admin_console import Publisher
        Publisher(g).publish(c,b,{});return {'verified':True,'status':'observing'}
    publication=module.NativePublication(gate,file_hash(config_path),config_path=config_path,transport_factory=Transport,bundle_verifier=lambda *a:packet,deployment_verifier=confirm)
    return publication,gate,cycle,bundle,holder,packet,case


def approve(native_case):
    from ops.pi.tests.test_nightly_gate import permit
    publication,gate,cycle,bundle,holder,packet,case=native_case;(path,pin),_=permit(case,cycle,packet['manifest'],['deploy']);gate.approve(cycle,path,pin)


def test_publication_prepares_exact_git_identity_without_deploying_or_charging(native_case):
    from ops.pi.development_inputs import ledger_snapshot
    publication,gate,cycle,bundle,holder,packet,case=native_case;before=[ledger_snapshot(p) for p in (gate.state,gate.billing)]
    plan=publication.prepare(cycle,bundle)
    assert plan['image_id']==packet['manifest']['image_id'] and len(plan['source_commit'])==40
    assert gate.status()['phase']=='awaiting_approval' and not holder.deployed and [ledger_snapshot(p) for p in (gate.state,gate.billing)]==before
    assert not any('up' in c or 'build' in c or 'push' in c for c in holder.calls)


def test_publication_deploys_only_exact_api_worker_image_then_verifies_gate(native_case):
    from ops.pi.development_inputs import ledger_snapshot
    publication,gate,cycle,bundle,holder,packet,case=native_case;before=[ledger_snapshot(p) for p in (gate.state,gate.billing)];plan=publication.prepare(cycle,bundle);approve(native_case)
    assert publication.publish(cycle,bundle,plan)['verified'] is True and gate.status()['phase']=='observing'
    calls=[c for c in holder.calls if 'up' in c];assert len(calls)==1
    assert calls[0][-2:]==['myink-api','myink-worker'] and '--no-build' in calls[0] and '--no-deps' in calls[0] and calls[0][calls[0].index('--pull')+1]=='never'
    assert [ledger_snapshot(p) for p in (gate.state,gate.billing)]==before


@pytest.mark.parametrize('fault',['product_drift','config_drift','alias_drift','busy'])
def test_publication_drift_or_busy_queues_prevent_deploy_before_command_intent(native_case,fault):
    publication,gate,cycle,bundle,holder,packet,case=native_case;plan=publication.prepare(cycle,bundle);approve(native_case);setattr(holder,fault,True)
    with pytest.raises(ValueError):publication.publish(cycle,bundle,plan)
    assert not holder.deployed and not (bundle.parent/'console-publication/deploy-intent.json').exists()


def test_preparation_cannot_be_replayed_after_an_interruption(native_case):
    publication,gate,cycle,bundle,holder,packet,case=native_case;holder.busy=True
    with pytest.raises(ValueError):publication.prepare(cycle,bundle)
    before=list(holder.calls);holder.busy=False
    with pytest.raises(ValueError):publication.prepare(cycle,bundle)
    assert holder.calls==before and gate.status()['phase']=='awaiting_approval'


def test_browser_cannot_replace_the_root_prepared_deployment_command(native_case):
    import copy
    publication,gate,cycle,bundle,holder,packet,case=native_case;plan=publication.prepare(cycle,bundle);approve(native_case);bad=copy.deepcopy(plan);bad['compose_arguments']=['arbitrary','shell']
    with pytest.raises(ValueError):publication.publish(cycle,bundle,bad)
    assert not holder.deployed


def test_actual_publisher_forbids_injected_transports_and_nonfixed_inputs(monkeypatch,tmp_path):
    from types import SimpleNamespace
    from ops.pi.admin_publication import NativePublication
    monkeypatch.setattr(os,'geteuid',lambda:0)
    with pytest.raises(ValueError):NativePublication(SimpleNamespace(mode='ACTUAL'),'0'*64,config_path=tmp_path/'arbitrary',transport_factory=lambda *a:None)


def test_candidate_source_object_is_retained_without_moving_main(repository):
    from ops.pi.admin_publication import candidate_commit
    root,base,candidate,files,work=repository;commit=candidate_commit(root/'.git',base,candidate,digest(files),work)
    assert git(root,'rev-parse','refs/pi-candidates/'+commit).decode().strip()==commit
    assert git(root,'rev-parse','HEAD').decode().strip()==base


def test_preexisting_compose_drift_is_rejected_against_live_cohort(native_case):
    publication,gate,cycle,bundle,holder,packet,case=native_case;holder.config_drift=True
    with pytest.raises(ValueError):publication.prepare(cycle,bundle)
    assert not holder.deployed and not holder.control_updates


def test_publication_fences_original_pg_then_changes_identity_and_reopens(native_case):
    publication,gate,cycle,bundle,holder,packet,case=native_case;plan=publication.prepare(cycle,bundle);approve(native_case)
    publication.publish(cycle,bundle,plan)
    assert holder.control_updates==['closed','identity','opened']
    assert holder.control['generation']==holder.deployed_identity['generation'] and holder.control['image_ids']==holder.deployed_identity['image_ids']
    assert holder.control['owner']==holder.deployed_identity['owner'] and holder.control['admission_closed'] is False


def test_inflight_admission_after_preparation_blocks_replacement(native_case):
    publication,gate,cycle,bundle,holder,packet,case=native_case;plan=publication.prepare(cycle,bundle);approve(native_case);holder.inflight=True
    with pytest.raises(ValueError):publication.publish(cycle,bundle,plan)
    assert not holder.deployed


def test_uncertain_compose_failure_preserves_closed_original_barrier(native_case):
    publication,gate,cycle,bundle,holder,packet,case=native_case;plan=publication.prepare(cycle,bundle);approve(native_case);holder.compose_failed=True
    with pytest.raises(ValueError):publication.publish(cycle,bundle,plan)
    assert holder.control_closed and holder.control_updates==['closed']
