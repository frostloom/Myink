"""Native fake Docker CLI exercises host commands without product resources."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import importlib.util
import json
import sys
from datetime import timedelta

import pytest

from ops.pi.audit import digest
from test_product_bootstrap import case as bootstrap_case, NOW, STEPS


def api():
    assert importlib.util.find_spec('ops.pi.product_runtime'), 'missing canonical Linux product host'
    from ops.pi.product_runtime import LinuxProductHost
    return LinuxProductHost


def write(path,value):
    path.write_text(json.dumps(value));path.chmod(0o600)
    return sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def runtime_case(bootstrap_case,tmp_path):
    _,plan,_=bootstrap_case
    root=(tmp_path/'runtime').resolve();root.mkdir(mode=0o700)
    project='myink-pi-rehearsal-'+plan['operation_id']
    source={'src/myink/__init__.py':'legacy-source\n'}
    files={p:sha256(raw.encode()).hexdigest() for p,raw in source.items()}
    plan['legacy']['source_sha256']=digest(files)
    aliases=dict(api='myink-api',worker='myink-worker',frontend='myink-caddy',postgres='myink-pg',redis='myink-redis',rabbitmq='myink-rabbitmq')
    rows={r['id']:dict(r,service=aliases[r['service']],project=project,running=True,exit_code=0,oom=False,ports={'8100/tcp':[dict(HostIp='127.0.0.1',HostPort='18100')]} if r['service']=='api' else {}) for r in plan['legacy']['containers']}
    state=dict(containers=rows,source=source,config={'apps':{'http':{'servers':{'srv0':{'listen':[':443'],'routes':[{'handle':[{'handler':'reverse_proxy','upstreams':[{'dial':'myink-api:8100'}]}]}]}}}}},copied={},effects=[],counts=dict(active_tasks=0,unknown=0),redis=dict(task_locks=0,book_locks=0),queues=[dict(name=n,messages_ready=0,messages_unacknowledged=0,consumers=0) for n in ('queue:tasks','queue:tasks:vip','queue:delay','queue:delay:vip','queue:dlq')])
    state_path=tmp_path/'engine.json';write(state_path,state)
    docker=tmp_path/'docker'
    program=r"""import json,sys,io,tarfile
from pathlib import Path
STATE=Path(STATE_PATH)
s=json.loads(STATE.read_text());a=sys.argv[3:]
def save():STATE.write_text(json.dumps(s))
if a[0]=='info':print(json.dumps({'ID':'product-native-test'}))
elif a[0]=='ps':print('\n'.join(s['containers']))
elif a[0]=='inspect':
 for cid in a:
  if cid in s['containers']:print(json.dumps(s['containers'][cid]))
elif a[0]=='cp':
 if a[1].endswith(':/app/src') and a[2]=='-':
  archive=io.BytesIO()
  with tarfile.open(fileobj=archive,mode='w') as tar:
   for path,raw in s['source'].items():
    raw=raw.encode();member=tarfile.TarInfo(path);member.size=len(raw);tar.addfile(member,io.BytesIO(raw))
  sys.stdout.buffer.write(archive.getvalue())
 else:
  s['copied'][a[2].split(':',1)[1]]=json.loads(Path(a[1]).read_bytes());save()
elif a[0]=='stop':
 cid=a[-1];s['effects'].append(['stop',cid])
 if s.get('keep_running')!=cid:s['containers'][cid].update(running=False,exit_code=s.get('bad_exit',0))
 save();print(cid)
elif a[0]=='exec':
 cid=a[1];cmd=a[2:]
 if cmd[0].endswith('curl'):print(json.dumps(s['config']))
 elif cmd[:2]==['caddy','validate']:pass
 elif cmd[:2]==['caddy','reload']:
  if s.get('reject_reload'):sys.exit(17)
  s['config']=s['copied'][cmd[-1]];s['effects'].append(['reload',cid]);save()
 elif cmd[0]=='psql':
  if '-q' not in cmd:print('BEGIN');print('SET')
  print(json.dumps(s['counts']))
  if '-q' not in cmd:print('ROLLBACK')
 elif cmd[0]=='/bin/sh':
  assert len(cmd)==5 and cmd[1]=='-c' and cmd[3]=='--'
  print(json.dumps(s['redis']))
 elif cmd[0]=='rabbitmqctl':print(json.dumps(s['queues']))
 else:raise RuntimeError('unreviewed fake exec '+str(cmd))
