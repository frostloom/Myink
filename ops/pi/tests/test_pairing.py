"""Pure paired evidence tests; no services, model calls or private story input."""
import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

import pytest


def api():
    assert importlib.util.find_spec('ops.pi.evaluate') is not None, 'C16 paired evaluator missing'
    return importlib.import_module('ops.pi.evaluate')


def sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def setup():
    config={'model':'mock-model','protocol':'anthropic','pricing_id':'a'*64,
            'budget_scope_id':'local-trial-1','temperature':0.1,'max_tokens':100,
            'base_url':'http://127.0.0.1:8088'}
    baseline={'id':'baseline','source_hash':'b'*64,'prompt':'old instruction','config':config}
    candidate={**copy.deepcopy(baseline),'id':'candidate','prompt':'new instruction'}
    cases=[]
    for i in range(6):
        text=['旧表已毁。','左膝受伤。','水泵承诺未完成。','昨天来过站台。','门外威胁未解。','仪器电池取出。'][i]
        doc={'id':'source','path':'/history/0','project_id':f'p{i}','chapter':1,
             'as_of_chapter':2,'text':text,'fingerprint':hashlib.sha256(text.encode()).hexdigest(),
             'complete':True,'representation':'original_utf8','role':'source'}
        cases.append({'id':f'c{i}','group_id':f'g{i}','source_family':f'family{i}',
          'project_id':f'p{i}','account_group':'synthetic','split':'development' if i<5 else 'holdout',
          'holdout_disclosure':'local_public_holdout' if i==5 else None,
          'source_kind':'synthetic','human_provenance':'unknown','label_status':'proposed',
          'task_type':'long_write','as_of_chapter':2,'input':{'history':text},
          'messages':[{'role':'user','content':'修复接线，说明替代表来源。'}],
          'documents':[doc],'required_ids':['old-meter'],'relevant_ids':['old-meter','alias'],
          'severe_rule_ids':['destroyed_item']})
    plan={'hypothesis':'fixed prompt','metric':'write.prose','guard_metrics':['write.constraints'],
          'minimum_improvement':0.1,'severe_regression':0.1,'sample_floor':5,
          'baseline':'baseline','baseline_config_hash':sha(config),'evidence_domain':'synthetic'}
    return baseline,candidate,cases,plan


def executor(request):
    text='他购入新表。'
    doc={'id':'draft','path':'/draft','project_id':request['case']['project_id'],'chapter':2,
         'as_of_chapter':2,'text':text,'fingerprint':hashlib.sha256(text.encode()).hexdigest(),
         'complete':True,'representation':'original_utf8','role':'draft'}
    return {'execution':'completed','raw_output':text,'model_id':'mock-model','documents':[doc],
            'executed_messages_sha256':sha(request['messages']),
            'executed_config_sha256':sha(request['config']),
            'accounting_status':'reconciled','pricing_id':'a'*64,
            'cost_status':'estimated','cost_est':0.01,'usage':{'input_tokens':2,'output_tokens':3},
            'mechanism_measurements':{}}


def freeze(b,c,cases,p,**kwargs):
    return api().freeze_pairing(b,c,cases,p,rubric=api().unified_rubric(),
        changed_factor=kwargs.pop('changed_factor','prompt'),**kwargs)


def citation(doc):
    return {k:doc[k] for k in ('id','path','project_id','chapter','as_of_chapter','fingerprint','representation')} | {
        'start_byte':0,'end_byte':len(doc['text'].encode()),'quote':doc['text']}


def judge(payload):
    assessments={}
    for label,row in payload['outputs'].items():
        docs=payload['case']['documents']+row['documents']
        cites=[citation(d) for d in docs]
        assessments[label]={'metrics':{
           'write.prose':{'value':1 if row['draft']=='他购入新表。' else 0.5,'reason':'cited prose','citations':cites},
           'write.constraints':{'value':1,'reason':'cited full constraints','citations':cites}},
           'severe':{'scope_complete':True,'checked_rule_ids':['destroyed_item'],'findings':[]}}
    return {'assessments':assessments,'actor_kind':'model'}


