"""Deployment model import must use the same catalog and runtime policy as admin models."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def store(monkeypatch):
    from myink import platform_configuration as pc
    from myink.models.platform import PlatformConfiguration
    engine = create_engine('sqlite://')
    PlatformConfiguration.__table__.create(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(pc, 'new_session', factory)
    monkeypatch.setattr('myink.api.routes_settings._assert_host_allowed', lambda url: None)
    return pc, factory


def deployment():
    return SimpleNamespace(platform_model_api_key='deployment-secret',
        platform_model_base_url='https://example.com/v1', platform_model_name='deployment-model',
        platform_model_protocol='openai')


@pytest.mark.parametrize('existing', [False, True, 'empty'])
def test_import_publishes_encrypted_model_and_preserves_existing_policy(store, existing, monkeypatch):
    pc, factory = store
    from myink.models.platform import PlatformConfiguration
    from myink.providers.credentials import decrypt_api_key
    old = pc.empty_configuration()
    old.update(user_defaults={'thinking_enabled': True}, prompts={'writer': 'keep prompt'},
               genre_packs={'xiuxian': {'pacing': 'keep pacing'}})
    if existing:
        if existing != 'empty':
            old['connections'] = {'other': {'name': 'Existing', 'enabled': True}}
            old['model_routes'] = {'writer': 'custom:other'}
        with factory() as db:
            db.add(PlatformConfiguration(id=1, version=7, document={k: v for k, v in old.items() if k != 'version'}))
            db.commit()
    with factory() as db:
        assert pc.initialize_builtin_model(db, deployment()) is True
        db.commit()
    config = pc.load_configuration()
    builtin = next((cid, rec) for cid, rec in config['connections'].items() if rec.get('origin') == 'builtin')
    cid, record = builtin
    assert decrypt_api_key(record['api_key_encrypted']) == 'deployment-secret'
    assert 'deployment-secret' not in repr(config)
    assert config['version'] == (8 if existing else 1)
    assert config['model_routes']['writer'] == ('custom:other' if existing is True else f'custom:{cid}')
    if existing:
        for key in ('user_defaults', 'prompts', 'genre_packs'):
            assert config[key] == old[key]
    assert {'id': f'custom:{cid}', 'name': 'deployment-model'} in pc.catalog()['models']
    assert next(item for item in pc.public_configuration()['model_connections'] if item['id'] == cid)['origin'] == 'builtin'
    before = deepcopy(config)
    with factory() as db:
        assert pc.initialize_builtin_model(db, deployment()) is False
        db.commit()
    assert pc.load_configuration() == before


def test_import_survives_edit_but_does_not_resurrect_deleted_model(store):
    pc, factory = store
    with factory() as db:
        pc.initialize_builtin_model(db, deployment())
        db.commit()
    public = pc.public_configuration()
    public['model_connections'][0].pop('has_api_key')
    public['model_connections'][0].pop('origin')
    public['model_connections'][0]['name'] = 'Edited builtin'
    pc.save_configuration(pc.ConfigurationBody(**public))
    assert pc.public_configuration()['model_connections'][0]['origin'] == 'builtin'
    pc.save_configuration(pc.ConfigurationBody(version=2, model_connections=[], model_routes={}, prompts={}, genre_packs={}))
    with factory() as db:
        assert pc.initialize_builtin_model(db, deployment()) is False
        db.commit()
    assert pc.catalog()['models'] == []


def test_imported_model_routes_actual_provider_requests(store, monkeypatch):
    pc, factory = store
    with factory() as db:
        pc.initialize_builtin_model(db, deployment())
        db.commit()
    from myink import providers
    from myink.providers.base import ModelProvider, ModelResponse
    requests = []
    class Recorder(ModelProvider):
        def name(self): return 'recording'
        def generate(self, messages, **kwargs):
            requests.append((messages, kwargs))
            return ModelResponse(content='ok', model_id='deployment-model')
    def provider(protocol, key, url):
        assert (protocol, key, url) == ('openai', 'deployment-secret', 'https://example.com/v1')
        return Recorder()
    monkeypatch.setattr(providers, '_provider_for', provider)
    monkeypatch.setattr('myink.writing_resource_runtime.configured', lambda: False)
    from myink.platform_readiness import readiness
    assert readiness()['ready'] is True
    chain = providers._central_chain('writer', {}, False)
    assert chain.chain == ['deployment-model']
    assert chain.generate([{'role': 'user', 'content': 'write'}]).content == 'ok'
    assert requests


def test_incomplete_deployment_does_not_mark_import_complete(store):
    pc, factory = store
    settings = deployment()
    settings.platform_model_api_key = ''
    with factory() as db:
        assert pc.initialize_builtin_model(db, settings) is False
        db.commit()
    assert pc.load_configuration()['version'] == 0
