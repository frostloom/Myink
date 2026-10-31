"""Functional assertion failures are not synthetic pairs or online samples."""
from dataclasses import replace
from copy import deepcopy
import pytest
from ops.pi.plans import Plan,validate_plan
from ops.pi.audit import digest
from ops.pi.tests.test_budget import policy


def baseline():
    cases=['fixed_development_tests.Names.test_one']
    reproduction=dict(tests=1,cases=cases,failures=1,errors=0,skipped=0,failed_cases=cases,error_cases=[])
    source='a'*64;gold='b'*64;repro=digest(reproduction)
    binding=digest(dict(source_sha256=source,test_sha256=gold,reproduction_sha256=repro))
    return dict(id='regression-1',metric='fixed_test_failures',config_hash=binding,evidence_domain='code_regression',source_sha256=source,test_sha256=gold,reproduction_sha256=repro,reproduction=reproduction)


def plan(**changes):
    b=baseline();p=Plan('existing behavior fails a fixed assertion','fixed_test_failures',1,.1,1,
        ('fixed_test_errors','fixed_test_skips'),b['id'],b['config_hash'],'stability',('src/names.py',),
        ('fixed-cases',),'existing behavior only','discard unadopted candidate',10,120,'names',evidence_domain='code_regression')
    return replace(p,**changes)


def test_code_regression_needs_one_real_failure_without_invented_online_samples(policy):
    b=baseline();assert not any(k in b for k in ('paired_groups','complete_tasks','tail_samples'))
    assert validate_plan(plan(),b,policy).status=='done'
    assert validate_plan(plan(evidence_domain='online',sample_floor=20),b,policy).status=='blocked'
    assert validate_plan(plan(evidence_domain='synthetic',sample_floor=5),b,policy).status=='blocked'


@pytest.mark.parametrize('fault',['passing','error','skip','case_mismatch','failed_mismatch','duplicate','bool','source','gold','reproduction_hash','binding','extra','borrowed_pairs','borrowed_online'])
def test_ineligible_functional_baseline_cannot_lower_evidence_gates(policy,fault):
    b=baseline();r=b['reproduction']
    if fault=='passing':r.update(failures=0,failed_cases=[])
    elif fault=='error':r.update(errors=1,error_cases=r['cases'])
    elif fault=='skip':r['skipped']=1
    elif fault=='case_mismatch':r['tests']=2
    elif fault=='failed_mismatch':r['failed_cases']=[]
    elif fault=='duplicate':r['cases']*=2;r['tests']=2
    elif fault=='bool':r['failures']=True
    elif fault=='source':b['source_sha256']='bad'
    elif fault=='gold':b['test_sha256']='bad'
    elif fault=='reproduction_hash':b['reproduction_sha256']='f'*64
    elif fault=='binding':b['config_hash']='f'*64
    elif fault=='extra':r['verified']=True
    elif fault=='borrowed_pairs':b['paired_groups']=999
    elif fault=='borrowed_online':b['complete_tasks']=999
    assert validate_plan(plan(),b,policy).status=='blocked'


@pytest.mark.parametrize('changes',[dict(scope='speed'),dict(metric='latency'),dict(sample_floor=5),dict(minimum_improvement=.2),dict(guard_metrics=('errors',)),dict(files=('ops/pi/policy.py',)),dict(change_types=('policy',))])
def test_functional_contract_cannot_claim_performance_or_change_protected_policy(policy,changes):
    assert validate_plan(plan(**changes),baseline(),policy).status=='blocked'


@pytest.mark.parametrize('files',[tuple('src/m'+str(i)+'.py' for i in range(9)),tuple('src/m'+str(i)+'.py' for i in range(4))])
def test_functional_domain_keeps_original_hard_and_soft_file_limits(policy,files):
    assert validate_plan(plan(files=files),baseline(),policy).status=='blocked'


def test_functional_domain_still_validates_optional_scope_reason(policy):
    assert validate_plan(plan(reason=True),baseline(),policy).status=='blocked'
    assert validate_plan(plan(files=tuple('src/m'+str(i)+'.py' for i in range(4)),reason='one atomic behavior'),baseline(),policy).status=='done'