def test_baseline_candidate_same_input_and_unaffected_factors():
    b,c,cases,p=setup(); calls=[]
    def execute(request):calls.append(copy.deepcopy(request));return executor(request)
    result=api().run_paired(b,c,cases,freeze(b,c,cases,p),execute)
    assert len(calls)==12 and len(result['outputs'])==12
    assert {r['case_sha256'] for r in result['outputs']}=={sha(x) for x in cases}
    for case in cases:
        pair=[r for r in calls if r['case']['id']==case['id']]
        assert pair[0]['case']==pair[1]['case'] and pair[0]['config']==pair[1]['config']
        assert 'severe_rule_ids' not in pair[0]['case'] and 'required_ids' not in pair[0]['case']
    assert result['release_allowed'] is False


def test_prompt_candidate_actually_executed():
    b,c,cases,p=setup(); seen=[]
    def execute(request):seen.append(request['messages'][0]['content']);return executor(request)
    bundle=api().run_paired(b,c,cases,freeze(b,c,cases,p),execute)
    assert seen.count('old instruction')==6 and seen.count('new instruction')==6
    assert len({r['messages_sha256'] for r in bundle['outputs']})==2


@pytest.mark.parametrize('change',['model','threshold','case','source','rubric'])
def test_changed_frozen_identity_rejected_before_execution(change):
    b,c,cases,p=setup(); frozen=freeze(b,c,cases,p)
    if change=='model':c['config']['model']='other'
    elif change=='threshold':frozen['plan']['minimum_improvement']=0.9
    elif change=='case':cases[0]['input']['history']='rewritten'
    elif change=='source':c['source_hash']='d'*64
    else:frozen['rubric']['version']='other'
    with pytest.raises(ValueError):api().run_paired(b,c,cases,frozen,executor)


def test_source_factor_and_existing_plan_support_deterministic_objective_without_model():
    from ops.pi.plans import Plan
    b,c,cases,p=setup(); c['prompt']=b['prompt'];c['source_hash']='c'*64
    plan=Plan(hypothesis='retain complete bytes',metric='trace_fidelity',minimum_improvement=.1,
      severe_regression=.1,sample_floor=5,guard_metrics=('encoded_cap','redaction'),baseline='baseline',
      baseline_config_hash=sha(b['config']),scope='stability',files=('src/myink/admin_observability.py',),
      slice_ids=('capture',),compatibility='same input',rollback='restore source',call_estimate=0,
      time_estimate=60,behavior='capture completeness',evidence_domain='synthetic')
    def execute(request):
        row=executor(request)
        row['actual_http_attempts']=0  # verified injected deterministic executor, no upstream calls
        row['mechanism_measurements']={k:{'value':1 if k!='trace_fidelity' or request['version']=='candidate' else 0,
          'availability':'measured','assessment_kind':'deterministic','evidence_sha256':'e'*64}
          for k in ('trace_fidelity','encoded_cap','redaction')}
        return row
    frozen=freeze(b,c,cases,plan,changed_factor='source',directions={'trace_fidelity':'higher','encoded_cap':'higher','redaction':'higher'})
    result=api().run_paired(b,c,cases,frozen,execute)
    assert frozen['approved_plan_hash']==plan.plan_hash
    assert result['mechanism']['status']=='improved' and result['semantic_quality_claim'] is False
    assert result['real_model_calls']==0 and result['release_allowed'] is False


def test_partial_comparison_cannot_release_and_all_slots_remain():
    b,c,cases,p=setup();n=0
    def execute(request):
        nonlocal n
        n+=1
        if n==3:raise TimeoutError('fixture')
        if n>4:raise RuntimeError('budget exhausted')
        return executor(request)
    result=api().run_paired(b,c,cases,freeze(b,c,cases,p),execute)
    reviewed=api().blind_review(result,judge,api().unified_rubric())
    assert len(result['outputs'])==12 and len(reviewed['judge_slots'])==6
    assert result['complete_pairs']==1 and reviewed['release_allowed'] is False
    assert any(r['execution']=='timeout' for r in result['outputs'])
    assert any(r['execution']=='budget_stopped' for r in result['outputs'])


