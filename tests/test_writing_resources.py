import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi import HTTPException
from myink.models.writing_resource import WritingResource, WritingResourceRevision, PersonalWritingResource, ProjectWritingResources, WritingResourcePublication
from myink import writing_resources as service

@pytest.fixture
def db():
    from myink.models.platform import PlatformConfiguration
    engine = create_engine('sqlite://')
    PlatformConfiguration.__table__.create(engine)
    for table in (WritingResource.__table__, WritingResourceRevision.__table__, PersonalWritingResource.__table__, ProjectWritingResources.__table__, WritingResourcePublication.__table__):
        table.create(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session

def resource(db):
    return service.create_resource(db, dict(name='original', kind='style', source='builtin', body={'profile': {'voice': 'one'}}))

def test_publication_history_and_draft_privacy(db):
    r = resource(db)
    service.publish(db, r.id, 0, 'first')
    service.update_resource(db, r.id, 1, dict(name='draft', source='private draft', body={'profile': {'voice': 'two'}}))
    assert service.catalog(db)[0]['name'] == 'original'
    service.publish(db, r.id, 2, 'second')
    service.publish(db, r.id, 3, 'undo', version=1)
    assert service.catalog(db)[0]['body']['profile']['voice'] == 'one'
    assert len(service.revisions(db, r.id)) == 2
    assert r.generation == 4
    with pytest.raises(HTTPException) as e:
        service.publish(db, r.id, 3, '')
    assert e.value.status_code == 409

def test_project_snapshot_adopt_dismiss_and_private(db):
    r = resource(db)
    service.publish(db, r.id, 0, '')
    pid = uuid.uuid4()
    uid = uuid.uuid4()
    assert service.project_snapshot(db, pid)['configured'] is False
    snap = service.set_selection(db, pid, uid, 0, [dict(origin='platform', resource_id=r.id)])
    captured = service.capture_task_resources(db, pid)
    service.update_resource(db, r.id, 1, dict(name='two', source='builtin', body={'profile': {'voice': 'two'}}))
    service.publish(db, r.id, 2, '')
    assert service.updates(db, pid)[0]['target_generation'] == 3
    service.dismiss(db, pid, [dict(resource_id=r.id, target_generation=3)])
    assert service.updates(db, pid)[0]['dismissed']
    adopted = service.adopt(db, pid, 1, [dict(resource_id=r.id, target_generation=3)])
    assert adopted['revision'] == 2
    assert captured == dict(snap, role_prompts={}, legacy_role_supplements={}, reference_library=[])
    personal = service.create_resource(db, dict(name='mine', kind='style', source='mine', body={'profile': {}}), user_id=uid)
    assert len(service.catalog(db)) == 1
    with pytest.raises(HTTPException):
        service.set_selection(db, uuid.uuid4(), uuid.uuid4(), 0, [dict(origin='personal', resource_id=personal.id)])

def test_rollback_update_and_override_protection(db):
    from sqlalchemy import select
    r = resource(db)
    service.publish(db, r.id, 0, 'one')
    pid = uuid.uuid4()
    uid = uuid.uuid4()
    service.set_selection(db, pid, uid, 0, [dict(origin='platform', resource_id=r.id)])
    service.update_resource(db, r.id, 1, dict(name='two', source='x', body={'profile': {'voice': 'two'}}))
    service.publish(db, r.id, 2, 'two')
    service.adopt(db, pid, 1, [dict(resource_id=r.id, target_generation=3)])
    service.publish(db, r.id, 3, 'rollback', version=1)
    update = service.updates(db, pid)[0]
    assert update['target_version'] == 1 and update['action'] == 'rollback'
    with pytest.raises(HTTPException) as exc:
        service.adopt(db, pid, 2, [dict(resource_id=r.id, target_generation=3)])
    assert exc.value.status_code == 409
    assert service.project_snapshot(db, pid)['revision'] == 2
    service.adopt(db, pid, 2, [dict(resource_id=r.id, target_generation=4)])
    assert len(db.scalars(select(WritingResourcePublication)).all()) == 3
    protected = service.set_selection(db, pid, uid, 3, [dict(origin='platform', resource_id=r.id, personal_override=True, body={'profile': {'voice': 'personal'}})])
    service.publish(db, r.id, 4, 'new')
    assert service.updates(db, pid) == []
    with pytest.raises(HTTPException):
        service.adopt(db, pid, 4, [dict(resource_id=r.id, target_generation=5)])
    assert service.project_snapshot(db, pid) == protected

def test_initialize_is_idempotent_and_preserves_edits(db, monkeypatch):
    import myink.writing_resource_seed as seed
    data = dict(id='builtin:test', name='source', kind='style', source='builtin', body={'profile': {}})
    monkeypatch.setattr(seed, 'builtin_resources', lambda: [data])
    service.initialize_builtin_resources(db)
    service.update_resource(db, 'builtin:test', 1, dict(name='edited', source='admin', body={'profile': {'voice': 'mine'}}))
    service.initialize_builtin_resources(db)
    assert service.resource(db, 'builtin:test').name == 'edited'
    assert service.catalog(db)[0]['name'] == 'source'

def test_ordinary_selection_edit_preserves_existing_release(db):
    r = resource(db)
    service.publish(db, r.id, 0, 'one')
    pid = uuid.uuid4()
    uid = uuid.uuid4()
    original = service.set_selection(db, pid, uid, 0, [dict(origin='platform', resource_id=r.id)])
    service.update_resource(db, r.id, 1, dict(name='new', source='x', body={'profile': {'voice': 'new'}}))
    service.publish(db, r.id, 2, 'new')
    kept = service.set_selection(db, pid, uid, 1, [dict(origin='platform', resource_id=r.id)])
    assert kept['selections'] == original['selections']
    assert service.updates(db, pid)[0]['target_generation'] == 3


def test_explicit_save_refreshes_personal_resource_preserving_overrides(db):
    uid = uuid.uuid4()
    pid = uuid.uuid4()
    private = service.create_resource(
        db,
        dict(name="mine", kind="style", source="mine", body={"profile": {"voice": "one"}}),
        user_id=uid,
    )
    item = dict(origin="personal", resource_id=private.id)
    original = service.set_selection(db, pid, uid, 0, [item])
    captured = service.capture_task_resources(db, pid)
    service.update_resource(
        db, private.id, 1,
        dict(name="edited", source="mine", body={"profile": {"voice": "two"}}),
        user_id=uid,
    )
    assert service.project_snapshot(db, pid) == original
    refreshed = service.set_selection(db, pid, uid, 1, [item])
    assert refreshed["selections"][0]["version"] == 2
    assert refreshed["selections"][0]["name"] == "edited"
    assert refreshed["selections"][0]["body"] == {"profile": {"voice": "two"}}
    assert captured == dict(original, role_prompts={}, legacy_role_supplements={}, reference_library=[])
    override = dict(item, personal_override=True, body={"profile": {"voice": "project"}})
    protected = service.set_selection(db, pid, uid, 2, [override])
    service.update_resource(
        db, private.id, 2,
        dict(name="again", source="mine", body={"profile": {"voice": "three"}}),
        user_id=uid,
    )
    kept = service.set_selection(db, pid, uid, 3, [item])
    assert kept["selections"] == protected["selections"]


def test_archive_hides_catalog_but_preserves_existing_snapshots_and_history(db):
    row = resource(db)
    service.publish(db, row.id, 0, 'initial')
    pid, uid = uuid.uuid4(), uuid.uuid4()
    original = service.set_selection(db, pid, uid, 0, [dict(origin='platform', resource_id=row.id)])
    service.update_resource(db, row.id, 1, dict(status='archived'))
    assert service.catalog(db) == []
    assert service.project_snapshot(db, pid) == original
    assert len(service.revisions(db, row.id)) == 1
    with pytest.raises(HTTPException) as exc:
        service.set_selection(db, uuid.uuid4(), uid, 0, [dict(origin='platform', resource_id=row.id)])
    assert exc.value.status_code == 409
    service.publish(db, row.id, 2, 'available again')
    assert service.catalog(db)[0]['id'] == row.id
    assert len(service.revisions(db, row.id)) == 2
    assert service.project_snapshot(db, pid) == original


def test_archived_platform_does_not_lock_existing_private_override(db):
    row = resource(db)
    service.publish(db, row.id, 0, '')
    pid, uid = uuid.uuid4(), uuid.uuid4()
    item = dict(origin='platform', resource_id=row.id, personal_override=True,
                body={'profile': {'voice': 'mine'}})
    before = service.set_selection(db, pid, uid, 0, [item])
    service.update_resource(db, row.id, 1, {'status': 'archived'})
    item['body'] = {'profile': {'voice': 'edited privately'}}
    saved = service.set_selection(db, pid, uid, 1, [item])
    assert saved['selections'][0]['body']['profile']['voice'] == 'edited privately'
    assert saved['selections'][0]['version'] == before['selections'][0]['version']
    with pytest.raises(HTTPException) as exc:
        service.set_selection(db, uuid.uuid4(), uid, 0, [item])
    assert exc.value.status_code == 409


def test_snapshot_total_size_is_bounded(db):
    selections = [{'body': {'text': 'x' * 250_000}} for _ in range(10)]
    with pytest.raises(HTTPException) as exc:
        service.save_snapshot(db, uuid.uuid4(), 0, selections)
    assert exc.value.status_code == 422


def test_automatic_library_freezes_revision_and_excludes_support(db):
    from myink.writing_resource_runtime import bind_resources
    from myink.workflow.tools import execute_tool
    import json
    row = service.create_resource(db, dict(name='characters.md', kind='reference', source='original', body={'files':[{'path':'characters.md','content':'OLD'}, {'path':'README.md','content':'technical'}]}))
    service.publish(db, row.id, 0, '')
    old = service.capture_task_resources(db, None)
    assert old['reference_library'][0]['files'] == [{'path':'characters.md'}]
    assert 'OLD' not in json.dumps(old)
    assert service.catalog(db) == []
    with pytest.raises(HTTPException) as exc:
        service.set_selection(db, uuid.uuid4(), uuid.uuid4(), 0, [{'origin':'platform','resource_id':row.id}])
    assert exc.value.detail == 'REFERENCE_IS_AUTOMATIC'
    service.update_resource(db, row.id, 1, {'source':'draft', 'body':{'files':[{'path':'characters.md','content':'NEW'}]}})
    assert service.capture_task_resources(db, None)['reference_library'] == old['reference_library']
    service.publish(db, row.id, 2, '')
    new = service.capture_task_resources(db, None)
    for snap, text in [(old,'OLD'), (new,'NEW')]:
        with bind_resources(snap):
            assert json.loads(execute_tool(db,None,'read_genre_reference',{'path':'characters.md'}))['content'] == text
            assert 'error' in json.loads(execute_tool(db,None,'read_genre_reference',{'path':'README.md'}))
            assert 'error' in json.loads(execute_tool(db,None,'read_genre_reference',{'path':'../characters.md'}))
    service.update_resource(db,row.id,3,{'status':'archived'})
    assert service.capture_task_resources(db,None)['reference_library'] == []
    with bind_resources(old):
        assert json.loads(execute_tool(db,None,'read_genre_reference',{'path':'characters.md'}))['content']=='OLD'


def test_automatic_reference_preserves_existing_and_personal_choices(db):
    from myink.writing_resource_runtime import bind_resources, reference_read
    uid, pid = uuid.uuid4(), uuid.uuid4()
    row = service.create_resource(db, dict(name='creative',kind='reference',source='builtin',body={'files':[{'path':'same.md','content':'PLATFORM'}]}))
    service.publish(db,row.id,0,'')
    previous = dict(resource_id=row.id,origin='platform',name=row.name,kind='reference',version=1,generation=1,personal_override=False,body={'files':[{'path':'same.md','content':'EXISTING'}]})
    service.save_snapshot(db,pid,0,[previous])
    service.set_selection(db,pid,uid,1,[{'origin':'platform','resource_id':row.id}])
    with bind_resources(service.capture_task_resources(db,pid)):
        assert reference_read('same.md',db=db)['content']=='EXISTING'
    private = service.create_resource(db,dict(name='private',kind='reference',source='mine',body={'files':[{'path':'same.md','content':'PRIVATE'}]}),user_id=uid)
    service.set_selection(db,pid,uid,2,[{'origin':'personal','resource_id':private.id}])
    with bind_resources(service.capture_task_resources(db,pid)):
        assert reference_read('same.md',db=db)['content']=='PRIVATE'


def test_unpublished_reference_never_enters_library(db):
    service.create_resource(db,dict(name='creative',kind='reference',source='builtin',body={'files':[{'path':'x.md','content':'DRAFT'}]}))
    assert service.capture_task_resources(db,None)['reference_library']==[]
