"""Only authenticated proposals reach the fixed checker; no approval is minted."""
from datetime import timedelta
from pathlib import Path
import importlib,pytest
from ops.pi.development_inputs import file_hash,ledger_snapshot,read_json,prepare_template
from ops.pi.tests.test_investigation_evidence import completed_research,research_config,diagnosis_config,config_file,configured,proof,NOW,write
from ops.pi.tests.test_package_baseline import fake_check


@pytest.fixture
def reproduction(completed_research):
    cp,c,context,permit=completed_research;parent=cp.parent;roots=parent/'reproductions';roots.mkdir(mode=0o700)
    p=dict(schema='pi-investigation-reproducer-v1',authority='isolated_reproducer',mode=c['mode'],run_id='reproduce-one',root=str(roots/('repro-'+context['research_fingerprint'])),research_config_path=str(cp),research_config_sha256=file_hash(cp),checker_image_id='sha256:'+'1'*64,check_seconds=60,max_requests=30,max_tools=64,development_seconds=900,behavior='value',issued_at=(NOW-timedelta(minutes=1)).isoformat(),expires_at=(NOW+timedelta(minutes=10)).isoformat())
    pp=parent/'reproducer-policy.json';write(pp,p);return pp,p,c


def api():return importlib.import_module('ops.pi.investigation_reproducer')


def runner(monkeypatch,kind='failed'):
    base=importlib.import_module('ops.pi.package_baseline')
    def refine(c,source,dest,limits,owners,result):
        result['container_id']='c'*64;owners.history[-1]['container_id']='c'*64
    fake_check(base,monkeypatch,kind,refine)
    return base.execute


def test_verified_failed_baseline_builds_unapproved_functional_template_and_dossier(reproduction,monkeypatch):
    pp,p,c=reproduction;before=ledger_snapshot(c['ledger_path']);r=api().execute(pp,file_hash(pp),runner=runner(monkeypatch),clock=lambda:NOW)
    assert r['status']=='reproduced' and r['eligible_for_review'] is True and r['model_requests']==0
    template=read_json(r['template_path']);plan=read_json(template['plan_path']);baseline=read_json(template['baseline_path'])
    assert plan['evidence_domain']=='code_regression' and baseline['reproduction']['failures']==1 and baseline['reproduction']['errors']==baseline['reproduction']['skipped']==0
    assert not {'paired_groups','complete_tasks'} & baseline.keys() and template['review_sha256']=='0'*64 and not Path(template['review_path']).exists()
    assert prepare_template(r['template_path'])[0]==template and ledger_snapshot(c['ledger_path'])==before
    assert read_json(r['dossier_path'])['authority']=='none'
    with pytest.raises(ValueError):api().execute(pp,file_hash(pp),runner=runner(monkeypatch),clock=lambda:NOW)


@pytest.mark.parametrize('kind',['green','error'])
def test_nonreproducing_or_error_baseline_never_emits_development_template(reproduction,monkeypatch,kind):
    pp,p,c=reproduction;before=ledger_snapshot(c['ledger_path']);r=api().execute(pp,file_hash(pp),runner=runner(monkeypatch,kind),clock=lambda:NOW)
    assert r['eligible_for_review'] is False and r['template_path'] is None and not (Path(p['root'])/'development-template.json').exists()
    assert ledger_snapshot(c['ledger_path'])==before


@pytest.mark.parametrize('fault',['policy_pin','authority','expiry','root_overlap','checker','limits','evidence','actual_injection'])
def test_bad_reproducer_scope_never_executes_gold_or_changes_ledger(reproduction,monkeypatch,fault):
    pp,p,c=reproduction
    if fault=='authority':p['authority']='model_approved_execution'
    elif fault=='expiry':p['expires_at']=NOW.isoformat()
    elif fault=='root_overlap':p['root']=c['source_path']
    elif fault=='checker':p['checker_image_id']='latest'
    elif fault=='limits':p['development_seconds']=1801
    elif fault=='evidence':write(Path(c['root'])/'verification.json',{})
    elif fault=='actual_injection':p['mode']='ACTUAL'
    write(pp,p);pin='f'*64 if fault=='policy_pin' else file_hash(pp);before=ledger_snapshot(c['ledger_path']);calls=[]
    def no(path):calls.append(path);raise AssertionError('invalid scope must not execute tests')
    with pytest.raises((ValueError,OSError,KeyError,TypeError)):api().execute(pp,pin,runner=no,clock=lambda:NOW)
    assert not calls and ledger_snapshot(c['ledger_path'])==before


def test_cancelled_reproduction_does_not_create_claim_or_run_gold(reproduction):
    from threading import Event
    pp,p,c=reproduction;cancel=Event();cancel.set();calls=[];before=ledger_snapshot(c['ledger_path'])
    def no(*args,**kwargs):calls.append(True)
    with pytest.raises(ValueError):api().execute(pp,file_hash(pp),runner=no,clock=lambda:NOW,cancel=cancel)
    assert not calls and not Path(p['root']).exists() and ledger_snapshot(c['ledger_path'])==before


def test_checker_exception_retains_intent_and_audits_failure_without_replay(reproduction):
    from ops.pi.audit import AuditStore
    pp,p,c=reproduction;before=ledger_snapshot(c['ledger_path'])
    def fail(*args,**kwargs):raise RuntimeError('synthetic checker crash')
    with pytest.raises(RuntimeError):api().execute(pp,file_hash(pp),runner=fail,clock=lambda:NOW)
    assert (Path(p['root'])/'intent.json').exists() and not (Path(p['root'])/'receipt.json').exists()
    events=AuditStore(c['audit_path']).events(run_id=p['run_id']);assert events[-1]['status']=='blocked' and events[-1]['details']['reason']=='RuntimeError'
    with pytest.raises(ValueError):api().execute(pp,file_hash(pp),runner=fail,clock=lambda:NOW)
    assert ledger_snapshot(c['ledger_path'])==before


@pytest.mark.parametrize('completed_research',['no_task'],indirect=True)
def test_verified_no_task_does_not_freeze_or_execute_gold(reproduction):
    pp,p,c=reproduction;calls=[];before=ledger_snapshot(c['ledger_path'])
    def no(*args,**kwargs):calls.append(True);raise AssertionError('no-task has no test')
    result=api().execute(pp,file_hash(pp),runner=no,clock=lambda:NOW)
    assert result['status']=='no_task' and not result['eligible_for_review'] and not calls
    assert not (Path(p['root'])/'untrusted-test.py').exists() and ledger_snapshot(c['ledger_path'])==before


def test_main_reader_exposes_baseline_failure_as_review_input_not_release(reproduction,monkeypatch):
    import importlib.util
    pp,p,c=reproduction;api().execute(pp,file_hash(pp),runner=runner(monkeypatch),clock=lambda:NOW)
    spec=importlib.util.spec_from_file_location('reproduction_reader',Path('src/myink/pi_audit.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    reader=module.AuditReader(Path(c['export_root']));event=reader.events(p['run_id'])['items'][-1]
    assert event['kind']=='test' and event['status']=='failed' and event['details']['test_total']==1 and event['details']['test_failures']==1
    assert event['details']['test_errors']==event['details']['test_skipped']==0 and event['details']['next_action']=='independent_review_required'
    assert reader.daily(event['day'])['release_state']=='unknown'
