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
    from myink.models import Project, ProjectSettings
    engine = create_engine('sqlite://')
    PlatformConfiguration.__table__.create(engine)
    Project.__table__.create(engine)
    ProjectSettings.__table__.create(engine)
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
    captured = service.capture_task_resources(db, pid)
    assert service.updates(db, pid)[0]['target_generation'] == 5
    assert service.project_snapshot(db, pid) == protected
    adopted = service.adopt(db, pid, 4, [dict(resource_id=r.id, target_generation=5)])
    assert adopted['selections'][0]['body'] == {'profile': {'voice': 'two'}}
    assert adopted['selections'][0]['personal_override'] is False
    assert captured['selections'][0]['body'] == {'profile': {'voice': 'personal'}}

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


def test_selection_save_preserves_personal_version_until_explicit_adoption(db):
    uid = uuid.uuid4()
    pid = uuid.uuid4()
    from myink.models import Project
    db.add(Project(id=pid,user_id=uid,title="book",genre="玄幻",form="long"))
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
    assert refreshed["selections"] == original["selections"]
    refreshed = service.adopt(db,pid,2,[{"resource_id":private.id,"target_generation":2}])
    assert refreshed["selections"][0]["version"] == 2
    assert refreshed["selections"][0]["name"] == "edited"
    assert refreshed["selections"][0]["body"] == {"profile": {"voice": "two"}}
    assert captured == dict(original, role_prompts={}, legacy_role_supplements={}, reference_library=[])
    override = dict(item, personal_override=True, body={"profile": {"voice": "project"}})
    protected = service.set_selection(db, pid, uid, 3, [override])
    service.update_resource(
        db, private.id, 2,
        dict(name="again", source="mine", body={"profile": {"voice": "three"}}),
        user_id=uid,
    )
    kept = service.set_selection(db, pid, uid, 4, [item])
    assert kept["selections"] == protected["selections"]
    assert service.updates(db, pid)[0]["target_generation"] == 3
    adopted = service.adopt(db, pid, 5, [{"resource_id": private.id, "target_generation": 3}])
    assert adopted["selections"][0]["origin"] == "personal"
    assert adopted["selections"][0]["body"] == {"profile": {"voice": "three"}}
    assert adopted["selections"][0]["personal_override"] is False
    assert captured == dict(original, role_prompts={}, legacy_role_supplements={}, reference_library=[])


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
    service.set_selection(db,pid,uid,1,[])
    with bind_resources(service.capture_task_resources(db,pid)):
        assert reference_read('same.md',db=db)['content']=='EXISTING'
    private = service.create_resource(db,dict(name='private',kind='reference',source='mine',body={'files':[{'path':'same.md','content':'PRIVATE'}]}),user_id=uid)
    service.save_snapshot(db,pid,2,[dict(previous,resource_id=private.id,origin='personal',body=private.body)])
    with bind_resources(service.capture_task_resources(db,pid)):
        assert reference_read('same.md',db=db)['content']=='PRIVATE'


def test_unpublished_reference_never_enters_library(db):
    service.create_resource(db,dict(name='creative',kind='reference',source='builtin',body={'files':[{'path':'x.md','content':'DRAFT'}]}))
    assert service.capture_task_resources(db,None)['reference_library']==[]


def test_linked_personal_copy_sync_publication_cas_and_ownership(db):
    row = resource(db)
    service.publish(db, row.id, 0, '')
    uid = uuid.uuid4()
    private = service.copy_platform(db, row.id, uid, 1)
    assert service.out(private)['source_resource_id'] == row.id
    assert private.source_generation == 1
    service.update_resource(db, private.id, 1, {'body': {'profile': {'voice': 'personal'}}}, user_id=uid)
    service.update_resource(db, row.id, 1, {'body': {'profile': {'voice': 'draft'}}})
    with pytest.raises(HTTPException):
        service.sync_personal(db, private.id, uid, 2, 2, True)
    service.publish(db, row.id, 2, '')
    for generation, target, ack in [(1, 3, True), (2, 1, True), (2, 3, False)]:
        with pytest.raises(HTTPException):
            service.sync_personal(db, private.id, uid, generation, target, ack)
    with pytest.raises(HTTPException):
        service.sync_personal(db, private.id, uuid.uuid4(), 2, 3, True)
    assert private.body['profile']['voice'] == 'personal'
    service.sync_personal(db, private.id, uid, 2, 3, True)
    assert private.body['profile']['voice'] == 'draft'
    assert private.source_generation == 3
    assert private.generation == 3


