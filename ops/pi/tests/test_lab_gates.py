"""Selected-lab authorization precedes database setup and rejects endpoint drift."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from ops.pi.tests import conftest
from ops.pi.lab import verify


def test_fabricated_receipt_never_authorizes_database_fixtures(monkeypatch,tmp_path):
    receipt=tmp_path/'receipt.json'
    receipt.write_text(json.dumps({'daemon_id':verify.DAEMON,'status':'done'}))
    monkeypatch.setenv('PI_LAB_ENV',str(receipt))
    item=SimpleNamespace(path=tmp_path/'integration/test_db_reader_lab.py',get_closest_marker=lambda name: name=='pi_lab')
    # pi_live must be absent; a fabricated lab receipt reaches the actual lab gate.
    item.get_closest_marker=lambda name: True if name=='pi_lab' else None
    config=SimpleNamespace(getoption=lambda name: name=='--pi-lab')
    with pytest.raises(pytest.UsageError,match='fresh owned'):
        conftest.pytest_collection_modifyitems(config,[item])


def _owned_test(monkeypatch,tmp_path):
    operation='11111111-1111-4111-8111-111111111111'
    owner={'operation_id':operation,'unit':'myinkpi-test-'+operation,'lab_uuid':'owned','group':'heavy','status':'active'}
    (tmp_path/'current-operation.json').write_text(json.dumps(owner))
    expected={'DATABASE_URL':'postgresql+psycopg://postgres:synthetic-lab-only@127.0.0.1:54321/myink',
              'ADMIN_DATABASE_URL':'postgresql+psycopg://postgres:synthetic-lab-only@127.0.0.1:54321/myink',
              'REDIS_URL':'redis://127.0.0.1:54322/0','AMQP_URL':'amqp://myink:synthetic-lab-only@127.0.0.1:54323/',
              'QUEUE_PREFIX':'-pi-owned-','JWT_SECRET':'synthetic-b7-jwt-secret-at-least-32-bytes','EMBED_ENABLED':'0'}
    (tmp_path/'test.env').write_text('\n'.join("export "+k+"='"+v+"'" for k,v in expected.items()))
    group='/myinkpi.slice/myinkpi-heavy.slice/'+owner['unit']+'.service'
    proc=tmp_path/'proc-cgroup';proc.write_text('0::'+group)
    monkeypatch.setattr(verify,'BASE',tmp_path)
    monkeypatch.setattr(verify,'_sealed_source',lambda:True)
    monkeypatch.setattr(verify,'Path',lambda p:proc if p=='/proc/self/cgroup' else Path(p))
    monkeypatch.setattr(verify.sys,'platform','linux')
    monkeypatch.setattr(verify,'verify_runtime',lambda:{'lab_uuid':'owned','project':'project'})
    monkeypatch.setattr(verify,'_run',lambda *args:'active' if args[1]=='is-active' else group)
    def docker(*args):
        ports={'project-pg':('5432/tcp',54321),'project-redis':('6379/tcp',54322),'project-rabbit':('5672/tcp',54323)}
        key,port=ports[args[1]]
        return [{'NetworkSettings':{'Ports':{key:[{'HostIp':'127.0.0.1','HostPort':str(port)}]}}}]
    monkeypatch.setattr(verify,'_docker',docker)
    monkeypatch.setenv('PI_LAB_ENV',str(tmp_path/'lab-env.json'))
    for k,v in expected.items():monkeypatch.setenv(k,v)
    return owner,expected


def test_stale_operation_rejected_before_database_setup(monkeypatch,tmp_path):
    owner,_=_owned_test(monkeypatch,tmp_path)
    owner['status']='completed';(tmp_path/'current-operation.json').write_text(json.dumps(owner))
    with pytest.raises(ValueError,match='stale'):
        verify.verify_test_environment()


@pytest.mark.parametrize('key',['DATABASE_URL','ADMIN_DATABASE_URL','REDIS_URL','AMQP_URL'])
def test_foreign_inherited_fixture_url_rejected(monkeypatch,tmp_path,key):
    _owned_test(monkeypatch,tmp_path)
    monkeypatch.setenv(key,'foreign://192.0.2.4/production')
    with pytest.raises(ValueError,match='foreign or inherited'):
        verify.verify_test_environment()


def test_owned_active_operation_accepts_only_exact_fixture_urls(monkeypatch,tmp_path):
    _,expected=_owned_test(monkeypatch,tmp_path)
    assert verify.verify_test_environment()[1]==expected


def test_stale_controller_cannot_cancel_later_operation(monkeypatch,tmp_path):
    owner,_=_owned_test(monkeypatch,tmp_path)
    (tmp_path/'lab-env.json').write_text(json.dumps({'lab_uuid':'owned'}))
    # A's completion/cancellation arrives after B owns the active heavy unit.
    assert verify.cancel_owned('22222222-2222-4222-8222-222222222222','owned')['status']=='refused'
    assert json.loads((tmp_path/'current-operation.json').read_text())==owner


def test_fixture_pid_must_be_inside_its_required_parent(monkeypatch,tmp_path):
    info={'Id':'owned-id','Image':'pin','State':{'Running':True,'Pid':42},'Config':{'User':'','Labels':{'myink.pi.lab':'owned'}},
          'HostConfig':{'CgroupParent':'myinkpi-heavy.slice'},'Mounts':[],'NetworkSettings':{'Networks':{}}}
    expected=verify._configuration(info)
    proc=tmp_path/'cgroup';proc.write_text('0::/myinkpi.slice/myinkpi-infra.slice/foreign.service')
    monkeypatch.setattr(verify,'Path',lambda _:proc)
    with pytest.raises(ValueError,match='PID outside'):
        verify.verify_container(info,expected,'owned','heavy')


@pytest.mark.parametrize('fault',['empty_chain','fixture_deny','preceding_accept'])
def test_effective_scoped_firewall_drift_rejected(monkeypatch,fault):
    rules={'MYINKPI_B7':'-N MYINKPI_B7\n-A MYINKPI_B7 -s 172.29.220.10/32 -d 172.29.220.2/32 -p tcp -m tcp --dport 8765 -j RETURN\n-A MYINKPI_B7 -s 172.29.220.10/32 -j DROP\n-A MYINKPI_B7 -j RETURN',
           'INPUT':'-P INPUT ACCEPT\n-A INPUT -i pi-lab-agent -j DROP',
           'DOCKER-USER':'-N DOCKER-USER\n-A DOCKER-USER -i pi-lab-agent -j MYINKPI_B7\n-A DOCKER-USER -i pi-lab-fixtures ! -o pi-lab-fixtures -j DROP'}
    if fault=='empty_chain':rules['MYINKPI_B7']='-N MYINKPI_B7'
    if fault=='fixture_deny':rules['DOCKER-USER']=rules['DOCKER-USER'].split('\n-A DOCKER-USER -i pi-lab-fixtures')[0]
    if fault=='preceding_accept':rules['INPUT']='-A INPUT -j ACCEPT\n'+rules['INPUT']
    monkeypatch.setattr(verify,'_run',lambda *args:rules[args[-1]])
    with pytest.raises(ValueError,match='firewall'):
        verify.verify_firewall()


def test_docker_mount_listing_order_is_not_configuration_drift():
    info={'Id':'id','Image':'pin','Config':{'User':'65534:65534'},'HostConfig':{},'NetworkSettings':{'Networks':{}},
          'Mounts':[{'Destination':'/policy','Source':'/policy','Type':'bind','RW':False},{'Destination':'/source','Source':'/candidate','Type':'bind','RW':False}]}
    original=verify._configuration(info)
    info['Mounts'].reverse()
    assert verify._configuration(info)==original