def test_blind_payload_seed_and_mapping_do_not_expose_variants():
    b,c,cases,p=setup();bundle=api().run_paired(b,c,cases,freeze(b,c,cases,p),executor);seen=[]
    def call(payload):seen.append(payload);return judge(payload)
    first=api().blind_review(bundle,call,api().unified_rubric())
    second=api().blind_review(bundle,judge,api().unified_rubric())
    assert first['blind_key']==second['blind_key'] and len(seen)==6
    assert all('cost_est' not in json.dumps(x) and 'source_hash' not in json.dumps(x) and
               'old instruction' not in json.dumps(x) and 'new instruction' not in json.dumps(x) for x in seen)
    assert first['online_quality_claim'] is False and first['p95_conclusion'] is None


def test_severe_rule_error_cannot_average_away():
    b,c,cases,p=setup();bundle=api().run_paired(b,c,cases,freeze(b,c,cases,p),executor)
    def call(payload):
        result=judge(payload)
        for label,row in payload['outputs'].items():
            result['assessments'][label]['severe']['findings']=[{'rule_id':'destroyed_item',
              'reason':'fixture contradiction','citations':[citation(payload['case']['documents'][0]),citation(row['documents'][0])]}]
        return result
    result=api().blind_review(bundle,call,api().unified_rubric())
    assert result['release_allowed'] is False and result['status']=='severe_veto'


def test_missing_guard_or_invalid_severe_evidence_is_unknown():
    b,c,cases,p=setup();bundle=api().run_paired(b,c,cases,freeze(b,c,cases,p),executor)
    def call(payload):
        result=judge(payload)
        for assessment in result['assessments'].values():
            assessment['metrics']['write.constraints']['citations']=[]
            assessment['severe']['findings']=[{'rule_id':'destroyed_item','reason':'unsupported','citations':[]}]
        return result
    result=api().blind_review(bundle,call,api().unified_rubric())
    assert result['release_allowed'] is False and result['status']=='insufficient_evidence'
    assert all(r['metrics']['write.constraints']['value'] is None for r in result['reviews'])


def test_all_45_metrics_unknown_short_na_and_no_implicit_acceptance():
    b,c,cases,p=setup();case=cases[0];case['task_type']='short_write'
    report=api().assess(case,executor({'case':case,'messages':[],'config':{}}),{'metrics':{},'severe':{}},api().unified_rubric())
    assert len(report['metrics'])==45
    assert report['metrics']['recall.facts.coverage']['availability']=='not_applicable'
    assert report['metrics']['extract.persistence']['availability']=='not_applicable'
    assert report['metrics']['experience.acceptance']['value'] is None
    assert all(v['label_status']=='proposed' and v['actor_kind']!='human' for v in report['metrics'].values())


def test_utf8_citation_fingerprint_scope_and_gap_validation():
    _,_,cases,_=setup();doc=cases[0]['documents'][0];ref=citation(doc)
    assert api().validate_citation(ref,[doc])
    for field,value in [('start_byte',1),('fingerprint','f'*64),('project_id','foreign'),('chapter',99),('quote','旧表没毁。')]:
        bad={**ref,field:value};assert not api().validate_citation(bad,[doc])
    clipped={**doc,'complete':False,'retained_ranges':[[0,3],[9,15]]}
    assert not api().validate_citation(ref,[clipped])


def test_clipped_trace_does_not_certify_absence_or_persistence():
    _,_,cases,_=setup();case=cases[0];out=executor({'case':case,'messages':[],'config':{}})
    out['documents'][0]['role']='extract_output';out['documents'][0]['complete']=False
    metrics={'extract.omission':{'value':1,'reason':'absent in clipped text','citations':[citation(case['documents'][0]),citation(out['documents'][0])]},
             'extract.persistence':{'value':1,'reason':'candidate confirmed','citations':[citation(case['documents'][0]),citation(out['documents'][0])]}}
    scored=api().assess(case,out,{'metrics':metrics,'severe':{}},api().unified_rubric())
    assert scored['metrics']['extract.omission']['value'] is None
    assert scored['metrics']['extract.persistence']['value'] is None


