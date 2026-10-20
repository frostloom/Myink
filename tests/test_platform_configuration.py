import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_platform_configuration_encrypts_preserves_and_conflicts(monkeypatch):
    from myink import platform_configuration as pc
    from myink.models.platform import PlatformConfiguration
    engine = create_engine('sqlite://')
    PlatformConfiguration.__table__.create(engine)
    monkeypatch.setattr(pc, 'new_session', sessionmaker(engine))
    monkeypatch.setattr('myink.api.routes_settings._assert_host_allowed', lambda url: None)
    cid = str(uuid.uuid4())
    body = pc.ConfigurationBody(version=0, model_connections=[dict(
        id=cid, name='Published', protocol='openai', base_url='https://example.com/v1',
        model='writer', api_key='private-secret', enabled=True, user_visible=True,
    )], model_routes={'writer': f'custom:{cid}'}, prompts={'writer': 'Additional guidance'},
        genre_packs={'xiuxian': {'pacing': 'Custom pacing'}})
    result = pc.save_configuration(body)
    assert result['version'] == 1
    assert 'private-secret' not in repr(result)
    assert 'api_key_encrypted' not in repr(result)
    encrypted = pc.load_configuration()['connections'][cid]['api_key_encrypted']
    assert encrypted != 'private-secret'
    assert pc.catalog()['models'] == [{'id': f'custom:{cid}', 'name': 'Published'}]
    body.version = 1
    body.model_connections[0].api_key = None
    pc.save_configuration(body)
    assert pc.load_configuration()['connections'][cid]['api_key_encrypted'] == encrypted
    with pytest.raises(HTTPException) as exc:
        pc.save_configuration(body)
    assert exc.value.status_code == 409


def test_platform_hidden_and_disabled_selection_policy(monkeypatch):
    from myink import platform_configuration as pc
    config = {'version': 1, 'connections': {
        'published': {'name': 'Public', 'enabled': True, 'user_visible': True},
        'internal': {'name': 'Internal', 'enabled': True, 'user_visible': False},
        'disabled': {'name': 'Disabled', 'enabled': False, 'user_visible': True}},
        'model_routes': {'writer': 'custom:internal'}, 'prompts': {}, 'genre_packs': {}}
    monkeypatch.setattr(pc, 'load_configuration', lambda: config)
    assert pc.catalog() == {'models': [{'id': 'custom:published', 'name': 'Public'}], 'model_routes': {}}
    for selected in ('custom:internal', 'custom:disabled', 'custom:deleted'):
        assert pc.resolve_connection('writer', {'writer': selected}) == config['connections']['internal']
        with pytest.raises(HTTPException):
            pc.validate_user_routes({'writer': selected})
    assert pc.resolve_connection('writer', {'writer': 'custom:published'}) == config['connections']['published']
    with pytest.raises(HTTPException):
        pc.validate_user_routes({'extract': 'custom:published'})


def test_writer_cannot_write_connections_even_empty(monkeypatch):
    from myink.api.routes_environment import put_environment, EnvironmentBody
    monkeypatch.setattr('myink.api.routes_environment.load_raw', lambda uid: {})
    with pytest.raises(HTTPException) as exc:
        put_environment(EnvironmentBody(model_connections=[]), user_id=str(uuid.uuid4()))
    assert exc.value.status_code == 403


def test_admin_api_enforces_roles_and_redacts(temp_user, monkeypatch):
    from fastapi.testclient import TestClient
    from conftest import identity_headers
    from myink.api.main import app
    from myink.db import new_session
    from myink.models import User
    from myink.api import routes_platform
    client = TestClient(app)
    headers = identity_headers(temp_user)
    for method, path, payload in [
        ('get', '/api/v1/admin/configuration', None),
        ('put', '/api/v1/admin/configuration', {}),
        ('post', '/api/v1/admin/configuration/models', {}),
        ('post', '/api/v1/environment/models', {}),
    ]:
        response = client.request(method, path, headers=headers, json=payload)
        assert response.status_code == 403
    with new_session() as db:
        user = db.get(User, uuid.UUID(temp_user))
        user.role = 'admin'
        db.commit()
    response = client.get('/api/v1/admin/configuration', headers=headers)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['version'] >= 0
    assert 'api_key_encrypted' not in response.text
    monkeypatch.setattr(routes_platform, '_audit_or_fail', lambda *args: None)
    response = client.post('/api/v1/admin/configuration/models', headers=headers,
                          json={'protocol': 'openai', 'base_url': 'http://127.0.0.1', 'api_key': 'x'})
    assert response.status_code == 400


