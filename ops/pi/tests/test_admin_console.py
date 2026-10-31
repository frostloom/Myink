"""Human console commands are metadata, never another Pi/fee executor."""
from datetime import timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import uuid
import pytest
from ops.pi.tests.test_nightly_bundle import bundle_case, finished, stopped, completed, config_file, prepare
from ops.pi.audit import digest
from ops.pi.development_inputs import ledger_snapshot, file_hash


class Publisher:
    def __init__(self, gate): self.gate = gate; self.calls = []
    def available(self): return True
    def prepare(self, cycle, bundle): self.calls.append('prepare'); return {'image_id': 'sha256:'+'7'*64}
    def publish(self, cycle, bundle, plan):
        self.calls.append('publish'); self.gate.require_action(cycle, 'deploy')
        with self.gate._connection() as db:
            row = self.gate._row(db, cycle); approval = json.loads(row['approval']); package = json.loads(row['package'])
        folder = bundle.parent/'deployment-receipts'; folder.mkdir(mode=0o700)
        packet = dict(schema='pi-nightly-deployment-receipt-v1',mode='SIMULATED',issuer='trusted_deployment_verifier',cycle_id=cycle,package_sha256=digest(package),approval_sha256=approval['sha256'],image_id=package['image_id'],source_sha256=package['source_sha256'],comparison_sha256=package['comparison_sha256'],deployment_id='fixture-'+cycle,deployed_at=self.gate.clock().isoformat())
        path=folder/'receipt.json';path.write_text(json.dumps(packet));path.chmod(0o600);self.gate.deployed(cycle,path,file_hash(path));return {'deployment_id':packet['deployment_id']}


@pytest.fixture
def console_case(bundle_case):
    from ops.pi.admin_console import Console
    prepare(bundle_case); gate,cycle,root,*_=bundle_case;state=root/'console-state';state.mkdir(mode=0o700)
    audit=root/'audit-state';audit.mkdir(mode=0o700);publisher=Publisher(gate)
    console=Console(gate,root.parent,audit/'events.sqlite',root/'audit-export',state/'console.sqlite',publisher=publisher)
    status=console.status();candidate=status['candidate']
    request=dict(request_id=str(uuid.uuid4()),actor_id=str(uuid.uuid4()),cycle_id=cycle,package_sha256=candidate['package_sha256'],image_id=candidate['image_id'],source_sha256=candidate['source_sha256'],comparison_sha256=candidate['comparison_sha256'],decision='publish')
    return console,request,publisher,bundle_case


def test_status_projects_current_package_without_private_host_paths(console_case):
    console,request,publisher,case=console_case;result=console.status()
    assert result['phase']=='awaiting_approval' and result['candidate']['publication_available'] is True
    assert result['candidate']['changes'] and result['candidate']['evaluation']['checker']['passed']
    assert str(case[2]) not in json.dumps(result) and not publisher.calls


def test_defer_is_audited_without_approval_models_or_ledger_changes(console_case):
    console,request,publisher,case=console_case;before=[ledger_snapshot(p) for p in case[4][:2]];request['decision']='defer'
    result=console.submit(request);assert result['status']=='deferred'
    assert case[0].status()['phase']=='awaiting_approval' and publisher.calls==[]
    assert [ledger_snapshot(p) for p in case[4][:2]]==before
    from myink.pi_audit import AuditReader
    events=AuditReader(console.export_root).events('admin-'+request['request_id'])['items'];assert events[-1]['details']['decision']=='defer'


def test_publish_is_async_and_bound_to_the_exact_human_approved_package(console_case):
    console,request,publisher,case=console_case;before=[ledger_snapshot(p) for p in case[4][:2]]
    assert console.submit(request)['status']=='queued' and not publisher.calls
    result=console.process(request['request_id']);assert result['status']=='succeeded' and publisher.calls==['prepare','publish']
    assert case[0].status()['phase']=='observing' and [ledger_snapshot(p) for p in case[4][:2]]==before
    assert console.submit(request)==result and console.process(request['request_id'])==result
    assert publisher.calls==['prepare','publish']


@pytest.mark.parametrize('field',['cycle_id','package_sha256','image_id','source_sha256','comparison_sha256'])
def test_stale_or_wrong_candidate_is_rejected_before_claim_or_side_effect(console_case,field):
    console,request,publisher,case=console_case;request[field]=str(uuid.uuid4()) if field=='cycle_id' else ('sha256:' if field=='image_id' else '')+'0'*64
    with pytest.raises(ValueError):console.submit(request)
    assert publisher.calls==[] and case[0].status()['phase']=='awaiting_approval'


def test_extra_fields_and_actor_spoofing_idempotency_are_rejected(console_case):
    console,request,publisher,case=console_case
    with pytest.raises(ValueError):console.submit(dict(request,command='arbitrary shell'))
    console.submit(request)
    with pytest.raises(ValueError):console.submit(dict(request,actor_id=str(uuid.uuid4())))
    assert publisher.calls==[]