else:raise RuntimeError('unreviewed fake Docker action '+str(a))
"""
    docker.write_text('#!'+sys.executable+'\n'+program.replace('STATE_PATH',repr(str(state_path))));docker.chmod(0o700)
    plan_path=tmp_path/'plan.json';plan_pin=write(plan_path,plan)
    approval_path=tmp_path/'approval.json';approval=dict(schema='pi-product-release-approval-v1',mode='SIMULATED',target='rehearsal',authority='owned_rehearsal',plan_sha256=digest(plan),approved_actions=list(STEPS),expires_at=plan['expires_at'])
    approval_pin=write(approval_path,approval)
    legacy_path=tmp_path/'legacy.json';legacy_pin=write(legacy_path,dict(source_commit=plan['legacy']['source_commit'],files=files))
    candidate_path=tmp_path/'candidate.json';candidate_pin=write(candidate_path,dict(source_commit=plan['candidate']['commit_sha'],files=files))
    backup_path=tmp_path/'backup.json';backup_pin=write(backup_path,dict(schema='pi-product-backup-v1',release_pair_id=plan['operation_id']))
    compose=tmp_path/'compose';compose.mkdir(mode=0o700)
    config=dict(schema='pi-linux-product-host-v1',mode='SIMULATED',target='rehearsal',docker=str(docker),endpoint='unix:///tmp/product-native-test.sock',daemon_id='product-native-test',root=str(root),lock_path=str(tmp_path/'maintenance.lock'),project=project,plan_path=str(plan_path),plan_sha256=plan_pin,approval_path=str(approval_path),approval_sha256=approval_pin,legacy_manifest_path=str(legacy_path),legacy_manifest_sha256=legacy_pin,candidate_manifest_path=str(candidate_path),candidate_manifest_sha256=candidate_pin,backup_path=str(backup_path),backup_sha256=backup_pin,compose_dir=str(compose),drain_seconds=5,queue_prefix='')
    lock=Path(config['lock_path']);lock.write_bytes(b'');lock.chmod(0o600)
    config_path=tmp_path/'host.json';pin=write(config_path,config)
    return config_path,pin,config,plan,state_path


def host(case):return api()(case[0],case[1],clock=lambda:NOW)


def claim(h,plan,action):
    h.ledger.intent(plan['operation_id'],'product_bootstrap',dict(plan_sha256=digest(plan)))
    h.ledger.intent(plan['operation_id']+':'+action,'product_bootstrap_step',dict(plan_sha256=digest(plan),action=action))


def test_sealed_files_and_complete_physical_source_are_observed(runtime_case):
    h=host(runtime_case);plan=runtime_case[3]
    with h.lock(plan):
        h.authorize(plan)
        assert h.inspect(plan)==plan['legacy']
    assert list((Path(runtime_case[2]['root'])/'commands').iterdir())


def test_approval_revocation_prevents_all_native_commands(runtime_case):
    h=host(runtime_case);plan=runtime_case[3]
    Path(runtime_case[2]['approval_path']).write_text('{}')
    with pytest.raises((ValueError,PermissionError)):
        with h.lock(plan):h.authorize(plan)
    assert list((Path(runtime_case[2]['root'])/'commands').iterdir())==[]


def test_mutation_requires_the_shared_lock_and_original_durable_step(runtime_case):
    h=host(runtime_case);plan=runtime_case[3]
    with pytest.raises((ValueError,PermissionError)):h.perform('close_ingress',plan,{})
    with h.lock(plan):
        with pytest.raises((ValueError,PermissionError)):h.perform('close_ingress',plan,{})
    assert json.loads(runtime_case[4].read_bytes())['effects']==[]


def test_close_and_graceful_drain_preserve_routes_and_stop_api_first(runtime_case):
    h=host(runtime_case);plan=runtime_case[3]
    original=deepcopy(json.loads(runtime_case[4].read_bytes())['config'])
    with h.lock(plan):
        claim(h,plan,'close_ingress');fence=h.perform('close_ingress',plan,{})
        claim(h,plan,'drain_legacy');drain=h.perform('drain_legacy',plan,{'close_ingress':fence})
    current=json.loads(runtime_case[4].read_bytes());routes=current['config']['apps']['http']['servers']['srv0']['routes']
    assert routes[1:]==original['apps']['http']['servers']['srv0']['routes']
    assert routes[0]['handle'][0]['status_code']==503
    stopped=[item[1] for item in current['effects'] if item[0]=='stop']
    assert stopped==[r['id'] for r in plan['legacy']['containers'] if r['service']=='api']+[r['id'] for r in plan['legacy']['containers'] if r['service']=='worker']
    assert drain['api_exit_code']==0 and drain['worker_exit_codes']==[0,0] and drain['fence_sha256']==fence['fence_sha256']
    assert all(drain[k]==0 for k in ('active_tasks','ready_messages','unacked_messages','consumers','task_locks','book_locks','unknown'))
    for folder in (Path(runtime_case[2]['root'])/'commands').iterdir():
        argv=json.loads((folder/'intent.json').read_bytes())['argv']
        if 'stop' in argv:assert argv[-4:-1]==['--signal','SIGTERM','--timeout'] or '--timeout' in argv
        assert 'kill' not in argv and '--force' not in argv


@pytest.mark.parametrize('kind',['source','image','public_port','extra_worker'])
def test_changed_or_exposed_product_is_not_fenced(runtime_case,kind):
    h=host(runtime_case);plan=runtime_case[3];state=json.loads(runtime_case[4].read_bytes());api_id=plan['legacy']['containers'][0]['id']
    if kind=='source':state['source']['src/myink/__init__.py']='changed'
    elif kind=='image':state['containers'][api_id]['image_id']='sha256:'+'0'*64
    elif kind=='public_port':state['containers'][api_id]['ports']['8100/tcp'][0]['HostIp']='0.0.0.0'
    else:
        row=deepcopy(state['containers'][api_id]);row.update(id='0'*64,service='myink-worker');state['containers'][row['id']]=row
    write(runtime_case[4],state)
    with pytest.raises((ValueError,PermissionError)):
        with h.lock(plan):
            claim(h,plan,'close_ingress');h.perform('close_ingress',plan,{})
    assert json.loads(runtime_case[4].read_bytes())['effects']==[]


def test_actual_rejects_injected_clock_and_noncanonical_paths(runtime_case):
    path,pin,config,plan,_=runtime_case;config['mode']='ACTUAL';pin=write(path,config)
    with pytest.raises((ValueError,PermissionError)):api()(path,pin,clock=lambda:NOW)


def test_plan_cannot_add_unapproved_actions(runtime_case):
    h=host(runtime_case);plan=runtime_case[3]
    with h.lock(plan):
        with pytest.raises((ValueError,PermissionError)):h.perform('arbitrary_shell',plan,{})
    assert json.loads(runtime_case[4].read_bytes())['effects']==[]


def test_quiet_revalidation_does_not_repeat_stop_or_reload(runtime_case):
    h=host(runtime_case);plan=runtime_case[3]
    with h.lock(plan):
        claim(h,plan,'close_ingress');fence=h.perform('close_ingress',plan,{})
        claim(h,plan,'drain_legacy');drain=h.perform('drain_legacy',plan,{'close_ingress':fence})
        before=json.loads(runtime_case[4].read_bytes())['effects']
        assert h.measure_quiet(plan,{'close_ingress':fence})==drain
        assert json.loads(runtime_case[4].read_bytes())['effects']==before


def test_production_control_ledger_survives_new_operation_directory(runtime_case):
    import uuid
    cp,_,c,plan,state_path=runtime_case
    c['target']='production';c['project']='myink'
    approval_path=Path(c['approval_path']);approval=json.loads(approval_path.read_bytes())
    approval.update(target='production',authority='human_product_release')
    c['approval_sha256']=write(approval_path,approval)
    pin=write(cp,c);first=api()(cp,pin,clock=lambda:NOW)
    first.ledger.intent('pending-post-original','backup',dict(phase='POST'))
    plan['operation_id']=str(uuid.uuid4());c['plan_sha256']=write(Path(c['plan_path']),plan)
    approval['plan_sha256']=digest(plan);c['approval_sha256']=write(approval_path,approval)
    newroot=first.root.parent/'next-operation';newroot.mkdir(mode=0o700);c['root']=str(newroot)
    pin=write(cp,c);second=api()(cp,pin,clock=lambda:NOW)
    assert second.ledger.path==first.ledger.path
    assert second.ledger.get('pending-post-original')['status']=='pending'


def test_missing_migration_capability_blocks_preflight_before_product_effect(runtime_case,monkeypatch):
    h=host(runtime_case)
    monkeypatch.setattr(h,'apply_schema',None,raising=False)
    monkeypatch.setattr(h,'bind_identity',None,raising=False)
    with h.lock(h.plan):
        with pytest.raises(ValueError):h.preflight()
    assert json.loads(runtime_case[-1].read_bytes())['effects']==[]
