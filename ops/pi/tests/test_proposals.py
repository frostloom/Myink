"""Observed signals require host rules and a fresh isolated failed baseline."""
from pathlib import Path
from threading import Event
import json,shutil,sys
import pytest
from ops.pi.development_inputs import file_hash,tree_hash,read_json
from ops.pi.observations import freeze
from ops.pi import proposals
from ops.pi import package_baseline
from ops.pi.tests.test_package_baseline import fake_check

@pytest.fixture
def batch(tmp_path):
    tmp_path.chmod(0o700)
    def write(name,value):
        p=tmp_path/name;p.write_text(value if isinstance(value,str) else json.dumps(value));p.chmod(0o600);return p
    source=tmp_path/'source';(source/'src').mkdir(parents=True);(source/'src/a.py').write_text('value=1\n')
    gold=write('gold.py','import unittest\nfrom a import value\nclass Case(unittest.TestCase):\n def test_bad(self):self.assertEqual(value,2)\n def test_good(self):self.assertEqual(value,1)\n')
    recipe=write('package.json',dict(schema='pi-task-package-v1',task_id='value-fix',problem='Observed existing value bug',source_path=str(source),source_sha256=tree_hash(source),test_path=str(gold),test_sha256=file_hash(gold),files=['src/a.py'],root=str(tmp_path/'draft')))
    xml=write('tests.xml','<testsuite><testcase classname="Case" name="bad"><failure/></testcase><testcase classname="Case" name="good"/><testcase classname="Case" name="unmapped"><failure/></testcase></testsuite>')
    intake=write('intake.json',dict(schema='pi-observation-intake-v1',batch_id='batch',root=str(tmp_path/'observed'),sources=[dict(source_id='junit',kind='junit',path=str(xml),sha256=file_hash(xml),source_sha256=tree_hash(source))]))
    result=freeze(intake)
    rule=dict(rule_id='fix',source_id='junit',observation_id='Case::bad',package_request_path=str(recipe),package_request_sha256=file_hash(recipe),priority=4,trigger=dict(kind='failure'))
    c=dict(schema='pi-proposal-batch-v1',batch_id='proposals',observation_path=result['report_path'],observation_sha256=result['report_sha256'],rules=[rule],root=str(tmp_path/'proposed'),baseline_environment=dict(docker=str(Path(sys.executable).resolve()),endpoint='unix:///tmp/synthetic-proposal-docker.sock',daemon_id='synthetic',checker_image_id='sha256:'+'a'*64,deadline_seconds=60),max_baselines=2,deadline_seconds=180)
    p=write('proposals.json',c)
    return p,c,write


def test_readonly_keeps_all_observation_and_rule_denominators(batch,monkeypatch):
    p,c,_=batch;before={str(f):f.read_bytes() for f in p.parent.rglob('*') if f.is_file()}
    monkeypatch.setattr(proposals,'run_baseline',lambda *a,**kw:pytest.fail('check contacted Docker'))
    r=proposals.check(p)
    assert r['metrics']['observations_total']==3 and r['metrics']['signals_unmapped']==1 and r['metrics']['candidate_count']==1
    assert before=={str(f):f.read_bytes() for f in p.parent.rglob('*') if f.is_file()}


def test_failure_requires_fresh_native_baseline_and_retains_evidence(batch,monkeypatch):
    p,c,_=batch;fake_check(package_baseline,monkeypatch)
    result=proposals.execute(p);r=read_json(result['report_path'])
    assert r['metrics']['baseline_executor_invocations']==1 and r['metrics']['eligible_proposals']==1
    proposal=r['proposals'][0];assert proposal['state']=='eligible' and proposal['catalog'][0]['baseline']['failures']==1
    assert proposal['requires']==['fresh_run_identity','independent_reviews','current_runtime','current_billing_checkpoint']
    assert r['automatic_execution'] is False and r['metrics']['signals_unmapped']==1


@pytest.mark.parametrize('kind',['green','error'])
def test_unqualified_baseline_never_enters_catalog(batch,monkeypatch,kind):
    p,c,_=batch;fake_check(package_baseline,monkeypatch,kind=kind)
    r=read_json(proposals.execute(p)['report_path'])
    assert r['metrics']['eligible_proposals']==0 and r['proposals'][0]['state']=='baseline_rejected'


