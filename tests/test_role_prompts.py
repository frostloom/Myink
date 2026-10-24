from myink.prompt_catalog import prompt_catalog
from myink.writing_resource_runtime import bind_resources
from myink.workflow import prompts


def test_catalog_separates_protocol_and_business():
    for group in prompt_catalog():
        for template in group['templates']:
            assert template['editable_content']
            assert template['fixed_content']
            assert template['when']


def test_published_role_replaces_business_preserves_protocol():
    with bind_resources({'configured': False, 'role_prompts': {'writer': {'body': {'role':'writer', 'templates': {'system_write':'只写新的创作要求'}}}}}):
        messages = prompts.write_messages({}, {})
    assert '只写新的创作要求' in messages[0]['content']
    assert '=== CONTENT ===' in messages[0]['content']
    assert '句式禁令' not in messages[0]['content']


def test_old_snapshot_and_other_role_do_not_apply():
    with bind_resources({'configured':False}):
        original = prompts.write_messages({}, {})
    with bind_resources({'configured':False, 'role_prompts': {'audit': {'body': {'templates': {'system_write':'wrong'}}}}}):
        assert prompts.write_messages({}, {}) == original


def test_publication_draft_rollback_and_private_isolation():
    import pytest
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from myink.models.writing_resource import WritingResource, WritingResourceRevision, WritingResourcePublication
    from myink import writing_resources as svc
    group = prompt_catalog()[0]
    body = {'role': group['role'], 'templates': {t['id']: t['editable_content'] for t in group['templates']}}
    engine = create_engine('sqlite://')
    for model in (WritingResource, WritingResourceRevision, WritingResourcePublication):
        model.__table__.create(engine)
    with Session(engine) as db:
        row = svc.create_resource(db, {'name':'writer', 'kind':'role_prompt', 'source':'internal', 'body':body}, rid='role-prompt:writer')
        svc.publish(db, row.id, 0, 'initial')
        frozen = svc.capture_role_prompts(db)
        changed = {'role':'writer', 'templates':dict(body['templates'], system_write='新的正文创作要求')}
        svc.update_resource(db, row.id, row.generation, {'body':changed})
        assert svc.capture_role_prompts(db) == frozen
        assert svc.catalog(db) == []
        svc.publish(db, row.id, row.generation, 'next')
        assert svc.capture_role_prompts(db)['writer']['body'] == changed
        assert frozen['writer']['body'] == body
        with bind_resources({'role_prompts':frozen, 'configured':False}):
            assert '新的正文创作要求' not in prompts.write_messages({}, {})[0]['content']
        svc.publish(db, row.id, row.generation, 'restore', 1)
        assert svc.capture_role_prompts(db)['writer']['body'] == body
        with pytest.raises(HTTPException):
            svc.create_resource(db, {'name':'private', 'kind':'role_prompt', 'source':'private', 'body':body}, user_id='00000000-0000-0000-0000-000000000001')
        with pytest.raises(HTTPException):
            svc.update_resource(db, row.id, row.generation, {'body':dict(body, role='audit')})


def test_every_phase_replacement_preserves_its_fixed_contract():
    from myink.prompt_catalog import apply_role_prompts
    for group in prompt_catalog():
        for template in group['templates']:
            snapshot = {'role_prompts':{group['role']:{'body':{'templates':{template['id']:'自定义业务要求'}}}}}
            result = apply_role_prompts([{'role':'system','content':template['content']}], group['role'], snapshot)[0]['content']
            assert result.startswith('自定义业务要求')
            assert template['fixed_content'] in result


def test_provider_receives_edited_messages():
    from myink.providers.base import FallbackChain, ModelResponse
    class RecordingProvider:
        def generate(self, messages, **kwargs):
            self.messages = messages
            return ModelResponse(content='正文', model_id='stub')
    provider = RecordingProvider()
    with bind_resources({'configured':True, 'selections':[], 'role_prompts':{'writer':{'body':{'templates':{'system_write':'以动作推动情节'}}}}}):
        FallbackChain(provider, ['stub']).generate(prompts.write_messages({}, {}))
    assert '以动作推动情节' in provider.messages[0]['content']
    assert '=== CONTENT ===' in provider.messages[0]['content']


