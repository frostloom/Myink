"""Offline evaluation contracts; no model, database or network required."""
import copy
import json
from pathlib import Path

import pytest

from myink.evaluation.cases import Case, load_cases
from myink.evaluation.scoring import score_case
from myink.evaluation.reporting import summarize, write_report
from myink.evaluation.runner import Budget, run_cases


def case(positive=True):
    return Case.model_validate({
        'schema_version': 1, 'id': 'demo.bad' if positive else 'demo.good',
        'group_id': 'demo', 'split': 'development', 'mode': 'audit',
        'category': 'item', 'polarity': 'positive' if positive else 'negative',
        'source': {'path': 'scripts/eval-logic.py', 'case_name': 'destroyed_item', 'adapted_from': []},
        'input': {'chapter_seq': 2, 'context': {'short_context': [{'chapter': 1, 'tail': '旧表已毁。'}]},
                  'plan': {}, 'draft': '他使用完好的旧表。'},
        'expected': {'allowed_verdicts': ['rewrite'] if positive else ['pass'],
            'required_issues': [{'id': 'item', 'description': '毁坏物品再现',
                'allowed_conflict_types': ['item_rule'], 'allowed_severities': ['major'],
                'evidence_sources': [{'chapter': 1, 'pointer': '/input/context/short_context/0/tail'},
                                     {'chapter': 2, 'pointer': '/input/draft'}]}] if positive else [],
            'forbidden_issues': [] if positive else ['不得误报合法更换']},
        'label': {'status': 'reviewed', 'review_note': 'test fixture', 'reviewer': 'test maintainer'}})


def result(findings=None, verdict='rewrite'):
    finding={'conflict_key': 'anything', 'conflict_type': 'item_rule', 'severity': 'major',
             'evidence': [{'chapter': 1, 'quote': '旧表已毁。'}, {'chapter': 2, 'quote': '完好的旧表'}]}
    return {'case_id': 'demo.bad', 'execution': 'completed', 'coverage': 'implemented',
            'raw_output': json.dumps({'verdict': verdict, 'findings': [finding] if findings is None else findings})}


def test_evidence_candidate_is_not_human_confirmation():
    s=score_case(case(), result())
    assert s['candidates'] == {'0': ['item']}
    assert s['review'] == 'provisional' and s['confirmed_pass'] is None


@pytest.mark.parametrize('chapter,quote', [(3,'旧表已毁。'),(1,'根本不存在的句子'),(1,'')])
def test_forged_evidence_does_not_match(chapter,quote):
    r=result(); v=json.loads(r['raw_output']);v['findings'][0]['evidence'][0]={'chapter':chapter,'quote':quote}
    r['raw_output']=json.dumps(v)
    assert score_case(case(),r)['candidates']=={'0': []}


def test_unrelated_rewrite_not_detection():
    r=result(); v=json.loads(r['raw_output']);v['findings'][0]['conflict_type']='style';r['raw_output']=json.dumps(v)
    s=score_case(case(),r)
    assert s['verdict_match'] and not s['automatic_pass']


def test_invalid_json_is_completed_output_failure():
    r=result();r['raw_output']='not json'
    s=score_case(case(),r)
    assert s['execution']=='completed' and not s['output_valid'] and not s['automatic_pass']


def test_review_can_confirm_only_valid_candidate():
    s=score_case(case(),result(),{'reviewer':'Alice','decisions':{'0':{'kind':'match','issue_id':'item'}}})
    assert s['confirmed_pass'] and s['tp']==1 and s['fn']==0
    r=result();r['raw_output']='{}'
    with pytest.raises(ValueError): score_case(case(),r,{'reviewer':'Alice','decisions':{'0':{'kind':'match','issue_id':'item'}}})


def test_duplicate_finding_not_two_true_positives():
    f=json.loads(result()['raw_output'])['findings'][0]
    r=result([f,copy.deepcopy(f)])
    s=score_case(case(),r,{'reviewer':'Alice','decisions':{
        '0':{'kind':'match','issue_id':'item'},'1':{'kind':'duplicate','issue_id':'item'}}})
    assert s['tp']==1 and s['duplicates']==1 and s['fp']==0


def test_negative_extra_finding_is_explicit_false_positive():
    s=score_case(case(False),result(verdict='pass'),{'reviewer':'Alice','decisions':{'0':{'kind':'false_positive'}}})
    assert s['fp']==1 and not s['confirmed_pass']


def test_partial_review_remains_provisional():
    assert score_case(case(),result(),{'reviewer':'Alice','decisions':{}})['confirmed_pass'] is None