def test_copy_automatic_role_is_linked_and_role_immutable(db):
    seed = dict(name='writer', kind='role_prompt', source='builtin', body={'role':'writer','templates':{'system_write':'Write'}})
    rid = 'role-prompt:writer'
    row = service.create_resource(db, seed, rid=rid)
    service.publish(db, row.id, 0, '')
    uid = uuid.uuid4()
    private = service.copy_platform(db, row.id, uid, 1)
    assert private.kind == 'role_prompt'
    assert any(x['id'] == rid for x in service.catalog(db, include_automatic=True))
    with pytest.raises(HTTPException):
        service.update_resource(db, private.id, 1, {'body': dict(private.body, role='writer' if private.body['role'] != 'writer' else 'planner')}, uid)


def test_automatic_project_genre_and_personal_roles_are_frozen(db):
    from myink.models import Project, ProjectSettings
    uid, pid = uuid.uuid4(), uuid.uuid4()
    db.add(Project(id=pid, user_id=uid, title='book', genre='玄幻', form='long'))
    db.add(ProjectSettings(project_id=pid, genre_pack={'source_id':'xiuxian'}))
    genre = service.create_resource(db, dict(name='genre',kind='genre',source='builtin',body={'catalog_id':'xiuxian','fields':{}}))
    role = service.create_resource(db, dict(name='role',kind='role_prompt',source='builtin',body={'role':'writer','templates':{'system_write':'original'}}),rid='role-prompt:writer')
    for row in [genre,role]:
        service.publish(db,row.id,0,'')
    personal = service.copy_platform(db, role.id, uid, 1, body={'role':'writer','templates':{'system_write':'PERSONAL'}})
    snapshot = service.set_selection(db,pid,uid,0,[])
    assert [s['kind'] for s in snapshot['selections']] == ['genre','role_prompt']
    first = service.capture_task_resources(db,pid)
    assert first['role_prompts']['writer']['body']['templates']['system_write'] == 'PERSONAL'
    service.update_resource(db, personal.id,1,{'body':{'role':'writer','templates':{'system_write':'NEW'}}},uid)
    assert service.capture_task_resources(db,pid) == first
    pending = service.updates(db,pid)
    assert pending[0]['resource_id'] == personal.id
    service.adopt(db,pid,1,[{'resource_id':personal.id,'target_generation':2}])
    assert service.capture_task_resources(db,pid)['role_prompts']['writer']['body']['templates']['system_write'] == 'NEW'
    with pytest.raises(HTTPException):
        service.set_selection(db,pid,uid,2,[{'origin':'platform','resource_id':genre.id}])


def test_capture_freezes_automatic_resources_for_legacy_book_without_selecting(db):
    from myink.models import Project
    uid, pid = uuid.uuid4(), uuid.uuid4()
    db.add(Project(id=pid,user_id=uid,title='legacy',genre='unknown',form='long'))
    role = service.create_resource(db, dict(name='role',kind='role_prompt',source='builtin',body={'role':'writer','templates':{'system_write':'OLD'}}),rid='role-prompt:writer')
    service.publish(db,role.id,0,'')
    first = service.capture_task_resources(db,pid)
    assert first['configured'] is False
    service.update_resource(db,role.id,1,{'body':{'role':'writer','templates':{'system_write':'NEW'}}})
    service.publish(db,role.id,2,'')
    second = service.capture_task_resources(db,pid)
    assert second['role_prompts'] == first['role_prompts']
    assert service.updates(db,pid)[0]['target_generation'] == 3


