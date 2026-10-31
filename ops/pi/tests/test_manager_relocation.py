"""Synthetic original-manager relocation; no model transport or candidate import."""
from pathlib import Path
import importlib
import json
import shutil
import sqlite3
import pytest
from ops.pi import manager,state_custody as custody
from ops.pi.ledger import Ledger
from ops.pi.development_inputs import ledger_snapshot,read_json
from ops.pi.tests.test_manager import queue,entry,pack,config_file,enqueue,request_for,result


@pytest.fixture
def api():
    try:return importlib.import_module('ops.pi.manager_relocation')
    except ModuleNotFoundError:pytest.fail('manager relocation API missing')


@pytest.fixture
def retired(queue):
    state,billing,*_=queue
    enqueue(queue,'done')
    assert manager.run(state,billing,mode='SIMULATED',executor=result)['dispatched']==1
    enqueue(queue,'blocked')
    def blocked(p,**kw):
        value=result(p);value['status']='blocked';return value
    assert manager.run(state,billing,mode='SIMULATED',executor=blocked)['status']=='blocked'
    enqueue(queue,'cancelled')
    manager.cancel_task(state,billing,'cancelled','synthetic retired task',mode='SIMULATED')
    return queue


def copy_db(source,target):
    assert not target.exists()
    with sqlite3.connect(source) as a,sqlite3.connect(target) as b:a.backup(b)
    target.chmod(0o600)


def frozen(queue,tmp_path,name='target'):
    state,billing,*_=queue
    target=tmp_path/name;target.mkdir(mode=0o700)
    destination=dict(host_sha256=custody.native_host_sha256(),ledger_path=str(target/'billing.sqlite'))
    proof=custody.freeze(Ledger(billing,existing=True),transfer_id='manager-transfer-'+name,destination=destination,authorization_reference='synthetic:handoff')
    return target,proof


def prepared(api,queue,tmp_path):
    state,billing,*_=queue;target,proof=frozen(queue,tmp_path)
    report=api.prepare(state,billing,destination_state=target/'manager.sqlite',root=tmp_path/'bundle',
        mode='SIMULATED',authorization_reference='synthetic:source-quiescence')
    manifest=Path(report['manifest_path'])
    copy_db(billing,target/'billing.sqlite')
    custody.activate(Ledger(target/'billing.sqlite',existing=True),transfer_id=proof['transfer_id'],
        snapshot_sha256=proof['snapshot_sha256'],authorization_reference='synthetic:target-billing')
    copy_db(Path(report['manager_path']),target/'manager.sqlite')
    return target,manifest


def apply(api,target,manifest):
    return api.apply(target/'manager.sqlite',target/'billing.sqlite',manifest,mode='SIMULATED',
                     authorization_reference='synthetic:target-manager')


def test_legacy_copy_without_relocation_still_rejects_billing_drift(retired,tmp_path):
    state,billing,*_=retired
    target=tmp_path/'plain';target.mkdir(mode=0o700)
    copy_db(state,target/'manager.sqlite');copy_db(billing,target/'billing.sqlite')
    with pytest.raises(ValueError,match='identity'):
        manager.status(target/'manager.sqlite',target/'billing.sqlite',mode='SIMULATED')


@pytest.mark.parametrize('operation',['run','enqueue'])
def test_frozen_source_manager_refuses_before_any_new_effect(retired,tmp_path,operation):
    state,billing,*_=retired
    request=request_for(retired,'never')
    frozen(retired,tmp_path)
    before=ledger_snapshot(state);fees=ledger_snapshot(billing)
    with pytest.raises(ValueError,match='custody'):
        if operation=='run':manager.run(state,billing,mode='SIMULATED',executor=lambda *a,**k:pytest.fail('replay'))
        else:manager.enqueue(state,billing,'never',request,manager.file_hash(request),mode='SIMULATED')
    assert ledger_snapshot(state)==before and ledger_snapshot(billing)==fees
    assert manager.status(state,billing,mode='SIMULATED')['metrics']['registered_tasks']==3