def test_composed_revision_replaces_both_phases():
    snapshot = {'configured':True, 'selections':[], 'role_prompts':{'writer':{'body':{'templates':{
        'system_write':'正文创作自定义', 'system_revise':'修订创作自定义'}}}}}
    with bind_resources(snapshot):
        messages = prompts.revise_messages('原文', [], 1)
    system = '\n'.join(m['content'] for m in messages if m['role']=='system')
    assert '正文创作自定义' in system
    assert '修订创作自定义' in system
    assert '=== CONTENT ===' in system
    assert '=== RESPONSES ===' in system


def test_batch_planner_provider_uses_published_business_and_fixed_json():
    from myink.workflow.batch_graph import _batch_plan_messages, _BATCH_PLAN_PROMPT
    from myink.providers.base import FallbackChain, ModelResponse
    assert _BATCH_PLAN_PROMPT == prompts.SYSTEM_BATCH_PLAN
    class RecordingProvider:
        def generate(self, messages, **kwargs):
            self.messages = messages
            return ModelResponse(content='{"chapters":[]}', model_id='stub')
    provider = RecordingProvider()
    snapshot = {'configured': True, 'selections': [], 'role_prompts': {'planner': {'body': {
        'role': 'planner', 'templates': {'system_batch_plan': '让每批次剧情沿核心矛盾递进'}}}}}
    with bind_resources(snapshot):
        messages = _batch_plan_messages({'start_chapter': 2, 'size': 3})
        FallbackChain(provider, ['stub']).generate(messages, json_mode=True)
    system = provider.messages[0]['content']
    assert '让每批次剧情沿核心矛盾递进' in system
    assert '整体推进蓝图' not in system
    assert '输出严格 JSON' in system
    assert '"chapters"' in system and '"goal"' in system and '"outline_advance"' in system
    assert 'N=3' in provider.messages[1]['content']


def test_older_role_publication_keeps_missing_new_phase_default():
    from myink.writing_resource_schemas import validate_resource_body
    from myink.workflow.batch_graph import _batch_plan_messages
    group = next(g for g in prompt_catalog() if g['role'] == 'planner')
    old_body = {'role':'planner', 'templates':{t['id']:t['editable_content']
                for t in group['templates'] if t['id'] != 'system_batch_plan'}}
    old_body['templates']['system_plan'] = '保留管理员已有章节规划草稿'
    validate_resource_body('role_prompt', old_body)
    with bind_resources({'configured':False, 'role_prompts':{'planner':{'body':old_body}}}):
        messages = _batch_plan_messages({'start_chapter': 1, 'size': 2})
    assert messages[0]['content'] == prompts.SYSTEM_BATCH_PLAN
    assert 'system_batch_plan' not in old_body['templates']
    assert old_body['templates']['system_plan'] == '保留管理员已有章节规划草稿'


def test_unconfigured_role_prompt_cannot_bypass_final_budget(monkeypatch):
    import pytest
    from dataclasses import replace
    from myink.config import settings
    from myink.context_budget import ContextBudgetExceeded
    from myink.workflow.batch_graph import _batch_plan_messages
    monkeypatch.setattr('myink.workflow.prompts.settings', replace(settings, request_token_budget=8000))
    cases = [
        ('writer', 'system_write', lambda: prompts.write_messages({}, {})),
        ('planner', 'system_short_creation', lambda: prompts.short_creation_messages([], {})),
        ('extract', 'system_style_extract', lambda: prompts.style_extract_messages(['作者样本'], {})),
        ('planner', 'system_batch_plan', lambda: _batch_plan_messages({'start_chapter':1, 'size':2})),
    ]
    for role, phase, build in cases:
        snapshot = {'configured':False, 'role_prompts':{role:{'body':{'templates':{phase:'要求'*10000}}}}}
        with bind_resources(snapshot), pytest.raises(ContextBudgetExceeded):
            build()


def test_automatic_role_budget_trims_optional_context_and_keeps_required_input(monkeypatch):
    from copy import deepcopy
    from dataclasses import replace
    from myink.config import settings
    from myink.context_budget import estimate_tokens
    monkeypatch.setattr('myink.workflow.prompts.settings', replace(settings, request_token_budget=8000))
    context = {'long_term_facts': [
        {'content':'必需世界规则', 'is_hard':True},
        *[{'content':f'可选事实{i}：' + '过往经历' * 150, 'is_hard':False} for i in range(10)],
    ], 'short_context':[{'kind':'user_instruction', 'text':'作者要求保留前章接续'}]}
    original = deepcopy(context)
    snapshot = {'configured':False, 'role_prompts':{'writer':{'body':{
        'templates':{'system_write':'角色创作要求：' + '动作推进。' * 300}}}}}
    with bind_resources(snapshot):
        messages = prompts.write_messages(context, {})
    joined = '\n'.join(message['content'] for message in messages)
    assert estimate_tokens(messages) <= prompts._tool_prompt_budget()
    assert '角色创作要求：' in joined
    assert '必需世界规则' in joined and '作者要求保留前章接续' in joined
    assert '=== CONTENT ===' in joined
    assert 0 < sum(f'可选事实{i}：' in joined for i in range(10)) < 10
    assert context == original


