"""Readonly final-candidate context cannot confer acceptance or release authority."""
import importlib,shutil
from pathlib import Path
import pytest
from ops.pi.audit import encoded
from ops.pi.development_inputs import file_hash,tree_hash,authorization_hash,read_json
from ops.pi.tests.test_development_inputs import config_file


def write(path,value):path.write_bytes(encoded(value));path.chmod(0o600)
def api():return importlib.import_module('ops.pi.candidate_dossier')


@pytest.fixture
def completed(config_file):
    cp,c=config_file
    state=cp.parent/'state';state.mkdir(mode=0o700);ledger=state/'ledger.sqlite';Path(c['ledger_path']).rename(ledger);c['ledger_path']=str(ledger)
    Path(c['test_path']).write_text('import unittest\nfrom a import value\nclass Case(unittest.TestCase):\n def test_one(self): self.assertEqual(value,2)\n');c['test_sha256']=file_hash(c['test_path'])
    review=read_json(c['review_path']);review['authorization_sha256']=authorization_hash(c);write(Path(c['review_path']),review);c['review_sha256']=file_hash(c['review_path']);write(cp,c)
    root=Path(c['root']);root.mkdir(mode=0o700);candidate=root/'candidate';shutil.copytree(c['source_path'],candidate);(candidate/'src/a.py').write_text('value = 2\n')
    write(root/'manifest-private.json',dict(config=c,provenance={},operation_id='synthetic'))
    check=root/'check-1';check.mkdir();shutil.copytree(candidate/'src',check/'src');shutil.copyfile(c['test_path'],check/'test.py')
    cleanup=[dict(container_id='a'*64,stopped=True,removed=True,exit_code=0)]
    report=dict(passed=True,tests=1,cases=c['test_cases'],failures=0,errors=0,skipped=0,failed_cases=[],error_cases=[],diagnostics=[],load_error=False,attach_returncode=0,container_id='a'*64,cleanup=cleanup)
    write(root/'check-1-receipt.json',report)
    write(root/'phase-verification.json',dict(verified=True,mode='ACTUAL',verified_tool_calls=['unit']))
    r=dict(verified=True,run_id=c['run_id'],authorization_sha256=authorization_hash(c),failure_class=None,cleanup=cleanup,policy_restored=True,original_history_unchanged=True,new_attempts=7,new_unknown=0,known_cost_microyuan=100,candidate_path=str(candidate),candidate_sha256=tree_hash(candidate),model_posts=[])
    write(root/'result.json',r)
    q=dict(schema='pi-candidate-review-request-v1',mode='SIMULATED',config_path=str(cp),config_sha256=file_hash(cp),result_sha256=file_hash(root/'result.json'),phase_sha256=file_hash(root/'phase-verification.json'),check_id='check-1',check_sha256=file_hash(root/'check-1-receipt.json'))
    qp=cp.parent/'candidate-review-request.json';write(qp,q);return qp,q,c,r,report


def test_candidate_dossier_is_readonly_complete_and_has_no_approval(completed):
    qp,q,c,r,report=completed;before={p:p.read_bytes() for p in qp.parent.rglob('*') if p.is_file()};d=api().compile_dossier(qp,file_hash(qp));view=d['model_view']
    assert d['authority']=='none' and view['authority']=='recommendation_only' and view['review_kind']=='post_development'
    assert view['candidate_sha256']==r['candidate_sha256'] and view['source_files'][0]['text']=='value = 1\n' and view['candidate_files'][0]['text']=='value = 2\n'
    assert '-value = 1' in view['diff'] and '+value = 2' in view['diff']
    assert view['changes']==[dict(path='src/a.py',category='production',added=1,deleted=1)]
    assert view['final_check']['tests']==1 and view['online_improvement_proven'] is False
    assert str(qp.parent) not in encoded(view).decode() and before=={p:p.read_bytes() for p in qp.parent.rglob('*') if p.is_file()}


@pytest.mark.parametrize('fault',['pin','source','candidate','copy','gold','gold_copy','out_of_scope','unchanged','link','oversize','secret','unverified','cleanup','unknown','phase','check','skipped','inventory','config','manifest','check_id'])
def test_changed_or_ineligible_completed_candidate_rejected(completed,fault):
    qp,q,c,r,report=completed;root=Path(c['root']);candidate=root/'candidate'
    if fault=='pin':pass
    elif fault=='source':(Path(c['source_path'])/'src/a.py').write_text('changed')
    elif fault=='candidate':(candidate/'src/a.py').write_text('changed')
    elif fault=='copy':(root/'check-1/src/a.py').write_text('old candidate')
    elif fault=='gold':Path(c['test_path']).write_text('changed')
    elif fault=='gold_copy':(root/'check-1/test.py').write_text('changed')
    elif fault in ('out_of_scope','unchanged','link','oversize','secret'):
        if fault=='out_of_scope':(candidate/'src/extra.py').write_text('extra=1')
        elif fault=='unchanged':(candidate/'src/a.py').write_text('value = 1\n')
        elif fault=='link':(candidate/'src/link.py').symlink_to('a.py')
        elif fault=='oversize':(candidate/'src/a.py').write_text('value = "'+'x'*30000+'"\n')
        else:(candidate/'src/a.py').write_text('API_KEY = "private_candidate_value"\n')
        if fault!='link':
            r['candidate_sha256']=tree_hash(candidate);shutil.rmtree(root/'check-1/src');shutil.copytree(candidate/'src',root/'check-1/src')
    elif fault=='unverified':r['verified']=False
    elif fault=='cleanup':r['cleanup'][0]['removed']=False
    elif fault=='unknown':r['new_unknown']=1
    elif fault=='phase':write(root/'phase-verification.json',dict(verified=False,mode='ACTUAL'))
    elif fault=='check':report['passed']=False
    elif fault=='skipped':report['skipped']=1
    elif fault=='inventory':report['cases']=['fixed_development_tests.Other.test_one']
    elif fault=='config':c['source_sha256']='b'*64;write(Path(q['config_path']),c);q['config_sha256']=file_hash(q['config_path'])
    elif fault=='manifest':write(root/'manifest-private.json',dict(config=dict(c,run_id='other')))
    else:q['check_id']='../../foreign'
    write(root/'result.json',r);q['result_sha256']=file_hash(root/'result.json');write(root/'check-1-receipt.json',report);q['check_sha256']=file_hash(root/'check-1-receipt.json');q['phase_sha256']=file_hash(root/'phase-verification.json');write(qp,q)
    with pytest.raises((ValueError,OSError)):
        api().compile_dossier(qp,'f'*64 if fault=='pin' else file_hash(qp))


def test_readonly_evidence_has_separate_bounded_capacity_without_relaxing_model_review(completed,monkeypatch):
    qp,q,c,r,report=completed;module=api();original=module.compile_dossier(qp,file_hash(qp));size=len(encoded(original['model_view']))
    before={p:p.read_bytes() for p in qp.parent.rglob('*') if p.is_file()}
    monkeypatch.setattr(module,'MAX_MODEL_BYTES',size-1)
    with pytest.raises(ValueError,match='complete final review context'):module.compile_dossier(qp,file_hash(qp))
    evidence=module.compile_evidence(qp,file_hash(qp));assert evidence==original and evidence['authority']=='none'
    monkeypatch.setattr(module,'MAX_EVIDENCE_BYTES',size-1)
    with pytest.raises(ValueError):module.compile_evidence(qp,file_hash(qp))
    assert before=={p:p.read_bytes() for p in qp.parent.rglob('*') if p.is_file()}
