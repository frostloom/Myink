from pathlib import Path
import runpy
import pytest
build_analysis_prompt=runpy.run_path(str(Path(__file__).parents[1]/'lab'/'pi-preview.py'))['build_analysis_prompt']


def test_source_preview_preserves_owner_and_unmeasured_baseline():
    prompt=build_analysis_prompt({'kind':'readonly_source_preview','evidence_domain':'source_only','new_features_require_owner':True,'commit_sha':'a'*40,'files':[{'path':'src/app.py','excerpt':'def example(): return 1'}]})
    assert 'src/app.py' in prompt and 'def example(): return 1' in prompt
    assert 'baseline' in prompt and 'not measured' in prompt
    assert 'owner' in prompt and 'JSON' in prompt


def test_live_or_feature_authority_cannot_be_inferred_from_source_preview():
    with pytest.raises(ValueError):
        build_analysis_prompt({'kind':'readonly_source_preview','evidence_domain':'live','new_features_require_owner':False})



def test_plan_requires_unknown_baseline_owner_and_exact_source_quote():
    validate=runpy.run_path(str(Path(__file__).parents[1]/'lab'/'pi-preview.py'))['validate_analysis_plan']
    snapshot={'files':[{'path':'src/app.py','excerpt':'def example(): return 1'}]}
    plan={'hypothesis':'缓存可避免重复解析','source_evidence':[{'path':'src/app.py','quote':'def example()'}],
          'baseline':{'availability':'unknown','reason':'本次未采集运行指标'},'candidate_metrics':['解析耗时'],
          'tests':['重复解析回归'],'risks':['缓存失效'],'owner_decision':{'new_features_require_owner':True}}
    assert validate(plan,snapshot)==plan
    with pytest.raises(ValueError): validate({'foo':1},snapshot)
    with pytest.raises(ValueError): validate({**plan,'source_evidence':[{'path':'src/app.py','quote':'stale code not present'}]},snapshot)