@pytest.mark.parametrize('form, status, allowed', [('long','ready',False),('long','legacy_ready',False),('long','draft',True),('short','ready',True)])
def test_adopting_genre_updates_obeys_book_lock(db, form, status, allowed):
    from myink.models import Project, ProjectSettings
    uid, pid = uuid.uuid4(), uuid.uuid4()
    db.add(Project(id=pid,user_id=uid,title='book',genre='玄幻',form=form,creation_status=status))
    db.add(ProjectSettings(project_id=pid,genre_pack={'source_id':'xiuxian'}))
    row = service.create_resource(db,dict(name='genre',kind='genre',source='builtin',body={'catalog_id':'xiuxian','fields':{'selling_point':'old'}}))
    service.publish(db,row.id,0,'')
    service.set_selection(db,pid,uid,0,[])
    service.update_resource(db,row.id,1,{'body':{'catalog_id':'xiuxian','fields':{'selling_point':'new'}}})
    service.publish(db,row.id,2,'')
    if not allowed:
        assert service.updates(db,pid) == []
    if allowed:
        assert service.adopt(db,pid,1,[{'resource_id':row.id,'target_generation':3}])['revision']==2
    else:
        with pytest.raises(HTTPException) as exc:
            service.adopt(db,pid,1,[{'resource_id':row.id,'target_generation':3}])
        assert exc.value.status_code==409


def test_started_book_can_edit_future_rules_without_changing_captured_task(db):
    from myink.models import Project
    uid, pid = uuid.uuid4(), uuid.uuid4()
    db.add(Project(id=pid,user_id=uid,title='book',genre='玄幻',current_chapter=3,form='long',creation_status='ready'))
    row = resource(db)
    service.publish(db,row.id,0,'')
    selected = {'origin':'platform','resource_id':row.id}
    service.set_selection(db,pid,uid,0,[selected])
    captured = service.capture_task_resources(db,pid)
    service.require_selection_editable(db,pid,uid)
    result = service.set_selection(db,pid,uid,1,[dict(selected,personal_override=True,body={'profile':{'voice':'NEW'}})])
    assert result['selections'][0]['body']['profile']['voice']=='NEW'
    assert captured['selections'][0]['body']['profile']['voice']=='one'
    with pytest.raises(HTTPException):
        service.set_selection(db,pid,uid,1,[selected])


def test_account_planning_without_book_uses_own_automatic_versions(db):
    uid = uuid.uuid4()
    role = service.create_resource(db,dict(name='role',kind='role_prompt',source='builtin',body={'role':'writer','templates':{'system_write':'platform'}}),rid='role-prompt:writer')
    ref = service.create_resource(db,dict(name='creative',kind='reference',source='builtin',body={'files':[{'path':'creative.md','content':'platform'}]}))
    for row in (role,ref):
        service.publish(db,row.id,0,'')
    service.copy_platform(db,role.id,uid,1,body={'role':'writer','templates':{'system_write':'personal'}})
    service.copy_platform(db,ref.id,uid,1,body={'files':[{'path':'creative.md','content':'personal'}]})
    snapshot = service.capture_task_resources(db,None,user_id=uid)
    assert snapshot['role_prompts']['writer']['body']['templates']['system_write']=='personal'
    from myink.writing_resource_runtime import bind_resources, reference_read
    with bind_resources(snapshot):
        assert reference_read('creative.md',db=db)['content']=='personal'
    assert service.capture_task_resources(db,None,user_id=uuid.uuid4())['role_prompts']['writer']['body']['templates']['system_write']=='platform'


def test_linked_personal_genre_cannot_change_catalog_identity(db):
    uid=uuid.uuid4()
    row=service.create_resource(db,dict(name='genre',kind='genre',source='builtin',body={'catalog_id':'xiuxian','fields':{}}))
    service.publish(db,row.id,0,'')
    with pytest.raises(HTTPException):
        service.copy_platform(db,row.id,uid,1,body={'catalog_id':'xianshi','fields':{}})
    private=service.copy_platform(db,row.id,uid,1)
    with pytest.raises(HTTPException):
        service.update_resource(db,private.id,1,{'body':{'catalog_id':'xianshi','fields':{}}},uid)


