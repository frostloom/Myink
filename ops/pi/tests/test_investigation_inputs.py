"""Research inputs retain reference identity; proposals are never approval."""
from pathlib import Path
import importlib,pytest
from ops.pi.audit import digest
from ops.pi.development_inputs import tree_hash,file_hash


@pytest.fixture
def research(tmp_path):
    tmp_path.chmod(0o700);source=tmp_path/'reference';(source/'src').mkdir(parents=True)
    (source/'src/a.py').write_text('def value():\n return 1\n');(source/'src/unrelated.py').write_text('unrelated = 1\n')
    evidence=dict(mode='SIMULATED',evidence_fingerprint='b'*64,cohort_sha256='c'*64,observed_samples=1,gaps=['insufficient_samples','unknown_identity'],source_commit=None)
    return source,evidence


def api():return importlib.import_module('ops.pi.investigation_inputs')


def context(research,**kwargs):
    source,e=research;return api().compile_context(source,tree_hash(source),['src/a.py'],e,**kwargs)


def test_research_context_is_reference_only_complete_bounded_and_readonly(research):
    source,e=research;before={p:p.read_bytes() for p in source.rglob('*') if p.is_file()};c=context(research,reference_commit='a'*40)
    assert c['authority']=='proposal_only' and c['source_kind']=='reference_snapshot' and c['online_improvement_proven'] is False
    assert c['observed_source_commit'] is None and c['reference_commit']=='a'*40 and c['observed_samples']==1
    assert c['files'][0]['text']=='def value():\n return 1\n' and str(source) not in str(c)
    assert before=={p:p.read_bytes() for p in source.rglob('*') if p.is_file()}


def test_research_novelty_ignores_unrelated_reference_commits_but_not_relevant_source(research):
    source,e=research;first=context(research,reference_commit='a'*40)
    (source/'src/unrelated.py').write_text('unrelated = 2\n');second=context(research,reference_commit='d'*40)
    assert first['research_fingerprint']==second['research_fingerprint'] and digest(first)!=digest(second)
    (source/'src/a.py').write_text('def value():\n return 3\n')
    assert context(research)['research_fingerprint']!=first['research_fingerprint']


@pytest.mark.parametrize('fault',['path','duplicate','source_pin','secret','oversize','bool_count','identity','pending_file','pending_symbol'])
def test_invalid_or_known_pending_research_never_becomes_model_input(research,fault):
    source,e=research;files=['src/a.py'];pin=tree_hash(source);pending=[]
    if fault=='path':files=['../outside.py']
    elif fault=='duplicate':files*=2
    elif fault=='source_pin':pin='e'*64
    elif fault=='secret':(source/'src/a.py').write_text('JWT_SECRET: str = "private_value"\n');pin=tree_hash(source)
    elif fault=='oversize':(source/'src/a.py').write_text('value = "'+'x'*25000+'"');pin=tree_hash(source)
    elif fault=='bool_count':e['observed_samples']=True
    elif fault=='identity':e['source_commit']='fabricated'
    elif fault=='pending_file':pending=[dict(path='src/a.py',file_sha256=file_hash(source/'src/a.py'),symbol=None,symbol_sha256=None,candidate_sha256='f'*64)]
    else:
        symbol=api().symbol_hash('def value():\n return 1\n','value');pending=[dict(path='src/a.py',file_sha256='0'*64,symbol='value',symbol_sha256=symbol,candidate_sha256='f'*64)]
        (source/'src/a.py').write_text('def value():\n return 1\nother = 7\n');pin=tree_hash(source)
    with pytest.raises((ValueError,OSError)):api().compile_context(source,pin,files,e,pending=pending)


def proposal(c,**changes):
    value=dict(schema='pi-test-proposal-v1',input_sha256=digest(c),decision='task',problem='Existing documented behavior returns wrong value.',files=['src/a.py'],test_source='import unittest\nfrom a import value\nclass Case(unittest.TestCase):\n def test_value(self): self.assertEqual(value(),2)\n',summary='Untrusted test proposal only.');value.update(changes);return value


def test_strict_test_proposal_and_abstention_grant_no_execution(research):
    c=context(research);value=proposal(c);r=api().validate_proposal(value,c)
    assert r==value and 'approved' not in r
    empty=proposal(c,decision='no_task',problem=None,files=[],test_source=None)
    assert api().validate_proposal(empty,c)==empty


@pytest.mark.parametrize('fault',['authority','input','scope','duplicate','test','no_task_payload','summary','extra'])
def test_untrusted_proposal_cannot_choose_authority_paths_or_incomplete_inventory(research,fault):
    c=context(research);v=proposal(c)
    if fault=='authority':v['decision']='approve'
    elif fault=='input':v['input_sha256']='e'*64
    elif fault=='scope':v['files']=['src/other.py']
    elif fault=='duplicate':v['files']*=2
    elif fault=='test':v['test_source']='raise AssertionError("not a test inventory")'
    elif fault=='no_task_payload':v['decision']='no_task'
    elif fault=='summary':v['summary']='x'*1001
    else:v['review_path']='/tmp/self-approval'
    with pytest.raises(ValueError):api().validate_proposal(v,c)


def test_research_preserves_real_host_failure_counts_without_claiming_improvement(research):
    from ops.pi.live_diagnosis import COUNTS
    source,e=research
    counts={key:0 for key in COUNTS};counts.update(planned=4,completed=1,failed=3,complete_tasks=1,tail_samples=1)
    e['facts']=dict(counts=counts,measurements={},version_range={},availability='unknown',confounders=[],task_types=['short'],model_ids=[],pricing_id=None,pricing_range=[],pricing_availability='unknown',cohort_sha256=e['cohort_sha256'],minimum_samples=20)
    value=context(research)
    assert value['observation_facts']==e['facts'] and value['observation_facts']['counts']['failed']==3
    assert value['online_improvement_proven'] is False