def test_recall_required_and_optional_relevant_sets_are_independent():
    rows=[{'id':'r','project_id':'p','chapter':1},{'id':'r','project_id':'p','chapter':1},
          {'id':'optional','project_id':'p','chapter':1},{'id':'future','project_id':'p','chapter':4},
          {'id':'foreign','project_id':'other','chapter':1}]
    result=api().recall_metrics(['r'],['r','optional'],rows,project_id='p',as_of_chapter=2)
    assert result['coverage']==1 and result['relevance']==0.5 and result['returned_unique']==4
    assert result['future_leaks']==1 and result['foreign_leaks']==1
    assert api().recall_metrics([],['optional'],[],project_id='p',as_of_chapter=2)['coverage'] is None


def test_extraction_one_to_one_identity_time_old_value_and_commit_ledger():
    expected=[{'id':'m','entity':'Lin','attribute':'meter','chapter':2,'old_value':'destroyed','new_value':'new'}]
    duplicate=[copy.deepcopy(expected[0]),copy.deepcopy(expected[0])]
    result=api().extraction_metrics(expected,duplicate,complete=True,commit_ledger=[])
    assert result['support']==0.5 and result['omission']==0 and result['persistence'] is None
    bad=[{**expected[0],'entity':'wrong','chapter':3,'old_value':'working'}]
    result=api().extraction_metrics(expected,bad,complete=True,commit_ledger=[])
    assert result['identity']==0 and result['time']==0 and result['old_value']==0
    assert api().extraction_metrics(expected,duplicate,complete=False,commit_ledger=[])['omission'] is None


def test_source_family_leakage_duplicate_groups_and_exposed_holdout_are_guarded():
    b,c,cases,p=setup();cases[-1]['source_family']=cases[0]['source_family']
    with pytest.raises(ValueError,match='split'):freeze(b,c,cases,p)
    b,c,cases,p=setup();cases[-1]['holdout_disclosure']=None
    with pytest.raises(ValueError,match='holdout'):freeze(b,c,cases,p)
    b,c,cases,p=setup();cases[-1]['group_id']=cases[0]['group_id']
    with pytest.raises(ValueError,match='group'):freeze(b,c,cases,p)


def test_full_task_operations_need_terminal_boundaries_and_all_role_cost_coverage():
    rows=[{'execution':'completed','output':{'model_id':'m','input_tokens':100,'cost_est':0.1}}]
    report=api().operational_metrics(rows)
    assert report['success']['value'] is None and report['cost']['value'] is None
    assert report['latency']['value'] is None and report['latency_p95']['value'] is None
    rows[0]['output'].update(task_terminal_verified=True,terminal_outcome='success',
      task_started_at='2026-10-12T00:00:00+00:00',task_finished_at='2026-10-12T00:00:02+00:00',
      cost_coverage_complete=True,accounting_status='reconciled',pricing_id='a'*64,source_kind='synthetic')
    report=api().operational_metrics(rows)
    assert report['success']['value']==1 and report['latency']['value']==2000
    assert report['cost']['value']==0.1 and report['latency_p95']['value'] is None


def test_no_selected_output_only_review_or_judge_identity_substitution():
    b,c,cases,p=setup();bundle=api().run_paired(b,c,cases,freeze(b,c,cases,p),executor)
    bundle['outputs']=bundle['outputs'][:2]
    with pytest.raises(ValueError,match='bundle'):api().blind_review(bundle,judge,api().unified_rubric())