def test_role_supplement_publication_lifecycle_reaches_provider(monkeypatch):
    from copy import deepcopy
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from myink.models.writing_resource import WritingResource, WritingResourceRevision, WritingResourcePublication
    from myink import providers, writing_resources as svc
    from myink.providers.base import FallbackChain, ModelResponse
    from myink.writing_resource_schemas import validate_resource_body
    config = {'version':0, 'connections':{}, 'model_routes':{}, 'prompts':{'writer':'当前全局值不应污染冻结调用'}}
    monkeypatch.setattr('myink.platform_configuration.load_configuration', lambda:config)
    monkeypatch.setattr('myink.platform_readiness.require_ready', lambda *a, **k:None)
    class RecordingProvider:
        def generate(self, messages, **kwargs):
            self.messages = messages
            return ModelResponse(content='正文', model_id='stub')
    provider = RecordingProvider()
    monkeypatch.setattr(providers, '_platform_chain', lambda _:FallbackChain(provider, ['stub']))
    def generate(snapshot):
        with bind_resources(snapshot):
            response = providers._central_chain('writer', {}, False).generate(prompts.write_messages({}, {}))
        assert response.error is None
        return '\n'.join(message['content'] for message in provider.messages)
    legacy = {'configured':False, 'role_prompts':{}, 'legacy_role_supplements':{'writer':'冻结旧平台补充'}}
    assert '冻结旧平台补充' in generate(legacy)
    body = {'role':'writer', 'templates':{'system_write':'以动作推动冲突'}, 'supplement':'初始共同要求'}
    validate_resource_body('role_prompt', body)
    engine = create_engine('sqlite://')
    for model in (WritingResource, WritingResourceRevision, WritingResourcePublication):
        model.__table__.create(engine)
    with Session(engine) as db:
        row = svc.create_resource(db, {'name':'writer', 'kind':'role_prompt', 'source':'internal', 'body':body}, rid='role-prompt:writer')
        svc.publish(db, row.id, 0, 'initial')
        frozen = dict(legacy, role_prompts=svc.capture_role_prompts(db))
        assert '初始共同要求' in generate(frozen)
        assert '冻结旧平台补充' not in generate(frozen)
        changed = dict(body, supplement='修改共同要求')
        svc.update_resource(db, row.id, row.generation, {'body':changed})
        assert '初始共同要求' in generate(dict(legacy, role_prompts=svc.capture_role_prompts(db)))
        svc.publish(db, row.id, row.generation, 'next')
        assert '修改共同要求' in generate(dict(legacy, role_prompts=svc.capture_role_prompts(db)))
        assert '初始共同要求' in generate(frozen)
        svc.publish(db, row.id, row.generation, 'restore', 1)
        assert '初始共同要求' in generate(dict(legacy, role_prompts=svc.capture_role_prompts(db)))
        svc.update_resource(db, row.id, row.generation, {'body':dict(body, supplement='')})
        svc.publish(db, row.id, row.generation, 'clear')
        cleared = generate(dict(legacy, role_prompts=svc.capture_role_prompts(db)))
        assert '初始共同要求' not in cleared and '冻结旧平台补充' not in cleared
        assert '当前全局值不应污染冻结调用' not in cleared
    migrated = deepcopy(frozen)
    migrated.update(configured=True, selections=[{'kind':'writing_rule', 'body':{'roles':{'writer':'初始共同要求'}}}])
    assert generate(migrated).count('初始共同要求') == 1


def test_role_supplement_rejects_nontext_and_unknown_fields():
    import pytest
    from myink.writing_resource_schemas import validate_resource_body
    body = {'role':'writer', 'templates':{'system_write':'写作要求'}}
    for invalid in (None, {}, 123, []):
        with pytest.raises(ValueError, match='supplement must be text'):
            validate_resource_body('role_prompt', dict(body, supplement=invalid))
    with pytest.raises(ValueError, match='Invalid role prompt body'):
        validate_resource_body('role_prompt', dict(body, fixed_content='不能编辑协议'))
