"""Finite machine-boundary tests. Check callbacks are simulated, not B7 acceptance."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import importlib
import json
import os
from pathlib import Path
import pytest
from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger
from ops.pi.tests.test_budget import policy
from ops.pi.tests.test_plans import candidate, baseline


def module():
    assert (Path(__file__).parents[1] / 'tools.py').is_file(), 'controlled broker missing'
    return importlib.import_module('ops.pi.tools')


def setup(tmp_path, policy, phase='develop', plan=None, **kwargs):
    m=module(); root=tmp_path/'candidate'; root.mkdir()
    (root/'app').mkdir(); (root/'app/worker.py').write_bytes(b'value = 1\n')
    (root/'app/other.py').write_bytes(b'other = 1\n')
    (root/'.env').write_text('UPSTREAM_KEY=private-key', encoding='utf-8')
    plan=plan or candidate()
    ledger=Ledger(tmp_path/'ledger.sqlite')
    cap=m.ToolCapability('session-1','candidate-1',root,'base-1','host',1,phase,
                         ('app/worker.py','app/other.py','.env'), plan)
    identity={'owner':'host','generation':1,'candidate_id':'candidate-1','base':'base-1'}
    broker=m.ControlledTools(ledger, policy, capability=cap, scope_token='scoped-only',
                             identity=lambda:identity, baseline=baseline(),
                             metrics={'availability':'partial','operations':{},'quality_catalog':{}}, **kwargs)
    return broker, cap, root, identity


def call(broker, cap, name, args=None, call_id='call-1'):
    return broker.handle_tool(name, {'call_id':call_id,'input':args or {}}, cap)


def approve(broker, cap):
    ledger=broker.ledger; plan=cap.plan
    fields=dict(source='independent_review',verified=True,result='approved',reviewer='reviewer-1',
                plan_hash=plan.plan_hash,base=cap.base,candidate_id=cap.candidate_id,
                owner=cap.owner,generation=cap.generation)
    ledger.intent('review-1','independent_review',{'plan_hash':plan.plan_hash})
    ledger.finish(Receipt('review-1','done',fields))
    broker.approve_plan(plan.plan_hash,'review-1')


def patch(broker, cap, old='value = 1', new='value = 2'):
    return dict(plan_hash=cap.plan.plan_hash,base=cap.base,candidate_hash=broker.candidate_hash(),
                edits=[{'path':'app/worker.py','source_hash':hashlib.sha256(b'value = 1\n').hexdigest(),
                        'old':old,'new':new}])


def test_read_source_has_real_hash_and_positions_and_denies_forged_capability(tmp_path,policy):
    broker,cap,root,_=setup(tmp_path,policy)
    receipt=call(broker,cap,'read_source',{'path':'app/worker.py','start_line':1,'end_line':1})
    assert receipt.status=='done' and receipt.evidence['text']=='value = 1\n'
    assert receipt.evidence['source_hash']==hashlib.sha256(b'value = 1\n').hexdigest()
    assert call(broker,replace(cap,owner='model'),'read_source',{'path':'app/worker.py','start_line':1,'end_line':1},'forged').status=='blocked'
    assert call(broker,asdict(cap),'candidate_status',call_id='dict').status=='blocked'


@pytest.mark.parametrize('path',['.env','backup/file.py','../app/worker.py','app\\worker.py','app/worker.py:stream','APP/worker.py','app//worker.py','ops/pi/policy.py','app/worker.py.','app/worker.py '])
def test_secret_protected_and_ambiguous_paths_denied(tmp_path,policy,path):
    broker,cap,_,_=setup(tmp_path,policy)
    assert call(broker,cap,'read_source',dict(path=path,start_line=1,end_line=1)).status=='blocked'


def test_hardlinks_and_secret_content_denied(tmp_path,policy):
    broker,cap,root,_=setup(tmp_path,policy,secret_values=('private-key',))
    (root/'app/worker.py').write_text('private-key')
    assert call(broker,cap,'read_source',dict(path='app/worker.py',start_line=1,end_line=1)).status=='blocked'
    (root/'app/worker.py').unlink(); os.link(root/'app/other.py',root/'app/worker.py')
    assert call(broker,cap,'read_source',dict(path='app/worker.py',start_line=1,end_line=1),'hardlink').status=='blocked'


def test_patch_requires_separate_host_review_not_model_self_approval(tmp_path,policy):
    broker,cap,root,_=setup(tmp_path,policy)
    args=patch(broker,cap)
    assert call(broker,cap,'apply_patch',args).status=='blocked'
    args['approval']={'verified':True}
    assert call(broker,cap,'apply_patch',args,'self').status=='blocked'
    assert (root/'app/worker.py').read_text()=='value = 1\n'


def test_allowed_patch_is_durable_idempotent_and_collision_denied(tmp_path,policy):
    broker,cap,root,_=setup(tmp_path,policy); approve(broker,cap)
    args=patch(broker,cap)
    result=call(broker,cap,'apply_patch',args)
    assert result.status=='done' and (root/'app/worker.py').read_text()=='value = 2\n'
    assert call(broker,cap,'apply_patch',deepcopy(args))==result
    changed=deepcopy(args); changed['edits'][0]['new']='value = 3'
    assert call(broker,cap,'apply_patch',changed).status=='blocked'
    assert (root/'app/worker.py').read_text()=='value = 2\n'
    row=Ledger(broker.ledger.path).get(result.operation_id)
    assert row['status']=='done' and row['evidence']==result.evidence


@pytest.mark.parametrize('fault',['base','candidate_hash','source_hash','protected','undeclared','overscope','second_bad'])
def test_all_patch_edits_and_cumulative_scope_validated_before_mutation(tmp_path,policy,fault):
    broker,cap,root,_=setup(tmp_path,policy); approve(broker,cap); args=patch(broker,cap)
    if fault in ('base','candidate_hash'): args[fault]='wrong'
    elif fault=='source_hash': args['edits'][0]['source_hash']='0'*64
    elif fault=='protected': args['edits'][0]['path']='ops/pi/policy.py'
    elif fault=='undeclared': args['edits'][0]['path']='app/other.py'
    elif fault=='overscope': args['edits'][0]['new']='line\n'*301
    else: args['edits'].append({'path':'app/other.py','source_hash':'0'*64,'old':'other','new':'changed'})
    assert call(broker,cap,'apply_patch',args).status=='blocked'
    assert (root/'app/worker.py').read_text()=='value = 1\n'


def test_generation_change_denies_even_receipt_replay(tmp_path,policy):
    broker,cap,_,identity=setup(tmp_path,policy)
    assert call(broker,cap,'candidate_status').status=='done'
    identity['generation']=2
    assert call(broker,cap,'candidate_status').status=='blocked'


def test_durable_pending_intent_never_reexecutes_after_crash(tmp_path,policy):
    broker,cap,root,_=setup(tmp_path,policy); approve(broker,cap); args=patch(broker,cap)
    def crash(*a): raise KeyboardInterrupt()
    broker._execute=crash
    with pytest.raises(KeyboardInterrupt): call(broker,cap,'apply_patch',args)
    broker._execute=lambda *a: pytest.fail('pending tool replayed')
    assert call(broker,cap,'apply_patch',args).status=='uncertain'
    assert (root/'app/worker.py').read_text()=='value = 1\n'


def test_proposed_plan_is_unapproved_and_candidate_status_reads_real_receipts(tmp_path,policy):
    broker,cap,_,_=setup(tmp_path,policy,phase='plan')
    proposal=call(broker,cap,'propose_plan',{'plan':json.loads(json.dumps(asdict(cap.plan)))})
    assert proposal.status=='done' and proposal.evidence['approved'] is False
    status=call(broker,cap,'candidate_status',call_id='status')
    assert proposal.operation_id in [r['operation_id'] for r in status.evidence['receipts']]
    assert status.evidence['published'] is False


def test_check_only_fixed_callback_and_missing_containment_is_blocked(tmp_path,policy):
    broker,cap,_,_=setup(tmp_path,policy); approve(broker,cap)
    args={'check_id':'unit','candidate_hash':broker.candidate_hash(),'plan_hash':cap.plan.plan_hash}
    result=call(broker,cap,'run_check',args)
    assert result.status=='blocked' and 'isolated' in result.evidence['reason']
    assert call(broker,cap,'run_check',{**args,'command':'whoami'},'shell').status=='blocked'


def test_fixed_simulated_check_receipt_cannot_claim_other_candidate(tmp_path,policy):
    def check(snapshot): return Receipt('simulated-check','done',dict(simulated=True,result='passed',**snapshot))
    broker,cap,_,_=setup(tmp_path,policy,checks={'unit':check}); approve(broker,cap)
    args={'check_id':'unit','candidate_hash':broker.candidate_hash(),'plan_hash':cap.plan.plan_hash}
    assert call(broker,cap,'run_check',args).evidence['check']['simulated'] is True
    broker.checks['unit']=lambda snapshot:Receipt('forged','done',dict(result='passed'))
    assert call(broker,cap,'run_check',args,'badcheck').status=='blocked'


@pytest.mark.parametrize('name,args',[('bash',{'command':'echo 1'}),('nested_model',{}),('observe_metrics',{'sql':'SELECT 1'}),('candidate_status',{'published':True}),('read_source',{'path':'app/worker.py','root':'/etc'}),('propose_plan',{'plan':{},'capability':{'phase':'develop'}})])
def test_unknown_tools_fields_sql_shell_and_permission_injection_denied(tmp_path,policy,name,args):
    broker,cap,_,_=setup(tmp_path,policy)
    assert call(broker,cap,name,args).status=='blocked'


def test_scoped_rpc_retrieves_authoritative_capability_and_rejects_extra_fields(tmp_path,policy):
    broker,cap,_,_=setup(tmp_path,policy)
    body={'tool':'candidate_status','call_id':'call','arguments':{}}
    assert broker.dispatch('scoped-only',body).status=='done'
    assert broker.dispatch('wrong',body).status=='blocked'
    assert broker.dispatch('scoped-only',{**body,'capability':asdict(cap)}).status=='blocked'


def test_restart_preserves_frozen_base_and_pending_never_replays(tmp_path,policy):
    broker,cap,root,identity=setup(tmp_path,policy); approve(broker,cap)
    args=patch(broker,cap); receipt=call(broker,cap,'apply_patch',args)
    assert receipt.status=='done'
    restarted=module().ControlledTools(Ledger(broker.ledger.path),policy,capability=cap,scope_token='scoped-only',
        identity=lambda:identity,baseline=baseline(),metrics={})
    assert restarted._base_sources['app/worker.py']==b'value = 1\n'
    assert call(restarted,cap,'apply_patch',args)==receipt


def test_patch_write_crash_is_uncertain_and_not_executed_twice(tmp_path,policy,monkeypatch):
    broker,cap,root,_=setup(tmp_path,policy); approve(broker,cap);args=patch(broker,cap)
    def fail(*args):raise OSError('simulated disk failure')
    monkeypatch.setattr(module().os,'replace',fail)
    result=call(broker,cap,'apply_patch',args)
    assert result.status=='uncertain'
    assert call(broker,cap,'apply_patch',args)==result
    assert (root/'app/worker.py').read_bytes()==b'value = 1\n'


def test_parallel_mutators_serialize_and_stale_candidate_loses(tmp_path,policy):
    from concurrent.futures import ThreadPoolExecutor
    broker,cap,root,_=setup(tmp_path,policy);approve(broker,cap);args=patch(broker,cap)
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts=list(pool.map(lambda i:call(broker,cap,'apply_patch',args,'parallel-'+str(i)),range(2)))
    assert sorted(r.status for r in receipts)==['blocked','done']
    assert (root/'app/worker.py').read_bytes()==b'value = 2\n'


def test_plan_proposal_replay_is_exact_after_durable_json_normalization(tmp_path,policy):
    broker,cap,_,_=setup(tmp_path,policy,phase='plan')
    args={'plan':json.loads(json.dumps(asdict(cap.plan)))}
    result=call(broker,cap,'propose_plan',args)
    assert result.status=='done' and call(broker,cap,'propose_plan',args)==result


def test_fixed_metrics_are_copied_and_never_model_selected(tmp_path,policy):
    from ops.pi.tests.test_writing_analysis import fixture
    view,_=fixture();broker,cap,_,_=setup(tmp_path,policy,phase='analysis')
    broker.metrics={'writing_view':deepcopy(view),'operations':{'errors':{'availability':'unknown'}}}
    result=call(broker,cap,'observe_metrics')
    assert result.evidence['snapshot']['writing_view']['evidence'][0]['evidence_index']==0
    assert broker.metrics['writing_view']==view and result.evidence['semantic_quality']=='unknown'


def test_binary_source_and_null_patch_are_denied(tmp_path,policy):
    broker,cap,root,_=setup(tmp_path,policy);approve(broker,cap)
    args=patch(broker,cap);args['edits'][0]['new']='value = 2'+chr(0)
    assert call(broker,cap,'apply_patch',args).status=='blocked'
    (root/'app/worker.py').write_bytes(b'value = 1'+bytes([0]))
    assert call(broker,cap,'read_source',{'path':'app/worker.py','start_line':1,'end_line':1},'binary').status=='blocked'


def test_pending_host_approval_never_grants_patch_after_crash(tmp_path,policy):
    broker,cap,root,_=setup(tmp_path,policy)
    operation='tool-approval:'+broker._binding+':'+cap.plan.plan_hash
    broker.ledger.intent(operation,'tool_approval',{'plan_hash':cap.plan.plan_hash,'binding':broker._binding,'review_id':'pending-review'})
    assert call(broker,cap,'apply_patch',patch(broker,cap)).status=='blocked'
    assert (root/'app/worker.py').read_bytes()==b'value = 1\n'


@pytest.mark.parametrize('second_rename_fails', [True, False], ids=['partial-rename-and-unlink-fail', 'successful-renames-and-stat-fail'])
def test_patch_cleanup_failure_never_records_mutated_candidate_as_blocked(tmp_path, policy, monkeypatch, second_rename_fails):
    plan = candidate(files=('app/worker.py', 'app/other.py'))
    broker, cap, root, _ = setup(tmp_path, policy, plan=plan)
    approve(broker, cap)
    args = patch(broker, cap)
    args['edits'].append(dict(path='app/other.py',
        source_hash=hashlib.sha256(b'other = 1\n').hexdigest(), old='other = 1', new='other = 2'))
    real_replace, real_unlink, real_exists = os.replace, Path.unlink, Path.exists
    def replace_file(source, target):
        if second_rename_fails and Path(target).name == 'other.py':
            raise OSError('second rename failed')
        return real_replace(source, target)
    def unlink_file(path, *args, **kwargs):
        if path.name.startswith('.controlled-'):
            raise OSError('remaining temporary cleanup failed')
        return real_unlink(path, *args, **kwargs)
    def exists_file(path):
        if not second_rename_fails and path.name.startswith('.controlled-'):
            raise OSError('cleanup stat failed after successful renames')
        return real_exists(path)
    monkeypatch.setattr(module().os, 'replace', replace_file)
    monkeypatch.setattr(Path, 'unlink', unlink_file)
    monkeypatch.setattr(Path, 'exists', exists_file)
    result = call(broker, cap, 'apply_patch', args)
    assert (root/'app/worker.py').read_bytes() == b'value = 2\n'
    assert (root/'app/other.py').read_bytes() == (b'other = 1\n' if second_rename_fails else b'other = 2\n')
    assert result.status == 'uncertain'
    persisted = Ledger(broker.ledger.path).get(result.operation_id)
    assert persisted['status'] == 'uncertain' and persisted['evidence'] == result.evidence
    monkeypatch.setattr(module().os, 'replace', lambda *args: pytest.fail('uncertain patch replayed'))
    assert call(broker, cap, 'apply_patch', args) == result
