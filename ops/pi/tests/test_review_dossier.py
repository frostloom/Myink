"""Read-only independent-review input binds source, actual checker and semantics."""
from copy import deepcopy
from pathlib import Path
from dataclasses import asdict
import importlib,json,shutil
import pytest
from ops.pi.audit import digest,encoded
from ops.pi.development_inputs import file_hash,read_json,tree_hash
from ops.pi.tests.test_development_inputs import config_file
from ops.pi.tests.test_code_regression_plan import plan as code_plan


def api():return importlib.import_module('ops.pi.review_dossier')


def write(p,v):p.write_bytes(encoded(v));p.chmod(0o600)


@pytest.fixture
def dossier_input(config_file):
    cp,c=config_file;root=cp.parent;gold=Path(c['test_path'])
    gold.write_text('import unittest\nfrom a import value\nclass Case(unittest.TestCase):\n def test_one(self): self.assertEqual(value,2)\n');c['test_sha256']=file_hash(gold)
    cases=c['test_cases'];r=dict(tests=1,cases=cases,failures=1,errors=0,skipped=0,failed_cases=cases,error_cases=[])
    b=dict(id='regression-1',metric='fixed_test_failures',evidence_domain='code_regression',source_sha256=c['source_sha256'],test_sha256=c['test_sha256'],reproduction_sha256=digest(r),reproduction=r)
    b['config_hash']=digest({k:b[k] for k in ('source_sha256','test_sha256','reproduction_sha256')})
    p=asdict(code_plan(files=('src/a.py',),baseline_config_hash=b['config_hash']));p['behavior']='value';write(Path(c['plan_path']),p);write(Path(c['baseline_path']),b)
    c['plan_sha256']=file_hash(c['plan_path']);c['baseline_sha256']=file_hash(c['baseline_path']);c['review_sha256']='0'*64;write(cp,c)
    draft=root/'task-draft.json';d=dict(schema='pi-task-package-draft-v1',task_id='value-fix',problem='Existing value should equal2.',source_path=c['source_path'],source_sha256=c['source_sha256'],test_path=c['test_path'],test_sha256=c['test_sha256'],files=['src/a.py'],test_case_hints=cases,inventory_status='static_unverified',requires=['fresh_isolated_baseline','fresh_run_identity','independent_reviews'],origin=dict(request_path=str(root/'origin.json'),request_sha256='d'*64,source_path=c['source_path'],test_path=c['test_path']))
    write(draft,d)
    request=root/'baseline-request.json';outroot=root/'isolated-baseline';outroot.mkdir(mode=0o700);check=outroot/'check';check.mkdir(mode=0o700);shutil.copytree(Path(c['source_path'])/'src',check/'src');shutil.copyfile(gold,check/'test.py')
    q=dict(schema='pi-package-baseline-request-v1',baseline_id=b['id'],draft_path=str(draft),draft_sha256=file_hash(draft),root=str(outroot),docker=c['docker'],endpoint=c['endpoint'],daemon_id=c['daemon_id'],checker_image_id=c['checker_image_id'],deadline_seconds=60);write(request,q)
    task=dict(task_id=d['task_id'],problem=d['problem'],source_sha256=c['source_sha256'],evidence_sha256=digest(r),test_sha256=c['test_sha256'],files=d['files'],test_cases=cases,baseline=r)
    report=dict(r,passed=False,diagnostics=[],load_error=False,attach_returncode=1,container_id='a'*64)
    outcome=outroot/'outcome.json';o=dict(schema='pi-package-baseline-outcome-v1',verified=True,baseline_id=q['baseline_id'],request_sha256=file_hash(request),draft_sha256=q['draft_sha256'],source_sha256=c['source_sha256'],test_sha256=c['test_sha256'],check_passed=False,eligible_for_selection=True,catalog=[task],catalog_rejection=None,checker_report=report,cleanup=[dict(container_id='a'*64,removed=True,stopped=True,exit_code=1)],failure_class=None,cleanup_failure_class=None,requires=['fresh_run_identity','independent_reviews','current_runtime']);write(outcome,o)
    return cp,c,request,q,outcome,o


def compile_dossier(value):
    cp,c,q,_,o,_=value;return api().compile_dossier(cp,file_hash(cp),q,file_hash(q),o,file_hash(o))