@pytest.mark.parametrize('entrypoint', ['select', 'capture'])
def test_legacy_long_first_snapshot_preserves_primary_secondary_book_genre(db, entrypoint):
    from myink.models import Project, ProjectSettings
    uid,pid=uuid.uuid4(),uuid.uuid4()
    db.add(Project(id=pid,user_id=uid,title='legacy',genre='修仙+现实',form='long',creation_status='ready'))
    db.add(ProjectSettings(project_id=pid,genre_pack={
        'source_id':'xiuxian','source_name':'本书修仙','secondary_id':'xianshi','secondary_name':'本书现实',
        'selling_point':'FROZEN_PRIMARY','_resource_caps':{'power_scaling':True},
        '_secondary_snapshot':{'name':'本书现实','selling_point':'FROZEN_SECONDARY'},
        '_resource_publications':[{'resource_id':'genre:xiuxian','version':1,'generation':1}]}))
    for gid in ('xiuxian','xianshi'):
        row=service.create_resource(db,dict(name='latest '+gid,kind='genre',source='platform',body={'catalog_id':gid,'fields':{'selling_point':'NEW_PLATFORM'}}),rid='genre:'+gid)
        service.publish(db,row.id,0,'')
        service.copy_platform(db,row.id,uid,1,body={'catalog_id':gid,'fields':{'selling_point':'NEW_PERSONAL'}})
    frozen=(service.set_selection(db,pid,uid,0,[]) if entrypoint=='select' else service.capture_task_resources(db,pid))
    genres=[item for item in frozen['selections'] if item['kind']=='genre']
    assert [g['body']['fields']['selling_point'] for g in genres]==['FROZEN_PRIMARY','FROZEN_SECONDARY']
    assert [g['name'] for g in genres]==['本书修仙','本书现实']
    from myink.writing_resource_runtime import bind_resources
    from myink.workflow import prompts
    import json
    with bind_resources(frozen):
        text=json.dumps(prompts.book_outline_messages('old','premise',10,'story'),ensure_ascii=False)
    assert 'FROZEN_PRIMARY' in text and 'FROZEN_SECONDARY' in text
    assert 'NEW_PLATFORM' not in text and 'NEW_PERSONAL' not in text


@pytest.mark.parametrize('stage', ['setup', 'outline'])
def test_draft_automatic_personal_genre_and_rules_reach_proposals_before_manual_selection(db, stage):
    from myink.models import Project, ProjectSettings
    from myink.writing_resource_runtime import bind_resources
    from myink.workflow import prompts
    import json
    uid,pid=uuid.uuid4(),uuid.uuid4()
    db.add(Project(id=pid,user_id=uid,title='draft',genre='修仙',form='long',creation_status='draft'))
    db.add(ProjectSettings(project_id=pid,genre_pack={'source_id':'xiuxian','selling_point':'BOOK_BASELINE'}))
    genre=service.create_resource(db,dict(name='genre',kind='genre',source='builtin',body={'catalog_id':'xiuxian','fields':{'selling_point':'PLATFORM'}}))
    rule=service.create_resource(db,dict(name='rule',kind='genre_rule',source='builtin',body={'genre_ids':['xiuxian'],'roles':{'planner':'PLATFORM_RULE'}}))
    for row in (genre,rule): service.publish(db,row.id,0,'')
    service.copy_platform(db,genre.id,uid,1,body={'catalog_id':'xiuxian','fields':{'selling_point':'PERSONAL_GENRE'}})
    service.copy_platform(db,rule.id,uid,1,body={'genre_ids':['xiuxian'],'roles':{'planner':'PERSONAL_RULE'}})
    snapshot=service.capture_task_resources(db,pid)
    assert snapshot['configured'] is False
    with bind_resources(snapshot):
        messages=prompts.book_setup_messages('old','premise') if stage=='setup' else prompts.book_outline_messages('old','premise',10,'story')
        text=json.dumps(messages,ensure_ascii=False)
    assert 'PERSONAL_GENRE' in text and 'PERSONAL_RULE' in text
    assert 'BOOK_BASELINE' not in text and 'PLATFORM_RULE' not in text
    from myink.genre_catalog import _REFINE
    assert _REFINE['xiuxian'] not in text


@pytest.mark.parametrize('entrypoint',['capture','select'])
def test_legacy_configured_snapshot_keeps_existing_genres_without_duplicate_or_refresh(db, entrypoint):
    from myink.models import Project, ProjectSettings
    uid,pid=uuid.uuid4(),uuid.uuid4()
    db.add(Project(id=pid,user_id=uid,title='old',genre='修仙',form='long',creation_status='ready'))
    db.add(ProjectSettings(project_id=pid,genre_pack={'source_id':'xiuxian','selling_point':'BOOK_SOURCE'}))
    genre=dict(resource_id='genre:old-choice',origin='platform',name='历史题材',kind='genre',version=4,generation=9,personal_override=False,body={'catalog_id':'xianshi','fields':{'selling_point':'EXISTING_CHOICE'}})
    rule=dict(resource_id='genre-rule:old-choice',origin='platform',name='历史规则',kind='genre_rule',version=2,generation=3,personal_override=False,body={'genre_ids':['xianshi'],'roles':{'writer':'EXISTING_RULE'}})
    service.save_snapshot(db,pid,0,[genre,rule])
    newrule=service.create_resource(db,dict(name='new rule',kind='genre_rule',source='builtin',body={'genre_ids':['xiuxian'],'roles':{'writer':'NEW_RULE'}}))
    service.publish(db,newrule.id,0,'')
    result=(service.capture_task_resources(db,pid) if entrypoint=='capture' else service.set_selection(db,pid,uid,1,[]))
    assert [item for item in result['selections'] if item['kind'] in ('genre','genre_rule')]==[genre,rule]
    assert service.capture_task_resources(db,pid)['selections']==result['selections']


