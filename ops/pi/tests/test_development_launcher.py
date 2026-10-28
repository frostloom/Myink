"""Host failure paths must restore gates and reject unauthenticated completion."""
from threading import Event
from pathlib import Path
import pytest
from ops.pi.development_launcher import PolicyLease, Limits, verify_check


def test_policy_lease_restores_exact_bytes_on_failure(tmp_path):
    p=tmp_path/'policy';p.write_bytes(b'closed');p.chmod(0o600)
    with pytest.raises(RuntimeError):
        with PolicyLease(p,b'closed',b'open'):
            assert p.read_bytes()==b'open'
            raise RuntimeError('failure')
    assert p.read_bytes()==b'closed'
    assert p.stat().st_mode & 0o777 == 0o600


def test_policy_drift_never_overwritten(tmp_path):
    p=tmp_path/'policy';p.write_bytes(b'closed')
    with pytest.raises(ValueError,match='policy drift'):
        with PolicyLease(p,b'closed',b'open'):
            p.write_bytes(b'other')
    assert p.read_bytes()==b'other'


def test_limits_cancel_expiry_and_request_cap():
    cancel=Event(); clock=[0]
    limits=Limits(2,3,10,cancel,clock=lambda:clock[0])
    limits.claim('model');limits.claim('model')
    with pytest.raises(ValueError,match='limit'): limits.claim('model')
    limits.claim('tool');limits.claim('verify');limits.claim('tool')
    with pytest.raises(ValueError,match='limit'): limits.claim('verify')
    cancel.set()
    with pytest.raises(ValueError,match='cancel'): limits.alive()
    cancel.clear();clock[0]=11
    with pytest.raises(ValueError,match='deadline'): limits.alive()


@pytest.mark.parametrize('override', [dict(passed=False),dict(cases=['wrong']),dict(skipped=1),dict(tests=0)])
def test_fixed_checker_rejects_forged_or_incomplete_evidence(override):
    result=dict(passed=True,cases=['fixed_development_tests.Case.test_one'],tests=1,skipped=0,failures=0,errors=0)
    verify_check(result,0,result['cases'])
    with pytest.raises(ValueError): verify_check(dict(result,**override),0,result['cases'])
    with pytest.raises(ValueError): verify_check(result,1,result['cases'])

from ops.pi.tests.test_development_inputs import config_file


def test_execute_failure_persists_receipt_and_restores_policy(config_file,monkeypatch):
    from ops.pi import development_launcher as launcher
    from ops.pi.development_inputs import ledger_snapshot
    import json
    cp,c=config_file
    class Host:
        def __init__(self): self.owned={};self.pending={};self.operation_id='synthetic'
        def reconcile(self): pass
        def _daemon(self): pass
        def _call(self,*a): return type('Output',(),{'stdout':''})()
    monkeypatch.setattr(launcher,'_host',lambda *a:Host())
    def fail(*a): raise RuntimeError('synthetic worker failure')
    monkeypatch.setattr(launcher,'_exchange',fail)
    original=Path(c['policy_path']).read_bytes()
    before=ledger_snapshot(c['ledger_path'])
    result=launcher.execute(cp,transport=lambda *a:None)
    assert not result['verified']
    assert result['failure_class']=='RuntimeError'
    assert result['policy_restored'] and result['original_history_unchanged']
    assert Path(c['policy_path']).read_bytes()==original
    assert ledger_snapshot(c['ledger_path'])==before
    assert json.loads((Path(c['root'])/'result.json').read_text())==result
    with pytest.raises(ValueError): launcher.execute(cp,transport=lambda *a:None)


def test_cleanup_rejects_untracked_owned_label(monkeypatch):
    from ops.pi.development_launcher import _cleanup
    class Host:
        owned={};pending={};operation_id='synthetic'
        def reconcile(self): pass
        def _daemon(self): pass
        def _call(self,*a): return type('Output',(),{'stdout':'unexpected-container'})()
    with pytest.raises(ValueError,match='label'): _cleanup(Host())


def test_worker_receipt_accepts_only_fixed_schema():
    from ops.pi.development_launcher import worker_receipt
    from ops.pi.contracts import Receipt
    assert worker_receipt(dict(operation_id='phase',status='done',evidence={},schema_version=1))==Receipt('phase','done',{})
    for raw in (dict(operation_id='phase',status='done',evidence={},schema_version=2),
                dict(operation_id='phase',status='done',evidence={},schema_version=1,extra=True)):
        with pytest.raises(ValueError): worker_receipt(raw)