def test_relocation_keeps_original_header_tasks_prefix_and_cold_no_replay(api,retired,tmp_path):
    state,billing,*_=retired;original=ledger_snapshot(state);oldstatus=manager.status(state,billing,mode='SIMULATED')
    target,manifest=prepared(api,retired,tmp_path);fees=ledger_snapshot(target/'billing.sqlite')
    assert apply(api,target,manifest)['relocated']
    after=ledger_snapshot(target/'manager.sqlite');rows={r['operation_id']:r for r in after['operations']}
    assert all(rows[r['operation_id']]==r for r in original['operations'])
    assert after['events'][:len(original['events'])]==original['events']
    status=manager.status(target/'manager.sqlite',target/'billing.sqlite',mode='SIMULATED')
    assert status['tasks']==oldstatus['tasks'] and status['metrics']==oldstatus['metrics']
    for _ in range(3):
        value=manager.run(target/'manager.sqlite',target/'billing.sqlite',mode='SIMULATED',executor=lambda *a,**k:pytest.fail('old replay'))
        assert value['dispatched']==0
    assert ledger_snapshot(target/'billing.sqlite')==fees
    assert ledger_snapshot(state)==original


@pytest.mark.parametrize('state_kind',['queued','pending_registration','uncertain'])
def test_source_nonretired_or_unresolved_refuses_export_without_changes(api,queue,tmp_path,state_kind):
    state,billing,*_=queue
    if state_kind=='pending_registration':
        enqueue(queue,'completed')
        manager.run(state,billing,mode='SIMULATED',executor=result)
        _,_,rows,_,_=manager._snapshot(state,billing,'SIMULATED')
        payload=dict(rows['manager:task:completed']['payload'],task_id='unfinished')
        manager.Ledger(state).intent('manager:task:unfinished','manager_task',payload)
    else:
        enqueue(queue)
        if state_kind=='uncertain':
            def lost(*a,**kw):raise RuntimeError('synthetic lost receipt')
            assert manager.run(state,billing,mode='SIMULATED',executor=lost)['status']=='uncertain'
    target,_=frozen(queue,tmp_path)
    before=ledger_snapshot(state)
    with pytest.raises(ValueError):
        api.prepare(state,billing,destination_state=target/'manager.sqlite',root=tmp_path/'bundle',
            mode='SIMULATED',authorization_reference='synthetic:source')
    assert ledger_snapshot(state)==before and not (tmp_path/'bundle').exists()


def test_prepare_requires_frozen_billing_and_explicit_authorization(api,retired,tmp_path):
    state,billing,*_=retired;before=ledger_snapshot(state)
    with pytest.raises(ValueError):
        api.prepare(state,billing,destination_state=tmp_path/'target/manager.sqlite',root=tmp_path/'bundle',
            mode='SIMULATED',authorization_reference='synthetic:source')
    assert ledger_snapshot(state)==before and not (tmp_path/'bundle').exists()


@pytest.mark.parametrize('tamper',['snapshot','transfer','destination','mode'])
def test_wrong_manifest_cannot_rebind_original_manager(api,retired,tmp_path,tamper):
    target,manifest=prepared(api,retired,tmp_path)
    value=read_json(manifest)
    if tamper=='snapshot':value['manager_snapshot_sha256']='0'*64
    if tamper=='transfer':value['transfer_id']='foreign-transfer'
    if tamper=='destination':value['destination_state']=str(target/'foreign.sqlite')
    if tamper=='mode':value['mode']='ACTUAL'
    manifest.write_text(json.dumps(value));before=ledger_snapshot(target/'manager.sqlite')
    with pytest.raises(ValueError):apply(api,target,manifest)
    assert ledger_snapshot(target/'manager.sqlite')==before


def test_active_manager_copy_wrong_path_refuses_even_same_billing(api,retired,tmp_path):
    target,manifest=prepared(api,retired,tmp_path);apply(api,target,manifest)
    copy_db(target/'manager.sqlite',target/'manager-copy.sqlite')
    with pytest.raises(ValueError):manager.status(target/'manager-copy.sqlite',target/'billing.sqlite',mode='SIMULATED')