def test_runtime_uses_only_platform_and_prompt_reaches_budget(monkeypatch):
    from myink import providers, platform_configuration as pc
    from myink.providers.base import ModelProvider, ModelResponse
    from myink.providers.credentials import encrypt_api_key
    from myink.model_admission import _reservation
    class Recorder(ModelProvider):
        def name(self): return 'recording'
        def generate(self, messages, **kwargs):
            self.messages = messages
            return ModelResponse(content='ok', model_id='central')
    recorder = Recorder()
    config = {'version': 1, 'connections': {'platform': {
        'enabled': True, 'user_visible': True, 'model': 'central', 'protocol': 'openai',
        'base_url': 'https://example.com', 'api_key_encrypted': encrypt_api_key('platform-secret'),
        'input_price': 1., 'output_price': 1.}}, 'model_routes': {'writer': 'custom:platform'},
        'prompts': {'writer': 'Additional platform instructions'}, 'genre_packs': {}}
    monkeypatch.setattr(pc, 'load_configuration', lambda: config)
    monkeypatch.setattr(providers, '_provider_for', lambda protocol, key, url: recorder)
    monkeypatch.setattr('myink.environment.thinking_enabled_for_user', lambda user: False)
    monkeypatch.setattr('myink.environment.packed_models', lambda user: {
        'writer': 'custom:legacy', '__connections__': {'legacy': {'model': 'legacy'}}})
    chain = providers.make_user_chain('writer', str(uuid.uuid4()))
    assert chain.chain == ['central']
    from types import SimpleNamespace
    class ProjectDB:
        def get(self, model, pid):
            return SimpleNamespace(user_id=uuid.uuid4())
    for role in ('planner', 'extract', 'validator_l2', 'audit', 'summarize'):
        assert providers.make_user_chain(role, str(uuid.uuid4())).chain == ['central']
        assert providers.make_chain(role, uuid.uuid4(), db=ProjectDB()).chain == ['central']
    messages = [{'role': 'system', 'content': 'Built in JSON rules'}, {'role': 'user', 'content': 'write'}]
    chain.generate(messages, json_mode=True)
    assert recorder.messages[0] == messages[0]
    assert recorder.messages[-1]['content'] == 'Additional platform instructions'
    assert len(messages) == 2
    baseline, _ = _reservation(chain, messages, 100)
    chain.system_addition = 'x' * 10000
    larger, _ = _reservation(chain, messages, 100)
    assert larger > baseline
    assert providers.platform_key_active('user', 'user') is True


def test_global_genre_overrides_snapshot_and_catalog(monkeypatch):
    from myink import platform_configuration as pc
    from myink.genre_catalog import build_book_pack, get_root, catalog_entries
    config = pc.empty_configuration()
    config['genre_packs'] = {'xiuxian': {'pacing': 'Published pacing'}}
    monkeypatch.setattr(pc, 'load_configuration', lambda: config)
    assert get_root('xiuxian')['pacing'] == 'Published pacing'
    assert next(item for item in catalog_entries() if item['id'] == 'xiuxian')['pacing'] == 'Published pacing'
    snapshot = build_book_pack('xiuxian', None)
    config['genre_packs']['xiuxian']['pacing'] = 'New pacing'
    assert snapshot['pacing'] == 'Published pacing'
    assert snapshot['baseline']['pacing'] == 'Published pacing'