@pytest.mark.parametrize('origin',['platform','personal'])
def test_existing_reference_cannot_be_hand_edited_through_selection(db, origin):
    uid,pid=uuid.uuid4(),uuid.uuid4()
    row=service.create_resource(db,dict(name='reference',kind='reference',source='test',body={'files':[{'path':'x.md','content':'old'}]}),user_id=uid if origin=='personal' else None)
    if origin=='platform': service.publish(db,row.id,0,'')
    service.save_snapshot(db,pid,0,[dict(resource_id=row.id,origin=origin,name=row.name,kind='reference',version=1,generation=1,personal_override=True,body=row.body)])
    with pytest.raises(HTTPException) as exc:
        service.set_selection(db,pid,uid,1,[dict(resource_id=row.id,origin=origin,personal_override=True,body={'files':[{'path':'x.md','content':'changed'}]})])
    assert exc.value.status_code==422


@pytest.mark.parametrize('configured', [None, False, True])
def test_legacy_book_get_initializes_real_default_rules_once_with_personal_priority(db, configured):
    from myink.models import Project, ProjectSettings
    from myink.writing_resource_runtime import bind_resources
    from myink.workflow import prompts
    import json
    uid,pid=uuid.uuid4(),uuid.uuid4()
    db.add(Project(id=pid,user_id=uid,title='legacy defaults',genre='修仙',form='long',creation_status='ready'))
    db.add(ProjectSettings(project_id=pid,genre_pack={'source_id':'xiuxian','selling_point':'FROZEN_BOOK'}))
    writer=service.create_resource(db,dict(name='writing',kind='writing_rule',source='platform',body={'roles':{'writer':'PLATFORM_WRITING'}}))
    expression=service.create_resource(db,dict(name='expression',kind='expression_rule',source='platform',body={'roles':{'writer':'DEFAULT_EXPRESSION'},'validation':{'not_is':False}}))
    style=resource(db)
    for row in (writer,expression,style): service.publish(db,row.id,0,'')
    private=service.copy_platform(db,writer.id,uid,1,body={'roles':{'writer':'PERSONAL_WRITING'}})
    if configured is not None:
        service.save_snapshot(db,pid,0,[],configured=configured,automatic_initialized=True)
    old_task=service.project_snapshot(db,pid)
    saved=service.ensure_project_resources(db,pid,uid)
    rules=[item for item in saved['selections'] if item['kind'] in ('writing_rule','expression_rule')]
    assert {(item['resource_id'],item['origin']) for item in rules}=={(private.id,'personal'),(expression.id,'platform')}
    assert not any(item['kind']=='style' for item in saved['selections'])
    assert old_task['selections']==[]
    with bind_resources(saved):
        text=json.dumps(prompts.write_messages({},{}),ensure_ascii=False)
        assert 'PERSONAL_WRITING' in text and 'DEFAULT_EXPRESSION' in text
        assert 'PLATFORM_WRITING' not in text
    service.update_resource(db,private.id,1,{'body':{'roles':{'writer':'LATER_PERSONAL'}}},uid)
    later=service.create_resource(db,dict(name='later',kind='expression_rule',source='platform',body={'roles':{'writer':'LATER_ADDITION'}}))
    service.publish(db,later.id,0,'')
    assert service.ensure_project_resources(db,pid,uid)==saved
    assert service.capture_task_resources(db,pid)['selections']==saved['selections']


