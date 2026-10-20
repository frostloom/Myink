"""Per-field platform preference inheritance and explicit override removal."""
from copy import deepcopy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from myink import environment, platform_configuration as pc
from myink.api.routes_environment import EnvironmentBody, put_environment
from myink.task_budget import snapshot_budget


@pytest.fixture
def configuration(monkeypatch):
    config = pc.empty_configuration()
    config['user_defaults'] = {
        'thinking_enabled': True,
        'task_budget': {'max_requests': 12, 'max_cost_yuan': 3.5, 'max_runtime_seconds': 120},
        'rankings': {'enabled': True, 'timeout': 9, 'limit': 6},
    }
    monkeypatch.setattr(pc, 'load_configuration', lambda: deepcopy(config))
    return config


def test_unset_preferences_use_live_platform_defaults_for_api_and_runtime(configuration, monkeypatch):
    monkeypatch.setattr(environment, 'load_raw', lambda uid: {})
    out = environment.load_environment('account')
    assert out['thinking_enabled'] is True
    assert out['task_budget'] == {'max_requests': 12, 'max_cost_yuan': 3.5, 'max_runtime_seconds': 120}
    assert out['rankings'] == {'enabled': True, 'timeout': 9, 'limit': 6}
    assert out['overridden_fields'] == []
    assert environment.thinking_enabled_for_user('account') is True
    view = environment.rankings_view_for_user('account')
    assert (view.rankings_enabled, view.rankings_timeout, view.rankings_limit) == (True, 9, 6)
    snapshot = snapshot_budget('account')
    configuration['user_defaults']['task_budget']['max_requests'] = 25
    assert snapshot['max_requests'] == 12
    assert snapshot_budget('account')['max_requests'] == 25


def test_false_zero_and_partial_historical_overrides_survive_platform_changes(configuration, monkeypatch):
    raw = {'thinking_enabled': False, 'task_budget': {'max_requests': 0},
           'rankings': {'enabled': False, 'limit': 2}}
    monkeypatch.setattr(environment, 'load_raw', lambda uid: raw)
    out = environment.load_environment('account')
    assert out['thinking_enabled'] is False
    assert out['task_budget'] == {'max_requests': 0, 'max_cost_yuan': 3.5, 'max_runtime_seconds': 120}
    assert out['rankings'] == {'enabled': False, 'timeout': 9, 'limit': 2}
    assert set(out['overridden_fields']) == {'thinking_enabled', 'task_budget.max_requests',
                                             'rankings.enabled', 'rankings.limit'}


def test_ownerless_preferences_use_platform_without_account_lookup(configuration, monkeypatch):
    def forbidden(uid):
        pytest.fail('None must never trigger an account lookup')
    monkeypatch.setattr(environment, 'load_raw', forbidden)
    assert snapshot_budget(None)['max_requests'] == 12
    assert environment.thinking_enabled_for_user(None) is True
    assert environment.rankings_view_for_user(None).rankings_timeout == 9


def test_partial_save_stores_only_supplied_fields_and_reset_is_isolated(configuration, temp_user):
    environment.save_raw(temp_user, {'thinking_enabled': False, 'task_budget': {'max_requests': 0},
                                     'rankings': {'enabled': False}, 'unrelated': {'keep': True}})
    out = put_environment(EnvironmentBody(rankings={'limit': 4}), user_id=temp_user)
    assert environment.load_raw(temp_user)['rankings'] == {'enabled': False, 'limit': 4}
    assert out['task_budget']['max_requests'] == 0
    out = put_environment(EnvironmentBody(reset_preferences=['task_budget.max_requests', 'rankings.enabled']),
                          user_id=temp_user)
    assert out['task_budget']['max_requests'] == 12
    assert out['rankings'] == {'enabled': True, 'timeout': 9, 'limit': 4}
    assert environment.load_raw(temp_user)['unrelated'] == {'keep': True}
    assert out['thinking_enabled'] is False
    assert set(out['overridden_fields']) == {'thinking_enabled', 'rankings.limit'}
    configuration['user_defaults']['rankings']['timeout'] = 15
    assert environment.load_environment(temp_user)['rankings']['timeout'] == 15


def test_invalid_reset_and_overlap_do_not_mutate(configuration, temp_user):
    environment.save_raw(temp_user, {'thinking_enabled': False})
    with pytest.raises(ValidationError):
        EnvironmentBody(reset_preferences=['task_budget.unknown'])
    with pytest.raises(HTTPException) as exc:
        put_environment(EnvironmentBody(thinking_enabled=True, reset_preferences=['thinking_enabled']),
                        user_id=temp_user)
    assert exc.value.status_code == 400
    assert environment.load_raw(temp_user) == {'thinking_enabled': False}


def test_reset_nested_field_can_be_combined_with_different_explicit_field(configuration, temp_user):
    environment.save_raw(temp_user, {'task_budget': {'max_requests': 2, 'max_cost_yuan': 1}})
    out = put_environment(EnvironmentBody(task_budget={'max_requests': 0},
                          reset_preferences=['task_budget.max_cost_yuan']), user_id=temp_user)
    assert out['task_budget'] == {'max_requests': 0, 'max_cost_yuan': 3.5, 'max_runtime_seconds': 120}
    assert out['overridden_fields'] == ['task_budget.max_requests']


