"""Fail-closed intake and evidence honesty for the private writing analysis path."""
from copy import deepcopy
import hashlib
from importlib.util import find_spec
import json
import os
from pathlib import Path

import pytest

TASK = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
PROJECT = '33333333-3333-4333-8333-333333333333'
START = '2026-10-01T00:00:00+00:00'
END = '2026-10-02T00:00:00+00:00'


def api():
    assert find_spec('ops.pi.writing_evidence') is not None, 'writing evidence capability is missing'
    from ops.pi import writing_evidence
    return writing_evidence


def bundle():
    return dict(schema_version=1, collected_at=END, source='production-readonly',
                source_role='myink_report', window=dict(start=START, end=END),
                provenance_note='human authorship not certified',
                tasks=[dict(id=TASK, project_id=PROJECT, task_type='chapter_generate', status='done',
                            request=dict(seq=2), created_at=START, updated_at=END, retry_count=1)],
                projects=[dict(id=PROJECT)], agent_runs=[], generation_snapshots=[],
                chapters=[], chapter_versions=[], memory_candidates=[], facts=[], events=[],
                character_states=[], characters=[], plot_threads=[], foreshadows=[],
                project_settings=[], validation_reports=[], findings=[],
                short_creation_sessions=[], short_creation_messages=[])


def run(identifier=1, **changes):
    value = dict(id=identifier, project_id=PROJECT, task_id=TASK, node='write',
                 duration_ms=100, input_tokens=2, output_tokens=3, cost_est=None,
                 retry_count=0, trace={}, created_at=START, updated_at=END)
    value.update(changes)
    return value


def save(root, value):
    path = root / 'bundle.json'
    raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def test_load_verifies_raw_hash_and_stable_row_fingerprints(tmp_path):
    path, sha = save(tmp_path, bundle())
    data = api().load_writing_bundle(path, sha, trusted_root=tmp_path)
    report = api().analyze_writing_bundle(data)
    assert report['dataset_sha256'] == sha
    assert len(report['sources']['tasks'][0]['fingerprint']) == 64
    with pytest.raises(ValueError, match='hash'):
        api().load_writing_bundle(path, 'a' * 64, trusted_root=tmp_path)


@pytest.mark.parametrize('change', ['duplicate', 'table', 'overcap', 'bad_id', 'schema', 'window'])
def test_load_rejects_invalid_intake_contract(tmp_path, change):
    data = bundle()
    if change == 'duplicate':
        data['tasks'].append(deepcopy(data['tasks'][0]))
    elif change == 'table':
        data['users'] = []
    elif change == 'overcap':
        data['agent_runs'] = [run(n) for n in range(401)]
    elif change == 'bad_id':
        data['tasks'][0]['id'] = 'arbitrary-prefix'
    elif change == 'schema':
        data['schema_version'] = 2
    else:
        data['window']['end'] = START
    path, sha = save(tmp_path, data)
    with pytest.raises(ValueError):
        api().load_writing_bundle(path, sha, trusted_root=tmp_path)


def test_load_rejects_outside_root_nonregular_and_oversize(tmp_path):
    root = tmp_path / 'private'
    root.mkdir()
    path, sha = save(tmp_path, bundle())
    with pytest.raises(ValueError):
        api().load_writing_bundle(path, sha, trusted_root=root)
    with pytest.raises(ValueError):
        api().load_writing_bundle(root, sha, trusted_root=root)
    path = root / 'large.json'
    with path.open('wb') as output:
        output.truncate(8 * 1024 * 1024 + 1)
    with pytest.raises(ValueError):
        api().load_writing_bundle(path, sha, trusted_root=root)


def test_load_rejects_symlink_even_when_target_is_inside_root(tmp_path):
    path, sha = save(tmp_path, bundle())
    link = tmp_path / 'link.json'
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip('host cannot create symlink without OS privilege')
    with pytest.raises(ValueError):
        api().load_writing_bundle(link, sha, trusted_root=tmp_path)


def test_exact_task_join_validates_project_and_chapter_suffix():
    data = bundle()
    data['agent_runs'] = [run(1), run(2, task_id=TASK + ':ch2'),
                          run(3, task_id=TASK + ':ch20'), run(4, project_id=OTHER),
                          run(5, task_id=TASK + ':extra'), run(6, task_id=None, project_id=None)]
    data['generation_snapshots'] = [dict(id=1, project_id=PROJECT, task_id=TASK + ':ch2',
                                       chapter_seq=2, stage='write', trace={})]
    result = api().analyze_writing_bundle(data)
    assert result['task_bundles'][0]['run_ids'] == [1, 2]
    assert result['task_bundles'][0]['snapshot_ids'] == [1]
    assert result['unassociated']['agent_runs'] == [3, 4, 5, 6]
    assert result['account_run_ids'] == [6]


