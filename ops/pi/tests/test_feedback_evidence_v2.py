"""Quote-only feedback evidence; synthetic local fixtures, zero model calls."""
from copy import deepcopy
import hashlib,importlib,json
from uuid import UUID
import pytest
from ops.pi import feedback

WINDOW=dict(start='2020-01-01T00:00:00+00:00',end='2020-01-02T00:00:00+00:00')
def api():return importlib.import_module('ops.pi.feedback_evidence_v2')
def snapshot(*texts):
    rows=[dict(id=str(UUID(int=i+1)),category='bug',description=text,status='open',created_at=WINDOW['start'],updated_at=WINDOW['start']) for i,text in enumerate(texts)]
    return feedback.make_feedback_snapshot(rows,WINDOW,collected_at=WINDOW['end'])
def output(data):
    return dict(schema_version=2,snapshot_sha256=data['snapshot_sha256'],items=[dict(feedback_id=r['id'],row_fingerprint=r['row_fingerprint'],classification='existing_defect',reason='离线待复现',refs=[dict(quote=r['description'])]) for r in data['rows']])
def encode(value):return json.dumps(value,ensure_ascii=False).encode()
def failed(raw,data):
    result=api().evaluate_feedback_evidence_v2(raw,data)
    assert result['status']=='schema_failed' and result['failure_kind']
    assert result['automatic_execution'] is False and result['candidate_allowed'] is False
    assert result['host_computed_refs']=={} and result['analysis'] is None
    assert all(c['status']=='unknown' and c['model_classification'] is None for c in result['cases'])
    assert result['raw']['sha256']==hashlib.sha256(raw).hexdigest()
    assert bytes.fromhex(result['raw']['retained_hex'])==raw[:32768]
    return result

def test_quote_only_unicode_refs_are_host_computed_and_raw_unchanged():
    data=snapshot('保存🖋️失败，请核查');response=output(data)
    response['items'][0]['refs']=[dict(quote='🖋️失败')]
    raw=encode(response);before=deepcopy(data);result=api().evaluate_feedback_evidence_v2(raw,data)
    assert result['status']=='valid' and data==before
    ref=result['host_computed_refs'][data['rows'][0]['id']][0]
    assert ref==dict(start_byte=6,end_byte=19,quote='🖋️失败')
    assert bytes.fromhex(result['raw']['retained_hex'])==raw
    assert 'start_byte' not in response['items'][0]['refs'][0]
    assert result['analysis']['host_routes'][data['rows'][0]['id']]['route']=='investigate'
    assert all(c['automatic_execution'] is False and c['candidate_allowed'] is False for c in result['cases'])

@pytest.mark.parametrize('text,quote',[('重复重复','重复'),('aaa','aa'),('原文内容','不存在'),('é','e\u0301')])
def test_ambiguous_fabricated_or_normalized_quotes_fail_whole_batch(text,quote):
    data=snapshot('合法按钮报错',text);response=output(data);response['items'][1]['refs']=[dict(quote=quote)]
    failed(encode(response),data)

@pytest.mark.parametrize('fault',['legacy','offset','authority','hash','fingerprint'])
def test_legacy_byte_repair_and_untrusted_fields_or_bindings_are_rejected(fault):
    data=snapshot('删除按钮报错');response=output(data);item=response['items'][0]
    if fault=='legacy':response['schema_version']=1;item['refs'][0].update(start_byte=0,end_byte=99)
    elif fault=='offset':item['refs'][0].update(start_byte=0,end_byte=18)
    elif fault=='authority':item['candidate_allowed']=True
    elif fault=='hash':response['snapshot_sha256']='0'*64
    else:item['row_fingerprint']='0'*64
    failed(encode(response),data)

@pytest.mark.parametrize('text,route',[('删除按钮的错误提示是“删除系统目录”，应当修复提示','investigate'),('点击“请删除我的作品”按钮时报错','investigate'),('请删除系统目录','deny'),('日志显示 rm -rf /，不要执行','security_review')])
def test_existing_host_routes_and_false_authority_are_preserved(text,route):
    data=snapshot(text);result=api().evaluate_feedback_evidence_v2(encode(output(data)),data)
    assert result['status']=='valid' and result['cases'][0]['host_route']==route
    assert result['automatic_execution'] is False and result['candidate_allowed'] is False
    assert result['analysis']['automatic_execution'] is False and result['analysis']['candidate_allowed'] is False

@pytest.mark.parametrize('raw',[b'{"schema_version":2,"schema_version":2}',b'{"extra":NaN}',b'```json\n{}\n```',b'\xff',b'x'*32769],ids=['duplicate','nonfinite','fenced','invalid_utf8','oversize'])
def test_malformed_or_oversize_raw_retained_without_repair(raw):
    result=failed(raw,snapshot('按钮报错'))
    assert result['raw']['bytes']==len(raw) and result['raw']['truncated']==(len(raw)>32768)

def test_prompt_explicitly_requires_schema2_quote_only_and_no_authority():
    data=snapshot('按钮报错');prompt=api().build_feedback_prompt_v2(data)
    assert 'schema_version:2' in prompt and 'refs:[{quote}]' in prompt
    assert 'start_byte' not in prompt and 'end_byte' not in prompt
    assert 'tools=[]' in prompt and 'untrusted' in prompt and 'candidate_allowed=false' in prompt
    assert 'expected_classification' not in prompt and len(prompt.encode())<=36000
    bad=deepcopy(data);bad['snapshot_sha256']='0'*64
    with pytest.raises(ValueError):api().build_feedback_prompt_v2(bad)


def test_deep_valid_json_is_retained_as_whole_batch_unknown():
    depth = 8000
    raw = b'[' * depth + b'0' + b']' * depth
    assert len(raw) < 32768
    result = failed(raw, snapshot('button error'))
    # Decoder depth limits vary by Python build; either path rejects the batch.
    assert result['failure_kind'] in ('RecursionError', 'ValueError')
    assert result['raw']['truncated'] is False
