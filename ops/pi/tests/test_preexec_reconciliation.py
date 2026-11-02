from pathlib import Path
import json,pytest
from ops.pi.audit import digest
from ops.pi.development_inputs import file_hash,ledger_snapshot
from ops.pi.tests.test_nightly_gate import case
from ops.pi.autonomy_coordinator import RESULT


@pytest.fixture
def old_claim(case):
    g=case[0](True);base=g.state.parent/'preexec';base.mkdir(mode=0o700)
    for n in ('autonomy','inbox','handoffs','investigations'):(base/n).mkdir(mode=0o700)
    c=base/'autonomy'/('a'*64);c.mkdir(mode=0o700)
    def put(path,value):
        path.write_text(json.dumps(value));path.chmod(0o600)
    fee=ledger_snapshot(g.billing);put(c/'ledger-before-private.json',fee)
    put(c/'intent.json',dict(research_fingerprint=c.name,profile_sha256='b'*64))
    phases={}
    for component in ('investigation','coordinator_audit'):
        p=c/('phase-'+component);p.mkdir(mode=0o700)
        put(p/'intent.json',dict(component=component))
        put(p/'capture.json',dict(returncode=127,interrupted=False,reason=None))
        put(p/'pid.json',dict(pid=9999999,process_group=9999999))
        for name,raw in [('stdout-private.log',''),('stderr-private.log','setpriv: setresuid failed: Operation not permitted\n')]:
            (p/name).write_text(raw);(p/name).chmod(0o600)
        put(p/'receipt.json',dict(component=component,status='uncertain',model_requests=None,result_sha256=None))
        phases[component]=file_hash(p/'receipt.json')
    r=dict.fromkeys(RESULT);r.update(schema='pi-autonomy-coordinator-result-v1',mode='SIMULATED',status='uncertain',profile_sha256='b'*64,research_fingerprint=c.name,model_requests=0,before_fee_sha256=fee['sha256'],after_fee_sha256=fee['sha256'],phases=phases,pending_file_hashes={})
    put(c/'receipt.json',r)
    return g,c,put


def test_preexec_certificate_preserves_old_uncertainty_and_ledgers(old_claim):
    from ops.pi.preexec_reconciliation import reconcile,verified
    from ops.pi.autonomy_coordinator import _history
    g,c,put=old_claim;before=ledger_snapshot(g.state),ledger_snapshot(g.billing);old=file_hash(c/'receipt.json')
    assert _history(c.parent)[1] is False
    reconcile(c,g.state,g.billing,mode='SIMULATED')
    assert verified(c,'SIMULATED') and _history(c.parent)[1] is True
    assert json.loads((c/'receipt.json').read_text())['status']=='uncertain' and file_hash(c/'receipt.json')==old
    assert (ledger_snapshot(g.state),ledger_snapshot(g.billing))==before
    reconcile(c,g.state,g.billing,mode='SIMULATED')


@pytest.mark.parametrize('fault',['stdout','stderr','exit','interrupted','worker_result','fee','handoff','certificate'])
def test_unproven_or_tampered_preexec_history_never_unlocks(old_claim,fault):
    from ops.pi.preexec_reconciliation import reconcile,verified
    g,c,put=old_claim;p=c/'phase-investigation'
    if fault=='certificate':
        reconcile(c,g.state,g.billing,mode='SIMULATED');(p/'stderr-private.log').write_text('changed')
        with pytest.raises(ValueError):verified(c,'SIMULATED')
        return
    if fault=='stdout':(p/'stdout-private.log').write_text('{}')
    if fault=='stderr':(p/'stderr-private.log').write_text('unknown error')
    if fault in ('exit','interrupted'):put(p/'capture.json',dict(returncode=0 if fault=='exit' else 127,interrupted=fault=='interrupted',reason=None))
    if fault=='worker_result':put(p/'result-private.json',{})
    if fault=='fee':
        d=json.loads((c/'ledger-before-private.json').read_text());d['sha256']='c'*64;put(c/'ledger-before-private.json',d)
    if fault=='handoff':put(c.parent.parent/'inbox'/('auto-'+c.name[:32]+'.task.json'),{})
    with pytest.raises(ValueError):reconcile(c,g.state,g.billing,mode='SIMULATED')
    assert not (c/'preexec-reconciliation.json').exists()


@pytest.mark.parametrize('point',['export','certificate'])
def test_interrupted_metadata_publication_resumes_without_phase_replay(old_claim,monkeypatch,point):
    from ops.pi import preexec_reconciliation as module
    from ops.pi.audit import AuditStore
    g,c,put=old_claim;before=ledger_snapshot(g.state),ledger_snapshot(g.billing);once=[True]
    original_export=AuditStore.export;original_write=module._write
    def fail_export(self,*args,**kwargs):
        if point=='export' and once[0]:once[0]=False;raise OSError('transient export')
        return original_export(self,*args,**kwargs)
    def fail_certificate(path,value):
        if point=='certificate' and Path(path).name=='preexec-reconciliation.json' and once[0]:once[0]=False;raise OSError('transient certificate write')
        return original_write(path,value)
    monkeypatch.setattr(AuditStore,'export',fail_export);monkeypatch.setattr(module,'_write',fail_certificate)
    with pytest.raises(OSError):module.reconcile(c,g.state,g.billing,mode='SIMULATED')
    assert not (c/'preexec-reconciliation.json').exists()
    module.reconcile(c,g.state,g.billing,mode='SIMULATED')
    assert module.verified(c,'SIMULATED')
    assert len(AuditStore(c/'reconciliation-audit/events.sqlite').events())==1
    assert (ledger_snapshot(g.state),ledger_snapshot(g.billing))==before
