"""Pure paired feedback experiment; callback responses are explicitly MOCK."""
import importlib
from pathlib import Path
import pytest

IDENTITY={'provider':'offline-fixture','model':'synthetic','revision':'v1'}


def api():
    return importlib.import_module('ops.pi.feedback_evaluation')


def manifest():
    return api().build_batches(model_identity=IDENTITY,baseline_instruction='Classify the feedback.',
                               candidate_instruction='Distinguish requests from quoted reports and UI defects.')


def test_paired_batches_share_inputs_and_never_expose_expected_labels():
    first=manifest();second=manifest()
    assert first==second and len(first['batches'])==6
    assert first['changed_factor']=='prompt_only' and first['tools']==[]
    assert sum(len(b['snapshot']['rows']) for b in first['batches'])==30
    for batch in first['batches']:
        assert len(batch['snapshot']['rows'])<=5
        before,after=(batch['requests'][arm] for arm in ('baseline','candidate'))
        assert before['input_sha256']==after['input_sha256']==batch['snapshot']['snapshot_sha256']
        assert before['model_identity']==after['model_identity']==IDENTITY
        assert before['prompt_sha256']!=after['prompt_sha256']
        assert 'expected_classification' not in before['prompt'] and 'model_classification' not in after['prompt']
from copy import deepcopy
import json


def raw_result(batch, *, classification=None):
    labels={item['feedback_id']:item for item in batch['reference_labels']}
    return json.dumps(dict(schema_version=1,snapshot_sha256=batch['snapshot']['snapshot_sha256'],items=[dict(
        feedback_id=row['id'],row_fingerprint=row['row_fingerprint'],
        classification=classification or labels[row['id']]['expected_classification'],reason='离线参考分类',
        refs=[dict(start_byte=0,end_byte=len(row['description'].encode()),quote=row['description'])])
        for row in batch['snapshot']['rows']]),ensure_ascii=False)


def test_incorrect_model_labels_are_distinct_from_host_denial():
    experiment=manifest();outcomes=[]
    for batch in experiment['batches']:
        outcomes.extend(api().evaluate_batch(batch,raw_result(batch,classification='existing_defect'))['cases'])
    attacks=[r for r in outcomes if r['expected_classification']=='unsafe_request']
    assert attacks and all(r['model_classification']=='existing_defect' and r['host_route']=='deny' for r in attacks)
    assert all(r['automatic_execution'] is False and r['candidate_allowed'] is False for r in outcomes)


@pytest.mark.parametrize('fault',['invalid_json','duplicate_key','nonfinite','fenced','missing','quote','oversize'])
def test_schema_failure_retains_raw_without_repair(fault):
    batch=manifest()['batches'][0];raw=raw_result(batch)
    if fault=='invalid_json':raw='{broken'
    elif fault=='duplicate_key':raw='{"schema_version":1,"schema_version":1}'
    elif fault=='nonfinite':raw='{"extra":NaN}'
    elif fault=='fenced':raw='```json\n'+raw+'\n```'
    elif fault=='oversize':raw='x'*32769
    else:
        output=json.loads(raw)
        if fault=='missing':output['items']=[]
        else:output['items'][0]['refs'][0]['quote']='fabricated'
        raw=json.dumps(output)
    evaluated=api().evaluate_batch(batch,raw)
    assert evaluated['status']=='schema_failed'
    assert evaluated['raw']['bytes']==len(raw.encode())
    assert evaluated['raw']['sha256']==api().hashlib.sha256(raw.encode()).hexdigest()
    assert all(row['model_classification'] is None and row['status']=='unknown' for row in evaluated['cases'])
    assert len(bytes.fromhex(evaluated['raw']['retained_hex']))<=32768
    assert evaluated['raw']['truncated'] is (fault=='oversize')


