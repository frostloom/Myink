"""Release is exact-scope, atomic, idempotent and preserves private/frozen/history."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from myink.models.writing_resource import (WritingResource, WritingResourceRevision,
    WritingResourcePublication, PersonalWritingResource, ProjectWritingResources)

spec = importlib.util.spec_from_file_location('craft_release', Path(__file__).parents[1] / 'scripts/publish-writing-craft.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture
def setup(monkeypatch):
    from myink.models import Project
    from myink.writing_resource_seed import builtin_resources
    from myink import writing_resources as svc
    monkeypatch.setattr('myink.platform_configuration.load_configuration', lambda: {})
    engine = create_engine('sqlite://')
    for model in (Project, WritingResource, WritingResourceRevision, WritingResourcePublication,
                  PersonalWritingResource, ProjectWritingResources):
        model.__table__.create(engine)
    expected = {r['id']: deepcopy(r) for r in builtin_resources() if r['id'] in release.UPGRADE}
    for rid in release.RETIRE:
        expected[rid] = dict(id=rid, name='历史示例', kind='style', source='seed.py:STYLE_PRESETS', body={'profile': {'narrative_voice': '历史文风'}})
    for rid in release.UPGRADE:
        expected[rid]['body'] = deepcopy(expected[rid]['body'])
        expected[rid]['body']['old_fixture'] = True
    with Session(engine, expire_on_commit=False) as db:
        for rid, item in expected.items():
            row = svc.create_resource(db, {k: item[k] for k in release.FIELDS}, rid=rid)
            svc.publish(db, rid, row.generation, 'old')
        pid, uid = uuid.uuid4(), uuid.uuid4()
        oldid = sorted(release.RETIRE)[0]
        db.add(Project(id=pid, user_id=uid, title='Author book', genre='现实题材'))
        db.flush()
        frozen = [{'resource_id': oldid, 'kind': 'style', 'body': expected[oldid]['body'], 'version': 1}]
        db.add(ProjectWritingResources(project_id=pid, selections=deepcopy(frozen)))
        private = svc.create_resource(db, dict(name='Private', kind='style', source='author', body=deepcopy(expected[oldid]['body'])), user_id=uid)
        private.source_resource_id = oldid
        db.commit()
        yield db, expected, pid, private.id, frozen


def test_upgrade_preserves_old_publications_private_and_frozen_selections(setup):
    db, expected, pid, privateid, frozen = setup
    before = {r.resource_id: deepcopy(r.document) for r in db.scalars(select(WritingResourceRevision))}
    assert not release.apply_bundle(db, expected)['applied']
    assert all(db.get(WritingResource, rid) is not None for rid in release.RETIRE)
    result = release.apply_bundle(db, expected, apply=True)
    assert set(result['upgraded']) == release.UPGRADE
    assert set(result['added']) == release.ADD
    assert all(db.get(WritingResource, rid).current_version == 1 for rid in release.ADD)
    assert db.get(WritingResource, 'genre-rule:craft-realism-suspense').current_version == 1
    assert set(result['removed_current_entries']) == release.RETIRE
    assert all(db.get(WritingResource, rid) is None for rid in release.RETIRE)
    for rid, document in before.items():
        assert db.get(WritingResourceRevision, (rid, 1)).document == document
        assert db.get(WritingResourcePublication, (rid, 1)) is not None
    assert all(db.get(WritingResource, rid).current_version == 2 for rid in release.UPGRADE)
    assert db.get(ProjectWritingResources, pid).selections == frozen
    assert db.get(PersonalWritingResource, privateid).body == frozen[0]['body']
    rerun = release.apply_bundle(db, expected, apply=True)
    assert not rerun['added'] and not rerun['upgraded'] and not rerun['removed_current_entries']


def test_custom_admin_definition_blocks_all_changes_before_mutation(setup):
    db, expected, *_ = setup
    row = db.get(WritingResource, 'writing-rule:continuity')
    row.body = {'roles': {'writer': 'Administrator custom'}}
    db.flush()
    with pytest.raises(ValueError, match='Unpublished administrator edits'):
        release.apply_bundle(db, expected, apply=True)
    assert all(db.get(WritingResource, rid) is not None for rid in release.RETIRE)
    assert all(db.get(WritingResource, rid).current_version == 1 for rid in release.UPGRADE)
    assert all(db.get(WritingResource, rid) is None for rid in release.ADD)
    with pytest.raises(ValueError, match='scope'):
        release.apply_bundle(db, {}, apply=True)


def test_new_id_collision_preserves_administrator_publication(setup):
    from myink import writing_resources as svc
    db, expected, *_ = setup
    rid = next(iter(release.ADD))
    custom = svc.create_resource(db, dict(name='Admin rule', kind='genre_rule', source='admin',
        body={'genre_ids': ['xianshi'], 'roles': {'writer': 'Admin custom method'}}), rid=rid)
    svc.publish(db, rid, custom.generation, 'Administrator created first')
    before = deepcopy(custom.publication)
    with pytest.raises(ValueError, match='Administrator definition differs'):
        release.apply_bundle(db, expected, apply=True)
    assert db.get(WritingResource, rid).publication == before
    assert all(db.get(WritingResource, old) is not None for old in release.RETIRE)
    assert all(db.get(WritingResource, old).current_version == 1 for old in release.UPGRADE)
