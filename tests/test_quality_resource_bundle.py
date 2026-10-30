"""New guidance uses the actual catalog/selection/message path, never forced on opt-outs."""
import pytest
from myink.workflow import prompts
from myink.writing_resource_runtime import bind_resources

RULE_IDS = {'writing-rule:scene-causality', 'expression-rule:dialogue', 'writing-rule:genre-pacing'}
STYLE_IDS = {'natural-narration', 'brisk-narration', 'character-narration'}

def definitions(monkeypatch):
    monkeypatch.setattr('myink.platform_configuration.load_configuration', lambda: {})
    from myink.writing_resource_seed import builtin_resources
    return {entry['id']: entry for entry in builtin_resources()}

def test_recommended_rules_are_valid_published_seed_candidates(monkeypatch):
    from myink.writing_resource_schemas import CreateResource
    entries = definitions(monkeypatch)
    assert RULE_IDS <= entries.keys()
    for rid in RULE_IDS:
        entry = {k: v for k, v in entries[rid].items() if k != 'id'}
        CreateResource(**entry)
        assert set(entry['body']['roles']) <= {'writer', 'planner', 'audit'}
        assert 'validation' not in entry['body']  # Guidance must not add hard validators.

@pytest.mark.parametrize('builder,role', [
    (lambda: prompts.plan_messages({}, '人物做出选择'), 'planner'),
    (lambda: prompts.write_messages({}, {}), 'writer'),
    (lambda: prompts.audit_messages('原稿', {}, {}, 1), 'audit'),
    (lambda: prompts.revise_messages('原稿', [], 1), 'writer'),
    (lambda: prompts.patch_messages({'draft': '原稿', 'chapter_seq': 1}), 'writer'),
    (lambda: prompts.short_write_messages({'chapter_count': 1}), 'writer'),
    (lambda: prompts.short_review_messages({'chapter_count': 1}, '原稿'), 'audit'),
    (lambda: prompts.short_revise_messages({'chapter_count': 1}, '原稿', {}), 'writer'),
])
def test_selected_quality_guidance_reaches_each_creative_stage(monkeypatch, builder, role):
    entries = definitions(monkeypatch)
    chosen = [{**entries[rid], 'kind': entries[rid]['kind']} for rid in sorted(RULE_IDS)]
    with bind_resources({'configured': True, 'selections': chosen}):
        content = '\n'.join(m['content'] for m in builder())
    with bind_resources({'configured': True, 'selections': []}):
        empty = '\n'.join(m['content'] for m in builder())
    for entry in chosen:
        rule = entry['body']['roles'].get(role)
        if rule:
            assert content.count(rule) == 1
            assert rule not in empty

def test_general_profiles_are_selectable_and_do_not_impose_pov_or_story_facts(monkeypatch):
    from myink.seed import STYLE_PRESETS
    entries = definitions(monkeypatch)
    presets = {item['id']: item for item in STYLE_PRESETS}
    assert STYLE_IDS <= presets.keys()
    for sid in STYLE_IDS:
        profile = presets[sid]['style_profile']
        assert 'pov' not in profile
        assert not profile.get('reference_excerpts')
        assert profile['narrative_voice']
        assert entries['style:' + sid]['body']['profile'] == profile
        messages = prompts.write_messages({}, {}, style_profile=profile)
        assert profile['narrative_voice'] in str(messages)


def test_publication_keeps_book_snapshots_and_explicit_opt_out(monkeypatch):
    from copy import deepcopy
    import uuid
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from myink.models import Project, ProjectSettings
    from myink.models.platform import PlatformConfiguration
    from myink.models.writing_resource import (WritingResource, WritingResourceRevision,
        PersonalWritingResource, ProjectWritingResources, WritingResourcePublication)
    from myink import writing_resources as service

    entries = definitions(monkeypatch)
    engine = create_engine('sqlite://')
    for model in (PlatformConfiguration, Project, ProjectSettings, WritingResource,
                  WritingResourceRevision, PersonalWritingResource, ProjectWritingResources,
                  WritingResourcePublication):
        model.__table__.create(engine)
    with Session(engine, expire_on_commit=False) as db:
        service.initialize_builtin_resources(db)
        pid, uid = uuid.uuid4(), uuid.uuid4()
        db.add(Project(id=pid, user_id=uid, title='资源冻结测试', genre='现实题材', form='short'))
        db.flush()
        first = service.capture_task_resources(db, pid, user_id=uid)
        assert RULE_IDS <= {s['resource_id'] for s in first['selections']}
        rid = 'expression-rule:dialogue'
        row = db.get(WritingResource, rid)
        changed = deepcopy(row.body)
        changed['roles']['writer'] = '管理员后来发布的对白要求'
        service.update_resource(db, rid, row.generation, dict(name=row.name, kind=row.kind, source=row.source, body=changed))
        service.publish(db, rid, row.generation, '更新对白规则')
        service.initialize_builtin_resources(db)
        assert db.get(WritingResource, rid).current_version == 2
        frozen = service.capture_task_resources(db, pid, user_id=uid)
        old = next(s for s in frozen['selections'] if s['resource_id'] == rid)
        assert old['version'] == 1
        assert old['body'] == entries[rid]['body']
        service.set_selection(db, pid, uid, frozen['revision'], [])
        empty = service.capture_task_resources(db, pid, user_id=uid)
        assert not RULE_IDS.intersection(s['resource_id'] for s in empty['selections'])