def test_guard_regression_in_one_pair_blocks_mechanism_average():
    b,c,cases,p=setup();c['prompt']=b['prompt'];c['source_hash']='c'*64
    p['metric']='trace_fidelity';p['guard_metrics']=['redaction']
    def execute(request):
        result=executor(request)
        result['mechanism_measurements']={k:{'value':1 if k=='redaction' or request['version']=='candidate' else 0,
          'availability':'measured','assessment_kind':'deterministic','evidence_sha256':'e'*64} for k in ('trace_fidelity','redaction')}
        if request['version']=='candidate' and request['case']['id']=='c0':
            result['mechanism_measurements']['redaction']['value']=0
        return result
    bundle=api().run_paired(b,c,cases,freeze(b,c,cases,p,changed_factor='source'),execute)
    assert bundle['mechanism']['status']=='regressed' and bundle['release_allowed'] is False



def test_unmetered_or_unbound_judge_cannot_release_even_with_positive_scores():
    b,c,cases,p=setup()
    def execute(request):
        out=executor(request)
        if request['version']=='baseline':
            out['raw_output']='他检查新表。';doc=out['documents'][0];doc['text']=out['raw_output']
            doc['fingerprint']=hashlib.sha256(doc['text'].encode()).hexdigest()
        return out
    bundle=api().run_paired(b,c,cases,freeze(b,c,cases,p),execute)
    reviewed=api().blind_review(bundle,judge,api().unified_rubric())
    assert reviewed['comparison']['status']=='improved'
    assert reviewed['release_allowed'] is False and reviewed['status']=='insufficient_evidence'


def test_blinded_document_identity_and_nested_metadata_do_not_reveal_version():
    b,c,cases,p=setup()
    for case in cases:case['input']['branch']='secret-branch'
    def execute(request):
        out=executor(request);out['documents'][0]['id']=request['version']+'-draft'
        out['documents'][0]['path']='/'+request['version']+'/draft'
        out['documents'][0]['cost_est']=42
        return out
    bundle=api().run_paired(b,c,cases,freeze(b,c,cases,p),execute);seen=[]
    def call(payload):seen.append(json.dumps(payload));return judge(payload)
    api().blind_review(bundle,call,api().unified_rubric())
    assert all('secret-branch' not in payload and 'baseline-draft' not in payload and
               'candidate-draft' not in payload and 'cost_est' not in payload for payload in seen)



def test_positive_cited_improvement_requires_frozen_and_accounted_judge():
    b,c,cases,p=setup();identity={'model':'mock-judge','config_sha256':'9'*64,'prompt_sha256':'8'*64}
    def execute(request):
        out=executor(request)
        if request['version']=='baseline':
            out['raw_output']='他检查新表。';doc=out['documents'][0];doc['text']=out['raw_output']
            doc['fingerprint']=hashlib.sha256(doc['text'].encode()).hexdigest()
        return out
    bundle=api().run_paired(b,c,cases,freeze(b,c,cases,p,judge=identity),execute)
    def metered(payload):
        return {'raw_output':json.dumps(judge(payload)),'model_id':'mock-judge',
          'accounting_status':'reconciled','cost_status':'estimated','cost_est':0.01,
          'executed_config_sha256':'9'*64,'judge_prompt_sha256':'8'*64}
    report=api().blind_review(bundle,metered,api().unified_rubric())
    assert report['release_allowed'] is True and report['status']=='improved'
    assert report['online_quality_claim'] is False


def test_wrong_case_scope_cannot_score_full_constraints():
    _,_,cases,_=setup();case=cases[0];out=executor({'case':case,'messages':[],'config':{}})
    out['documents'][0]['as_of_chapter']=99
    judgment={'metrics':{'write.constraints':{'value':1,'reason':'full scope',
      'citations':[citation(case['documents'][0]),citation(out['documents'][0])]}},'severe':{}}
    assert api().assess(case,out,judgment,api().unified_rubric())['metrics']['write.constraints']['value'] is None


def test_duplicate_recall_observations_keep_future_and_foreign_evidence():
    rows=[{'id':'r','project_id':'foreign','chapter':3},{'id':'r','project_id':'p','chapter':1}]
    scored=api().recall_metrics(['r'],['r'],rows,project_id='p',as_of_chapter=2)
    assert scored['coverage']==1 and scored['future_leaks']==1 and scored['foreign_leaks']==1


