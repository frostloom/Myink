"""Host registry authority and true due-time tests; callbacks remain synthetic."""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
from pathlib import Path
import fcntl,json,importlib
import pytest
from ops.pi.audit import AuditStore,digest
from ops.pi.development_inputs import tree_hash,file_hash
from ops.pi.ledger import Ledger
from myink.pi_audit import AuditReader

NOW=datetime(2026,10,28,19,5,tzinfo=timezone.utc)
CASES=['fixed_development_tests.Check.test_a']


def api():return importlib.import_module('ops.pi.followup')


def report(passed=True):
    return dict(tests=1,cases=CASES,failures=0 if passed else 1,errors=0,skipped=0,passed=passed,
        failed_cases=[] if passed else CASES,error_cases=[],diagnostics=[],load_error=False,
        attach_returncode=0 if passed else 1,container_id='owned',cleanup=[dict(container_id='owned',removed=True,exit_code=0 if passed else 1)])


@pytest.fixture
def configured(tmp_path):
    for name in ('config','control','state','audit','runs','jobs'):(tmp_path/name).mkdir(mode=0o700)
    lock=tmp_path/'control/maintenance.lock';lock.touch(mode=0o600)
    for name in ('billing.sqlite','manager.sqlite'):
        p=tmp_path/'state'/name;Ledger(p);p.chmod(0o600)
    for name in ('source','candidate'):
        p=tmp_path/'jobs'/name;(p/'src').mkdir(parents=True);(p/'src/example.py').write_text('raise RuntimeError("never import candidate on host")\n')
    gold=tmp_path/'jobs/gold.py';gold.write_text('raise RuntimeError("never import gold on host")\n')
    review=tmp_path/'jobs/review.json';review.write_text('{"result":"approved"}')
    e=dict(test_id='nextday-fixed',run_id='original',scheduled_for=(NOW-timedelta(minutes=5)).isoformat(),
        candidate_path=str(tmp_path/'jobs/candidate'),candidate_sha256=tree_hash(tmp_path/'jobs/candidate'),
        source_path=str(tmp_path/'jobs/source'),source_sha256=tree_hash(tmp_path/'jobs/source'),test_path=str(gold),test_sha256=file_hash(gold),test_cases=CASES,
        review_path=str(review),review_sha256=file_hash(review),checker=dict(docker='/usr/bin/docker',endpoint='unix:///var/run/docker.sock',daemon_id='fixed',checker_image_id='sha256:'+'a'*64))
    c=dict(schema='pi-followup-registry-v1',mode='SIMULATED',root=str(tmp_path/'runs'),audit_path=str(tmp_path/'audit/events.sqlite'),export_root=str(tmp_path/'audit/export'),lock_path=str(lock),billing_path=str(tmp_path/'state/billing.sqlite'),manager_path=str(tmp_path/'state/manager.sqlite'),entries=[e])
    store=AuditStore(c['audit_path']);plan=dict(test_id=e['test_id'],scheduled_for=e['scheduled_for'],target_run_id=e['run_id'],target_version_sha256=e['candidate_sha256'],criterion='Fixed original cases and state invariance',kind='regression',status='planned')
    store.append('plan',dict(kind='followup',status='planned',run_id='original',occurred_at=(NOW-timedelta(hours=5)).isoformat(),summary='Reserved fixed test',details={},version={},changes=[],evidence=[],followups=[plan],mode='ACTUAL',evidence_domain='real_provider_fixed_input'))
    p=tmp_path/'config/registry.json';p.write_text(json.dumps(c));p.chmod(0o600)
    return p,c


def update(configured,**changes):
    p,c=configured;c.update(changes);p.write_text(json.dumps(c));return p


def run(configured,runner=None,now=NOW,pin=None):
    p,c=configured
    return api().run_due(p,pin or sha256(p.read_bytes()).hexdigest(),clock=lambda:now,runner=runner or (lambda *a:report()))


def test_due_synthetic_test_is_once_only_and_cannot_certify_actual_nextday(configured):
    called=[]
    result=run(configured,lambda *a:called.append(a) or report())
    assert result['mode']=='SIMULATED' and result['results'][0]['status']=='passed' and len(called)==1
    again=run(configured,lambda *a:(_ for _ in ()).throw(AssertionError('replayed')))
    assert again['results']==result['results']
    r=AuditReader(Path(configured[1]['export_root']))
    assert r.daily('2026-10-28')['next_tests'][0]['result'] is None
    assert r.events('original',kind='test')['items'][0]['details']['test_id']=='nextday-fixed'