def test_paired_exactly_once_metrics_and_mock_provenance():
    experiment=manifest();calls=[];byid={b['batch_id']:b for b in experiment['batches']}
    def invoke(request):
        calls.append(deepcopy(request))
        return api().ModelResponse(raw_result(byid[request['batch_id']],classification='existing_defect' if request['variant']=='candidate' else None),IDENTITY)
    report=api().run_paired(experiment,invoke,execution_kind='MOCK')
    assert len(calls)==12 and len({(r['batch_id'],r['variant']) for r in calls})==12
    assert all(r['tools']==[] and r['model_identity']==IDENTITY for r in calls)
    assert report['execution_kind']=='MOCK' and report['semantic_quality']=='unknown'
    baseline,candidate=(report['metrics'][v] for v in ('baseline','candidate'))
    assert baseline['classification']['correct']==30 and baseline['classification']['accuracy_valid']==1
    assert candidate['model_attack']['recognized']==0 and candidate['host_attack']['denied']==candidate['host_attack']['expected']
    assert candidate['classification']['correct']<30 and candidate['authority_always_false'] is True
    assert len(candidate['confusion'])==7 and all(len(v)==7 for v in candidate['confusion'].values())
    assert report['paired']['common_valid_case_pairs']==30 and report['paired']['classification_delta_on_common']<0


@pytest.mark.parametrize('fault',['transport','identity'])
def test_unresolved_transport_or_model_identity_stops_remaining_requests(fault):
    experiment=manifest();calls=[]
    def invoke(request):
        calls.append(request)
        if fault=='transport':raise RuntimeError('secret-must-not-leak')
        return api().ModelResponse(raw_result(experiment['batches'][0]),{**IDENTITY,'revision':'other'})
    report=api().run_paired(experiment,invoke,execution_kind='MOCK')
    assert len(calls)==1
    assert report['attempted_requests']==1 and report['not_run_requests']==11
    assert 'secret-must-not-leak' not in json.dumps(report)
    assert report['metrics']['baseline']['classification']['unknown']==30
    assert report['paired']['common_valid_case_pairs']==0


def test_schema_failures_are_counted_unknown_without_retry():
    experiment=manifest();calls=[]
    def invoke(request):
        calls.append(request);return api().ModelResponse('```bad```',IDENTITY)
    report=api().run_paired(experiment,invoke,execution_kind='MOCK')
    assert len(calls)==12 and report['schema_failed_requests']==12
    assert report['metrics']['baseline']['classification']['valid']==0
    assert report['metrics']['baseline']['classification']['unknown']==30
    assert report['metrics']['baseline']['classification']['accuracy_valid'] is None
    assert report['metrics']['baseline']['model_attack']['unknown']>0


@pytest.mark.parametrize('fault',['labels','snapshot','request_identity','prompt','source','tools'])
def test_manifest_tamper_denied_before_callback(fault):
    experiment=manifest()
    if fault=='labels':experiment['batches'][0]['reference_labels'][0]['expected_classification']='unsafe_request'
    elif fault=='snapshot':experiment['batches'][0]['snapshot']['rows'][0]['description']='foreign'
    elif fault=='request_identity':experiment['batches'][0]['requests']['candidate']['model_identity']['revision']='other'
    elif fault=='prompt':experiment['batches'][0]['requests']['candidate']['prompt']='different'
    elif fault=='source':experiment['source_sha256']['feedback.py']='0'*64
    else:experiment['tools']=['shell']
    with pytest.raises(ValueError):api().run_paired(experiment,lambda r:pytest.fail('tamper reached callback'),execution_kind='MOCK')


def test_unfrozen_identity_identical_prompts_and_unknown_provenance_rejected():
    with pytest.raises(ValueError):api().build_batches(model_identity={**IDENTITY,'api_key':'secret'},baseline_instruction='a',candidate_instruction='b')
    with pytest.raises(ValueError):api().build_batches(model_identity=IDENTITY,baseline_instruction='same',candidate_instruction='same')
    with pytest.raises(ValueError):api().run_paired(manifest(),lambda r:pytest.fail('unlabeled invocation'),execution_kind='unknown')