def test_model_route_partial_update_and_empty_selection_reset(configuration, temp_user):
    configuration['connections'] = {'a': {'name': 'A'}, 'b': {'name': 'B'}}
    put_environment(EnvironmentBody(model_routes={'writer': 'custom:a', 'planner': 'custom:b'}), user_id=temp_user)
    out = put_environment(EnvironmentBody(model_routes={'writer': ''}), user_id=temp_user)
    assert out['model_routes'] == {'planner': 'custom:b'}
    assert out['overridden_fields'] == ['model_routes.planner']
    out = put_environment(EnvironmentBody(reset_preferences=['model_routes.planner']), user_id=temp_user)
    assert out['model_routes'] == {}


def test_configuration_nested_partial_updates_old_client_omission_and_cas(monkeypatch):
    from myink.models.platform import PlatformConfiguration
    engine = create_engine('sqlite://')
    PlatformConfiguration.__table__.create(engine)
    monkeypatch.setattr(pc, 'new_session', sessionmaker(engine))
    base = dict(model_connections=[], model_routes={}, prompts={}, genre_packs={})
    first = pc.save_configuration(pc.ConfigurationBody(version=0, **base, user_defaults={
        'thinking_enabled': True, 'task_budget': {'max_requests': 8}, 'rankings': {'timeout': 11}}))
    assert first['user_defaults']['task_budget'] == {
        'max_requests': 8, 'max_cost_yuan': 5.0, 'max_runtime_seconds': 1800}
    second = pc.save_configuration(pc.ConfigurationBody(version=1, **base,
                                                       user_defaults={'task_budget': {'max_cost_yuan': 0}}))
    assert second['user_defaults']['thinking_enabled'] is True
    assert second['user_defaults']['task_budget']['max_requests'] == 8
    assert second['user_defaults']['task_budget']['max_cost_yuan'] == 0
    old_client = pc.save_configuration(pc.ConfigurationBody(version=2, **base))
    assert old_client['user_defaults'] == second['user_defaults']
    with pytest.raises(HTTPException) as exc:
        pc.save_configuration(pc.ConfigurationBody(version=2, **base, user_defaults={'thinking_enabled': False}))
    assert exc.value.status_code == 409
    assert pc.public_configuration()['user_defaults'] == second['user_defaults']


@pytest.mark.parametrize('defaults', [None, {'thinking_enabled': None}, {'task_budget': None},
    {'task_budget': {'max_requests': None}}, {'task_budget': {'max_cost_yuan': True}},
    {'rankings': {'enabled': None}}, {'rankings': {'timeout': 61}}, {'unexpected': True}])
def test_platform_defaults_reject_null_and_invalid_values(defaults):
    with pytest.raises(ValidationError):
        pc.ConfigurationBody(version=0, model_connections=[], model_routes={}, prompts={}, genre_packs={},
                             user_defaults=defaults)


def test_ownerless_model_chains_use_default_thinking_without_account_lookup(configuration, monkeypatch):
    from myink import providers
    def forbidden(uid):
        pytest.fail('Ownerless model chain must not load an account')
    monkeypatch.setattr(environment, 'load_raw', forbidden)
    assert providers.make_chain('writer').thinking_enabled is True
    assert providers.make_user_chain('writer', None).thinking_enabled is True


def test_global_rankings_facade_uses_live_platform_defaults(configuration, monkeypatch):
    import asyncio
    from myink.integrations import rankings
    async def fetcher(*, timeout):
        assert timeout == 9
        return [{'title': f'Book {i}'} for i in range(10)]
    monkeypatch.setattr(rankings, 'fetch_all', fetcher)
    monkeypatch.setattr(rankings, '_user_services', {})
    result = asyncio.run(rankings.fetch_rankings(refresh=True))
    assert result['source'] == 'remote'
    assert len(result['items']) == 6
    configuration['user_defaults']['rankings']['enabled'] = False
    assert asyncio.run(rankings.fetch_rankings(refresh=True))['source'] == 'sample'


def test_reset_api_rejects_invalid_and_overlapping_paths_before_storage(configuration, temp_user):
    from fastapi.testclient import TestClient
    from conftest import identity_headers
    from myink.api.main import app
    client = TestClient(app)
    headers = identity_headers(temp_user)
    for payload, status in [({'reset_preferences': ['models.writer']}, 422),
                            ({'rankings': {'enabled': False}, 'reset_preferences': ['rankings.enabled']}, 400),
                            ({'task_budget': {'max_cost_yuan': 0}, 'reset_preferences': ['task_budget.max_cost_yuan']}, 400),
                            ({'model_routes': {'writer': ''}, 'reset_preferences': ['model_routes.writer']}, 400)]:
        assert client.put('/api/v1/environment', headers=headers, json=payload).status_code == status
        assert environment.load_raw(temp_user) == {}