def test_current_memory_does_not_backfill_historical_recall():
    data = bundle()
    data['facts'] = [dict(id=OTHER, project_id=PROJECT, content='CURRENT SECRET PROSE')]
    report = api().analyze_writing_bundle(data)
    task = report['task_bundles'][0]
    assert task['stages']['recall']['availability'] == 'unknown'
    assert task['contextual_now']['facts'] == [OTHER]
    assert all(metric['value'] is None for metric in report['quality_catalog'].values())
    assert 'CURRENT SECRET PROSE' not in json.dumps(report)


def test_trace_coverage_distinguishes_empty_retained_groups_and_truncation():
    data = bundle()
    data['agent_runs'] = [run(node='recall', trace=dict(context=dict(
        long_term_facts=[dict(fact_id=OTHER, content='trace')], mid_term_events=[],
        entity_snapshots=[], plot_threads=[]), _capture=dict(truncated=True, scope='telemetry_only')))]
    report = api().analyze_writing_bundle(data)
    stage = report['task_bundles'][0]['stages']['recall']
    assert stage['availability'] == 'retained'
    assert stage['families']['facts']['records'] == 1
    assert stage['families']['events']['records'] == 0
    assert stage['families']['characters']['availability'] == 'retained'
    assert stage['families']['plot']['availability'] == 'retained'
    assert stage['capture_truncated'] is True
    assert report['quality_catalog']['recall.facts.coverage']['availability'] == 'unknown'


def test_short_recall_and_extract_are_not_applicable():
    data = bundle()
    data['tasks'][0]['task_type'] = 'short_generate'
    report = api().analyze_writing_bundle(data)
    assert report['task_bundles'][0]['stages']['recall']['availability'] == 'not_applicable'
    assert report['task_bundles'][0]['stages']['extract']['availability'] == 'not_applicable'


def test_success_denominators_preserve_failed_unknown_and_task_types():
    data = bundle()
    data['tasks'] += [dict(id=OTHER, task_type='chapter_generate', status='failed',created_at=START,updated_at=END),
                      dict(id='44444444-4444-4444-8444-444444444444', task_type='short_generate', status='running')]
    operations = api().analyze_writing_bundle(data)['operations']
    assert operations['chapter_generate']['status_counts'] == {'done': 1, 'failed': 1}
    assert operations['chapter_generate']['success']['value'] == .5
    assert operations['short_generate']['success']['value'] is None
    assert operations['short_generate']['success']['denominator'] == 1
    assert operations['chapter_generate']['lifecycle_proxy_ms']['p95'] is None
    assert operations['chapter_generate']['lifecycle_proxy_ms']['availability'] == 'reported_proxy'


def test_reported_cost_duration_not_mismeasured_unknown_cost_not_zero():
    data = bundle()
    data['agent_runs'] = [run(1, cost_est=2), run(2, cost_est=None)]
    operations = api().analyze_writing_bundle(data)['operations']['chapter_generate']
    assert operations['run_cost']['value'] is None
    assert operations['run_cost']['known_samples'] == 1
    assert operations['run_duration_ms']['value'] == 200
    assert operations['run_duration_ms']['availability'] == 'reported'
    assert operations['run_input_tokens']['value'] == 4
    data['agent_runs'][1]['cost_est'] = 0
    assert api().analyze_writing_bundle(data)['operations']['chapter_generate']['run_cost']['value'] is None


def test_measured_zero_cost_requires_measurement_pricing_and_provenance():
    data = bundle()
    data['agent_runs'] = [run(model_id='m',cost_est=0, trace=dict(measurement=dict(kind='model', cost=True,
                                  zero_cost=True, pricing_id='a' * 64), run_provenance=dict(model_id='m',
                                  deployment_id='d',generation=1,owner='human',schema_id='s',config_id='c',
                                  prompt_id='p',rubric_id='r',data_id='x',image_ids={'api':'image'})))]
    cost = api().analyze_writing_bundle(data)['operations']['chapter_generate']['run_cost']
    assert cost['value'] == 0
    assert cost['availability'] == 'measured'


def test_row_cap_is_possible_truncation_and_dataset_id_changes_with_rows():
    data = bundle()
    first = api().analyze_writing_bundle(data)
    data['short_creation_sessions'] = [dict(id=f'{n:08d}-1111-4111-8111-111111111111') for n in range(6)]
    second = api().analyze_writing_bundle(data)
    assert second['table_coverage']['short_creation_sessions']['possibly_truncated'] is True
    assert first['dataset_id'] != second['dataset_id']