def test_empty_summary_na_and_provider_failure_in_denominator():
    assert summarize([])['confirmed']['recall'] is None
    good=score_case(case(False),result([], 'pass'),{'reviewer':'Alice','decisions':{}})
    bad=score_case(case(),{'execution':'provider_error','coverage':'implemented','error':'offline'})
    s=summarize([good,bad])
    assert s['planned']==2 and s['completed']==1 and s['confirmed']['overall_success']==0.5


def test_duplicate_ids_and_split_leak_rejected(tmp_path):
    a=case().model_dump();b=case(False).model_dump();b['split']='holdout'
    (tmp_path/'a.json').write_text(json.dumps(a));(tmp_path/'b.json').write_text(json.dumps(b))
    with pytest.raises(ValueError,match='split'):load_cases(tmp_path,Path.cwd())


def test_unknown_case_field_rejected():
    a=case().model_dump();a['typo']=1
    with pytest.raises(ValueError):Case.model_validate(a)


def test_budget_reserves_unknown_price_and_actual_usage():
    b=Budget(max_calls=1,max_cost_yuan=1,deadline_seconds=10)
    with pytest.raises(ValueError):b.reserve(10,10,None)
    b.reserve(10,10,{'input':1,'output':1});b.settle(.01)
    with pytest.raises(RuntimeError):b.reserve(1,1,{'input':1,'output':1})


def test_cost_limit_stops_before_request():
    b=Budget(max_calls=5,max_cost_yuan=.001,deadline_seconds=10)
    with pytest.raises(RuntimeError):b.reserve(10000,10000,{'input':1,'output':1})
    assert b.calls==0


def test_dry_run_never_calls_model_or_creates_output(tmp_path):
    def forbidden(*args):raise AssertionError('network')
    with pytest.raises(ValueError,match='live'):
        run_cases([case()],tmp_path/'run',{},live=False,call=forbidden)
    assert not (tmp_path/'run').exists()


def test_run_preserves_failure_and_no_overwrite(tmp_path):
    def fail(*args):raise TimeoutError('synthetic timeout')
    config={'model':'test','max_tokens':100,'temperature':.1,'max_calls':2,'max_cost_yuan':1,
            'deadline_seconds':10,'prices':{'input':1,'output':1}}
    path=tmp_path/'run'
    rows=run_cases([case(),case(False)],path,config,live=True,call=fail)
    assert len(rows)==2 and all(r['execution']=='timeout' for r in rows)
    assert len((path/'results.jsonl').read_text().splitlines())==2
    with pytest.raises(FileExistsError):run_cases([case()],path,config,live=True,call=fail)


def test_html_escapes_model_output(tmp_path):
    r=result();r['raw_output']='<script>alert(1)</script>'
    write_report(tmp_path,[score_case(case(),r)])
    text=(tmp_path/'report.html').read_text(encoding='utf-8')
    assert '<script>alert(1)</script>' not in text and '&lt;script&gt;' in text


def test_budget_unknown_usage_keeps_reservation():
    b=Budget(max_calls=3,max_cost_yuan=.02,deadline_seconds=10)
    b.reserve(10000,0,{'input':1,'output':1});b.settle(None)
    assert b.spent==.01


def test_budget_deadline_stops_scheduling():
    b=Budget(max_calls=3,max_cost_yuan=1,deadline_seconds=10);b.deadline=0
    with pytest.raises(RuntimeError,match='deadline'):b.reserve(1,1,{'input':1,'output':1})


def test_invalid_pointer_rejected():
    c=case().model_dump();c['expected']['required_issues'][0]['evidence_sources'][0]['pointer']='/missing'
    with pytest.raises(ValueError):Case.model_validate(c)


def test_duplicate_id_rejected(tmp_path):
    c=case().model_dump()
    for name in ('a','b'):(tmp_path/f'{name}.json').write_text(json.dumps(c))
    with pytest.raises(ValueError,match='duplicate'):load_cases(tmp_path,Path.cwd())


def test_review_dispute_not_formal_quality():
    s=score_case(case(),result(),{'reviewer':'Alice','decisions':{'0':{'kind':'disputed'}}})
    assert s['review']=='disputed' and s['confirmed_pass'] is None


def test_measured_results_not_rewritten_when_report_rebuilt(tmp_path):
    raw=tmp_path/'results.jsonl';raw.write_text('original',encoding='utf-8')
    write_report(tmp_path,[score_case(case(),result())])
    assert raw.read_text(encoding='utf-8')=='original'