def test_relocation_reapplication_cannot_append_another_owner(api,retired,tmp_path):
    target,manifest=prepared(api,retired,tmp_path);apply(api,target,manifest)
    before=ledger_snapshot(target/'manager.sqlite')
    with pytest.raises(ValueError):apply(api,target,manifest)
    assert ledger_snapshot(target/'manager.sqlite')==before

from ops.pi.tests.test_selection_abandonment import stopped,approved
from ops.pi import selection_abandonment as recovery


def abandoned_bundle(api,stopped,tmp_path):
    p,c,review=approved(stopped);recovery.apply(p,review)
    state,billing=Path(c['state_path']),Path(c['billing_path'])
    target,proof=frozen((state,billing,p,None),tmp_path)
    report=api.prepare(state,billing,destination_state=target/'manager.sqlite',root=tmp_path/'bundle',
        mode='ACTUAL',authorization_reference='synthetic:abandoned-source')
    copy_db(billing,target/'billing.sqlite')
    custody.activate(Ledger(target/'billing.sqlite',existing=True),transfer_id=proof['transfer_id'],
        snapshot_sha256=proof['snapshot_sha256'],authorization_reference='synthetic:target')
    copy_db(Path(report['manager_path']),target/'manager.sqlite')
    return state,billing,target,Path(report['manifest_path'])


def test_abandoned_original_facts_and_bytes_survive_without_old_absolute_files(api,stopped,tmp_path,monkeypatch):
    source_state,source_bill,target,manifest=abandoned_bundle(api,stopped,tmp_path)
    value=read_json(manifest);original_raw={}
    for old in value['archives']:
        original=Path(old);original_raw[old]=original.read_bytes()
        original.rename(original.with_name(original.name+'.retained'))
    calls=[];original=recovery.validate_resolution
    def verify(task,dispatch,row,state,billing,**kwargs):
        calls.append((state,billing,kwargs))
        return original(task,dispatch,row,state,billing,**kwargs)
    monkeypatch.setattr(recovery,'validate_resolution',verify)
    assert api.apply(target/'manager.sqlite',target/'billing.sqlite',manifest,mode='ACTUAL',
        authorization_reference='synthetic:target')['relocated']
    status=manager.status(target/'manager.sqlite',target/'billing.sqlite')
    assert status['tasks'][0]['state']=='uncertain' and status['tasks'][0]['resolution']=='abandoned'
    assert status['metrics']['outcomes']['done']==0 and status['metrics']['unresolved_dispatches']==0
    assert all(a==source_state and b==source_bill and c['artifact_paths'] for a,b,c in calls)
    for old,item in value['archives'].items():assert (manifest.parent/item['relative_path']).read_bytes()==original_raw[old]
    fees=ledger_snapshot(target/'billing.sqlite')
    assert manager.run(target/'manager.sqlite',target/'billing.sqlite',seconds=5)['dispatched']==0
    assert ledger_snapshot(target/'billing.sqlite')==fees


@pytest.mark.parametrize('tamper',['missing','corrupt','hardlink','permission','partial'])
def test_archive_defects_prevent_relocation_without_destination_mutation(api,stopped,tmp_path,tamper):
    _,_,target,manifest=abandoned_bundle(api,stopped,tmp_path)
    value=read_json(manifest);old=next(iter(value['archives']));item=value['archives'][old]
    archive=manifest.parent/item['relative_path']
    if tamper=='missing':archive.rename(archive.with_name(archive.name+'.retained'))
    if tamper=='corrupt':archive.write_text('{}')
    if tamper=='hardlink':archive.with_name(archive.name+'.alias').hardlink_to(archive)
    if tamper=='permission':archive.chmod(0o644)
    if tamper=='partial':
        del value['archives'][old];manifest.write_text(json.dumps(value))
    before=ledger_snapshot(target/'manager.sqlite')
    with pytest.raises((ValueError,OSError)):
        api.apply(target/'manager.sqlite',target/'billing.sqlite',manifest,mode='ACTUAL',authorization_reference='synthetic:target')
    assert ledger_snapshot(target/'manager.sqlite')==before


