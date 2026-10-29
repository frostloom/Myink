import uuid
from contextlib import contextmanager
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from myink.api import routes_writing_resources as admin, routes_user_writing_resources as user
from myink.api.auth import require_user, require_admin, require_owner
from myink.models.writing_resource import WritingResource, WritingResourceRevision, PersonalWritingResource, ProjectWritingResources, WritingResourcePublication

@pytest.fixture
def api(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    from myink.models import Project, ProjectSettings
    Project.__table__.create(engine)
    ProjectSettings.__table__.create(engine)
    for table in (WritingResource.__table__, WritingResourceRevision.__table__, PersonalWritingResource.__table__, ProjectWritingResources.__table__, WritingResourcePublication.__table__):
        table.create(engine)

    def session():
        return Session(engine, expire_on_commit=False)

    @contextmanager
    def tenant(pid):
        with session() as db:
            yield db
            db.commit()
    monkeypatch.setattr(admin, 'new_session', session)
    monkeypatch.setattr(user, 'new_session', session)
    monkeypatch.setattr(user, 'tenant_session', tenant)
    monkeypatch.setattr(admin, '_audit_or_fail', lambda *args: None)
    # This isolated SQLite fixture covers resource CRUD; real ownership/admission
    # state and its selection lock are exercised in the PostgreSQL integration suite.
    monkeypatch.setattr(user.svc, 'require_selection_editable', lambda *args: None)
    app = FastAPI()
    app.include_router(admin.router)
    app.include_router(user.router)
    app.dependency_overrides[require_user] = lambda: str(uuid.UUID(int=1))
    app.dependency_overrides[require_admin] = lambda: object()
    app.dependency_overrides[require_owner] = lambda: None
    return (TestClient(app), app)

def test_api_publication_private_and_snapshot(api):
    client, app = api
    base = '/api/v1'
    payload = dict(name='first', kind='style', source='test', body={'profile': {'voice': 'first'}})
    created = client.post(base + '/admin/writing-resources', json=payload)
    assert created.status_code == 200, created.text
    rid = created.json()['id']
    assert client.get(base + '/writing-resources').json() == {'items': []}
    release = client.post(base + f'/admin/writing-resources/{rid}/publish', json={'expected_generation': 0, 'note': 'first'})
    assert release.status_code == 200, release.text
    assert release.headers['cache-control'] == 'no-store'
    edited = client.put(base + f'/admin/writing-resources/{rid}', json=dict(expected_generation=1, name='secret', source='secret', body={'profile': {'voice': 'draft'}}))
    assert edited.status_code == 200, edited.text
    public = client.get(base + '/writing-resources').json()['items'][0]
    assert public['name'] == 'first' and public['generation'] == 1
    private = client.post(base + '/my-writing-resources', json=payload)
    assert private.status_code == 200
    assert len(client.get(base + '/admin/writing-resources').json()['items']) == 1
    pid = str(uuid.uuid4())
    route = base + f'/projects/{pid}/writing-resources'
    selected = client.put(route, json={'expected_revision': 0, 'selections': [{'origin': 'platform', 'resource_id': rid}]})
    assert selected.status_code == 200, selected.text
    assert selected.json()['selections'][0]['name'] == 'first'
    assert client.get(route + '/updates').json() == {'items': []}
    assert client.put(route, json={'expected_revision': 0, 'selections': []}).status_code == 409
    app.dependency_overrides[require_user] = lambda: str(uuid.UUID(int=2))
    assert client.get(base + '/my-writing-resources').json() == {'items': []}
    assert client.put(base + f"/my-writing-resources/{private.json()['id']}", json=dict(expected_generation=1, name='x', source='x', body={'profile': {}})).status_code == 404

def test_authorization_audit_and_invalid_body(api, monkeypatch):
    client, app = api

    def denied():
        raise HTTPException(403, 'denied')
    app.dependency_overrides[require_admin] = denied
    assert client.get('/api/v1/admin/writing-resources').status_code == 403
    app.dependency_overrides[require_admin] = lambda: object()
    monkeypatch.setattr(admin, '_audit_or_fail', lambda *args: denied())
    payload = dict(name='x', kind='style', source='x', body={'profile': {}})
    assert client.post('/api/v1/admin/writing-resources', json=payload).status_code == 403
    monkeypatch.setattr(admin, '_audit_or_fail', lambda *args: None)
    assert client.get('/api/v1/admin/writing-resources').json() == {'items': []}
    app.dependency_overrides[require_owner] = denied
    assert client.get(f'/api/v1/projects/{uuid.uuid4()}/writing-resources').status_code == 403
    payload.update(kind='reference', body={'files': [{'path': '../secret', 'content': 'x'}]})
    assert client.post('/api/v1/admin/writing-resources', json=payload).status_code == 422

@pytest.mark.parametrize('kind,body', [('reference', {'files': ['invalid']}), ('reference', {'files': [{'path': 42, 'content': 'x'}]}), ('genre', {'catalog_id': 'x', 'fields': {'pacing': []}}), ('writing_rule', {'roles': {'unknown': 'x'}})])
def test_invalid_resource_body_is_422(api, kind, body):
    client, _ = api
    response = client.post('/api/v1/admin/writing-resources', json=dict(name='invalid', kind=kind, source='test', body=body))
    assert response.status_code == 422, response.text


def seed_resources(monkeypatch):
    from myink import platform_configuration
    from myink.writing_resource_seed import builtin_resources
    monkeypatch.setattr(platform_configuration, "load_configuration", lambda: {"genre_packs": {}, "prompts": {}})
    return builtin_resources()


def test_all_real_builtin_genres_validate(monkeypatch):
    from myink.writing_resource_schemas import CreateResource
    genres = [r for r in seed_resources(monkeypatch) if r["kind"] == "genre"]
    assert len(genres) == 37
    failures = []
    for resource in genres:
        try:
            CreateResource.model_validate({k: v for k, v in resource.items() if k != "id"})
        except ValueError as exc:
            failures.append((resource["id"], str(exc)))
    assert not failures, failures


def test_all_real_seed_resources_create_update_override(api, monkeypatch):
    client, _ = api
    resources = seed_resources(monkeypatch)
    project = f"/api/v1/projects/{uuid.uuid4()}/writing-resources"
    revision = 0
    for resource in resources:
        payload = {k: v for k, v in resource.items() if k != "id"}
        response = client.post("/api/v1/admin/writing-resources", json=payload)
        if resource["kind"] == "role_prompt":
            assert response.status_code == 422, response.text
            private = client.post("/api/v1/my-writing-resources", json=payload)
            assert private.status_code == 422, private.text
            # Automatic roles are installed internally with reserved IDs.
            from myink import writing_resources as svc
            with admin.new_session() as db:
                row = svc.create_resource(db, payload, rid=resource["id"])
                svc.publish(db, row.id, 0, "automatic initial publication")
                db.commit()
            override = client.put(project, json={"expected_revision": revision, "selections": [{
                "origin": "platform", "resource_id": resource["id"],
                "personal_override": True, "body": payload["body"],
            }]})
            assert override.status_code == 422, override.text
            continue
        assert response.status_code == 200, (resource["id"], response.text)
        rid = response.json()["id"]
        updated = client.put(f"/api/v1/admin/writing-resources/{rid}", json={
            "expected_generation": 0, "name": payload["name"],
            "source": payload["source"], "body": payload["body"],
        })
        assert updated.status_code == 200, (resource["id"], updated.text)
        published = client.post(f"/api/v1/admin/writing-resources/{rid}/publish", json={"expected_generation": 1})
        assert published.status_code == 200, published.text
        copied = client.post("/api/v1/my-writing-resources", json=payload)
        assert copied.status_code == 200, (resource["id"], copied.text)
        private_id = copied.json()["id"]
        private_update = client.put(f"/api/v1/my-writing-resources/{private_id}", json={
            "expected_generation": 1, "name": payload["name"],
            "source": payload["source"], "body": payload["body"],
        })
        assert private_update.status_code == 200, (resource["id"], private_update.text)
        overridden = client.put(project, json={"expected_revision": revision, "selections": [{
            "origin": "platform", "resource_id": rid, "personal_override": True,
            "body": payload["body"],
        }]})
        if resource["kind"] in ("genre", "genre_rule"):
            assert overridden.status_code == 422, overridden.text
            assert overridden.json()["detail"] == "GENRE_RESOURCE_IS_AUTOMATIC"
            continue
        if resource["kind"] == "reference":
            assert overridden.status_code == 422, overridden.text
            assert overridden.json()["detail"] == "REFERENCE_IS_AUTOMATIC"
            # Reference copies are automatically bound, never hand-selected.
            overridden = client.put(project, json={"expected_revision": revision, "selections": [{
                "origin": "personal", "resource_id": private_id,
            }]})
            assert overridden.status_code == 422, overridden.text
            continue
        assert overridden.status_code == 200, (resource["id"], overridden.text)
        revision += 1


@pytest.mark.parametrize("kind,body", [
    ("genre", {"catalog_id": "x", "fields": {"subgenres": ["invalid"]}}),
    ("genre", {"catalog_id": "x", "fields": {"subgenres": [{"name": "x", "hook": 1}]}}),
    ("genre", {"catalog_id": "x", "fields": {"subgenres": [{"name": "x"}]}}),
    ("genre", {"catalog_id": "x", "fields": {}, "setup_caps": {"power_scaling": "false"}}),
    ("expression_rule", {"roles": {}, "validation": {"not_is": "false"}}),
    ("expression_rule", {"roles": {}, "validation": {"parallel": 1}}),
])
def test_structured_body_types_reject_invalid_values(api,kind,body):
    client, _ = api
    response = client.post("/api/v1/admin/writing-resources", json=dict(name="invalid", kind=kind, source="test", body=body))
    assert response.status_code == 422, response.text


@pytest.mark.parametrize('body', [
    {'files': [{'path': f'{i}.md', 'content': 'text'} for i in range(81)]},
    {'files': [{'path': 'large.md', 'content': 'x' * 262144}]},
])
def test_personal_reference_rejects_unbounded_body(api, body):
    client, _ = api
    response = client.post('/api/v1/my-writing-resources', json={
        'name': 'large', 'kind': 'reference', 'source': 'private', 'body': body})
    assert response.status_code == 422


@pytest.mark.parametrize('chunked', [False, True])
def test_resource_http_rejects_oversized_request_before_parsing(chunked):
    from myink.api.main import app
    content = (iter([b'x' * 1024 * 1024] * 9) if chunked
               else b'x' * (8 * 1024 * 1024 + 1))
    response = TestClient(app).post('/api/v1/my-writing-resources',
        content=content, headers={'content-type': 'application/json'})
    assert response.status_code == 413


def test_archived_private_override_can_still_save_via_api(api):
    client, _ = api
    admin = '/api/v1/admin/writing-resources'
    payload = dict(name='style', kind='style', source='test', body={'profile': {'voice': 'platform'}})
    rid = client.post(admin, json=payload).json()['id']
    assert client.post(f'{admin}/{rid}/publish', json={'expected_generation': 0}).status_code == 200
    route = f'/api/v1/projects/{uuid.uuid4()}/writing-resources'
    chosen = dict(origin='platform', resource_id=rid, personal_override=True,
                  body={'profile': {'voice': 'private'}})
    assert client.put(route, json={'expected_revision': 0, 'selections': [chosen]}).status_code == 200
    archived = client.put(f'{admin}/{rid}', json=dict(expected_generation=1, name='archived',
        source='test', body=payload['body'], status='archived'))
    assert archived.status_code == 200
    chosen['body']['profile']['voice'] = 'edited private'
    saved = client.put(route, json={'expected_revision': 1, 'selections': [chosen]})
    assert saved.status_code == 200, saved.text
    selected = saved.json()['selections'][0]
    assert selected['body']['profile']['voice'] == 'edited private'
    assert selected['name'] == 'style' and selected['version'] == 1


def test_source_copy_and_sync_require_exact_generations_and_ack(api):
    client, app = api
    payload = dict(name='first',kind='style',source='platform',body={'profile':{'voice':'first'}})
    row = client.post('/api/v1/admin/writing-resources',json=payload).json()
    rid = row['id']
    assert client.post('/api/v1/my-writing-resources/from-platform',json={'source_resource_id':rid,'target_generation':1}).status_code == 409
    client.post(f'/api/v1/admin/writing-resources/{rid}/publish',json={'expected_generation':0})
    private = client.post('/api/v1/my-writing-resources/from-platform',json={'source_resource_id':rid,'target_generation':1,'name':'mine','body':{'profile':{'voice':'mine'}}})
    assert private.status_code == 200, private.text
    data = private.json()
    assert data['source_resource_id'] == rid and data['source_generation'] == 1
    assert data['body']['profile']['voice'] == 'mine'
    sync = f"/api/v1/my-writing-resources/{data['id']}/sync"
    assert client.post(sync,json={'expected_generation':1,'target_generation':1}).status_code == 422
    assert client.post(sync,json={'expected_generation':1,'target_generation':1,'acknowledge_overwrite':False}).status_code == 422
    assert client.post(sync,json={'expected_generation':1,'target_generation':1,'acknowledge_overwrite':1}).status_code == 422
    assert client.post(sync,json={'expected_generation':1,'target_generation':1,'acknowledge_overwrite':True}).json()['body']==payload['body']
    app.dependency_overrides[require_user] = lambda: str(uuid.UUID(int=2))
    assert client.post(sync,json={'expected_generation':2,'target_generation':1,'acknowledge_overwrite':True}).status_code == 404


def test_get_snapshot_initializes_persistent_defaults_and_requires_returned_revision(api):
    from myink.models import Project
    client,_=api
    pid=uuid.uuid4()
    with admin.new_session() as db:
        db.add(Project(id=pid,user_id=uuid.UUID(int=1),title='old book',genre='玄幻',form='long',creation_status='ready'))
        db.commit()
    payload=dict(name='default',kind='writing_rule',source='platform',body={'roles':{'writer':'DEFAULT'}})
    row=client.post('/api/v1/admin/writing-resources',json=payload).json()
    assert client.post(f"/api/v1/admin/writing-resources/{row['id']}/publish",json={'expected_generation':0}).status_code==200
    route=f'/api/v1/projects/{pid}/writing-resources'
    initial=client.get(route)
    assert initial.status_code==200,initial.text
    snapshot=initial.json()
    assert any(item['resource_id']==row['id'] for item in snapshot['selections'])
    assert client.get(route).json()==snapshot
    with admin.new_session() as db:
        assert db.get(ProjectWritingResources,pid).defaults_initialized is True
    assert client.put(route,json={'expected_revision':0,'selections':[]}).status_code==409
    saved=client.put(route,json={'expected_revision':snapshot['revision'],'selections':[]})
    assert saved.status_code==200,saved.text
    assert saved.json()['selections']==[item for item in snapshot['selections'] if item['kind'] not in ('writing_rule','expression_rule')]
    assert client.get(route).json()==saved.json()