def test_analysis_view_is_bounded_referenced_untrusted_and_honest_about_omissions():
    data = bundle()
    data['agent_runs'] = [run(n, node=node, trace=dict(messages=[dict(role='user', content='提示' * 2000)],
                            response=dict(content='输出' * 2000), context=dict(
                            long_term_facts=[dict(content='fact ' * 500)],
                            mid_term_events=[dict(summary='event ' * 500)],
                            entity_snapshots=[dict(content='character ' * 500)],
                            plot_threads=[dict(name='plot ' * 500)]),
                            _capture=dict(truncated=True)))
                          for n,node in enumerate(['recall','extract','write','audit','revise'],1)]
    report = api().analyze_writing_bundle(data)
    view = api().make_analysis_view(data, report, max_bytes=9000)
    raw = json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    assert len(raw) <= 9000
    assert view['dataset_sha256'] == report['dataset_sha256']
    assert view['untrusted_body_text'] is True
    assert view['limits']['omitted_evidence'] > 0
    assert view['limits']['clipped_fields'] > 0
    assert all(len(item['source']['fingerprint']) == 64 and item['source']['path'] for item in view['evidence'])
    assert {x['category'] for x in view['evidence']} >= {'recall.facts','recall.events','recall.characters','recall.plot','extract','audit'}


def test_analysis_view_redacts_contacts_and_credentials_and_short_turn_is_preserved():
    data = bundle()
    data['short_creation_sessions'] = [dict(id=OTHER, book_id=PROJECT)]
    data['short_creation_messages'] = [dict(id=1, session_id=OTHER, role='user',
        content='Contact name@example.com 13800138000 token sk-abc12345678901234567890')]
    view = api().make_analysis_view(data, api().analyze_writing_bundle(data))
    encoded = json.dumps(view)
    assert 'name@example.com' not in encoded and '13800138000' not in encoded
    assert 'sk-abc123' not in encoded
    assert any(item['category'] == 'short_turn' for item in view['evidence'])


def test_view_does_not_accept_report_from_other_dataset():
    data = bundle()
    report = api().analyze_writing_bundle(data)
    data['tasks'][0]['status'] = 'failed'
    with pytest.raises(ValueError):
        api().make_analysis_view(data, report)


def test_invalid_measured_provenance_cannot_certify_zero_cost():
    data = bundle()
    data['agent_runs'] = [run(cost_est=0, trace=dict(measurement=dict(kind='model', cost=True,
             zero_cost=True, pricing_id='a' * 64), run_provenance='untrusted claim'))]
    assert api().analyze_writing_bundle(data)['operations']['chapter_generate']['run_cost']['value'] is None
    data['agent_runs'][0]['trace']['run_provenance'] = dict(model_id='m')
    data['agent_runs'][0]['trace']['measurement']['pricing_id'] = 'not-a-fingerprint'
    assert api().analyze_writing_bundle(data)['operations']['chapter_generate']['run_cost']['value'] is None


def test_snapshot_with_contradicting_chapter_does_not_exactly_join_task():
    data = bundle()
    data['generation_snapshots'] = [dict(id=1, project_id=PROJECT, task_id=TASK,
                                       chapter_seq=20, stage='write', trace={})]
    report = api().analyze_writing_bundle(data)
    assert report['task_bundles'][0]['snapshot_ids'] == []
    assert report['unassociated']['generation_snapshots'] == [1]


def test_json_duplicate_keys_cannot_override_validated_intake(tmp_path):
    raw = json.dumps(bundle()).replace('"schema_version": 1', '"schema_version": 2, "schema_version": 1').encode()
    path = tmp_path / 'duplicate.json'
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        api().load_writing_bundle(path, hashlib.sha256(raw).hexdigest(), trusted_root=tmp_path)


def test_plan_cast_character_context_is_historical_evidence_separate_from_initial_recall():
    data = bundle()
    data['agent_runs'] = [run(1,node='recall',trace=dict(context=dict(entity_snapshots=[]))),
                          run(2,node='plan_cast',trace=dict(context=dict(entity_snapshots=[dict(character_id=OTHER)])))]
    stage = api().analyze_writing_bundle(data)['task_bundles'][0]['stages']['recall']
    assert stage['families']['characters']['records'] == 1
    assert [(c['node'],c['families']['characters']['records']) for c in stage['context_sources']] == [('recall',0),('plan_cast',1)]