def test_new_foreign_billing_request_refused_after_relocation(api,retired,tmp_path):
    target,manifest=prepared(api,retired,tmp_path);apply(api,target,manifest)
    request=request_for(retired,'foreign')
    before=ledger_snapshot(target/'manager.sqlite')
    with pytest.raises(ValueError):
        manager.enqueue(target/'manager.sqlite',target/'billing.sqlite','foreign',request,manager.file_hash(request),mode='SIMULATED')
    assert ledger_snapshot(target/'manager.sqlite')==before


def test_new_current_billing_task_can_run_after_relocation(api,retired,tmp_path,monkeypatch):
    target,manifest=prepared(api,retired,tmp_path);apply(api,target,manifest)
    request=request_for(retired,'fresh');c=read_json(request)
    selection=read_json(c['selection_config_path']);selection['ledger_path']=str(target/'billing.sqlite')
    selection['root']=str(target/'selection-fresh')
    sp=Path(c['selection_config_path']);sp.write_text(json.dumps(selection))
    templates=read_json(c['templates_path'])
    for entry in templates.values():
        tp=Path(entry['path']);v=read_json(tp);v['ledger_path']=str(target/'billing.sqlite');v['root']=str(target/'development-fresh');tp.write_text(json.dumps(v))
    c['root']=str(target/'cycle-fresh');c['control_ledger_path']=str(target/'control-fresh.sqlite')
    request.write_text(json.dumps(c))
    # Same explicit SIMULATED package reader as existing cross-process manager tests.
    def inspect(p):
        v=read_json(p);return v,read_json(v['selection_config_path']),[],read_json(v['templates_path'])
    monkeypatch.setattr(manager,'inspect_cycle',inspect)
    manager.enqueue(target/'manager.sqlite',target/'billing.sqlite','fresh',request,manager.file_hash(request),mode='SIMULATED')
    fees=ledger_snapshot(target/'billing.sqlite')
    run=manager.run(target/'manager.sqlite',target/'billing.sqlite',mode='SIMULATED',executor=result)
    assert run['tasks']==['fresh'] and run['dispatched']==1
    assert ledger_snapshot(target/'billing.sqlite')==fees


def inject_relocation(target,value,archive_root,*,events='valid'):
    from ops.pi.ledger import _json
    payload=dict(value,archive_root=str(archive_root),destination_authorization_reference='synthetic:target');op='manager:relocation:'+value['transfer_id']
    evidence=dict(verified=True,binding=manager.digest(payload))
    l=manager.Ledger(target/'manager.sqlite',existing=True)
    with l.transaction() as db:
        db.execute('INSERT INTO operations VALUES (?,?,?,?,?,1)',(op,'manager_relocation',_json(payload),'done',_json(evidence)))
        if events!='missing':
            intent=dict(operation_id=op,kind='manager_relocation',payload=payload,schema_version=1)
            receipt=dict(operation_id=op,status='done',evidence=evidence,schema_version=1)
            if events=='wrong_intent':intent['payload']=dict(payload,source_state='/foreign/manager.sqlite')
            if events=='wrong_receipt':receipt['evidence']=dict(verified=False)
            for kind,event in [('intent',intent),('receipt',receipt)]:
                db.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',(kind,_json(event)))


@pytest.mark.parametrize('events',['missing','wrong_intent','wrong_receipt'])
def test_relocation_event_mirrors_required_on_every_recovery(api,retired,tmp_path,events):
    target,manifest=prepared(api,retired,tmp_path)
    inject_relocation(target,read_json(manifest),manifest.parent,events=events)
    before=ledger_snapshot(target/'manager.sqlite')
    with pytest.raises(ValueError):manager.status(target/'manager.sqlite',target/'billing.sqlite',mode='SIMULATED')
    assert ledger_snapshot(target/'manager.sqlite')==before