def test_duplicate_rules_do_not_duplicate_baselines(batch,monkeypatch):
    p,c,write=batch;c['rules'].append(dict(c['rules'][0],rule_id='copy',priority=8));write(p.name,c);fake_check(package_baseline,monkeypatch)
    r=read_json(proposals.execute(p)['report_path'])
    assert len(r['assessments'])==2 and r['metrics']['triggered_rules']==2 and r['metrics']['duplicate_rules']==1
    assert r['metrics']['baseline_executor_invocations']==1 and r['proposals'][0]['priority']==8


def test_passed_rule_preserved_as_non_triggered(batch):
    p,c,write=batch;c['rules'][0]['observation_id']='Case::good';write(p.name,c)
    r=proposals.check(p);assert r['metrics']['candidate_count']==0 and r['metrics']['rules_not_triggered']==1


def test_unknown_execution_blocks_batch_without_baselines(batch,monkeypatch):
    p,c,write=batch;obs=read_json(c['observation_path']);request=read_json(obs['request_path'])
    cycle=write('cycle.json',dict(operation_id='maintenance:x',schema_version=1,status='uncertain',evidence=dict(mode='ACTUAL',released=False)))
    request['sources'].append(dict(source_id='uncertain',kind='cycle',path=str(cycle),sha256=file_hash(cycle),source_sha256=request['sources'][0]['source_sha256']))
    request['root']=str(p.parent/'observed-unknown');new=write('intake-unknown.json',request);o=freeze(new)
    c.update(observation_path=o['report_path'],observation_sha256=o['report_sha256']);write(p.name,c)
    monkeypatch.setattr(proposals,'run_baseline',lambda *a,**kw:pytest.fail('unknown replayed'))
    r=read_json(proposals.execute(p)['report_path']);assert r['requires_reconciliation'] and r['metrics']['baseline_executor_invocations']==0


@pytest.mark.parametrize('kind',['source_drift','observation_drift','rule_source_mismatch','overlap','unknown_field'])
def test_drift_or_invalid_role_rejected(batch,kind):
    p,c,write=batch
    if kind=='source_drift':(p.parent/'source/src/a.py').write_text('value=99\n')
    if kind=='observation_drift':c['observation_sha256']='0'*64
    if kind=='rule_source_mismatch':
        recipe=read_json(c['rules'][0]['package_request_path']);recipe['source_sha256']='e'*64
        f=write('package.json',recipe);c['rules'][0]['package_request_sha256']=file_hash(f)
    if kind=='overlap':c['root']=str(p.parent/'source/new')
    if kind=='unknown_field':c['approved']=True
    write(p.name,c)
    if kind in ('source_drift','rule_source_mismatch'):
        r=proposals.check(p);assert r['metrics']['candidate_count']==0 and r['metrics']['rules_rejected']==1
    else:
        with pytest.raises(ValueError):proposals.check(p)


def test_pre_cancel_never_creates_output(batch):
    p,c,_=batch;cancel=Event();cancel.set()
    with pytest.raises(ValueError):proposals.execute(p,cancel=cancel)
    assert not Path(c['root']).exists()


@pytest.mark.parametrize('value,samples,confounders,expected',[(3,5,[],1),(3,4,[],0),(None,5,[],0),(3,5,['mixed_versions'],0),(1,5,[],0)])
def test_metric_threshold_requires_measured_unconfounded_sample_floor(batch,value,samples,confounders,expected):
    p,c,write=batch;old=read_json(read_json(c['observation_path'])['request_path'])
    m=write('metrics.json',dict(availability='unknown' if value is None else 'measured',confounders=confounders,
        measurements=dict(errors=dict(value=value,samples=samples,availability='unknown' if value is None else 'measured',direction='lower'))))
    old['sources']=[dict(source_id='metrics',kind='metrics',path=str(m),sha256=file_hash(m),source_sha256=tree_hash(p.parent/'source'))];old['root']=str(p.parent/'metric-observations')
    intake=write('metric-intake.json',old);obs=freeze(intake)
    c.update(observation_path=obs['report_path'],observation_sha256=obs['report_sha256'])
    c['rules'][0].update(source_id='metrics',observation_id='metric:errors',trigger=dict(kind='metric_threshold',operator='gt',threshold=2,minimum_samples=5));write(p.name,c)
    assert proposals.check(p)['metrics']['candidate_count']==expected