def test_long_response_excerpts_include_tail_with_source_offsets_and_declared_gap():
    data = bundle()
    data['agent_runs'] = [run(node='short_review',trace=dict(response=dict(content='begin'+'a'*3000+'TAIL_MALFORMED')))]
    view = api().make_analysis_view(data,api().analyze_writing_bundle(data))
    item = next(e for e in view['evidence'] if e['source']['path']=='trace.response.content')
    assert any('TAIL_MALFORMED' in excerpt['text'] for excerpt in item['excerpts'])
    assert item['view_clipped'] is True and item['omitted_source_bytes'] > 0
    assert all(e['end_byte'] > e['start_byte'] for e in item['excerpts'])
    assert item['source']['node'] == 'short_review'


def test_capture_metadata_cannot_smuggle_secret_into_view():
    data = bundle()
    data['agent_runs'] = [run(trace=dict(messages=['safe'],_capture=dict(truncated=True,password='credential-secret')))]
    view = api().make_analysis_view(data,api().analyze_writing_bundle(data))
    assert 'credential-secret' not in json.dumps(view)


def test_partial_retries_and_lifecycle_proxy_do_not_claim_complete_availability():
    data = bundle()
    data['tasks'].append(dict(id=OTHER,task_type='chapter_generate',status='done'))
    result = api().analyze_writing_bundle(data)['operations']['chapter_generate']
    assert result['task_retries']['value'] is None
    assert result['task_retries']['availability'] == 'unknown'
    assert result['lifecycle_proxy_ms']['value'] is None
    assert result['lifecycle_proxy_ms']['availability'] == 'unknown'


def test_partial_provenance_cannot_certify_measured_zero_cost():
    data = bundle()
    data['agent_runs'] = [run(model_id='m',cost_est=0,trace=dict(measurement=dict(kind='model',cost=True,
        zero_cost=True,pricing_id='a'*64),run_provenance=dict(model_id='m')))]
    assert api().analyze_writing_bundle(data)['operations']['chapter_generate']['run_cost']['value'] is None





def test_recognized_dotted_credentials_and_structured_secrets_are_removed_before_clipping():
    data = bundle()
    data['agent_runs'] = [run(trace=dict(messages=[dict(content=dict(api_key='sk-ws-A.BBBBB.CCCCC.DDDDDD',
        authorization='Bearer arbitrary', nested=dict(password='private-password-value')))],
        response=dict(content='URL https://alice:private-password@example.test/path?token=hidden-key')))]
    view = api().make_analysis_view(data,api().analyze_writing_bundle(data))
    text = json.dumps(view)
    assert 'sk-ws-A.BBBBB' not in text and 'private-password' not in text
    assert 'arbitrary' not in text and 'hidden-key' not in text
    assert all(e['position_basis'] in ('retained_field_bytes','redacted_field_bytes') for e in view['evidence'])


def test_extract_view_prioritizes_raw_output_and_source_draft_from_same_run():
    data = bundle()
    data['agent_runs'] = [run(node='extract',trace=dict(messages=[dict(role='system',content='system'),
        dict(role='user',content='draft')],response=dict(content='raw mutations')))]
    view = api().make_analysis_view(data,api().analyze_writing_bundle(data))
    selected = [e for e in view['evidence'] if e['category']=='extract']
    assert [e['source']['path'] for e in selected[:2]] == ['trace.response.content','trace.messages[1].content']


def test_batch_snapshot_suffix_must_match_its_own_chapter():
    data = bundle()
    data['tasks'][0].update(chapter_seq=None,request=dict(start=1,size=2))
    data['generation_snapshots'] = [dict(id=1,project_id=PROJECT,task_id=TASK+':ch1',chapter_seq=2,stage='write',trace={}),
        dict(id=2,project_id=PROJECT,task_id=TASK+':ch2',chapter_seq=2,stage='write',trace={})]
    report = api().analyze_writing_bundle(data)
    assert report['task_bundles'][0]['snapshot_ids'] == [2]
    assert report['unassociated']['generation_snapshots'] == [1]


def test_child_alias_requires_chapter_in_parent_declared_range():
    data = bundle()
    data['tasks'][0].update(chapter_seq=None,request=dict(start=1,size=2))
    data['tasks'].append(dict(id=OTHER,project_id=PROJECT,batch_task_id=TASK,chapter_seq=3,task_type='chapter_generate',request={}))
    data['agent_runs'] = [run(1,task_id=TASK+':ch3')]
    report = api().analyze_writing_bundle(data)
    assert report['task_bundles'][1]['run_ids'] == []
    assert report['unassociated']['agent_runs'] == [1]
    data['tasks'][1]['chapter_seq'] = 2
    data['agent_runs'][0]['task_id'] = TASK+':ch2'
    report = api().analyze_writing_bundle(data)
    assert report['task_bundles'][1]['run_ids'] == [1]