def test_archive_root_cannot_cover_current_manager_or_billing(api,retired,tmp_path):
    target,manifest=prepared(api,retired,tmp_path)
    conflicting=target/'manifest.json';shutil.copyfile(manifest,conflicting);conflicting.chmod(0o600)
    before=ledger_snapshot(target/'manager.sqlite')
    with pytest.raises(ValueError):apply(api,target,conflicting)
    assert ledger_snapshot(target/'manager.sqlite')==before


def test_source_prefix_cannot_hide_a_runnable_task_on_recovery(api,retired,tmp_path):
    target,manifest=prepared(api,retired,tmp_path)
    l=manager.Ledger(target/'manager.sqlite',existing=True)
    raw=ledger_snapshot(target/'manager.sqlite')
    source=next(r for r in raw['operations'] if r['kind']=='manager_task')
    payload=dict(Ledger._decode(source['payload']),task_id='hidden')
    l.intent('manager:task:hidden','manager_task',payload)
    from ops.pi.contracts import Receipt
    l.finish(Receipt('manager:task:hidden','done',dict(verified=True,binding=manager.digest(payload))))
    snap=ledger_snapshot(target/'manager.sqlite');v=read_json(manifest)
    v.update(manager_snapshot_sha256=snap['sha256'],source_operation_ids=sorted(r['operation_id'] for r in snap['operations']),event_hwm=snap['events'][-1]['id'])
    inject_relocation(target,v,manifest.parent)
    with pytest.raises(ValueError):manager.status(target/'manager.sqlite',target/'billing.sqlite',mode='SIMULATED')


def test_destination_operator_authorization_is_persisted(api,retired,tmp_path):
    target,manifest=prepared(api,retired,tmp_path)
    api.apply(target/'manager.sqlite',target/'billing.sqlite',manifest,mode='SIMULATED',
              authorization_reference='synthetic:distinct-destination-operator')
    snap=ledger_snapshot(target/'manager.sqlite')
    record=next(r for r in snap['operations'] if r['kind']=='manager_relocation')
    assert Ledger._decode(record['payload'])['destination_authorization_reference']=='synthetic:distinct-destination-operator'


@pytest.mark.parametrize('omission',['header_operation','last_source_event'])
def test_declared_source_prefix_must_be_complete_at_transition(api,retired,tmp_path,omission):
    target,manifest=prepared(api,retired,tmp_path);v=read_json(manifest);snap=ledger_snapshot(target/'manager.sqlite')
    if omission=='header_operation':
        v['source_operation_ids'].remove('manager:identity')
    else:v['event_hwm']-=1
    prefix=dict(operations=[r for r in snap['operations'] if r['operation_id'] in v['source_operation_ids']],
                events=[r for r in snap['events'] if r['id']<=v['event_hwm']],limits=None)
    v['manager_snapshot_sha256']=manager.digest(prefix)
    inject_relocation(target,v,manifest.parent)
    with pytest.raises(ValueError):manager.status(target/'manager.sqlite',target/'billing.sqlite',mode='SIMULATED')


def test_sequence_drift_refuses_and_rolls_back_complete_transition(api,retired,tmp_path):
    target,manifest=prepared(api,retired,tmp_path);state=target/'manager.sqlite'
    before=ledger_snapshot(state);sequence=before['events'][-1]['id']+100
    with sqlite3.connect(state) as db:db.execute("UPDATE sqlite_sequence SET seq=? WHERE name='events'",(sequence,))
    db.close()
    assert ledger_snapshot(state)==before
    with pytest.raises(ValueError,match='transition'):apply(api,target,manifest)
    assert ledger_snapshot(state)==before
    with sqlite3.connect(state) as db:assert db.execute("select seq from sqlite_sequence where name='events'").fetchone()[0]==sequence


