"""Real PostgreSQL RLS and authenticated release/snapshot integration."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from conftest import identity_headers
from myink import writing_resources as svc
from myink.api.main import app
from myink.db import new_session, tenant_session
from myink.models import Project, User
from myink.models.writing_resource import (
    ProjectWritingResources, WritingResource,
    WritingResourcePublication, WritingResourceRevision,
)


def test_authenticated_release_snapshot_rollback_and_owner(temp_project, temp_user):
    client = TestClient(app)
    with new_session() as db:
        owner = db.get(Project, uuid.UUID(temp_project)).user_id
        admin = db.get(User, uuid.UUID(temp_user))
        admin.role = "admin"
        db.commit()
    user_headers, admin_headers = identity_headers(owner), identity_headers(temp_user)
    path = f"/api/v1/projects/{temp_project}/writing-resources"
    body = dict(name="Integration style", kind="style", source="integration-test",
                body={"profile": {"voice": "original"}})
    rid = None
    try:
        created = client.post("/api/v1/admin/writing-resources", json=body, headers=admin_headers)
        assert created.status_code == 200, created.text
        rid = created.json()["id"]
        base = f"/api/v1/admin/writing-resources/{rid}"
        assert client.post(base + "/publish", json={"expected_generation": 0}, headers=admin_headers).status_code == 200
        chosen = client.put(path, json={"expected_revision": 0, "selections": [{"origin": "platform", "resource_id": rid}]}, headers=user_headers)
        assert chosen.status_code == 200, chosen.text
        original = chosen.json()
        assert client.get(path, headers=admin_headers).status_code == 403
        body.update(name="Integration v2", body={"profile": {"voice": "new"}})
        assert client.put(base, json={k: v for k, v in dict(body, expected_generation=1).items() if k != "kind"}, headers=admin_headers).status_code == 200
        assert client.post(base + "/publish", json={"expected_generation": 2}, headers=admin_headers).status_code == 200
        assert client.get(path, headers=user_headers).json() == original
        changes = client.get(path + "/updates", headers=user_headers).json()["items"]
        target = [{"resource_id": rid, "target_generation": changes[0]["target_generation"]}]
        assert client.post(path + "/dismiss", json={"updates": target}, headers=user_headers).status_code == 200
        assert client.get(path, headers=user_headers).json() == original
        assert client.get(path + "/updates", headers=user_headers).json()["items"][0]["dismissed"]
        adopted = client.post(path + "/adopt", json={"expected_revision": 1, "updates": target}, headers=user_headers)
        assert adopted.status_code == 200, adopted.text
        assert adopted.json()["selections"][0]["body"]["profile"]["voice"] == "new"
        assert client.post(base + "/rollback", json={"expected_generation": 3, "version": 1}, headers=admin_headers).status_code == 200
        changes = client.get(path + "/updates", headers=user_headers).json()["items"]
        assert changes[0]["action"] == "rollback" and changes[0]["target_version"] == 1
        assert changes[0]["target_generation"] == 4
        assert len(client.get(base + "/revisions", headers=admin_headers).json()["items"]) == 2
        with new_session() as db:
            assert db.get(ProjectWritingResources, uuid.UUID(temp_project)) is None
        with tenant_session(uuid.uuid4()) as db:
            assert db.get(ProjectWritingResources, uuid.UUID(temp_project)) is None
        with tenant_session(temp_project) as db:
            assert svc.project_snapshot(db, temp_project)["revision"] == 2
    finally:
        with tenant_session(temp_project) as db:
            db.execute(delete(ProjectWritingResources).where(ProjectWritingResources.project_id == uuid.UUID(temp_project)))
        if rid:
            with new_session() as db:
                for model in (WritingResourcePublication, WritingResourceRevision):
                    db.execute(delete(model).where(model.resource_id == rid))
                db.execute(delete(WritingResource).where(WritingResource.id == rid))
                db.commit()


def test_concurrent_publication_has_one_winner():
    with new_session() as db:
        row = svc.create_resource(db, dict(name="Race", kind="style", source="test", body={"profile": {}}))
        rid = row.id
        db.commit()
    barrier = Barrier(2)
    def publish():
        with new_session() as db:
            svc.resource(db, rid)
            barrier.wait(timeout=10)
            try:
                svc.publish(db, rid, 0, "race")
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: publish(), range(2))) == [200, 409]
        with new_session() as db:
            assert len(svc.revisions(db, rid)) == 1
            assert len(list(db.scalars(select(WritingResourcePublication).where(WritingResourcePublication.resource_id == rid)))) == 1
    finally:
        with new_session() as db:
            for model in (WritingResourcePublication, WritingResourceRevision):
                db.execute(delete(model).where(model.resource_id == rid))
            db.execute(delete(WritingResource).where(WritingResource.id == rid))
            db.commit()


def test_persisted_task_uses_admission_snapshot_after_project_changes(temp_project, stub_provider, monkeypatch):
    from copy import deepcopy
    import pytest
    from myink.maintenance import register_admission
    from myink.worker.handoff import QueueAuthorityUnknown
    from myink.models import Task
    from myink.worker.processor import process
    from myink.workflow.runner import new_task
    from myink.worker.redis_client import get_redis, sse_key
    provider = stub_provider("金丹", "金丹")
    captured = []
    original_generate = provider.generate
    def capture(messages, **kwargs):
        captured.append(deepcopy(messages))
        return original_generate(messages, **kwargs)
    monkeypatch.setattr(provider, "generate", capture)
    with new_session() as db:
        owner = str(db.get(Project, uuid.UUID(temp_project)).user_id)
        resource = svc.create_resource(db, dict(name="Pinned", kind="writing_rule", source="test", body={"roles": {"writer": "ADMISSION_PINNED_RULE"}}))
        rid = resource.id
        svc.publish(db, rid, 0, "original")
        db.commit()
    task_id = None
    try:
        with tenant_session(temp_project) as db:
            svc.set_selection(db, temp_project, owner, 0, [{"origin": "platform", "resource_id": rid}])
        task_id = new_task(project_id=temp_project, task_type="chapter_generate", payload={"seq": 1}, chapter_seq=1)
        with tenant_session(temp_project) as db:
            svc.set_selection(db, temp_project, owner, 1, [])
        # A stale/tampered transport must not replace the persisted admission snapshot.
        body = {"task_id": task_id, "task_type": "chapter_generate", "project_id": temp_project,
                "user_id": owner, "payload": {"seq": 1, "writing_resources": {"configured": True, "selections": []}},
                "retry_count": 1, "trace_id": "resource-freeze-test", "request_id": "resource-freeze-test"}
        with tenant_session(temp_project) as db:
            frozen = db.get(Task, uuid.UUID(task_id)).payload["writing_resources"]
            original = {**body, "retry_count": 0,
                        "payload": {"seq": 1, "writing_resources": frozen}}
            register_admission(db, original, priority=0)
        with pytest.raises(QueueAuthorityUnknown):
            process(body)
        assert captured == []
        assert process(original) == "terminal"
        writer_messages = [m for m in captured if "写作 Agent" in m[0]["content"]]
        assert writer_messages, "full graph must reach the writer provider"
        assert any("ADMISSION_PINNED_RULE" in str(messages) for messages in writer_messages)
        with new_session() as db:
            task = db.get(Task, uuid.UUID(task_id))
            assert task.payload["writing_resources"]["selections"][0]["resource_id"] == rid
    finally:
        with tenant_session(temp_project) as db:
            db.execute(delete(ProjectWritingResources).where(ProjectWritingResources.project_id == uuid.UUID(temp_project)))
        with new_session() as db:
            for model in (WritingResourcePublication, WritingResourceRevision):
                db.execute(delete(model).where(model.resource_id == rid))
            db.execute(delete(WritingResource).where(WritingResource.id == rid))
            db.commit()
        if task_id:
            get_redis().delete(sse_key(task_id))


def test_project_delete_cascades_private_resource_snapshot(temp_project):
    from myink.db import get_admin_engine
    from sqlalchemy import text
    with tenant_session(temp_project) as db:
        db.add(ProjectWritingResources(project_id=uuid.UUID(temp_project),
            selections=[{'personal_override': True, 'body': {'private': 'text'}}]))
    with new_session() as db:
        db.execute(delete(Project).where(Project.id == uuid.UUID(temp_project)))
        db.commit()
    # Superuser query avoids mistaking RLS invisibility for actual deletion.
    with get_admin_engine().connect() as conn:
        count = conn.scalar(text('SELECT count(*) FROM project_writing_resources WHERE project_id=:pid'),
                            {'pid': uuid.UUID(temp_project)})
    assert count == 0


def test_legacy_snapshot_upgrade_cleans_orphans_and_keeps_valid_books(monkeypatch):
    from sqlalchemy import create_engine, text
    import myink.db as db_module
    schema = 'resource_upgrade_' + uuid.uuid4().hex
    admin = db_module.get_admin_engine()
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    isolated = create_engine(admin.url, connect_args={'options': f'-csearch_path={schema}'})
    pid, orphan = uuid.uuid4(), uuid.uuid4()
    try:
        with isolated.begin() as conn:
            conn.execute(text('CREATE TABLE projects (id uuid PRIMARY KEY)'))
            conn.execute(text('CREATE TABLE project_writing_resources (project_id uuid PRIMARY KEY, selections json)'))
            conn.execute(text('ALTER TABLE project_writing_resources ENABLE ROW LEVEL SECURITY'))
            conn.execute(text('ALTER TABLE project_writing_resources FORCE ROW LEVEL SECURITY'))
            conn.execute(text('CREATE POLICY deny_snapshots ON project_writing_resources USING (false)'))
            conn.execute(text('INSERT INTO projects VALUES (:id)'), {'id': pid})
            conn.execute(text("INSERT INTO project_writing_resources VALUES (:id, '[{\"body\":\"private\"}]')"),
                         [{'id': pid}, {'id': orphan}])
        monkeypatch.setattr(db_module, 'get_admin_engine', lambda: isolated)
        db_module.ensure_writing_resource_snapshot_fk()
        db_module.ensure_writing_resource_snapshot_fk()
        with isolated.begin() as conn:
            rows = conn.execute(text('SELECT project_id, selections FROM project_writing_resources')).all()
            assert rows == [(pid, [{'body': 'private'}])]
            conn.execute(text('DELETE FROM projects WHERE id=:id'), {'id': pid})
            assert conn.scalar(text('SELECT count(*) FROM project_writing_resources')) == 0
    finally:
        isolated.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))


def test_resource_selection_after_generation_edits_only_future_snapshot(temp_project):
    from myink.models import Task
    client = TestClient(app)
    with new_session() as db:
        owner = db.get(Project, uuid.UUID(temp_project)).user_id
        resource = svc.create_resource(db, dict(name='Locked', kind='style', source='test', body={'profile': {'voice': 'one'}}))
        rid = resource.id
        svc.publish(db, rid, 0, '')
        db.commit()
    path = f'/api/v1/projects/{temp_project}/writing-resources'
    headers = identity_headers(owner)
    try:
        selected = client.put(path, headers=headers, json={'expected_revision': 0, 'selections': [{'origin': 'platform', 'resource_id': rid}]})
        assert selected.status_code == 200, selected.text
        with tenant_session(temp_project) as db:
            captured = svc.capture_task_resources(db, temp_project)
            task = Task(project_id=uuid.UUID(temp_project), task_type='chapter_generate', status='running', payload={'writing_resources': captured})
            db.add(task)
            db.flush()
            task_id = task.id
        edited = client.put(path, headers=headers, json={'expected_revision': 1, 'selections': [{
            'origin':'platform','resource_id':rid,'personal_override':True,'body':{'profile':{'voice':'two'}}}]})
        assert edited.status_code == 200, edited.text
        assert edited.json()['selections'][0]['body']['profile']['voice'] == 'two'
        with tenant_session(temp_project) as db:
            assert db.get(Task,task_id).payload['writing_resources'] == captured
            assert svc.capture_task_resources(db,temp_project)['selections'][0]['body']['profile']['voice'] == 'two'
    finally:
        with tenant_session(temp_project) as db:
            db.execute(delete(ProjectWritingResources).where(ProjectWritingResources.project_id == uuid.UUID(temp_project)))
        with new_session() as db:
            db.execute(delete(WritingResourcePublication).where(WritingResourcePublication.resource_id == rid))
            db.execute(delete(WritingResourceRevision).where(WritingResourceRevision.resource_id == rid))
            db.execute(delete(WritingResource).where(WritingResource.id == rid))
            db.commit()


def test_resource_selection_waits_for_enqueue_and_rejects_stale_revision(temp_project, monkeypatch):
    from threading import Event
    from concurrent.futures import TimeoutError
    import pytest
    from myink.worker import enqueue as queue
    from myink.worker.redis_client import get_redis, inflight_key
    client = TestClient(app)
    with new_session() as db:
        owner = str(db.get(Project, uuid.UUID(temp_project)).user_id)
    published, release, selection_started = Event(), Event(), Event()
    monkeypatch.setattr('myink.platform_readiness.require_operation_ready', lambda *args: None)
    original_capture = svc.capture_task_resources
    def capture(*args, **kwargs):
        published.set()
        assert release.wait(5)
        return original_capture(*args, **kwargs)
    monkeypatch.setattr(svc, 'capture_task_resources', capture)
    monkeypatch.setattr(queue.amqp, 'publish', lambda *args, **kwargs: None)
    def change_selection():
        selection_started.set()
        return client.put(f'/api/v1/projects/{temp_project}/writing-resources', headers=identity_headers(owner), json={'expected_revision':0,'selections':[]})
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            admission = pool.submit(queue.enqueue, user_id=owner, project_id=temp_project, task_type='chapter_generate', payload={'seq':1}, quota_n=1, cost_est=0, priority=0)
            assert published.wait(5)
            selection = pool.submit(change_selection)
            assert selection_started.wait(5)
            with pytest.raises(TimeoutError):
                selection.result(timeout=0.1)
            release.set()
            assert admission.result(timeout=5)['status'] == 'queued'
            denied = selection.result(timeout=5)
            assert denied.status_code == 409, denied.text
    finally:
        release.set()
        get_redis().delete(inflight_key(owner, temp_project))


def test_resource_selection_does_not_require_redis_admission_state(temp_project, monkeypatch):
    from myink.worker import redis_client
    with new_session() as db:
        owner = db.get(Project, uuid.UUID(temp_project)).user_id
    def unavailable():
        raise ConnectionError('offline')
    monkeypatch.setattr(redis_client, 'get_redis', unavailable)
    response = TestClient(app).put(f'/api/v1/projects/{temp_project}/writing-resources', headers=identity_headers(owner), json={'expected_revision':0,'selections':[]})
    assert response.status_code == 200, response.text
    with tenant_session(temp_project) as db:
        assert svc.project_snapshot(db, temp_project)['configured'] is True


def test_definite_publish_failure_leaves_resource_selection_editable(temp_project, monkeypatch):
    import pika
    import pytest
    from myink.worker import enqueue as queue
    with new_session() as db:
        owner = str(db.get(Project, uuid.UUID(temp_project)).user_id)
    monkeypatch.setattr('myink.platform_readiness.require_operation_ready', lambda *args: None)
    def reject(*args, **kwargs):
        raise pika.exceptions.NackError([])
    monkeypatch.setattr(queue.amqp, 'publish', reject)
    with pytest.raises(queue.EnqueueUnavailable):
        queue.enqueue(user_id=owner, project_id=temp_project, task_type='chapter_generate', payload={'seq':1}, quota_n=1, cost_est=0, priority=0)
    client = TestClient(app)
    path = f'/api/v1/projects/{temp_project}/writing-resources'
    current = client.get(path, headers=identity_headers(owner))
    assert current.status_code == 200
    response = client.put(path, headers=identity_headers(owner), json={'expected_revision':current.json()['revision'],'selections':[]})
    assert response.status_code == 200, response.text


def test_enqueue_resource_lock_works_with_one_database_connection(temp_project, monkeypatch):
    from contextlib import contextmanager
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from myink import db as database
    from myink.config import settings
    from myink.worker import enqueue as queue
    from myink.worker.redis_client import get_redis, inflight_key
    with new_session() as db:
        owner = str(db.get(Project, uuid.UUID(temp_project)).user_id)
    engine = create_engine(settings.database_url, pool_size=1, max_overflow=0, pool_timeout=0.1)
    @contextmanager
    def one_connection(pid):
        with Session(engine) as db:
            with db.begin():
                db.execute(text("SELECT set_config('app.tenant_id', :pid, true)"), {'pid':pid})
                yield db
    def configuration_read(*args):
        with one_connection(temp_project) as db:
            db.execute(text('SELECT 1'))
        return {}
    monkeypatch.setattr(database, 'tenant_session', one_connection)
    monkeypatch.setattr('myink.platform_readiness.require_operation_ready', configuration_read)
    monkeypatch.setattr('myink.task_budget.snapshot_budget', configuration_read)
    monkeypatch.setattr(queue.amqp, 'publish', lambda *args, **kwargs: None)
    try:
        assert queue.enqueue(user_id=owner,project_id=temp_project,task_type='chapter_generate',payload={'seq':1},quota_n=1,cost_est=0,priority=0)['status'] == 'queued'
    finally:
        get_redis().delete(inflight_key(owner, temp_project))
        engine.dispose()


def test_personal_source_migration_is_idempotent_and_preserves_independent_rows(monkeypatch):
    from contextlib import contextmanager
    from sqlalchemy import text
    import myink.db as database
    schema = 'resource_source_' + uuid.uuid4().hex
    engine = database.get_admin_engine()
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(text(f'CREATE SCHEMA {schema}'))
            conn.execute(text(f'SET LOCAL search_path TO {schema}'))
            conn.execute(text('CREATE TABLE personal_writing_resources (id text PRIMARY KEY, user_id uuid, body json)'))
            conn.execute(text('CREATE TABLE project_writing_resources (project_id uuid PRIMARY KEY, selections json)'))
            conn.execute(text("INSERT INTO personal_writing_resources VALUES ('old', :uid, '{\"profile\":{\"voice\":\"mine\"}}')"), {'uid':uuid.uuid4()})
            conn.execute(text("INSERT INTO project_writing_resources VALUES (:pid, '[]')"), {'pid':uuid.uuid4()})
            class ExistingEngine:
                @contextmanager
                def begin(self):
                    yield conn
            monkeypatch.setattr(database, 'get_admin_engine', lambda: ExistingEngine())
            database.ensure_personal_resource_sources()
            database.ensure_personal_resource_sources()
            saved = conn.execute(text('SELECT body, source_resource_id, source_generation FROM personal_writing_resources')).one()
            assert saved[0] == {'profile':{'voice':'mine'}}
            assert saved[1:] == (None,None)
            assert conn.execute(text('SELECT configured, automatic_initialized, defaults_initialized FROM project_writing_resources')).one() == (True,False,False)
        finally:
            transaction.rollback()


def test_parallel_personal_copy_and_sync_have_one_cas_winner(temp_user):
    from myink.models.writing_resource import PersonalWritingResource
    uid = uuid.UUID(temp_user)
    with new_session() as db:
        row = svc.create_resource(db,dict(name='copy',kind='style',source='test',body={'profile':{}}))
        svc.publish(db,row.id,0,'')
        rid = row.id
        db.commit()
    def copy():
        with new_session() as db:
            try:
                result = svc.copy_platform(db,rid,uid,1)
                db.commit()
                return 200,result.id
            except HTTPException as exc:
                return exc.status_code,None
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: copy(),range(2)))
        assert sorted(code for code,_ in results)==[200,409]
        private_id = next(value for code,value in results if code==200)
        def sync():
            with new_session() as db:
                try:
                    svc.sync_personal(db,private_id,uid,1,1,True)
                    db.commit()
                    return 200
                except HTTPException as exc:
                    return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: sync(),range(2)))==[200,409]
    finally:
        with new_session() as db:
            db.execute(delete(PersonalWritingResource).where(PersonalWritingResource.source_resource_id==rid))
            db.execute(delete(WritingResourcePublication).where(WritingResourcePublication.resource_id==rid))
            db.execute(delete(WritingResourceRevision).where(WritingResourceRevision.resource_id==rid))
            db.execute(delete(WritingResource).where(WritingResource.id==rid))
            db.commit()


def test_concurrent_snapshot_get_initializes_defaults_once_without_mutating_admitted_task(temp_project):
    from myink.models import Task
    from myink.models.writing_resource import PersonalWritingResource
    client=TestClient(app)
    with new_session() as db:
        owner=db.get(Project,uuid.UUID(temp_project)).user_id
        writing=svc.create_resource(db,dict(name='automatic test rule',kind='writing_rule',source='test',body={'roles':{'writer':'PLATFORM_DEFAULT'}}))
        svc.publish(db,writing.id,0,'')
        private=svc.copy_platform(db,writing.id,owner,1,body={'roles':{'writer':'PERSONAL_DEFAULT'}})
        rid,private_id=writing.id,private.id
        db.commit()
    path=f'/api/v1/projects/{temp_project}/writing-resources'
    headers=identity_headers(owner)
    try:
        with tenant_session(temp_project) as db:
            before=svc.save_snapshot(db,temp_project,0,[],configured=True,automatic_initialized=True)
            task=Task(project_id=uuid.UUID(temp_project),task_type='chapter_generate',status='running',payload={'writing_resources':before})
            db.add(task)
            db.flush()
            task_id=task.id
        def read():
            response=client.get(path,headers=headers)
            assert response.status_code==200,response.text
            assert response.headers['cache-control']=='no-store'
            return response.json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            copies=list(pool.map(lambda _:read(),range(2)))
        assert copies[0]==copies[1]
        saved=copies[0]
        assert saved['revision']==2
        assert next(item for item in saved['selections'] if item['resource_id']==private_id)['body']['roles']['writer']=='PERSONAL_DEFAULT'
        assert {'writing_rule','expression_rule'} <= {item['kind'] for item in saved['selections']}
        with tenant_session(temp_project) as db:
            assert db.get(ProjectWritingResources,uuid.UUID(temp_project)).defaults_initialized
            assert db.get(Task,task_id).payload['writing_resources']==before
        with new_session() as db:
            assert db.get(ProjectWritingResources,uuid.UUID(temp_project)) is None
            svc.update_resource(db,private_id,1,{'body':{'roles':{'writer':'PERSONAL_LATER'}}},owner)
            db.commit()
        assert read()==saved
        kept=client.put(path,headers=headers,json={'expected_revision':saved['revision'],'selections':[]})
        assert kept.status_code==200,kept.text
        assert not any(item['kind'] in {'writing_rule','expression_rule'} for item in kept.json()['selections'])
        assert read()==kept.json()
        with tenant_session(temp_project) as db:
            captured=svc.capture_task_resources(db,temp_project)
            assert captured['selections']==kept.json()['selections']
            assert captured['revision']==kept.json()['revision']
            assert db.get(Task,task_id).payload['writing_resources']==before
    finally:
        with new_session() as db:
            db.execute(delete(PersonalWritingResource).where(PersonalWritingResource.id==private_id))
            db.execute(delete(WritingResourcePublication).where(WritingResourcePublication.resource_id==rid))
            db.execute(delete(WritingResourceRevision).where(WritingResourceRevision.resource_id==rid))
            db.execute(delete(WritingResource).where(WritingResource.id==rid))
            db.commit()
