"""新建书读取平台发布题材；临时 SQLite，不读取本机部署数据库。"""
from contextlib import contextmanager
from copy import deepcopy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from myink import genre_catalog as genres, writing_resources as resources
from myink.models.writing_resource import WritingResource, WritingResourceRevision, WritingResourcePublication


@pytest.fixture
def library(monkeypatch):
    engine = create_engine('sqlite://')
    for model in (WritingResource, WritingResourceRevision, WritingResourcePublication):
        model.__table__.create(engine)
    with Session(engine) as db:
        @contextmanager
        def session():
            db.flush()
            yield db
        monkeypatch.setattr('myink.db.new_session', session)
        monkeypatch.setattr('myink.platform_configuration.load_configuration', lambda: {
            'genre_packs': {'xiuxian': {'pacing': 'STALE_LEGACY_PACING'}}})
        yield db
    engine.dispose()


def release(db, pid='xiuxian', *, name='已发布修仙', pacing='PUBLISHED_PACING'):
    pack = genres.PACKS[pid]
    body = {'catalog_id': pid, 'fields': {key: deepcopy(pack[key]) for key in genres.FIELD_KEYS},
            'setup_caps': {'power_scaling': False, 'numerical_system': False, 'era_research': True}}
    body['fields']['pacing'] = pacing
    row = resources.create_resource(db, {'name': name, 'kind': 'genre', 'source': 'test', 'body': body}, rid='genre:' + pid)
    resources.publish(db, row.id, 0, 'v1')
    return row


def test_creation_catalog_and_snapshot_use_published_content(library):
    release(library)
    entry = next(item for item in genres.catalog_entries() if item['id'] == 'xiuxian')
    assert entry['pacing'] == 'PUBLISHED_PACING'
    assert entry['name'] == '已发布修仙'
    snapshot = genres.build_book_pack('xiuxian', None)
    assert snapshot['pacing'] == snapshot['baseline']['pacing'] == 'PUBLISHED_PACING'
    assert snapshot['source_name'] == '已发布修仙'
    assert genres.setup_capabilities(snapshot)['era_research'] is True
    assert snapshot['_resource_publications'][0] == {
        'resource_id': 'genre:xiuxian', 'version': 1, 'generation': 1}


def test_draft_edits_do_not_change_new_book_content(library):
    row = release(library)
    body = deepcopy(row.body)
    body['fields']['pacing'] = 'UNPUBLISHED_DRAFT'
    resources.update_resource(library, row.id, row.generation, {'body': body, 'name': '未发布新名', 'status': 'draft'})
    assert genres.get_root('xiuxian')['pacing'] == 'PUBLISHED_PACING'
    assert genres.build_book_pack('xiuxian', None)['source_name'] == '已发布修仙'


def test_archived_genre_is_not_listed_and_stale_selection_is_rejected(library):
    row = release(library)
    resources.update_resource(library, row.id, row.generation, {'status': 'archived'})
    assert genres.catalog_entries() == []
    assert genres.get_root('xiuxian') is None
    with pytest.raises(ValueError, match='下架|发布'):
        genres.build_book_pack('xiuxian', None)


def test_unpublished_genre_never_falls_back_to_builtin(library):
    resources.create_resource(library, {'name': '草稿', 'kind': 'genre', 'source': 'test',
        'body': {'catalog_id': 'xiuxian', 'fields': {'pacing': 'DRAFT'}}}, rid='genre:xiuxian')
    assert genres.catalog_entries() == []
    with pytest.raises(ValueError, match='下架|发布'):
        genres.build_book_pack('xiuxian', None)


def test_rollback_affects_future_books_but_preserves_existing_snapshot(library):
    row = release(library)
    old = genres.build_book_pack('xiuxian', None)
    body = deepcopy(row.body)
    body['fields']['pacing'] = 'VERSION_TWO'
    resources.update_resource(library, row.id, row.generation, {'body': body})
    resources.publish(library, row.id, row.generation, 'v2')
    second = genres.build_book_pack('xiuxian', None)
    assert second['pacing'] == 'VERSION_TWO'
    resources.publish(library, row.id, row.generation, 'rollback', version=1)
    restored = genres.build_book_pack('xiuxian', None)
    assert restored['pacing'] == old['pacing'] == 'PUBLISHED_PACING'
    assert restored['_resource_publications'][0]['version'] == 1
    assert restored['_resource_publications'][0]['generation'] == 4
    assert second['pacing'] == 'VERSION_TWO'


def test_primary_secondary_publications_are_both_frozen(library):
    release(library)
    secondary = release(library, 'xitong', name='已发布系统', pacing='SECONDARY_PACING')
    snapshot = genres.build_book_pack('xiuxian', 'xitong')
    assert snapshot['pacing'] == 'PUBLISHED_PACING'
    assert snapshot['secondary_name'] == '已发布系统'
    assert [item['resource_id'] for item in snapshot['_resource_publications']] == ['genre:xiuxian', 'genre:xitong']
    resources.update_resource(library, secondary.id, secondary.generation, {'status': 'archived'})
    with pytest.raises(ValueError, match='下架|发布'):
        genres.build_book_pack('xiuxian', 'xitong')
    assert snapshot['_secondary_snapshot']['pacing'] == 'SECONDARY_PACING'


def test_conversational_creation_can_resolve_published_name(library):
    release(library, name='新版题材名字')
    assert genres.resolve_pack_id('新版题材名字') == 'xiuxian'
    assert genres.build_book_pack('新版题材名字', None)['pacing'] == 'PUBLISHED_PACING'


def test_pre_resource_installation_retains_legacy_defaults(library):
    assert len(genres.catalog_entries()) == 37
    assert genres.build_book_pack('xiuxian', None)['pacing'] == 'STALE_LEGACY_PACING'


def test_archived_published_name_remains_recognizable_as_unavailable(library):
    row = release(library, name='新版仙侠创作')
    resources.update_resource(library, row.id, row.generation, {'status': 'archived'})
    assert genres.resolve_pack_id('新版仙侠创作') == 'xiuxian'
    with pytest.raises(ValueError, match='下架|发布'):
        genres.build_book_pack('新版仙侠创作', None)
    assert genres.resolve_pack_id('完全自由创作题材') is None