def test_complete_review_dossier_is_readonly_and_has_no_permission_or_private_paths(dossier_input):
    api();cp,c,*_=dossier_input;before={p:p.read_bytes() for p in cp.parent.rglob('*') if p.is_file()};result=compile_dossier(dossier_input)
    assert result['authority']=='none' and result['model_view']['authority']=='recommendation_only'
    assert result['model_view']['evidence_domain']=='code_regression' and result['model_view']['online_improvement_proven'] is False
    assert str(cp.parent) not in encoded(result['model_view']).decode() and 'PLATFORM_MODEL_API_KEY' not in encoded(result).decode()
    assert result['model_view']['source_files'][0]['text']=='value = 1\n' and result['model_view']['baseline']['failures']==1
    assert before=={p:p.read_bytes() for p in cp.parent.rglob('*') if p.is_file()} and not Path(c['root']).exists()


@pytest.mark.parametrize('fault',['outcome_pin','request_pin','template_pin','cleanup','container','checker','catalog','catalog_hash','baseline_id','request_binding','copy','gold_copy','schema','bool','outcome_location','source_secret','gold_secret','oversize','source_db_credential','source_other_secret'])
def test_unverified_or_unbounded_review_material_rejected_before_any_fee(dossier_input,fault):
    cp,c,qp,q,op,o=dossier_input;module=api();pins=[file_hash(cp),file_hash(qp),file_hash(op)]
    if fault=='outcome_pin':pins[2]='f'*64
    elif fault=='request_pin':pins[1]='f'*64
    elif fault=='template_pin':pins[0]='f'*64
    elif fault=='cleanup':o['cleanup'][0]['removed']=False
    elif fault=='container':o['cleanup'][0]['container_id']='b'*64
    elif fault=='checker':o['checker_report']['passed']=True
    elif fault=='catalog':o['catalog'][0]['baseline']['failed_cases']=[]
    elif fault=='catalog_hash':o['catalog'][0]['evidence_sha256']='f'*64
    elif fault=='baseline_id':o['baseline_id']='other'
    elif fault=='request_binding':o['request_sha256']='f'*64
    elif fault=='copy':(Path(q['root'])/'check/src/a.py').write_text('changed')
    elif fault=='gold_copy':(Path(q['root'])/'check/test.py').write_text('changed')
    elif fault=='schema':o['approved']=True
    elif fault=='bool':o['verified']=1
    elif fault=='outcome_location':other=cp.parent/'copied-outcome.json';write(other,o);op=other
    elif fault in ('source_secret','oversize','source_db_credential','source_other_secret'):
        source=Path(c['source_path'])/'src/a.py';source.write_text({'source_secret':'value = "synthetic"\n','oversize':'value = "'+'x'*30000+'"\n','source_db_credential':'value = "postgresql://user:private_value@internal/db"\n','source_other_secret':'JWT_SECRET: str = "private_value"\nvalue = 1\n'}[fault])
        # Re-sign every source binding so only secret/size policy rejects it.
        c['source_sha256']=tree_hash(c['source_path']);o['source_sha256']=c['source_sha256'];o['catalog'][0]['source_sha256']=c['source_sha256']
        d=read_json(q['draft_path']);d['source_sha256']=c['source_sha256'];write(Path(q['draft_path']),d);q['draft_sha256']=file_hash(q['draft_path']);o['draft_sha256']=q['draft_sha256'];write(qp,q);o['request_sha256']=file_hash(qp)
        b=read_json(c['baseline_path']);b['source_sha256']=c['source_sha256'];b['config_hash']=digest({k:b[k] for k in ('source_sha256','test_sha256','reproduction_sha256')});write(Path(c['baseline_path']),b);c['baseline_sha256']=file_hash(c['baseline_path']);p=read_json(c['plan_path']);p['baseline_config_hash']=b['config_hash'];write(Path(c['plan_path']),p);c['plan_sha256']=file_hash(c['plan_path']);write(cp,c);pins[0]=file_hash(cp);pins[1]=file_hash(qp);shutil.copyfile(source,Path(q['root'])/'check/src/a.py')
    else:Path(c['test_path']).write_text('synthetic')
    if fault not in ('outcome_pin','request_pin','template_pin'):write(op,o);pins[2]=file_hash(op)
    before=Path(c['ledger_path']).read_bytes()
    expected='credential literal' if fault=='source_secret' else 'bound' if fault=='oversize' else 'credential-shaped' if fault in ('source_db_credential','source_other_secret') else None
    with pytest.raises((ValueError,OSError),match=expected):module.compile_dossier(cp,pins[0],qp,pins[1],op,pins[2])
    assert Path(c['ledger_path']).read_bytes()==before and not Path(c['root']).exists()


