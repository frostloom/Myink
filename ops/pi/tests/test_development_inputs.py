"""Read-only host input boundaries for the controlled development entry."""
import json
from pathlib import Path

import pytest
from ops.pi.ledger import Ledger
from ops.pi.development_inputs import (read_json, tree_hash, ledger_snapshot,
                                       authorization_hash, validate_review)


def test_duplicate_json_rejected(tmp_path):
    path = tmp_path/'config.json'
    path.write_text('{"run_id":"a","run_id":"b"}')
    with pytest.raises(ValueError, match='duplicate'):
        read_json(path)


def test_full_tree_dependency_drift_and_links(tmp_path):
    (tmp_path/'src').mkdir()
    (tmp_path/'src/a.py').write_text('a')
    (tmp_path/'src/dependency.py').write_text('before')
    first = tree_hash(tmp_path)
    (tmp_path/'src/dependency.py').write_text('after')
    assert tree_hash(tmp_path) != first
    (tmp_path/'src/link.py').symlink_to('a.py')
    with pytest.raises(ValueError, match='link'):
        tree_hash(tmp_path)


def test_missing_ledger_never_created(tmp_path):
    path = tmp_path/'missing.sqlite'
    with pytest.raises((ValueError, OSError)):
        ledger_snapshot(path)
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_ledger_snapshot_readonly_and_detects_history_append(tmp_path):
    path = tmp_path/'ledger.sqlite'
    ledger = Ledger(path)
    ledger.intent('one', 'test', {})
    before = {p.name:p.read_bytes() for p in tmp_path.iterdir() if not p.name.endswith('-shm')}
    snap = ledger_snapshot(path)
    assert snap['operations'][0]['operation_id'] == 'one'
    assert before == {p.name:p.read_bytes() for p in tmp_path.iterdir() if not p.name.endswith('-shm')}
    ledger.intent('two', 'test', {})
    assert ledger_snapshot(path)['sha256'] != snap['sha256']


def test_review_binds_authorization_not_own_location():
    config = dict(run_id='fresh', root='/tmp/output', review_path='/tmp/review', review_sha256='x')
    expected = authorization_hash(config)
    assert authorization_hash(dict(config, review_sha256='y')) == expected
    assert authorization_hash(dict(config, root='/tmp/other')) != expected
    review = dict(source='independent_review', verified=True, result='approved', reviewer='human-review',
                  authorization_sha256=expected, plan_hash='plan', base='source', candidate_id='fresh',
                  owner='local-development-controller', generation=1)
    validate_review(review, config, 'plan', 'source')
    with pytest.raises(ValueError, match='review'):
        validate_review(dict(review, reviewer='model'), config, 'plan', 'source')
    with pytest.raises(ValueError, match='review'):
        validate_review(review, dict(config, root='/tmp/other'), 'plan', 'source')

@pytest.fixture
def config_file(tmp_path, monkeypatch):
    from dataclasses import asdict, replace
    from ops.pi import development_inputs as inputs
    from ops.pi.plans import Plan
    from ops.pi.policy import load_policy
    tmp_path.chmod(0o700)
    def write(name, value):
        p = tmp_path/name
        p.write_text(json.dumps(value)); p.chmod(0o600)
        return str(p)
    source = tmp_path/'source'; (source/'src').mkdir(parents=True)
    (source/'src/a.py').write_text('value = 1\n')
    runtime = tmp_path/'runtime'; runtime.mkdir()
    for name in ('extensions/controlled-tools.ts','extensions/tool-schemas.json','lab/pi-wire-guard.mjs'):
        target=runtime/'code/ops/pi'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('synthetic')
    ledger_path = tmp_path/'ledger.sqlite'
    Ledger(ledger_path).intent('model-scope:local-trial-1','model-scope',dict(max_attempts=100,budget_microyuan=10000000))
    ledger_path.chmod(0o600)
    policy = replace(load_policy(Path('ops/pi/policy.example.json')), input_bound_calibrated=True)
    plan = Plan('fix','coverage',.1,.1,5,('guard',),'baseline','test','stability',('src/a.py',),('slice',),
                'preserved','restore',30,900,'change value',evidence_domain='synthetic')
    c = dict(schema='pi-development-v1',run_id='test-run',root=str(tmp_path/'output'),
             source_path=str(source),source_sha256=tree_hash(source),runtime_path=str(runtime),runtime_sha256='0'*64,
             ledger_path=str(ledger_path),ledger_sha256=ledger_snapshot(ledger_path)['sha256'],
             policy_path=write('policy.json',asdict(policy)),credential_path=write('credential.json',dict(
                 PLATFORM_MODEL_API_KEY='synthetic',PLATFORM_MODEL_BASE_URL=policy.base_url,
                 PLATFORM_MODEL_NAME=policy.model,PLATFORM_MODEL_PROTOCOL=policy.protocol)),
             plan_path=write('plan.json',asdict(plan)),baseline_path=write('baseline.json',dict(
                 id='baseline',metric='coverage',config_hash='test',evidence_domain='synthetic',paired_groups=5)),
             test_path=write('test.py','synthetic'),test_cases=['fixed_development_tests.Case.test_one'],
             docker='/bin/false',endpoint='unix:///tmp/docker.sock',daemon_id='synthetic',
             image_id='sha256:'+'0'*64,checker_image_id='sha256:'+'1'*64,
             max_requests=30,max_tools=64,deadline_seconds=900)
    for name in ('policy','credential','plan','baseline','test'):
        c[name+'_sha256']=inputs.file_hash(c[name+'_path'])
    review = dict(source='independent_review',verified=True,result='approved',reviewer='host-review',
                  authorization_sha256=authorization_hash(c),plan_hash=plan.plan_hash,base=c['source_sha256'],
                  candidate_id=c['run_id'],owner=inputs.OWNER,generation=1)
    c['review_path']=write('review.json',review)
    c['review_sha256']=inputs.file_hash(c['review_path'])
    cp = Path(write('config.json',c))
    monkeypatch.setattr(inputs,'verify_source',lambda *a: {})
    return cp, c


def test_valid_preflight_does_not_create_output_or_lock(config_file):
    from ops.pi.development_inputs import check
    cp,c = config_file
    before = {p.relative_to(cp.parent):p.read_bytes() for p in cp.parent.rglob('*') if p.is_file()}
    assert check(cp)['ready'] is True
    assert not Path(c['root']).exists()
    assert before == {p.relative_to(cp.parent):p.read_bytes() for p in cp.parent.rglob('*') if p.is_file()}


@pytest.mark.parametrize('change', ['unknown','source','ledger','review','open_policy','case_inventory'])
def test_preflight_rejects_drift_before_output(config_file, change):
    from ops.pi.development_inputs import check
    cp,c = config_file
    if change == 'unknown': c['unexpected']=True
    elif change == 'source': (Path(c['source_path'])/'src/a.py').write_text('drift')
    elif change == 'ledger': Ledger(c['ledger_path']).intent('new','test',{})
    elif change == 'review':
        p=Path(c['review_path']); r=json.loads(p.read_text());r['reviewer']='model';p.write_text(json.dumps(r))
        c['review_sha256']=__import__('hashlib').sha256(p.read_bytes()).hexdigest()
    elif change == 'open_policy':
        p=Path(c['policy_path']);r=json.loads(p.read_text());r['live_enabled']=True;p.write_text(json.dumps(r))
        c['policy_sha256']=__import__('hashlib').sha256(p.read_bytes()).hexdigest()
    else: c['test_cases'] = []
    cp.write_text(json.dumps(c))
    with pytest.raises(ValueError): check(cp)
    assert not Path(c['root']).exists()