def test_project_settings_and_genre_mutations_require_admin(temp_user, temp_project):
    from fastapi.testclient import TestClient
    from conftest import identity_headers
    from myink.api.main import app
    client = TestClient(app)
    headers = identity_headers(temp_user)
    # Require owner first: set this disposable project to the disposable writer.
    from myink.db import new_session
    from myink.models import Project
    with new_session() as db:
        db.get(Project, uuid.UUID(temp_project)).user_id = uuid.UUID(temp_user)
        db.commit()
    for method, path, body in [
        ('put', f'/api/v1/projects/{temp_project}/settings', {'model_connections': []}),
        ('put', f'/api/v1/projects/{temp_project}/genre-pack', {'pacing': 'writer override'}),
        ('post', f'/api/v1/projects/{temp_project}/genre-pack/restore', {}),
        ('post', f'/api/v1/projects/{temp_project}/settings/models', {}),
    ]:
        assert client.request(method, path, headers=headers, json=body).status_code == 403


def test_platform_prompt_cannot_exceed_final_request_budget(monkeypatch):
    from dataclasses import replace
    from myink.config import settings
    from myink.context_budget import ContextBudgetExceeded
    from myink.providers.base import FallbackChain, MissingModelProvider
    import myink.config as config
    monkeypatch.setattr(config, 'settings', replace(settings, request_token_budget=1100))
    chain = FallbackChain(MissingModelProvider(), ['unconfigured'])
    chain.system_addition = 'long policy ' * 200
    with pytest.raises(ContextBudgetExceeded):
        chain.generate([{'role': 'user', 'content': 'write'}], tools=[{'name': 'tool'}])


def test_existing_secondary_genre_snapshot_is_not_reconfigured(monkeypatch):
    from myink import platform_configuration as pc
    from myink.genre_catalog import build_book_pack, format_prompt
    config = pc.empty_configuration()
    config['genre_packs'] = {'xitong': {'mechanics': ['Original secondary rule']}}
    monkeypatch.setattr(pc, 'load_configuration', lambda: config)
    snapshot = build_book_pack('xiuxian', 'xitong')
    config['genre_packs']['xitong']['mechanics'] = ['New secondary rule']
    prompt = format_prompt(snapshot)
    assert 'Original secondary rule' in prompt
    assert 'New secondary rule' not in prompt


def test_saved_empty_policy_disables_environment_model_fallback(monkeypatch):
    from myink import platform_configuration as pc, providers
    config = pc.empty_configuration()
    config['version'] = 1
    monkeypatch.setattr(pc, 'load_configuration', lambda: config)
    def forbidden(*args):
        pytest.fail('Deployment environment model must not bypass a saved platform policy')
    monkeypatch.setattr(providers, '_platform_chain', forbidden)
    from myink.platform_readiness import PlatformNotReady
    with pytest.raises(PlatformNotReady):
        providers._central_chain('writer', {}, False)


def test_runtime_policy_database_failure_does_not_fall_back(monkeypatch):
    from myink import platform_configuration as pc, providers
    def unavailable():
        raise RuntimeError('policy database unavailable')
    monkeypatch.setattr(pc, 'load_configuration', unavailable)
    with pytest.raises(RuntimeError, match='policy database unavailable'):
        providers._central_chain('writer', {}, False)


def test_configuration_requires_enabled_writer_default(monkeypatch):
    from myink import platform_configuration as pc
    monkeypatch.setattr(pc, 'load_configuration', pc.empty_configuration)
    from myink.models.platform import PlatformConfiguration
    engine = create_engine('sqlite://')
    PlatformConfiguration.__table__.create(engine)
    monkeypatch.setattr(pc, 'new_session', sessionmaker(engine))
    monkeypatch.setattr('myink.api.routes_settings.connection_record', lambda item, old: (item.id, {'name': item.name}))
    cid = str(uuid.uuid4())
    for routes in ({}, {'extract': f'custom:{cid}'}):
        body = pc.ConfigurationBody(version=0, model_connections=[dict(
            id=cid, name='Internal', protocol='openai', base_url='https://example.com',
            model='model', api_key='key')], model_routes=routes, prompts={}, genre_packs={})
        with pytest.raises(HTTPException) as exc:
            pc.save_configuration(body)
        assert exc.value.status_code == 400