def test_default_rule_upgrade_keeps_book_override_until_explicitly_cleared(db):
    from myink.models import Project
    uid,pid=uuid.uuid4(),uuid.uuid4()
    db.add(Project(id=pid,user_id=uid,title='override',genre='修仙',form='long',creation_status='ready'))
    writer=service.create_resource(db,dict(name='writing',kind='writing_rule',source='platform',body={'roles':{'writer':'PLATFORM'}}))
    expression=service.create_resource(db,dict(name='expression',kind='expression_rule',source='platform',body={'roles':{'writer':'EXPRESSION'}}))
    for row in (writer,expression):service.publish(db,row.id,0,'')
    old=dict(resource_id=writer.id,origin='platform',name=writer.name,kind='writing_rule',version=1,generation=1,personal_override=True,body={'roles':{'writer':'BOOK_OVERRIDE'}})
    genre=dict(resource_id='old-genre',origin='platform',name='old',kind='genre',version=1,generation=1,personal_override=False,body={'catalog_id':'xiuxian','fields':{'selling_point':'BOOK_GENRE'}})
    service.save_snapshot(db,pid,0,[old,genre],configured=True,automatic_initialized=True)
    saved=service.ensure_project_resources(db,pid,uid)
    assert next(item for item in saved['selections'] if item['kind']=='writing_rule')==old
    assert next(item for item in saved['selections'] if item['kind']=='genre')==genre
    result=service.set_selection(db,pid,uid,saved['revision'],[])
    assert result['selections']==[genre]
    assert service.capture_task_resources(db,pid)['selections']==[genre]


def test_empty_platform_defaults_are_frozen_without_future_silent_additions(db):
    from myink.models import Project
    uid,pid=uuid.uuid4(),uuid.uuid4()
    db.add(Project(id=pid,user_id=uid,title='no defaults',genre='修仙',form='long',creation_status='ready'))
    before=service.ensure_project_resources(db,pid,uid)
    assert not any(item['kind'] in ('writing_rule','expression_rule') for item in before['selections'])
    row=service.create_resource(db,dict(name='later',kind='writing_rule',source='platform',body={'roles':{'writer':'LATER'}}))
    service.publish(db,row.id,0,'')
    assert service.ensure_project_resources(db,pid,uid)==before
    newer=uuid.uuid4()
    db.add(Project(id=newer,user_id=uid,title='new book',genre='修仙',form='long',creation_status='ready'))
    assert any(item['resource_id']==row.id for item in service.ensure_project_resources(db,newer,uid)['selections'])


def test_explicit_personal_rule_replacement_does_not_duplicate_platform_default(db):
    from myink.models import Project
    uid,pid=uuid.uuid4(),uuid.uuid4()
    db.add(Project(id=pid,user_id=uid,title='replace',genre='修仙',form='long',creation_status='ready'))
    row=service.create_resource(db,dict(name='writing',kind='writing_rule',source='platform',body={'roles':{'writer':'PLATFORM'}}))
    service.publish(db,row.id,0,'')
    original=service.ensure_project_resources(db,pid,uid)
    private=service.copy_platform(db,row.id,uid,1,body={'roles':{'writer':'PERSONAL'}})
    result=service.set_selection(db,pid,uid,original['revision'],[{'origin':'personal','resource_id':private.id}])
    rules=[item for item in result['selections'] if item['kind']=='writing_rule']
    assert len(rules)==1 and rules[0]['resource_id']==private.id
    with pytest.raises(HTTPException) as exc:
        service.set_selection(db,pid,uid,result['revision'],[{'origin':'platform','resource_id':row.id},{'origin':'personal','resource_id':private.id}])
    assert exc.value.status_code==422

@pytest.mark.parametrize('form', ['long', 'short'])
def test_explicit_empty_initial_selection_does_not_restore_defaults(db, form):
    from myink.models import Project
    uid,pid=uuid.uuid4(),uuid.uuid4()
    db.add(Project(id=pid,user_id=uid,title='empty choice',genre='修仙',form=form,creation_status='draft'))
    for kind in ('writing_rule','expression_rule'):
        row=service.create_resource(db,dict(name=kind,kind=kind,source='platform',body={'roles':{'writer':'DEFAULT'}}))
        service.publish(db,row.id,0,'')
    saved=service.set_selection(db,pid,uid,0,[])
    assert not any(item['kind'] in ('writing_rule','expression_rule') for item in saved['selections'])
    assert service.ensure_project_resources(db,pid,uid)==saved
    assert service.capture_task_resources(db,pid)['selections']==saved['selections']
