"""题材锁路由单测：只替换数据库边界，不依赖运行中的服务。"""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest
from fastapi import HTTPException

from myink.api import routes_book, routes_genre
from myink.models import Project


@pytest.fixture
def book_store(monkeypatch):
    project = Project(id=uuid.uuid4(), title='旧书名', genre='历史', form='long',
                      creation_status='ready', current_chapter=0)
    settings = SimpleNamespace(genre_pack={'source_id': 'history'}, version=1)
    db = Mock()
    db.get.return_value = project
    db.scalar.return_value = project

    @contextmanager
    def session(*args):
        yield db

    for module in (routes_book, routes_genre):
        monkeypatch.setattr(module, 'tenant_session', session)
        monkeypatch.setattr(module, 'get_settings', lambda *_: settings)
        monkeypatch.setattr(module, 'is_managed_pack', lambda _: True)
    monkeypatch.setattr(routes_book, 'new_session', session)
    monkeypatch.setattr(routes_genre, 'apply_field_edits', lambda pack, fields: {**pack, **fields})
    monkeypatch.setattr(routes_genre, 'restore_baseline', lambda _: {'source_id': 'history', 'pacing': 'baseline'})
    monkeypatch.setattr(routes_genre, 'public_pack', lambda pack: pack)
    return project, settings


@pytest.mark.parametrize('state', ['ready', 'legacy_ready'])
@pytest.mark.parametrize('action', ['name', 'fields', 'restore'])
def test_completed_long_genre_write_is_rejected(book_store, monkeypatch, state, action):
    project, settings = book_store
    project.creation_status = state
    monkeypatch.setattr(routes_book, 'is_managed_pack', lambda _: False)
    with pytest.raises(HTTPException) as error:
        if action == 'name':
            routes_book.update_project(str(project.id), routes_book.ProjectUpdateBody(genre='都市'))
        elif action == 'fields':
            routes_genre.put_genre_pack(str(project.id), routes_genre.GenrePackFieldsBody(pacing='新节奏'))
        else:
            routes_genre.restore_genre_pack(str(project.id))
    assert error.value.status_code == 409
    assert '题材' in error.value.detail
    assert project.genre == '历史'
    assert settings.genre_pack == {'source_id': 'history'}
    assert settings.version == 1


def test_completed_long_allows_same_genre_and_unrelated_metadata(book_store):
    project, _ = book_store
    result = routes_book.update_project(str(project.id), routes_book.ProjectUpdateBody(
        genre='历史', title='新书名', target_words=3000))
    assert result['title'] == '新书名'
    assert result['genre'] == '历史'
    assert result['target_words'] == 3000


@pytest.mark.parametrize('form,state', [('long', 'draft'), ('long', 'setup_confirmed'), ('short', 'ready')])
def test_draft_and_short_keep_genre_editing(book_store, monkeypatch, form, state):
    project, settings = book_store
    project.form, project.creation_status = form, state
    monkeypatch.setattr(routes_book, 'is_managed_pack', lambda _: False)
    assert routes_book.update_project(str(project.id), routes_book.ProjectUpdateBody(genre='都市'))['genre'] == '都市'
    assert routes_genre.put_genre_pack(str(project.id), routes_genre.GenrePackFieldsBody(pacing='新节奏'))['pacing'] == '新节奏'
    assert routes_genre.restore_genre_pack(str(project.id))['pacing'] == 'baseline'
    assert settings.version == 3