@pytest.mark.parametrize('attempts', ['missing', None, 0, 2])
def test_fixround1_attempt_aggregate_preserves_unknown_and_explicit_zero(attempts):
    b,c,cases,p=setup()
    def execute(request):
        row=executor(request)
        if attempts!='missing':row['actual_http_attempts']=attempts
        return row
    result=api().run_paired(b,c,cases,freeze(b,c,cases,p),execute)
    assert result['complete_pairs']==6
    assert result['real_model_calls']==(0 if attempts==0 else 24 if attempts==2 else None)


@pytest.mark.parametrize('target,guard,want', [
    ('trace_fidelity','latency_p95','insufficient_evidence'),
    ('latency_p95','encoded_cap','insufficient_evidence'),
    ('trace_fidelity','encoded_cap','improved')])
def test_fixround1_synthetic_p95_target_and_guard_are_ineligible(target,guard,want):
    b,c,cases,p=setup();p.update(metric=target,guard_metrics=[guard])
    def execute(request):
        row=executor(request);row['actual_http_attempts']=0
        row['mechanism_measurements']={metric:{'value':2 if request['version']=='candidate' and metric==target else 1,
          'availability':'measured','assessment_kind':'deterministic','evidence_sha256':'e'*64}
          for metric in (target,guard)}
        return row
    result=api().run_paired(b,c,cases,freeze(b,c,cases,p),execute)
    assert result['mechanism']['status']==want
    if want=='insufficient_evidence':assert result['mechanism']['deltas']=={}


def extraction_assessment_fixture():
    _,_,cases,_=setup();case=cases[0]
    out=executor({'case':case,'messages':[],'config':{}});out['documents'][0]['role']='extract_output'
    refs=[citation(case['documents'][0]),citation(out['documents'][0])]
    return case,out,refs


@pytest.mark.parametrize('labels', ['absent','missing','gap','unreviewed'])
def test_fixround1_extraction_missing_independent_labels_stays_unknown(labels):
    case,out,refs=extraction_assessment_fixture()
    if labels!='absent':case['expected_mutations']=[]
    if labels=='gap':case.update(expected_mutations_status='independently_reviewed',label_gaps=['missing historical labels'])
    item={'value':1,'reason':'cited no omissions','citations':refs,'denominator':0,'items':[]}
    scored=api().assess(case,out,{'metrics':{'extract.omission':item}},api().unified_rubric())
    row=scored['metrics']['extract.omission']
    assert row['value'] is None and row['availability']=='unknown'


@pytest.mark.parametrize('bad', [None,'denominator','item_citation','duplicate','label_citation'])
def test_fixround1_extraction_independent_nonempty_set_needs_item_evidence(bad):
    case,out,refs=extraction_assessment_fixture()
    case['expected_mutations_status']='independently_reviewed'
    case['expected_mutations']=[{'id':'meter-change','entity':'Lin','attribute':'meter',
      'chapter':2,'old_value':'destroyed','new_value':'new','citations':[refs[0]]}]
    item={'value':1,'reason':'one independently expected mutation checked','citations':refs,
          'denominator':1,'items':[{'id':'meter-change','citations':refs}]}
    if bad=='denominator':item['denominator']=None
    elif bad=='item_citation':item['items'][0]['citations']=[]
    elif bad=='duplicate':item['items']*=2
    elif bad=='label_citation':case['expected_mutations'][0]['citations']=[]
    row=api().assess(case,out,{'metrics':{'extract.omission':item}},api().unified_rubric())['metrics']['extract.omission']
    assert row['value']==(1 if bad is None else None)
    if bad is None:assert row['denominator']==1 and row['availability']=='provisional'


def test_fixround1_verified_empty_extraction_set_is_na_not_a_perfect_score():
    case,out,refs=extraction_assessment_fixture()
    case.update(expected_mutations=[],expected_mutations_status='independently_reviewed',label_gaps=[])
    item={'value':1,'reason':'no independently expected mutations','citations':refs,'denominator':0,'items':[]}
    row=api().assess(case,out,{'metrics':{'extract.omission':item}},api().unified_rubric())['metrics']['extract.omission']
    assert row['value'] is None and row['availability']=='not_applicable' and row['denominator']==0