def test_stalled_worker_input_obeys_deadline():
    import os,time
    from ops.pi.development_launcher import write_frame
    read,write=os.pipe()
    try:
        limits=Limits(1,1,.03,Event())
        started=time.monotonic()
        with pytest.raises(ValueError,match='deadline'):
            write_frame(write,{'large':'x'*200000},limits)
        assert time.monotonic()-started<1
    finally:
        os.close(read);os.close(write)


def test_checker_cleanup_failure_remains_fatal_after_later_cleanup(monkeypatch):
    from ops.pi import development_launcher as launcher
    cancel=Event();records=[]
    owners=launcher.OwnedHosts(cancel,lambda *a:None)
    host=type('Host',(),{'operation_id':'checker'})()
    owners.add(host)
    def fail(_,**kwargs):raise RuntimeError('cleanup failed')
    monkeypatch.setattr(launcher,'_cleanup',fail)
    with pytest.raises(RuntimeError): owners.cleanup(host)
    assert cancel.is_set() and owners.failed
    def removed(_,*,on_removed=None):
        receipt=dict(removed=True)
        if on_removed is not None:on_removed(receipt)
        return [receipt]
    monkeypatch.setattr(launcher,'_cleanup',removed)
    assert owners.finish()==[dict(removed=True)]
    assert owners.failed


def test_execute_rejects_config_switch_under_wrong_ledger_lock(config_file,monkeypatch):
    from ops.pi import development_launcher as launcher
    cp,c=config_file;real=launcher.prepare;calls=[]
    def switch(p):
        result=list(real(p));calls.append(1)
        if len(calls)==2:result[0]=dict(result[0],ledger_path=str(cp.parent/'other.sqlite'))
        return result
    monkeypatch.setattr(launcher,'prepare',switch)
    with pytest.raises(ValueError,match='config drift'):launcher.execute(cp,transport=lambda *a:None)
    assert not Path(c['root']).exists()


@pytest.mark.parametrize('missing',['policy','credential'])
def test_missing_sensitive_file_still_writes_failure_receipt(config_file,monkeypatch,missing):
    from ops.pi import development_launcher as launcher
    import json
    cp,c=config_file
    class Host:
        owned={};pending={};operation_id='synthetic'
        def reconcile(self):pass
        def _daemon(self):pass
        def _call(self,*a):return type('Output',(),{'stdout':''})()
    monkeypatch.setattr(launcher,'_host',lambda *a:Host())
    def fail(*a):
        Path(c[missing+'_path']).unlink()
        raise RuntimeError('injected file disappearance')
    monkeypatch.setattr(launcher,'_exchange',fail)
    result=launcher.execute(cp,transport=lambda *a:None)
    assert not result['verified']
    assert result[missing+'_audit_failure_class']=='FileNotFoundError'
    assert result['original_history_unchanged']
    assert json.loads((Path(c['root'])/'result.json').read_text())==result


@pytest.mark.parametrize('private_umask',[0o077,0o027])
def test_fixed_checker_bind_root_is_readable_by_unprivileged_worker(tmp_path,monkeypatch,private_umask):
    import os
    from ops.pi import development_launcher as launcher
    from ops.pi.development_inputs import file_hash
    tmp_path.chmod(0o700);candidate=tmp_path/'candidate'
    (candidate/'src').mkdir(parents=True);(candidate/'src/a.py').write_text('value=1\n')
    gold=tmp_path/'gold.py';gold.write_text('fixed input\n');gold.chmod(0o600)
    destination=tmp_path/'check'
    class BoundaryReached(RuntimeError):pass
    class Host:
        def create(self,mode,*,source,**kwargs):
            # The bind exposes this root directly to UID65534, regardless of its private host ancestor.
            if source.stat().st_mode&0o005!=0o005:
                raise PermissionError('worker cannot traverse bind root')
            for p in source.rglob('*'):
                assert p.stat().st_mode&(0o005 if p.is_dir() else 0o004)==(0o005 if p.is_dir() else 0o004)
            assert tmp_path.stat().st_mode&0o777==0o700
            raise BoundaryReached('fixed container boundary reached')
    host=Host();monkeypatch.setattr(launcher,'_host',lambda *a:host)
    class Owners:
        def add(self,value):return value
        def cleanup(self,value):return []
    c=dict(test_path=str(gold),test_sha256=file_hash(gold))
    previous=os.umask(private_umask)
    try:
        with pytest.raises(BoundaryReached,match='fixed container boundary'):
            launcher._fixed_check(c,candidate,destination,Limits(1,1,60,Event()),lambda *a:None,Owners())
    finally:os.umask(previous)