@pytest.mark.parametrize('bad',['cleanup','skipped','inventory','copy','source','cancel'])
def test_baseline_rejection_and_parent_cancel_preserve_failure_denominator(batch,monkeypatch,bad):
    p,c,_=batch;cancel=Event()
    def change(cfg,source,dest,limits,owners,result):
        if bad=='cleanup':owners.history.clear()
        elif bad=='skipped':result.update(skipped=1,failures=0,failed_cases=[])
        elif bad=='inventory':result['cases']=[]
        elif bad=='copy':(dest/'src/a.py').write_text('wrong=True\n')
        elif bad=='source':(p.parent/'source/src/a.py').write_text('value=3\n')
        else:cancel.set()
    fake_check(package_baseline,monkeypatch,change=change)
    r=read_json(proposals.execute(p,cancel=cancel)['report_path'])
    assert r['metrics']['baseline_executor_invocations']==1 and r['metrics']['eligible_proposals']==0
    assert r['metrics']['signals_total']==2 and len(r['assessments'])==1


def test_duplicate_observation_cannot_be_selected_implicitly(batch):
    p,c,write=batch;old=read_json(read_json(c['observation_path'])['request_path'])
    xml=write('duplicates.xml','<testsuite><testcase classname="Case" name="bad"><failure/></testcase><testcase classname="Case" name="bad"><failure/></testcase></testsuite>')
    old['sources'][0].update(path=str(xml),sha256=file_hash(xml));old['root']=str(p.parent/'duplicates-observations')
    intake=write('duplicates-intake.json',old);obs=freeze(intake);c.update(observation_path=obs['report_path'],observation_sha256=obs['report_sha256']);write(p.name,c)
    r=proposals.check(p);assert r['metrics']['observations_total']==2 and r['metrics']['candidate_count']==0 and r['metrics']['rules_rejected']==1


def test_later_baseline_drift_invalidates_earlier_eligibility(batch,monkeypatch):
    p,c,write=batch;original=read_json(c['rules'][0]['package_request_path']);other_source=p.parent/'other-source';shutil.copytree(p.parent/'source',other_source)
    (other_source/'src/a.py').write_text('value=0\n')
    other=write('other.json',dict(original,task_id='other',source_path=str(other_source),source_sha256=tree_hash(other_source),root=str(p.parent/'other-draft')))
    old=read_json(read_json(c['observation_path'])['request_path']);xml=write('other.xml','<testsuite><testcase classname="Case" name="bad"><failure/></testcase></testsuite>')
    old['sources'].append(dict(old['sources'][0],source_id='other',path=str(xml),sha256=file_hash(xml),source_sha256=tree_hash(other_source)));old['root']=str(p.parent/'other-observations')
    obs=freeze(write('other-intake.json',old));c.update(observation_path=obs['report_path'],observation_sha256=obs['report_sha256'])
    c['rules'].append(dict(c['rules'][0],rule_id='other',source_id='other',package_request_path=str(other),package_request_sha256=file_hash(other)));write(p.name,c)
    calls=[]
    def change(*args):
        calls.append(1)
        if len(calls)==2:(p.parent/'source/src/a.py').write_text('value=99\n')
    fake_check(package_baseline,monkeypatch,change=change)
    r=read_json(proposals.execute(p)['report_path'])
    assert r['inputs_current'] is False and r['metrics']['eligible_proposals']==1
    assert r['proposals'][0]['state']=='input_changed'


def test_baseline_observation_protects_all_native_input_and_output_roles(batch,monkeypatch):
    p,c,write=batch;fake_check(package_baseline,monkeypatch);first=read_json(proposals.execute(p)['report_path']);proposal=first['proposals'][0]
    intake=write('baseline-intake.json',dict(schema='pi-observation-intake-v1',batch_id='baseline-observed',root=str(p.parent/'baseline-observed'),sources=[dict(source_id='baseline',kind='baseline',path=proposal['baseline_outcome_path'],sha256=proposal['baseline_outcome_sha256'],source_sha256=proposal['source_sha256'],request_path=proposal['baseline_request_path'],request_sha256=proposal['baseline_request_sha256'])]))
    observed=freeze(intake);parent=Path(proposal['baseline_root'])/'check/src';parent.chmod(0o700)
    c.update(observation_path=observed['report_path'],observation_sha256=observed['report_sha256'],root=str(parent/'new-proposals'))
    c['rules'][0].update(source_id='baseline',observation_id='baseline');new=write('overlap-proposals.json',c)
    with pytest.raises(ValueError):proposals.check(new)
    assert not (parent/'new-proposals').exists()
