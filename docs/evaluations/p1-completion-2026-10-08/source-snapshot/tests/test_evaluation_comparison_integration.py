"""Production graph and isolated DB integration; SDK alone is replaced."""
import importlib.util
from pathlib import Path

from myink.evaluation.comparison import BudgetedProvider
from test_flow import StubProvider


def test_enabled_embedding_rejected_before_database_or_sdk(tmp_path, monkeypatch):
    import pytest
    from myink.config import settings
    spec=importlib.util.spec_from_file_location('comparison_guard',Path('scripts/evaluate-comparison.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    from dataclasses import replace
    monkeypatch.setattr(module,'settings',replace(settings,embed_enabled=True),raising=False)
    def blocked():raise ValueError('database must not be touched')
    monkeypatch.setattr(module,'require_isolated_database',blocked)
    with pytest.raises(ValueError,match='EMBED_ENABLED=0'):
        module.run(tmp_path/'run',[],live=True,max_calls=1,max_cost=1)
    assert not (tmp_path/'run').exists()


def test_direct_full_and_ablation_preserve_all_outputs_and_persisted_body(tmp_path, monkeypatch):
    import os
    import pytest
    if not os.getenv('MYINK_EVALUATION_SYSTEM_ID'):
        pytest.skip('requires explicitly approved localhost:15432 evaluation database identity')
    spec=importlib.util.spec_from_file_location('comparison_cli',Path('scripts/evaluate-comparison.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    stub=StubProvider('金丹','金丹')
    def sdk(messages,config):
        resp=stub.generate(messages,model_id='deepseek-v4-flash',json_mode=config['json_mode'],tools=None)
        return {'raw_output':resp.content,'model_id':resp.model_id,'input_tokens':100,'output_tokens':200,
                'cost_est':.0018,'cost_status':'estimated','finish_reason':'stop'}
    monkeypatch.setattr(module,'BudgetedProvider',lambda directory,budget,config:BudgetedProvider(directory,budget,config,call=sdk))
    case={'id':'fixture','characters':['林砚'],'history':[],'previous_tail':'林砚在黑市。',
          'constraints':[],'instruction':'林砚在黑市查探玉佩真相。','target_words':100}
    summary=module.run(tmp_path/'run',[case],live=True,max_calls=60,max_cost=5)
    import json
    outputs=json.loads((tmp_path/'run/results.json').read_text(encoding='utf-8'))
    assert len(outputs)==6 and summary['actual_requests']<=60
    assert summary['completed_outputs']==6, outputs
    assert all(r['database_matches_draft'] for r in outputs if r['variant']!='direct')
    assert summary['quality_status']=='pending_independent_review'
    assert (tmp_path/'run/blind-review.json').is_file()