def test_two_concurrent_publish_requests_cannot_create_two_operations(console_case):
    console,request,publisher,case=console_case
    def submit(r):
        try:return console.submit(r)['request_id']
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(submit,[request,dict(request,request_id=str(uuid.uuid4()))]))
    assert sum(r is not None for r in results)==1 and publisher.calls==[]


def test_restart_retains_unknown_operation_and_never_replays(console_case):
    from ops.pi.admin_console import Console
    console,request,publisher,case=console_case;console.submit(request)
    reopened=Console(case[0],console.root,console.audit_path,console.export_root,console.path,publisher=publisher)
    assert reopened.operation(request['request_id'])['status']=='uncertain'
    assert reopened.process(request['request_id'])['status']=='uncertain' and publisher.calls==[]


def test_audit_failure_prevents_approval_and_publication(console_case,monkeypatch):
    console,request,publisher,case=console_case
    def broken(*args):raise OSError('audit unavailable')
    monkeypatch.setattr(console,'_audit',broken)
    with pytest.raises(OSError):console.submit(request)
    assert case[0].status()['phase']=='awaiting_approval' and publisher.calls==[]


def test_interruption_after_approval_is_uncertain_and_not_replayed(console_case,monkeypatch):
    console,request,publisher,case=console_case;console.submit(request)
    def stopped(*args):publisher.calls.append('interrupted');raise TimeoutError('unknown deployment')
    monkeypatch.setattr(publisher,'publish',stopped)
    result=console.process(request['request_id']);assert result['status']=='uncertain'
    assert case[0].status()['phase']=='awaiting_deployment'
    console.process(request['request_id']);assert publisher.calls==['prepare','interrupted']


def test_concurrent_identical_request_is_idempotent_even_before_first_audit_finishes(console_case,monkeypatch):
    from threading import Barrier
    console,request,publisher,case=console_case;barrier=Barrier(2);original=console._candidate
    def together(state):
        value=original(state);barrier.wait(timeout=5);return value
    monkeypatch.setattr(console,'_candidate',together)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(console.submit,[request,request]))
    assert {r['request_id'] for r in results}=={request['request_id']} and publisher.calls==[]


def test_a_command_cannot_run_until_its_host_decision_audit_is_durable(console_case,monkeypatch):
    from threading import Event
    console,request,publisher,case=console_case;entered=Event();release=Event();original=console._audit
    def hold(*args):
        entered.set();assert release.wait(5);return original(*args)
    monkeypatch.setattr(console,'_audit',hold)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(console.submit,request);assert entered.wait(5)
        try:
            assert console.operation(request['request_id'])['status']=='recording'
            assert console.process(request['request_id'])['status']=='recording' and publisher.calls==[]
        finally:release.set()
        assert future.result()['status']=='queued'


def test_gate_read_failure_after_deploy_attempt_is_still_recorded_uncertain(console_case,monkeypatch):
    console,request,publisher,case=console_case;console.submit(request)
    def broken_gate():raise OSError('gate unavailable')
    def interrupted(*args):
        monkeypatch.setattr(case[0],'status',broken_gate);raise TimeoutError('deployment interrupted')
    monkeypatch.setattr(publisher,'publish',interrupted)
    assert console.process(request['request_id'])['status']=='uncertain'


def test_defer_cannot_claim_to_hold_a_publication_already_queued(console_case):
    console,request,publisher,case=console_case;console.submit(request)
    with pytest.raises(ValueError):console.submit(dict(request,request_id=str(uuid.uuid4()),decision='defer'))
    assert console.operation(request['request_id'])['status']=='queued' and publisher.calls==[]


def test_candidate_cost_and_request_counts_preserve_original_evidence_domain(console_case):
    console,request,publisher,case=console_case;source=json.loads((case[2]/'bundle/evaluation.json').read_bytes());value=console.status()['candidate']['evaluation']
    for key in ('model_requests','known_cost_microyuan','tool_count','evidence_domain','online_improvement_proven'):assert value[key]==source[key]
    assert value['online_improvement_proven'] is False


def test_verified_publication_registers_nextday_plans_from_actual_deployment_time(console_case):
    from myink.pi_audit import AuditReader
    console,request,publisher,case=console_case;console.submit(request);assert console.process(request['request_id'])['status']=='succeeded'
    daily=AuditReader(console.export_root).daily('2026-10-31');plans={p['test_id']:p for p in daily['next_tests']}
    assert set(plans)=={'nightly-regression-'+case[1],'nightly-metrics-'+case[1]}
    assert all(p['scheduled_for']=='2026-10-31T19:00:00+00:00' and p['target_run_id']==case[3] and p['target_version_sha256']==request['source_sha256'] and p['result'] is None for p in plans.values())
    assert console.status()['next_assessment_at']=='2026-10-31T19:00:00+00:00'
    events=AuditReader(console.export_root).events('admin-'+request['request_id'])['items']
    assert any(proof['kind']=='physical_deployment_receipt' for event in events for proof in event['evidence'])