def test_migrated_cases_and_catalog_cover_existing_assets():
    cases=load_cases(Path('evals/cases/audit'),Path.cwd())
    legacy=[c for c in cases if not c.id.startswith('hard.')]
    assert len(legacy)==15 and sum(c.polarity=='positive' for c in legacy)==8
    catalog=json.loads(Path('evals/catalog.json').read_text(encoding='utf-8'))['cases']
    assert len(catalog)==40 and len({c['id'] for c in catalog})==40
    assert all(c['coverage']=='gap' for c in catalog if c['id'] in
               {'conflict-samples:05','conflict-samples:28','conflict-samples:38'})


def test_review_can_confirm_proposed_label_without_changing_source():
    c=case().model_copy(update={'label':case().label.model_copy(update={'status':'proposed'})})
    s=score_case(c,result(),{'reviewer':'Alice','label_confirmed':True,
        'decisions':{'0':{'kind':'match','issue_id':'item'}}})
    assert s['confirmed_pass'] and c.label.status=='proposed'


def test_invalid_output_confirmed_failure_counts_missing_issue():
    r=result();r['raw_output']='not json'
    s=score_case(case(),r,{'reviewer':'Alice','decisions':{}})
    assert s['confirmed_pass'] is False and summarize([s])['confirmed']['recall']==0


def test_no_review_does_not_publish_zero_as_accuracy():
    assert summarize([score_case(case(),result())])['confirmed']['overall_success'] is None


def test_saved_recovery_does_not_claim_new_run():
    from myink.evaluation.recovery import check_recovery
    r=check_recovery(Path('docs/evaluations/workflow-recovery-2026-10-08-live.json'))
    assert r['deterministic_pass'] and r['semantic_review']=='pending'
    assert r['mode']=='recovery_saved_evidence'


def test_extra_true_source_is_not_forged_quote():
    c=case().model_dump();c['input']['context']['recent_openings']=[{'chapter':4,'text':'他在门外等待。'}]
    r=result();v=json.loads(r['raw_output']);v['findings'].append({
        'conflict_key':'extra','conflict_type':'plotline','severity':'major',
        'evidence':[{'chapter':4,'quote':'他在门外等待。'}]})
    r['raw_output']=json.dumps(v)
    s=score_case(Case.model_validate(c),r)
    assert s['evidence']['1']==[True] and s['candidates']['1']==[]


def test_one_finding_cannot_satisfy_two_issues():
    c=case().model_dump();second=copy.deepcopy(c['expected']['required_issues'][0]);second['id']='other'
    c['expected']['required_issues'].append(second)
    assert not score_case(Case.model_validate(c),result())['automatic_pass']


@pytest.mark.parametrize('review',[{'reviewer':' ','decisions':{}},
    {'reviewer':'Alice','decisions':{'0':'match'}}])
def test_malformed_review_rejected(review):
    with pytest.raises(ValueError):score_case(case(),result(),review)


def test_budget_stop_is_saved_for_each_unstarted_case(tmp_path):
    calls=[]
    def success(messages,config):
        calls.append(messages)
        return {'raw_output':'{"verdict":"pass","findings":[]}',
                'cost_est':0.001,'cost_status':'estimated'}
    config={'model':'test','max_tokens':100,'temperature':.1,'max_calls':1,
        'max_cost_yuan':1,'deadline_seconds':10,'prices':{'input':1,'output':1}}
    rows=run_cases([case(),case(False)],tmp_path/'run',config,live=True,call=success)
    assert len(calls)==1 and rows[1]['execution']=='budget_stopped'
    assert not rows[1]['attempted'] and len(rows)==2


@pytest.mark.parametrize('pointer,chapter',[('/input/draft',1),('/label/review_note',1)])
def test_source_pointer_cannot_lie_about_text_or_chapter(pointer,chapter):
    c=case().model_dump();c['expected']['required_issues'][0]['evidence_sources'][0]={'chapter':chapter,'pointer':pointer}
    with pytest.raises(ValueError):Case.model_validate(c)


@pytest.mark.parametrize('key,value',[('temperature','0.1'),('max_calls',True),('deadline_seconds',float('nan'))])
def test_config_rejects_ambiguous_types_and_nan(key,value):
    from myink.evaluation.cases import EvaluationConfig
    c=json.loads(Path('evals/configs/audit.json').read_text(encoding='utf-8'));c[key]=value
    with pytest.raises(ValueError):EvaluationConfig.model_validate(c)


def test_interrupted_run_can_score_preserved_prefix(tmp_path):
    import importlib.util
    from myink.evaluation.runner import digest
    spec=importlib.util.spec_from_file_location('evaluation_cli','scripts/evaluate.py')
    cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    cases=[case(),case(False)];rows=[{**result(),'case_sha256':digest(case().model_dump())}]
    (tmp_path/'cases.json').write_text(json.dumps([c.model_dump() for c in cases]),encoding='utf-8')
    (tmp_path/'results.jsonl').write_text(json.dumps(rows[0])+'\n',encoding='utf-8')
    manifest={'status':'running','results_sha256':digest(rows),'cases_sha256':digest([c.model_dump() for c in cases])}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    summary=cli.score_run(tmp_path)
    assert summary['planned']==2 and summary['execution_counts']['not_run']==1