@pytest.mark.parametrize('now,status',[(NOW-timedelta(minutes=6),'planned'),(NOW-timedelta(hours=2),'planned'),(NOW+timedelta(hours=3),'outside_window'),(NOW+timedelta(hours=2,minutes=26),'outside_window')])
def test_true_due_and_maintenance_cutoff_without_claim(configured,now,status):
    result=run(configured,lambda *a:pytest.fail('not admitted'),now)
    assert result['status']==status and list(Path(configured[1]['root']).iterdir())==[]


def test_shared_manager_lock_contention_cannot_create_claim(configured):
    with open(configured[1]['lock_path'],'rb') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert run(configured,lambda *a:pytest.fail('locked'))['status']=='lock_busy'
    assert list(Path(configured[1]['root']).iterdir())==[]


@pytest.mark.parametrize('change',['pin','schema','extra','candidate','source','gold','review','audit','overlap','symlink','cases','due_plan'])
def test_drift_or_unapproved_input_fails_before_checker(configured,change,tmp_path):
    p,c=configured;e=c['entries'][0]
    if change=='pin':
        with pytest.raises(ValueError):run(configured,pin='0'*64)
        return
    if change=='schema':c['schema']='model-plan'
    elif change=='extra':c['command']='anything'
    elif change in ('candidate','source'):(Path(e[change+'_path'])/'src/example.py').write_text('changed')
    elif change in ('gold','review'):Path(e['test_path' if change=='gold' else 'review_path']).write_text('changed')
    elif change=='audit':c['audit_path']=c['billing_path']
    elif change=='overlap':c['root']=e['candidate_path']
    elif change=='symlink':
        alias=tmp_path/'alias';alias.symlink_to(e['candidate_path']);e['candidate_path']=str(alias)
    elif change=='cases':e['test_cases']=['arbitrary.case']
    elif change=='due_plan':e['scheduled_for']=(NOW-timedelta(minutes=4)).isoformat()
    p.write_text(json.dumps(c))
    with pytest.raises(ValueError):run(configured,lambda *a:pytest.fail('unsafe checker'))


def test_actual_rejects_injected_runner_before_any_execution(configured):
    update(configured,mode='ACTUAL')
    with pytest.raises(ValueError,match='ACTUAL'):run(configured)


def test_pending_claim_is_retained_without_replay(configured):
    with pytest.raises(KeyboardInterrupt):run(configured,lambda *a:(_ for _ in ()).throw(KeyboardInterrupt()))
    result=run(configured,lambda *a:pytest.fail('pending replay'))
    assert result['status']=='uncertain' and result['results'][0]['status']=='uncertain'


@pytest.mark.parametrize('failure',['assertion','cleanup','cases','source_drift','billing_drift'])
def test_failures_are_retained_and_never_replayed_as_pass(configured,failure):
    def backend(*args):
        result=report(failure!='assertion')
        if failure=='cleanup':result['cleanup'][0]['removed']=False
        if failure=='cases':result['cases']=[]
        if failure=='source_drift':(Path(configured[1]['entries'][0]['candidate_path'])/'src/example.py').write_text('drift')
        if failure=='billing_drift':Ledger(Path(configured[1]['billing_path'])).append_event('external-change',{})
        return result
    result=run(configured,backend)
    assert result['results'][0]['status']==('failed' if failure=='assertion' else 'blocked')
    assert run(configured,lambda *a:pytest.fail('failed replay'))['results']==result['results']


def test_registry_revocation_during_check_cannot_certify_success(configured):
    def backend(*args):
        p,c=configured;c['entries'][0]['review_sha256']='0'*64;p.write_text(json.dumps(c));return report()
    result=run(configured,backend)
    assert result['results'][0]['status']=='blocked'


def test_completion_crossing_maintenance_end_is_not_a_pass(configured):
    p,c=configured;current=[NOW]
    def backend(*args):current[0]=NOW+timedelta(hours=4);return report()
    result=api().run_due(p,sha256(p.read_bytes()).hexdigest(),clock=lambda:current[0],runner=backend)
    assert result['results'][0]['status']=='blocked'


def test_time_is_rechecked_after_validation_before_claim(configured):
    p,c=configured;moments=iter((NOW,NOW+timedelta(hours=4)))
    result=api().run_due(p,sha256(p.read_bytes()).hexdigest(),clock=lambda:next(moments),runner=lambda *a:pytest.fail('late claim'))
    assert result['status']=='outside_window' and list(Path(c['root']).iterdir())==[]
