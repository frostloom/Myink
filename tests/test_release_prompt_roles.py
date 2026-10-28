"""Release regressions for short idea attribution and personal model routing."""
import json
import pytest
from fastapi import HTTPException

LEGACY_OPENING = ('想写个什么样的短篇？先说一句大方向就行——比如「一个渡口老人等最后一班船」，'
                  '我来陪你把它聊成能开写的方案。')
ROLES = ('writer', 'planner', 'extract', 'validator_l2', 'audit', 'summarize')


@pytest.mark.parametrize('configured', [False, True])
def test_short_history_normalizes_only_stock_opening_and_retains_attribution_with_publication(configured):
    from myink.workflow.prompts import short_creation_messages
    from myink.prompt_catalog import prompt_catalog
    from myink.writing_resource_runtime import bind_resources
    from myink.api.routes_short_creation import OPENING
    group = next(g for g in prompt_catalog() if g['role'] == 'planner')
    templates = {t['id']: '自定义规划指导' for t in group['templates']}
    history = [{'role': 'assistant', 'content': LEGACY_OPENING},
               {'role': 'user', 'content': '随便写，你决定'},
               {'role': 'assistant', 'content': '我提出一个新故事'},
               {'role': 'user', 'content': '我想保留渡口老人'}]
    card = {'working_title': '已确认的名字', 'direction': '渡口老人'}
    with bind_resources({'configured': configured, 'role_prompts': {'planner': {'body': {'templates': templates}}}}):
        messages = short_creation_messages(history, card)
    assert '渡口' not in OPENING
    assert messages[0]['content'].startswith('自定义规划指导')
    assert not any(m['content'] == LEGACY_OPENING for m in messages)
    assert {'role': 'user', 'content': '我想保留渡口老人'} in messages
    assert {'role': 'assistant', 'content': '我提出一个新故事'} in messages
    rules = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
    assert '助手建议不等于用户设定' in rules
    assert '随便写' in rules and '新方案卡' in rules
    assert json.loads(messages[-1]['content'].split('\n', 1)[1].split('\n\n请继续')[0]) == card
    assert history[0]['content'] == LEGACY_OPENING
    user_history = [{'role': 'user', 'content': LEGACY_OPENING}]
    assert user_history[0] in short_creation_messages(user_history, {})


@pytest.mark.parametrize('role', ROLES)
def test_personal_roles_save_load_runtime_reset_and_hidden_cleanup(temp_user, monkeypatch, role):
    from myink import platform_configuration as pc, providers
    from myink.api.routes_environment import EnvironmentBody, put_environment
    from myink.environment import load_environment, load_raw
    from myink.providers.credentials import encrypt_api_key
    config = pc.empty_configuration()
    config['version'] = 1
    config['connections'] = {key: {'name': key, 'model': key, 'enabled': True,
        'user_visible': key == 'selected', 'protocol': 'openai', 'base_url': 'https://example.com',
        'api_key_encrypted': encrypt_api_key('test')} for key in ('default', 'selected')}
    config['model_routes'] = {'writer': 'custom:default'}
    monkeypatch.setattr(pc, 'load_configuration', lambda: config)
    result = put_environment(EnvironmentBody(model_routes={role: 'custom:selected'}), temp_user)
    assert result['model_routes'][role] == 'custom:selected'
    assert load_environment(temp_user)['model_routes'][role] == 'custom:selected'
    assert providers.make_user_chain(role, temp_user).chain == ['selected']
    assert pc.resolve_connection(role, {role: 'custom:selected'})['model'] == 'selected'
    result = put_environment(EnvironmentBody(reset_preferences=[f'model_routes.{role}']), temp_user)
    assert role not in result['model_routes']
    assert providers.make_user_chain(role, temp_user).chain == ['default']
    put_environment(EnvironmentBody(model_routes={role: 'custom:selected'}), temp_user)
    assert role not in put_environment(EnvironmentBody(model_routes={role: ''}), temp_user)['model_routes']
    put_environment(EnvironmentBody(model_routes={role: 'custom:selected'}), temp_user)
    config['connections']['selected']['user_visible'] = False
    assert load_environment(temp_user)['model_routes'] == {}
    assert providers.make_user_chain(role, temp_user).chain == ['default']
    with pytest.raises(HTTPException):
        put_environment(EnvironmentBody(model_routes={role: 'custom:selected'}), temp_user)
    put_environment(EnvironmentBody(thinking_enabled=False), temp_user)
    assert role not in load_raw(temp_user)['models']
