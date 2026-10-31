"""Operator entry uses the canonical host and the original real file lock."""
from types import SimpleNamespace
import fcntl,importlib.util
import pytest
from ops.pi.contracts import Receipt
from test_product_bootstrap import case as bootstrap_case,NOW
from test_product_runtime import runtime_case


def api():
    assert importlib.util.find_spec('ops.pi.product_entrypoint'),'missing same-lock product operator entry'
    from ops.pi import product_entrypoint
    return product_entrypoint


@pytest.mark.parametrize('action',['activate','rollback'])
def test_operator_action_holds_original_lock_in_controller(runtime_case,monkeypatch,action):
    from ops.pi.product_runtime import LinuxProductHost
    module=api();path,pin,config,plan,*_=runtime_case;calls=[]
    monkeypatch.setattr(module,'LinuxProductHost',lambda *a,**kw:LinuxProductHost(*a,clock=lambda:NOW,**kw))
    def controller(host,*args):
        host.authorize(host.plan)
        with host.lock_path.open('rb') as another:
            with pytest.raises(BlockingIOError):fcntl.flock(another,fcntl.LOCK_EX|fcntl.LOCK_NB)
        def run():
            host.authorize(host.plan);calls.append(action);return Receipt(plan['operation_id'],'done',dict(verified=True))
        return SimpleNamespace(activate=run,rollback=run)
    monkeypatch.setattr(module,'NativeProductRelease',controller)
    result=module.execute(action,host_path=path,host_sha256=pin,control_path=path,control_sha256='a'*64,control_approval_path=path,control_approval_sha256='b'*64)
    assert result.status=='done' and calls==[action]
    with __import__('pathlib').Path(config['lock_path']).open('rb') as released:fcntl.flock(released,fcntl.LOCK_EX|fcntl.LOCK_NB)


def test_prepare_delegates_to_internal_protocol_lock_without_nesting(runtime_case,monkeypatch):
    from ops.pi.product_runtime import LinuxProductHost
    module=api();path,pin,_,plan,*_=runtime_case
    monkeypatch.setattr(module,'LinuxProductHost',lambda *a,**kw:LinuxProductHost(*a,clock=lambda:NOW,**kw))
    def prepare(ledger,plan,host):
        with host.lock(plan):host.authorize(plan)
        return Receipt(plan['operation_id'],'blocked',dict(reason='qualification pending'))
    monkeypatch.setattr(module,'prepare_bootstrap',prepare)
    assert module.execute('prepare',host_path=path,host_sha256=pin).status=='blocked'


@pytest.mark.parametrize('fault',['unknown-action','missing-control','lease-activate','lease-prepare'])
def test_operator_rejects_incomplete_or_wrong_phase_before_host_creation(monkeypatch,fault):
    module=api();calls=[];monkeypatch.setattr(module,'LinuxProductHost',lambda *a,**kw:calls.append('host'))
    values=dict(host_path='/not-used',host_sha256='a'*64);action='activate'
    if fault=='unknown-action':action='shell'
    elif fault.startswith('lease'):
        action='prepare' if fault=='lease-prepare' else 'activate';values.update(rollback_lease_path='/not-used',rollback_lease_sha256='c'*64)
    with pytest.raises(ValueError):module.execute(action,**values)
    assert calls==[]


def test_operator_failure_releases_lock_without_an_alternate_deployment(runtime_case,monkeypatch):
    from ops.pi.product_runtime import LinuxProductHost
    module=api();path,pin,config,*_=runtime_case
    monkeypatch.setattr(module,'LinuxProductHost',lambda *a,**kw:LinuxProductHost(*a,clock=lambda:NOW,**kw))
    def fail(host,*args):
        host.authorize(host.plan);raise TimeoutError('unconfirmed native stage')
    monkeypatch.setattr(module,'NativeProductRelease',fail)
    with pytest.raises(TimeoutError):module.execute('activate',host_path=path,host_sha256=pin,control_path=path,control_sha256='a'*64,control_approval_path=path,control_approval_sha256='b'*64)
    with __import__('pathlib').Path(config['lock_path']).open('rb') as released:fcntl.flock(released,fcntl.LOCK_EX|fcntl.LOCK_NB)


def test_cli_error_does_not_publish_private_exception_content(monkeypatch,capsys):
    import json
    module=api()
    def fail(*a,**kw):raise RuntimeError('private-original-path-and-credential')
    monkeypatch.setattr(module,'execute',fail)
    assert module.main(['prepare','--host-config','/private/input','--host-sha256','a'*64])==1
    output=capsys.readouterr().out;assert 'private-original' not in output and json.loads(output)['status']=='unconfirmed'