def test_omitted_backend_defaults_use_platform_writer_not_user_selection(monkeypatch):
    from myink import platform_configuration as pc
    config = pc.empty_configuration()
    config['version'] = 1
    config['connections'] = {'default': {'name': 'Platform', 'enabled': True, 'user_visible': False},
                             'user': {'name': 'User choice', 'enabled': True, 'user_visible': True}}
    config['model_routes'] = {'writer': 'custom:default'}
    monkeypatch.setattr(pc, 'load_configuration', lambda: config)
    for role in ('planner', 'extract', 'validator_l2', 'audit', 'summarize'):
        assert pc.resolve_connection(role, {'writer': 'custom:user'}) is config['connections']['default']
    assert pc.resolve_connection('writer', {'writer': 'custom:user'}) is config['connections']['user']
    assert pc.resolve_connection('planner', {'planner': 'custom:user'}) is config['connections']['user']


@pytest.mark.parametrize('genre, expected_pacing', [('修仙', 'Published pacing'), ('自定义题材', None)])
def test_short_commit_uses_published_snapshot_on_creation_and_retry(monkeypatch, genre, expected_pacing, stub_provider):
    stub_provider("金丹", "金丹")
    from contextlib import contextmanager
    from types import SimpleNamespace
    from myink.api import routes_short_creation as routes
    from myink.api.schemas import ShortCreationCommitBody
    from myink import platform_configuration as pc
    uid, pid = uuid.uuid4(), uuid.uuid4()
    card = {field: 'ready' for field in routes.creation.REQUIRED_CARD_FIELDS}
    card.update(genre=genre, working_title='Short book', chapter_count=3, chars_per_chapter=1000)
    session = SimpleNamespace(status='active', card=card, book_id=None)
    project = SimpleNamespace(id=pid)
    user = SimpleNamespace(role='user', platform_short_used=0)
    config = pc.empty_configuration()
    config['genre_packs'] = {'xiuxian': {'pacing': 'Published pacing'}}
    monkeypatch.setattr(pc, 'load_configuration', lambda: config)
    stored = []
    captured = []
    class DB:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def scalar(self, statement):
            return session if 'short_creation_sessions' in str(statement) else user
        def get(self, model, key): return project
        def commit(self): pass
        def close(self): pass
    monkeypatch.setattr(routes, 'new_session', DB)
    @contextmanager
    def tenant_db(pid): yield DB()
    monkeypatch.setattr(routes, 'tenant_session', tenant_db)
    monkeypatch.setattr(routes, 'get_settings', lambda db, pid: SimpleNamespace(genre_pack=stored[0]))
    monkeypatch.setattr(routes, '_retitle', lambda *args: None)
    monkeypatch.setattr(routes, 'platform_key_active', lambda *args: False)
    def create(db, uid, **kwargs):
        stored.append(kwargs.get('genre_pack') or {})
        return project, True
    monkeypatch.setattr(routes._book, '_create_project_row', create)
    class OutlineReached(Exception): pass
    def outline(pid, body, genre, genre_pack, chapters, db):
        captured.append(genre_pack)
        raise OutlineReached()
    monkeypatch.setattr(routes._book, '_short_outline_draft', outline)
    for _ in range(2):
        with pytest.raises(OutlineReached):
            routes.commit(ShortCreationCommitBody(), uuid.uuid4(), str(uid))
        config['genre_packs']['xiuxian']['pacing'] = 'Changed global pacing'
    assert len(stored) == 1
    assert captured == [stored[0], stored[0]]
    if expected_pacing:
        assert stored[0]['pacing'] == expected_pacing
    else:
        assert stored[0] == {}
