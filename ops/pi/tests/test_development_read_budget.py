"""Durable ASCII source caps are host-only and never execute candidate code."""
from copy import deepcopy
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
import pytest
from ops.pi.tools import ControlledTools,canonical
from ops.pi.tests.test_tools import setup,call,approve,patch
from ops.pi.tests.test_budget import policy


def read(b,c,id='read',path='app/worker.py'):
    return call(b,c,'read_source',dict(path=path,start_line=1,end_line=1),id)


def test_ascii_cap_rejects_chinese_that_fits_utf8(tmp_path,policy):
    b,c,r,_=setup(tmp_path,policy,source_read_limits=(16,32));(r/'app/worker.py').write_text('汉汉汉\n')
    q=read(b,c);assert q.status=='blocked' and 'ASCII' in q.evidence['reason'] and 'text' not in q.evidence
    assert b.lookup('read','read_source',dict(path='app/worker.py',start_line=1,end_line=1),asdict(q))


def test_cumulative_caps_across_files_and_duplicates(tmp_path,policy):
    b,c,_,_=setup(tmp_path,policy,source_read_limits=(20,32))
    first=read(b,c,'one');assert first.status=='done'
    second=read(b,c,'two','app/other.py');assert second.status=='done'
    third=read(b,c,'three');assert third.status=='blocked' and 'session' in third.evidence['reason']
    assert third.evidence.get('text') is None


def test_exact_replay_does_not_spend_source_twice(tmp_path,policy):
    b,c,_,_=setup(tmp_path,policy,source_read_limits=(20,30));a=read(b,c,'one');assert read(b,c,'one')==a
    assert read(b,c,'two').status=='done';assert read(b,c,'three').status=='blocked'


def test_recreated_broker_and_patch_cannot_reset_budget(tmp_path,policy):
    b,c,_,_=setup(tmp_path,policy,source_read_limits=(20,20));approve(b,c)
    assert read(b,c).status=='done';assert call(b,c,'apply_patch',patch(b,c),'patch').status=='done'
    b2=ControlledTools(b.ledger,policy,capability=c,scope_token='scoped-only',identity=b.identity,baseline=b.baseline,metrics={},source_read_limits=(20,20))
    assert read(b2,c,'new-version').status=='blocked'


def test_rejected_read_does_not_spend_source_and_fewer_lines_can_retry(tmp_path,policy):
    b,c,r,_=setup(tmp_path,policy,source_read_limits=(20,30));(r/'app/worker.py').write_text('x'*20+'\n'+'ok\n')
    assert read(b,c).status=='blocked'
    q=call(b,c,'read_source',dict(path='app/worker.py',start_line=2,end_line=2),'retry')
    assert q.status=='done' and q.evidence['text']=='ok\n' and q.evidence['source_ascii_remaining']==30-len(canonical('ok\n').encode())


def test_budget_not_selectable_by_model(tmp_path,policy):
    b,c,_,_=setup(tmp_path,policy,source_read_limits=(20,30))
    q=call(b,c,'read_source',dict(path='app/worker.py',start_line=1,end_line=1,source_read_limits=[100000,100000]))
    assert q.status=='blocked'


@pytest.mark.parametrize('limits',[(True,30),(0,30),(30,20),[20,30],(20.0,30),(20,True)])
def test_invalid_host_limits_rejected(tmp_path,policy,limits):
    with pytest.raises(ValueError,match='source read'):setup(tmp_path,policy,source_read_limits=limits)


def test_parallel_brokers_cannot_double_spend_source(tmp_path,policy):
    b,c,_,_=setup(tmp_path,policy,source_read_limits=(20,20))
    b2=ControlledTools(b.ledger,policy,capability=c,scope_token='scoped-only',identity=b.identity,baseline=b.baseline,metrics={},source_read_limits=(20,20))
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda x:read(x[0],c,x[1]),[(b,'one'),(b2,'two')]))
    assert sum(r.status=='done' for r in results)==1
    loser=[b,b2][next(i for i,r in enumerate(results) if r.status!='done')]
    retry=read(loser,c,'after-contention')
    assert retry.status=='blocked' and 'session' in retry.evidence['reason']


def test_exact_ascii_boundary_is_inclusive(tmp_path,policy):
    b,c,r,_=setup(tmp_path,policy,source_read_limits=(20,20));(r/'app/worker.py').write_text('x'*16+'\n')
    q=read(b,c);assert q.status=='done' and q.evidence['source_ascii_remaining']==0
    assert read(b,c,'next').status=='blocked'


def test_budget_rejection_is_valid_verified_provider_history(tmp_path,policy):
    from ops.pi.model_gateway import _validate
    from ops.pi.tools import tool_definitions,PHASE_TOOLS
    from ops.pi.tests.test_budget import request as model_request
    b,c,r,_=setup(tmp_path,policy,source_read_limits=(16,32));(r/'app/worker.py').write_text('汉汉汉\n')
    args=dict(path='app/worker.py',start_line=1,end_line=1);q=read(b,c)
    body=model_request()|dict(tools=tool_definitions('develop'),messages=[
        dict(role='assistant',content=[dict(type='tool_use',id='read',name='read_source',input=args)]),
        dict(role='user',content=[dict(type='tool_result',tool_use_id='read',content=[dict(type='text',text=canonical(asdict(q)))],is_error=True)])])
    original=deepcopy(body);_validate(body,policy,PHASE_TOOLS['develop'],blocked_tool_lookup=b.lookup);assert body==original


def test_uncapped_legacy_broker_retains_existing_behavior(tmp_path,policy):
    b,c,r,_=setup(tmp_path,policy);(r/'app/worker.py').write_text('汉'*100+'\n')
    assert read(b,c).status=='done'