@pytest.mark.parametrize('raw', ['{"verdict":"pass","findngs":[]}',
    '{"verdict":"pass","findings":[],"unknown":true}',
    '{"verdict":"rewrite","findings":[{"conflict_key":"k","conflict_type":"item_rule","severity":"major","evidence":[{"chapter":1,"quote":"旧表已毁。","other":1}]}]}'])
def test_output_strictly_rejects_unknown_fields(raw):
    r=result();r['raw_output']=raw
    assert not score_case(case(False),r)['output_valid']


def test_human_rejection_controls_score_exit():
    import importlib.util
    spec=importlib.util.spec_from_file_location('evaluation_cli','scripts/evaluate.py')
    cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    s={'planned':1,'completed':1,'provisional_automatic':{'passed':1},
       'confirmed':{'cases':1,'overall_success':0}}
    assert cli.quality_exit(s,reviewed=True)==1


def test_catalog_points_to_real_functions():
    from myink.evaluation.cases import validate_catalog
    assert validate_catalog(Path.cwd())==40


def test_torn_jsonl_tail_recovers_durable_artifact(tmp_path):
    import importlib.util
    from myink.evaluation.runner import digest
    spec=importlib.util.spec_from_file_location('evaluation_cli','scripts/evaluate.py')
    cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    c=case();r={**result(),'case_sha256':digest(c.model_dump())}
    (tmp_path/'cases.json').write_text(json.dumps([c.model_dump()]),encoding='utf-8')
    (tmp_path/'results.jsonl').write_text(json.dumps(r,ensure_ascii=False)[:30],encoding='utf-8')
    (tmp_path/'manifest.json').write_text(json.dumps({'status':'running','results_sha256':digest([]),
        'cases_sha256':digest([c.model_dump()])}),encoding='utf-8')
    artifact=tmp_path/'artifacts'/c.id;artifact.mkdir(parents=True)
    (artifact/'result.json').write_text(json.dumps(r),encoding='utf-8')
    cases,rows=cli.load_run(tmp_path)
    assert rows==[r] and len(cases)==1


def test_case_snapshot_tampering_rejected(tmp_path):
    import importlib.util
    from myink.evaluation.runner import digest
    spec=importlib.util.spec_from_file_location('evaluation_cli','scripts/evaluate.py')
    cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    original=case();r={**result(),'case_sha256':digest(original.model_dump())}
    edited=original.model_dump();edited['label']['review_note']='changed after run'
    (tmp_path/'cases.json').write_text(json.dumps([edited]),encoding='utf-8')
    (tmp_path/'results.jsonl').write_text(json.dumps(r)+'\n',encoding='utf-8')
    (tmp_path/'manifest.json').write_text(json.dumps({'status':'finished','results_sha256':digest([r]),
        'cases_sha256':digest([edited])}),encoding='utf-8')
    with pytest.raises(ValueError,match='case hash'):cli.load_run(tmp_path)


def test_live_adapter_disables_sdk_retries_and_marks_projection(monkeypatch):
    from types import SimpleNamespace
    from myink.evaluation.runner import deepseek_call
    secret='sk-synthetic-secret12345';monkeypatch.setenv('DEEPSEEK_API_KEY',secret)
    captured={}
    class Client:
        def __init__(self,**kwargs):
            captured.update(kwargs);self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def create(self,**kwargs):
            captured['request']=kwargs
            return SimpleNamespace(model='actual-model',usage=SimpleNamespace(prompt_tokens=11,completion_tokens=9),
                choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps(
                    {'verdict':'pass','findings':[],'reasons':[secret]}),reasoning_content=None,
                    tool_calls=[SimpleNamespace(id='call-1',function=SimpleNamespace(name='query',arguments=json.dumps({'nested':[{'echo':secret}]})))]))])
    monkeypatch.setattr('openai.OpenAI',Client)
    config={'model':'deepseek-v4-flash','max_tokens':100,'temperature':.1,'timeout_seconds':5,
            'prices':{'input':2,'output':8}}
    row=deepseek_call([{'role':'user','content':'audit'}],config)
    assert captured['max_retries']==0 and captured['timeout']==5
    assert row['model_id']=='actual-model' and row['cost_status']=='estimated'
    assert secret not in row['raw_output'] and secret not in row['raw_response_content']
    assert secret not in json.dumps(row['tool_calls'])
    assert row['response_projection']['scrubbed']