def payload_only_extraction_judge(payload):
    """Independent mock judge reads labels and citations ONLY from the blind payload."""
    case=payload['case'];labels=case.get('expected_mutations',[]);assessments={}
    for anonymous,row in payload['outputs'].items():
        output_refs=[citation(doc) for doc in row['documents'] if doc.get('role')=='extract_output']
        checked=[{'id':label['id'],'citations':label.get('citations',[])+output_refs} for label in labels]
        refs=[citation(doc) for doc in case['documents']]+output_refs
        assessments[anonymous]={'metrics':{'extract.omission':{
          'value':1,'reason':'payload comparison set checked','citations':refs,
          'denominator':len(labels),'items':checked}},'severe':{}}
    return {'actor_kind':'model','assessments':assessments}


@pytest.mark.parametrize('provenance', ['valid','missing','gapped','invalid','unmapped'])
def test_fixround2_blind_judge_uses_only_anonymous_frozen_extraction_labels(provenance):
    b,c,cases,p=setup()
    for i,case in enumerate(cases):
        doc=case['documents'][0]
        doc['id']=f'private-source-{i}';doc['path']=f'/private-source-family/{i}'
        label_ref=citation(doc) | {'side':'candidate','version':'private-version','source_hash':'private-source-hash','source_path':'private-provenance-path'}
        if provenance=='invalid':label_ref['fingerprint']='f'*64
        elif provenance=='unmapped':label_ref['path']='/unmapped-private-path'
        case.update(expected_mutations_status='independently_reviewed',label_gaps=[],
          expected_mutations=[{'id':f'mutation-{i}','entity':'Lin','attribute':'meter','chapter':2,
            'old_value':'destroyed','new_value':'new','citations':[label_ref]}])
        if provenance=='missing':
            case.pop('expected_mutations_status');case['expected_mutations']=[]
        elif provenance=='gapped':case['label_gaps']=['independent historical labels missing']
    def execute(request):
        out=executor(request);out['documents'][0]['role']='extract_output';out['actual_http_attempts']=0
        return out
    bundle=api().run_paired(b,c,cases,freeze(b,c,cases,p),execute);seen=[]
    def call(payload):
        seen.append(copy.deepcopy(payload))
        return payload_only_extraction_judge(payload)
    report=api().blind_review(bundle,call,api().unified_rubric())
    assert all(slot['execution']=='completed' for slot in report['judge_slots'])
    for row in report['reviews']:
        metric=row['metrics']['extract.omission']
        assert metric['value']==(1 if provenance=='valid' else None)
        assert metric['availability']==('provisional' if provenance=='valid' else 'unknown')
        if provenance=='valid':
            assert metric['denominator']==1 and metric['items'][0]['id'].startswith('mutation-')
            assert metric['items'][0]['citations'][0]['id'].startswith('private-source-')
            assert metric['items'][0]['citations'][0]['path'].startswith('/private-source-family/')
    assert len(seen)==6
    for payload in seen:
        supplied=payload['case']
        assert 'expected_mutations' in supplied and 'label_gaps' in supplied
        if provenance!='missing':assert supplied['expected_mutations_status']=='independently_reviewed'
        if provenance=='gapped':assert supplied['label_gaps']==['independent historical labels missing']
        for mutation in supplied['expected_mutations']:
            for ref in mutation['citations']:
                assert (ref['id'],ref['path'])==(('unknown-source','/evidence/unknown') if provenance=='unmapped' else ('S1','/evidence/S/1'))
        encoded=json.dumps(payload)
        assert all(secret not in encoded for secret in ('private-source-','private-source-family','private-version','private-source-hash','private-provenance-path','unmapped-private-path'))
    assert report['release_allowed'] is False and report['online_quality_claim'] is False
