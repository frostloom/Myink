"""Retrospective import reads fixed receipts, never executes model code."""
import importlib
import json
from pathlib import Path
from copy import deepcopy
import pytest
from ops.pi.audit import digest,encoded
from ops.pi.tests.test_audit import record


def module():return importlib.import_module('ops.pi.audit_import')


@pytest.fixture
def packet(tmp_path,monkeypatch):
    tmp_path.chmod(0o700);job=tmp_path/'job';job.mkdir(mode=0o700)
    state=tmp_path/'manager.sqlite';billing=tmp_path/'fees.sqlite'
    state.write_bytes(b'original-manager');billing.write_bytes(b'original-fees')
    for p in (state,billing):p.chmod(0o600)
    files={
      'bundle/selection-output/result.json':dict(verified=True,new_attempts=1,new_unknown=0,known_cost_microyuan=3,proposal=dict(reason='Numeric conversion mismatch; token=private-value')),
      'development-output/result.json':dict(verified=True,new_attempts=2,new_unknown=0,known_cost_microyuan=5,candidate_sha256='b'*64),
      'development-output/phase-verification.json':dict(verified=True,mode='ACTUAL',verified_tool_calls=['call-one','call-two']),
      'development-output/check-2-receipt.json':dict(tests=18,failures=0,errors=0,skipped=0,passed=True),
      'development-entry-review.json':dict(verified=True),
    }
    review=dict(schema='pi-server-owner-acceptance-review-v1',source='independent_review',verified=True,result='approved',task_id='task-1',candidate_sha256='b'*64,source_sha256='c'*64,gold_sha256='d'*64,source_commit='a'*40,tests=18,baseline_failures=7,new_unknown=0,new_model_attempts=3,new_known_cost_microyuan=8,product_adoption=False,dispatch_count=1,dispatch_elapsed_ms=123.25,containers_absent=True,policy_restored=True,original_history_unchanged=True)
    review['evidence_sha256']={name:__import__('hashlib').sha256(encoded(value)).hexdigest() for name,value in files.items()}
    cycle=dict(schema_version=1,operation_id='maintenance:one',status='done',evidence=dict(verified=True,mode='ACTUAL',released=False,next_action='review_candidate',result=files['development-output/result.json']))
    files['bundle/cycle-output/result.json']=cycle;files['final-acceptance-review.json']=review
    for name,value in files.items():
        p=job/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(encoded(value));p.chmod(0o600)
    tools=[]
    for i,name in enumerate(['read_source','run_check']):
        tools.append(dict(operation_id='tool:dev:call-'+('one' if i==0 else 'two'),kind='controlled_tool',status='blocked' if i==0 else 'done',payload=json.dumps(dict(tool=name,input_hash='e'*64,binding='f'*64)),evidence=json.dumps(dict(tool=name,input_hash='e'*64,binding='f'*64,reason='token=private-value' if i==0 else None))))
    task=dict(operation_id='manager:task:task-1',status='done',payload=dict(task_id='task-1'))
    dispatch=dict(status='done',evidence=dict(verified=True,mode='ACTUAL',released=False,cycle_result_sha256=digest(cycle),elapsed_ms=123.25))
    rows={'manager:task:task-1:dispatch':dispatch}
    # The existing manager validator is independently exercised by its own suite.
    import ops.pi.manager as manager
    monkeypatch.setattr(manager,'_snapshot',lambda *a:(state,billing,rows,[task],dict(original=True)))
    import ops.pi.development_inputs as inputs
    snap=dict(operations=[],events=[])
    tool_events=[dict(kind='intent',payload=json.dumps(dict(operation_id=t['operation_id']))) for t in tools]
    monkeypatch.setattr(inputs,'ledger_snapshot',lambda p:dict(operations=tools,events=tool_events) if Path(p).name=='tools.sqlite' else deepcopy(snap))
    return dict(state=state,billing=billing,task_id='task-1',job_root=job,audit_path=tmp_path/'audit.sqlite'),files,dispatch


def test_retrospective_import_is_idempotent_private_and_preserves_originals(packet):
    args,files,_=packet;before={k:args[k].read_bytes() for k in ('state','billing')}
    first=module().import_manager_run(**args);second=module().import_manager_run(**args)
    assert first['event_count']==second['event_count'] and first['canonical_unchanged']
    from ops.pi.audit import AuditStore
    events=AuditStore(args['audit_path']).events();assert len(events)==first['event_count']
    text=json.dumps(events);assert 'private-value' not in text
    assert all(e['occurred_at'] is None for e in events)
    assert [e['status'] for e in events if e['kind']=='tool']==['blocked','passed']
    assert next(e for e in events if e['kind']=='development')['details']['model_requests']==3
    assert events[-1]['status']=='no_release'
    assert all(args[k].read_bytes()==v for k,v in before.items())


@pytest.mark.parametrize('bad',['stale','mode','unverified','candidate','unknown','count','timing'])
def test_unverified_or_stale_receipts_fail_before_audit_append(packet,bad):
    args,files,dispatch=packet
    if bad=='stale':
        p=args['job_root']/'development-output/result.json';p.write_bytes(p.read_bytes()+b' ')
    elif bad=='mode':dispatch['evidence']['mode']='SIMULATED'
    elif bad=='unverified':dispatch['evidence']['verified']=False
    else:
        review=files['final-acceptance-review.json']
        if bad=='candidate':review['candidate_sha256']='e'*64
        elif bad=='unknown':review['new_unknown']=1
        elif bad=='count':review['new_model_attempts']=True
        else:review['dispatch_elapsed_ms']=999
        (args['job_root']/'final-acceptance-review.json').write_bytes(encoded(review))
    with pytest.raises((ValueError,OSError)):module().import_manager_run(**args)
    assert not args['audit_path'].exists()


def test_diff_is_bound_to_frozen_trees_and_keeps_real_line_counts(tmp_path):
    from ops.pi.development_inputs import tree_hash
    source=tmp_path/'source';candidate=tmp_path/'candidate'
    for root in (source,candidate):(root/'src').mkdir(parents=True)
    (source/'src/example.py').write_text('first\nold\n')
    (candidate/'src/example.py').write_text('first\nnew\nextra\n')
    expected=dict(source_sha256=tree_hash(source),candidate_sha256=tree_hash(candidate))
    assert module().snapshot_changes(source,candidate,expected)==[dict(path='src/example.py',category='production',added=2,deleted=1)]
    (candidate/'src/example.py').write_text('changed again\n')
    with pytest.raises(ValueError):module().snapshot_changes(source,candidate,expected)
