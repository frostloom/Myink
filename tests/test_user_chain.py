"""Account model calls resolve centralized resources and published user selections."""
import uuid

import pytest

from myink import platform_configuration as pc
from myink.providers import make_user_chain
from myink.providers.credentials import encrypt_api_key


@pytest.fixture
def central_policy(monkeypatch):
    config = pc.empty_configuration()
    config['version'] = 1
    config['connections'] = {
        'default': {'name': 'Platform default', 'protocol': 'openai',
                    'base_url': 'https://models.example.com/v1', 'model': 'platform-pro',
                    'api_key_encrypted': encrypt_api_key('k'), 'enabled': True, 'user_visible': False,
                    'input_price': 3.5, 'output_price': 8},
        'published': {'name': 'Published', 'protocol': 'openai',
                      'base_url': 'https://models.example.com/v1', 'model': 'user-selected',
                      'api_key_encrypted': encrypt_api_key('k'), 'enabled': True, 'user_visible': True},
    }
    config['model_routes'] = {'writer': 'custom:default'}
    selections = {}
    monkeypatch.setattr(pc, 'load_configuration', lambda: config)
    monkeypatch.setattr('myink.environment.packed_models', lambda uid: selections)
    monkeypatch.setattr('myink.environment.thinking_enabled_for_user', lambda uid: False)
    return config, selections


def test_user_chain_uses_published_account_route_and_platform_prices(central_policy):
    config, selections = central_policy
    selections['planner'] = 'custom:published'
    assert make_user_chain('planner', uuid.uuid4()).chain == ['user-selected']
    chain = make_user_chain('writer', uuid.uuid4())
    assert chain.chain == ['platform-pro']
    assert chain.prices == {'input': 3.5, 'input_cache_hit': 3.5, 'output': 8.0}


def test_planner_uses_platform_writer_default_not_user_writer(central_policy):
    config, selections = central_policy
    selections['writer'] = 'custom:published'
    assert make_user_chain('planner', uuid.uuid4()).chain == ['platform-pro']


def test_backend_extract_ignores_user_planner_and_writer(central_policy):
    config, selections = central_policy
    selections.update(planner='custom:published', writer='custom:published', extract='custom:published')
    assert make_user_chain('extract', uuid.uuid4()).chain == ['platform-pro']
    config['model_routes']['extract'] = 'custom:published'
    assert make_user_chain('extract', uuid.uuid4()).chain == ['user-selected']


def test_user_chain_without_any_platform_route_is_unconfigured(central_policy):
    config, selections = central_policy
    config['connections'] = {}
    config['model_routes'] = {}
    assert make_user_chain('planner', uuid.uuid4()).chain == ['unconfigured']
