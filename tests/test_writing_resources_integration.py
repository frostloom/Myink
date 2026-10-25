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
        assert process(body) == "terminal"
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
