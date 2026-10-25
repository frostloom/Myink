"""Writer environment contains published selections and non-model preferences."""
import uuid
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from myink.api.routes_environment import EnvironmentBody, get_environment, put_environment
from myink.environment import save_raw


def test_environment_omitting_fields_preserves_preferences(temp_user):
    put_environment(EnvironmentBody(rankings={'enabled': False, 'timeout': 8, 'limit': 5},
                                    thinking_enabled=True), user_id=temp_user)
    out = put_environment(EnvironmentBody(), user_id=temp_user)
    assert out['rankings'] == {'enabled': False, 'timeout': 8, 'limit': 5}
    assert out['thinking_enabled'] is True
    assert out['model_connections'] == []
    assert out['available_models'] == []


@pytest.mark.parametrize('items', [[], [{'id': str(uuid.uuid4()), 'name': 'private', 'protocol': 'openai',
    'base_url': 'https://example.com', 'model': 'model', 'api_key': 'secret'}]])
def test_environment_rejects_all_connection_writes(temp_user, items):
    with pytest.raises(HTTPException) as exc:
        put_environment(EnvironmentBody(model_connections=items), user_id=temp_user)
    assert exc.value.status_code == 403


def test_environment_published_selection_and_legacy_redaction(temp_user, monkeypatch):
    from myink import platform_configuration as pc
    from myink.providers.connections import pack_model_settings
    config = pc.empty_configuration()
    config['connections'] = {'published': {'name': 'Published', 'enabled': True, 'user_visible': True},
                             'internal': {'name': 'Internal', 'enabled': True, 'user_visible': False}}
    monkeypatch.setattr(pc, 'load_configuration', lambda: config)
    save_raw(temp_user, {'models': pack_model_settings({'writer': 'custom:legacy'}, {
        'legacy': {'name': 'Old', 'base_url': 'https://private', 'api_key_encrypted': 'cipher'}})})
    out = get_environment(user_id=temp_user)
    assert out['model_routes'] == {}
    assert out['model_connections'] == []
    assert out['available_models'] == [{'id': 'custom:published', 'name': 'Published'}]
    assert 'private' not in repr(out)
    out = put_environment(EnvironmentBody(model_routes={'writer': 'custom:published'}), user_id=temp_user)
    assert out['model_routes'] == {'writer': 'custom:published'}
    out = put_environment(EnvironmentBody(model_routes={}), user_id=temp_user)
    assert out['model_routes'] == {}
    for routes in ({'writer': 'custom:internal'}, {'writer': 'custom:missing'}, {'extract': 'custom:published'}):
        with pytest.raises(HTTPException) as exc:
            put_environment(EnvironmentBody(model_routes=routes), user_id=temp_user)
        assert exc.value.status_code == 400


def test_environment_rejects_invalid_rankings(temp_user):
    with pytest.raises(HTTPException) as exc:
        put_environment(EnvironmentBody(rankings={'timeout': 61}), user_id=temp_user)
    assert exc.value.status_code == 400


def test_environment_requires_auth():
    from myink.api.main import app
    client = TestClient(app)
    assert client.get('/api/v1/environment').status_code == 403
    assert client.get('/api/v1/model-catalog').status_code == 403
    assert client.put('/api/v1/environment', json={}).status_code == 403


def test_save_raw_unknown_user():
    with pytest.raises(LookupError):
        save_raw(uuid.uuid4(), {})


def test_task_budget_environment_roundtrip_and_partial_update(temp_user):
    assert get_environment(user_id=temp_user)['task_budget'] == {
        'max_requests': 100, 'max_cost_yuan': 5.0, 'max_runtime_seconds': 1800,
    }
    put_environment(EnvironmentBody(task_budget={
        'max_requests': 3, 'max_cost_yuan': 2, 'max_runtime_seconds': 60,
    }), user_id=temp_user)
    out = put_environment(EnvironmentBody(thinking_enabled=True), user_id=temp_user)
    assert out['task_budget']['max_requests'] == 3
    assert out['thinking_enabled'] is True
    out = put_environment(EnvironmentBody(task_budget={'max_requests': 4}), user_id=temp_user)
    assert out['task_budget'] == {
        'max_requests': 4, 'max_cost_yuan': 2.0, 'max_runtime_seconds': 60,
    }