@pytest.mark.parametrize('field,invalid', [
    ('deployment_id',''),('config_id','  '),('model_id',''),('schema_id',2),('owner',False),
    ('generation','1'),('generation',True),('generation',-1),('image_ids',''),('image_ids',{}),
    ('image_ids',{'api':''}),('image_ids',{'': 'image'}),('image_ids',{'api':42})])
def test_invalid_identity_cannot_certify_measurement(field,invalid):
    provenance = dict(model_id='m',deployment_id='d',generation=1,owner='human',schema_id='s',
                      config_id='c',prompt_id='p',rubric_id='r',data_id='x',image_ids={'api':'image'})
    provenance[field] = invalid
    data = bundle()
    data['agent_runs'] = [run(model_id=provenance['model_id'],cost_est=0,trace=dict(run_provenance=provenance,
        measurement=dict(kind='model',cost=True,zero_cost=True,pricing_id='a'*64,latency=True)))]
    metrics = api().analyze_writing_bundle(data)['operations']['chapter_generate']
    assert metrics['run_cost']['value'] is None
    assert metrics['run_duration_ms']['availability'] == 'reported'
    data['agent_runs'][0]['cost_est'] = 2
    cost = api().analyze_writing_bundle(data)['operations']['chapter_generate']['run_cost']
    assert cost['value'] == 2 and cost['availability'] == 'reported'


def test_short_turn_view_retains_exact_sessions_and_speakers_without_account_run_join():
    data = bundle()
    data['short_creation_sessions'] = [dict(id=TASK,book_id=PROJECT),dict(id=OTHER,book_id=PROJECT)]
    data['short_creation_messages'] = [dict(id=1,session_id=TASK,role='user',content='brief'),
        dict(id=2,session_id=OTHER,role='assistant',content='response')]
    data['agent_runs'] = [run(task_id=None,project_id=None,node='short_creation')]
    view = api().make_analysis_view(data,api().analyze_writing_bundle(data))
    refs = [e['source'] for e in view['evidence'] if e['category']=='short_turn']
    assert [(r['session_id'],r['role'],r['session_association']) for r in refs] == [(TASK,'user','exact'),(OTHER,'assistant','exact')]
    assert [(s['session_id'],s['message_ids']) for s in view['short_sessions']] == [(TASK,[1]),(OTHER,[2])]
    assert all(s['run_association']=='unknown: no session FK on account runs' for s in view['short_sessions'])
    assert len(json.dumps(view,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()) <= 48000


def test_short_turn_missing_session_or_invalid_role_stays_unavailable():
    data = bundle()
    data['short_creation_messages'] = [dict(id=1,session_id=OTHER,role='unexpected-secret-role',content='body'),
        dict(id=2,session_id='arbitrary-secret-reference',role='user',content='body')]
    view = api().make_analysis_view(data,api().analyze_writing_bundle(data))
    refs = [e['source'] for e in view['evidence'] if e['category']=='short_turn']
    assert refs[0]['session_id'] == OTHER and refs[0]['session_association'] == 'unavailable: session not retained'
    assert refs[0]['role'] == 'unknown'
    assert refs[1]['session_id'] is None and refs[1]['session_association'] == 'unknown: invalid session ID'
    assert 'unexpected-secret-role' not in json.dumps(view) and 'arbitrary-secret-reference' not in json.dumps(view)


def test_feedback_experience_bridge_is_finite_cited_and_body_only():
    from ops.pi import feedback
    from ops.pi.tests.test_feedback_reader import source_rows,WINDOW
    assert api()._CAPS.get('feedback')==50
    rows=source_rows();rows[0]['description']='删除按钮报错'
    data=bundle();data['window']={k:v.isoformat() for k,v in WINDOW.items()};data['collected_at']=data['window']['end']
    data['feedback']=feedback.make_feedback_snapshot(rows,WINDOW)['rows']
    report=api().analyze_writing_bundle(data);view=api().make_analysis_view(data,report)
    evidence=[item for item in view['evidence'] if item['category']=='experience']
    assert len(evidence)==1 and evidence[0]['source']['table']=='feedback'
    assert evidence[0]['source']['id']==data['feedback'][0]['id']
    assert evidence[0]['source']['path']=='description'
    assert len(report['quality_catalog'])==45 and all(v['availability']=='unknown' for v in report['quality_catalog'].values())
    assert 'contact' not in json.dumps(view) and 'attachments' not in json.dumps(view)
    data['feedback'][0]['contact']='private'
    with pytest.raises(ValueError):api().analyze_writing_bundle(data)
