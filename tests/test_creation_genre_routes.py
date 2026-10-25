"""题材发布与真实建书 API 的隔离数据库回归。"""
from copy import deepcopy
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update

from conftest import identity_headers
from myink.api.main import app
from myink.db import new_session, tenant_session
from myink.models import ProjectSettings, ShortCreationSession
from myink.models.writing_resource import WritingResource, WritingResourceRevision, WritingResourcePublication
from myink import writing_resources as resources
from myink.short import creation

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def publication():
    rid = 'genre:xiuxian'
    with new_session() as db:
        row = resources.resource(db, rid)
        original = {key: deepcopy(getattr(row, key)) for key in (
            'name', 'body', 'source', 'status', 'generation', 'current_version', 'publication')}
        max_version = db.scalar(select(func.max(WritingResourceRevision.version)).where(WritingResourceRevision.resource_id == rid))
        body = deepcopy(row.body)
        body['fields']['pacing'] = 'ROUTE_PUBLISHED_PACING'
        resources.update_resource(db, rid, row.generation, {'body': body})
        resources.publish(db, rid, row.generation, 'route regression')
        db.commit()
    try:
        yield rid
    finally:
        with new_session() as db:
            db.execute(delete(WritingResourcePublication).where(WritingResourcePublication.resource_id == rid,
                WritingResourcePublication.generation > original['generation']))
            db.execute(delete(WritingResourceRevision).where(WritingResourceRevision.resource_id == rid,
                WritingResourceRevision.version > (max_version or 0)))
            db.execute(update(WritingResource).where(WritingResource.id == rid).values(**original))
            db.commit()


def archive(rid):
    with new_session() as db:
        row = resources.resource(db, rid)
        resources.update_resource(db, rid, row.generation, {'status': 'archived'})
        db.commit()


def new_session_card(user_id, genre="修仙"):
    card = {field: '已有内容' for field in creation.REQUIRED_CARD_FIELDS}
    card.update(genre=genre, working_title='发布题材短篇', chapter_count=1, chars_per_chapter=1000)
    with new_session() as db:
        row = ShortCreationSession(user_id=uuid.UUID(user_id), card=card, status='active')
        db.add(row)
        db.flush()
        sid = row.id
        db.commit()
    return sid


def test_long_creation_uses_published_genre_snapshot(publication, temp_user):
    headers = identity_headers(temp_user)
    catalog = client.get('/api/v1/genre-packs', headers=headers)
    assert catalog.status_code == 200
    assert next(item for item in catalog.json() if item['id'] == 'xiuxian')['pacing'] == 'ROUTE_PUBLISHED_PACING'
    response = client.post('/api/v1/projects', headers=headers, json={'title': '发布题材长篇', 'primary_id': 'xiuxian'})
    assert response.status_code == 200, response.text
    with tenant_session(response.json()['id']) as db:
        stored = db.scalar(select(ProjectSettings).where(ProjectSettings.project_id == uuid.UUID(response.json()['id']))).genre_pack
        assert stored['pacing'] == 'ROUTE_PUBLISHED_PACING'
        assert stored['_resource_publications'][0]['resource_id'] == publication


def test_long_creation_replay_retains_snapshot_after_archive(publication, temp_user):
    headers = identity_headers(temp_user)
    body = {'title': '幂等快照', 'primary_id': 'xiuxian', 'request_id': str(uuid.uuid4())}
    first = client.post('/api/v1/projects', headers=headers, json=body)
    assert first.status_code == 200, first.text
    archive(publication)
    replay = client.post('/api/v1/projects', headers=headers, json=body)
    assert replay.status_code == 200, replay.text
    assert replay.json()['id'] == first.json()['id']
    stale = client.post('/api/v1/projects', headers=headers, json={**body, 'request_id': str(uuid.uuid4())})
    assert stale.status_code == 400, stale.text


@pytest.mark.parametrize('genre', ['修仙', '新版仙侠创作'])
def test_short_commit_returns_readable_error_for_archived_genre(publication, temp_user, stub_provider, genre):
    stub_provider('金丹', '金丹')
    with new_session() as db:
        row = resources.resource(db, publication)
        resources.update_resource(db, row.id, row.generation, {'name': genre})
        resources.publish(db, row.id, row.generation, 'rename')
        db.commit()
    sid = new_session_card(temp_user, genre)
    archive(publication)
    response = client.post(f'/api/v1/short/creation/sessions/{sid}/commit', headers=identity_headers(temp_user), json={})
    assert response.status_code == 400, response.text
    assert '下架' in response.json()['detail']


def test_short_retry_keeps_published_snapshot_after_archive(publication, temp_user, stub_provider, monkeypatch):
    stub_provider('金丹', '金丹')
    from myink.api import routes_book
    captured = []
    def plan(pid, body, genre, genre_pack, chapters, db):
        captured.append(deepcopy(genre_pack))
        return {'outline_error': 'stub plan unavailable'}, []
    monkeypatch.setattr(routes_book, '_short_outline_draft', plan)
    sid = new_session_card(temp_user)
    headers = identity_headers(temp_user)
    first = client.post(f'/api/v1/short/creation/sessions/{sid}/commit', headers=headers, json={})
    assert first.status_code == 502, first.text
    assert captured[0]['pacing'] == 'ROUTE_PUBLISHED_PACING'
    archive(publication)
    retry = client.post(f'/api/v1/short/creation/sessions/{sid}/commit', headers=headers, json={})
    assert retry.status_code == 502, retry.text
    assert captured == [captured[0], captured[0]]