@pytest.mark.parametrize('source_kind',['other_path','same_path'])
def test_same_transfer_foreign_billing_freeze_cannot_attach_original_manager(api,retired,tmp_path,source_kind):
    state,billing,*_=retired;target,proof=frozen(retired,tmp_path)
    export=api.prepare(state,billing,destination_state=target/'manager.sqlite',root=tmp_path/'bundle',
        mode='SIMULATED',authorization_reference='synthetic:original-source')
    if source_kind=='same_path':
        billing.rename(billing.with_name(billing.name+'.original-retained'));foreign=billing
    else:foreign=tmp_path/'unrelated.sqlite'
    foreign.touch(mode=0o600);l=Ledger(foreign)
    fake=custody.freeze(l,transfer_id=proof['transfer_id'],destination=proof['destination'],authorization_reference='synthetic:foreign-source')
    copy_db(foreign,target/'billing.sqlite')
    custody.activate(Ledger(target/'billing.sqlite',existing=True),transfer_id=fake['transfer_id'],
        snapshot_sha256=fake['snapshot_sha256'],authorization_reference='synthetic:foreign-activation')
    copy_db(Path(export['manager_path']),target/'manager.sqlite')
    before=ledger_snapshot(target/'manager.sqlite')
    with pytest.raises(ValueError):apply(api,target,Path(export['manifest_path']))
    assert ledger_snapshot(target/'manager.sqlite')==before


def test_recovery_rechecks_original_billing_freeze_not_only_transfer_name(api,retired,tmp_path):
    target,manifest=prepared(api,retired,tmp_path);apply(api,target,manifest)
    transfer=read_json(manifest)['transfer_id'];state=target/'manager.sqlite';before=ledger_snapshot(state)
    foreign=tmp_path/'unrelated.sqlite';foreign.touch(mode=0o600);l=Ledger(foreign)
    fake=custody.freeze(l,transfer_id=transfer,destination=dict(host_sha256=custody.native_host_sha256(),ledger_path=str(target/'billing.sqlite')),
                        authorization_reference='synthetic:foreign-source')
    (target/'billing.sqlite').rename(target/'original-billing-retained.sqlite')
    copy_db(foreign,target/'billing.sqlite')
    custody.activate(Ledger(target/'billing.sqlite',existing=True),transfer_id=transfer,snapshot_sha256=fake['snapshot_sha256'],
                     authorization_reference='synthetic:foreign-activation')
    with pytest.raises(ValueError):manager.status(state,target/'billing.sqlite',mode='SIMULATED')
    assert ledger_snapshot(state)==before


def test_foreign_destination_is_logical_not_this_hosts_symlink_namespace(api,retired,tmp_path):
    state,billing,*_=retired
    local=tmp_path/'local-only';local.mkdir(mode=0o700)
    alias=tmp_path/'foreign-namespace';alias.symlink_to(local,target_is_directory=True)
    destination_state=alias/'state/manager.sqlite';destination_billing=alias/'state/billing.sqlite'
    custody.freeze(Ledger(billing,existing=True),transfer_id='foreign-namespace-transfer',
        destination=dict(host_sha256='b'*64,ledger_path=str(destination_billing)),authorization_reference='synthetic:foreign-host')
    before=ledger_snapshot(state)
    report=api.prepare(state,billing,destination_state=destination_state,root=tmp_path/'bundle',
        mode='SIMULATED',authorization_reference='synthetic:source')
    value=read_json(report['manifest_path'])
    assert value['destination_state']==str(destination_state) and value['destination_billing']==str(destination_billing)
    assert ledger_snapshot(state)==before
    # Actual host operations still reject local symlink paths.
    with pytest.raises((ValueError,OSError)):
        manager.status(destination_state,destination_billing,mode='SIMULATED')


def test_custody_inspection_uses_only_immutable_read_connections(api,retired,tmp_path,monkeypatch):
    target,manifest=prepared(api,retired,tmp_path)
    billing=target/'billing.sqlite';before=ledger_snapshot(billing)
    original=sqlite3.connect
    connections=[]
    def readonly(database,*args,**kwargs):
        assert isinstance(database,str) and 'mode=ro' in database and 'immutable=1' in database,'custody inspection must not open writable SQLite'
        connections.append(database)
        return original(database,*args,**kwargs)
    monkeypatch.setattr(sqlite3,'connect',readonly)
    latest,activation=api._custody(billing,transfer_id='manager-transfer-target')
    assert latest==activation and latest['phase']=='active'
    assert connections and ledger_snapshot(billing)==before