def test_semantic_review_binds_everything_except_latest_fee_lowered_deadline_and_review_location(dossier_input):
    cp,c,*_=dossier_input;module=api();result=compile_dossier(dossier_input);ceiling=result['deadline_ceiling'];semantic=result['semantic_sha256']
    refreshed=dict(c,ledger_sha256='f'*64,deadline_seconds=ceiling-1,review_path=str(cp.parent/'prepared/review.json'),review_sha256='e'*64)
    assert module.semantic_hash(refreshed,deadline_ceiling=ceiling)==semantic
    for change in (dict(max_requests=c['max_requests']+1),dict(source_sha256='e'*64),dict(root=str(cp.parent/'other')),dict(policy_sha256='e'*64),dict(test_sha256='e'*64)):
        assert module.semantic_hash(dict(c,**change),deadline_ceiling=ceiling)!=semantic
    with pytest.raises(ValueError):module.semantic_hash(dict(c,deadline_seconds=ceiling+1),deadline_ceiling=ceiling)


def test_pin_authenticates_returned_bytes_not_a_second_file_read(dossier_input,monkeypatch):
    cp,c,qp,q,op,o=dossier_input;module=api();original=module._read
    monkeypatch.setattr(module,'_read',lambda p,*args:encoded(dict(o,baseline_id='substituted')) if Path(p)==op else original(p,*args))
    with pytest.raises(ValueError,match='drift'):module._pin(op,file_hash(op))


def test_gold_text_is_exactly_the_hashed_test_not_a_racing_read(dossier_input,monkeypatch):
    cp,c,*_=dossier_input;module=api();original=module._read
    def read(p,*args):
        raw=original(p,*args)
        return raw.replace(b'value,2',b'value,999') if Path(p)==Path(c['test_path']) else raw
    monkeypatch.setattr(module,'_read',read)
    with pytest.raises(ValueError,match='gold.*drift'):compile_dossier(dossier_input)


@pytest.mark.parametrize('identity',['source_sha256','test_sha256'])
def test_development_template_binds_functional_reproduction_to_its_own_source_and_gold(dossier_input,identity):
    from ops.pi.development_inputs import prepare_template
    cp,c,*_=dossier_input;b=read_json(c['baseline_path']);b[identity]='f'*64
    b['config_hash']=digest({k:b[k] for k in ('source_sha256','test_sha256','reproduction_sha256')});write(Path(c['baseline_path']),b);c['baseline_sha256']=file_hash(c['baseline_path'])
    p=read_json(c['plan_path']);p['baseline_config_hash']=b['config_hash'];write(Path(c['plan_path']),p);c['plan_sha256']=file_hash(c['plan_path']);write(cp,c)
    with pytest.raises(ValueError,match='functional baseline source/test identity'):prepare_template(cp)


def test_draft_changed_during_final_validation_is_not_accepted(dossier_input,monkeypatch):
    cp,c,qp,q,*_=dossier_input;module=api();original=module.prepare_template;calls=[]
    def check(p,**kwargs):
        value=original(p,**kwargs);calls.append(1)
        if len(calls)==2:Path(q['draft_path']).write_bytes(b'{}')
        return value
    monkeypatch.setattr(module,'prepare_template',check)
    with pytest.raises(ValueError,match='draft snapshot drift'):compile_dossier(dossier_input)


def test_paid_review_can_revalidate_same_dossier_at_explicit_current_fee_without_execution_approval(dossier_input):
    from ops.pi.ledger import Ledger
    from ops.pi.development_inputs import ledger_snapshot,prepare
    from ops.pi.development_inputs import authorization_hash
    cp,c,qp,q,op,o=dossier_input;module=api()
    review=dict(source='independent_review',verified=True,result='approved',reviewer='synthetic-independent',authorization_sha256=authorization_hash(c),plan_hash=digest(read_json(c['plan_path'])),base=c['source_sha256'],candidate_id=c['run_id'],owner='local-development-controller',generation=1)
    write(Path(c['review_path']),review);c['review_sha256']=file_hash(c['review_path']);write(cp,c)
    prepare(cp);before=compile_dossier(dossier_input)
    Ledger(Path(c['ledger_path']),existing=True).append_event('synthetic_review_settlement',dict(charged_microyuan=3))
    current=ledger_snapshot(c['ledger_path'])['sha256'];assert current!=c['ledger_sha256']
    with pytest.raises(ValueError,match='ledger checkpoint drift'):compile_dossier(dossier_input)
    after=module.compile_dossier(cp,file_hash(cp),qp,file_hash(qp),op,file_hash(op),expected_current_fee_sha256=current)
    assert after==before and after['authority']=='none'
    with pytest.raises(ValueError,match='ledger checkpoint drift'):prepare(cp)
    from ops.pi.development_inputs import _prepare
    with pytest.raises(ValueError,match='read-only current fee'):_prepare(cp,review_required=True,expected_current_fee_sha256=current)
    with pytest.raises(ValueError):module.compile_dossier(cp,file_hash(cp),qp,file_hash(qp),op,file_hash(op),expected_current_fee_sha256='f'*64)
