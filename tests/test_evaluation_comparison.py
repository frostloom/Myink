from pathlib import Path
import json
import pytest

from myink.evaluation.comparison import BudgetedProvider, blind_bundle
from myink.evaluation.runner import Budget


def test_all_roles_share_budget_and_denied_requests_do_not_call_sdk(tmp_path):
    called=[]
    def sdk(messages, config):
        called.append(config)
        return {'raw_output':'正文','model_id':'deepseek-v4-flash','input_tokens':10,'output_tokens':20,
                'cost_est':.00018,'cost_status':'estimated','finish_reason':'stop'}
    provider=BudgetedProvider(tmp_path, Budget(max_calls=1,max_cost_yuan=5,deadline_seconds=60),
        {'model':'deepseek-v4-flash','temperature':.1,'prices':{'input':2,'output':8}},call=sdk)
    assert provider.generate([{'role':'user','content':'写'}],model_id='stub',json_mode=False,max_tokens=100).content=='正文'
    assert provider.generate([{'role':'user','content':'审'}],model_id='stub',json_mode=True,max_tokens=100).error
    assert len(called)==1 and called[0]['json_mode'] is False
    assert json.loads((tmp_path/'requests/0001/result.json').read_text(encoding='utf-8'))['execution']=='completed'


def test_provider_timeout_is_saved_and_unknown_usage_holds_reservation(tmp_path):
    def sdk(*_): raise TimeoutError('fixture timeout')
    budget=Budget(max_calls=1,max_cost_yuan=5,deadline_seconds=60)
    provider=BudgetedProvider(tmp_path,budget,{'model':'deepseek-v4-flash','temperature':.1,'prices':{'input':2,'output':8}},call=sdk)
    assert provider.generate([{'role':'user','content':'写'}],model_id='stub',max_tokens=100).error
    row=json.loads((tmp_path/'requests/0001/result.json').read_text(encoding='utf-8'))
    assert row['execution']=='timeout' and budget.spent>0


def test_blind_bundle_preserves_failures_and_separates_variant_key():
    outputs=[{'case_id':'x','variant':'full','repetition':1,'draft':'内容','execution':'completed'},
             {'case_id':'x','variant':'direct','repetition':1,'draft':'','execution':'timeout'}]
    blind,key=blind_bundle(outputs,seed=3)
    assert len(blind)==len(key)==2
    assert all('variant' not in row and 'full' not in str(row) for row in blind)
    assert any(row['execution']=='timeout' for row in blind)


def test_supplement_only_selects_budget_stopped_slots_and_validates_ids():
    from myink.evaluation.comparison import ComparisonCase, pending_slots
    cases=[{'id':'one'}]
    rows=[{'case_id':'one','variant':'full','repetition':1,'execution':'completed'},
          {'case_id':'one','variant':'no_hybrid','repetition':2,'execution':'budget_stopped'}]
    assert pending_slots(rows,cases)=={('one','no_hybrid',2)}
    with pytest.raises(ValueError):pending_slots([{'case_id':'other','variant':'direct','repetition':1,'execution':'budget_stopped'}],cases)
    with pytest.raises(ValueError):ComparisonCase.model_validate({'id':'../../escape'})


def test_direct_context_keeps_previous_tail_and_alias_mapping():
    from myink.evaluation.comparison import direct_context
    case={'constraints':['现实题材'],'history':[],'instruction':'检修','characters':['林川'],
          'aliases':{'林川':['老林']},'previous_tail':'在楼梯口商量。'}
    context=direct_context(case)
    assert any(r.get('tail')==case['previous_tail'] for r in context['short_context'])
    assert any('老林' in r.get('text','') and '林川' in r.get('text','') for r in context['short_context'])


def test_combining_supplement_preserves_attempts_and_rejects_success_replacement():
    from myink.evaluation.comparison import combine_outputs
    stopped={'case_id':'a','variant':'full','repetition':1,'execution':'budget_stopped','draft':'部分'}
    complete={**stopped,'execution':'completed','draft':'完整'}
    selected,attempts=combine_outputs([stopped],[complete])
    assert selected==[complete] and attempts==[stopped,complete]
    with pytest.raises(ValueError):combine_outputs([complete],[complete])
    with pytest.raises(ValueError):combine_outputs([stopped],[{**complete,'repetition':2}])
