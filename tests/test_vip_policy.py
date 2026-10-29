"""Tier restrictions apply to catalog, saved selection and actual resolution."""
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from myink import platform_configuration as pc


def policy():
    return {**pc.empty_configuration(), 'version': 1, 'connections': {
        'basic': {'name': 'Basic', 'enabled': True, 'user_visible': True, 'minimum_tier': 'normal'},
        'premium': {'name': 'Premium', 'enabled': True, 'user_visible': True, 'minimum_tier': 'vip'},
        'internal': {'name': 'Internal premium', 'enabled': True, 'user_visible': False, 'minimum_tier': 'vip'},
    }, 'model_routes': {'writer': 'custom:basic'}, 'vip_model_routes': {'writer': 'custom:premium'}}


def test_catalog_filters_membership_and_uses_tier_defaults(monkeypatch):
    monkeypatch.setattr(pc, 'load_configuration', policy)
    assert pc.catalog(tier='normal')['models'] == [{'id': 'custom:basic', 'name': 'Basic'}]
    assert pc.catalog(tier='vip')['model_routes']['writer'] == 'custom:premium'
    assert {m['id'] for m in pc.catalog(tier='vip')['models']} == {'custom:basic', 'custom:premium'}


@pytest.mark.parametrize('role', sorted(pc.PLATFORM_ROLES))
def test_tampered_or_downgraded_selection_cannot_resolve_vip_model(role):
    config = policy()
    for ref in ('custom:premium', 'custom:internal'):
        assert pc.resolve_connection(role, {role: ref}, config, tier='normal') == config['connections']['basic']
        with pytest.raises(HTTPException):
            pc.validate_user_routes({role: ref}, config=config, tier='normal')
    assert pc.resolve_connection(role, {}, config, tier='vip') == config['connections']['premium']
    assert pc.resolve_connection(role, {role: 'custom:basic'}, config, tier='vip') == config['connections']['basic']


def test_hidden_defaults_cannot_bypass_normal_permission():
    config = policy()
    config['model_routes']['writer'] = 'custom:internal'
    assert pc.resolve_connection('writer', {}, config, tier='normal') is None
    config['vip_model_routes']['writer'] = 'custom:internal'
    assert pc.resolve_connection('writer', {}, config, tier='vip') == config['connections']['internal']


def test_configuration_roundtrips_tier_policy_and_preserves_it_on_legacy_save(monkeypatch):
    from myink.models.platform import PlatformConfiguration
    engine = create_engine('sqlite://')
    PlatformConfiguration.__table__.create(engine)
    monkeypatch.setattr(pc, 'new_session', sessionmaker(engine))
    monkeypatch.setattr('myink.api.routes_settings._assert_host_allowed', lambda url: None)
    basic, premium = str(uuid.uuid4()), str(uuid.uuid4())
    connections = [dict(id=cid, name=cid, protocol='openai', base_url='https://example.com/v1',
                        model=cid, api_key='test-only', minimum_tier=tier)
                   for cid, tier in [(basic, 'normal'), (premium, 'vip')]]
    body = pc.ConfigurationBody(version=0, model_connections=connections,
        model_routes={'writer': f'custom:{basic}'}, vip_model_routes={'writer': f'custom:{premium}'},
        queue_weights={'vip': 4, 'normal': 2}, prompts={}, genre_packs={})
    saved = pc.save_configuration(body)
    assert saved['vip_model_routes'] == {'writer': f'custom:{premium}'}
    assert saved['queue_weights'] == {'vip': 4, 'normal': 2}
    assert saved['model_connections'][1]['minimum_tier'] == 'vip'
    # Older clients may omit new root fields, but must not reset the policy.
    old_body = body.model_dump(exclude={'vip_model_routes', 'queue_weights'})
    old_body['version'] = 1
    saved = pc.save_configuration(pc.ConfigurationBody(**old_body))
    assert saved['vip_model_routes'] == {'writer': f'custom:{premium}'}
    assert saved['queue_weights'] == {'vip': 4, 'normal': 2}
    invalid = body.model_copy(update={'version': 2, 'model_routes': {'writer': f'custom:{premium}'}})
    with pytest.raises(HTTPException):
        pc.save_configuration(invalid)
    assert pc.load_configuration()['version'] == 2


@pytest.mark.parametrize('weights', [{'vip': 0, 'normal': 1}, {'vip': 3, 'normal': 0}, {'vip': 11, 'normal': 1}])
def test_admin_cannot_disable_regular_scheduling(weights):
    with pytest.raises(ValidationError):
        pc.ConfigurationBody(version=0, model_connections=[], model_routes={}, prompts={}, genre_packs={}, queue_weights=weights)


def test_actual_provider_resolution_uses_current_account_tier(monkeypatch):
    from myink import providers
    from myink.providers.credentials import encrypt_api_key
    config = policy()
    for key, rec in config['connections'].items():
        rec.update(model=key, protocol='openai', base_url='https://example.com/v1', api_key_encrypted=encrypt_api_key('test'))
    monkeypatch.setattr(pc, 'load_configuration', lambda: config)
    monkeypatch.setattr('myink.environment.thinking_enabled_for_user', lambda uid: False)
    monkeypatch.setattr('myink.environment.packed_models', lambda uid: {'writer': 'custom:premium'})
    monkeypatch.setattr(pc, 'tier_for_user', lambda uid, config=None: 'normal')
    assert providers.make_user_chain('writer', uuid.uuid4()).chain == ['basic']
    monkeypatch.setattr(pc, 'tier_for_user', lambda uid, config=None: 'vip')
    assert providers.make_user_chain('writer', uuid.uuid4()).chain == ['premium']


def test_membership_changes_are_admin_only_audited_and_fresh(temp_user, monkeypatch):
    from fastapi.testclient import TestClient
    from conftest import identity_headers
    from myink.api.main import app
    from myink.api import routes_platform
    from myink.db import new_session
    from myink.models import User
    from sqlalchemy import select
    from myink.models import AdminAccessLog
    client = TestClient(app)
    path = f'/api/v1/admin/users/{temp_user}/membership'
    headers = identity_headers(temp_user)
    assert client.put(path, headers=headers, json={'tier': 'vip'}).status_code == 403
    with new_session() as db:
        user = db.get(User, uuid.UUID(temp_user))
        user.role = 'admin'
        db.commit()
    for tier in ['vip', 'normal']:
        response = client.put(path, headers=headers, json={'tier': tier})
        assert response.status_code == 200, response.text
        assert response.json() == {'id': temp_user, 'tier': tier}
        with new_session() as db:
            assert db.get(User, uuid.UUID(temp_user)).tier == tier
    assert client.put(path, headers=headers, json={'tier': 'root'}).status_code == 422
    assert client.put('/api/v1/admin/users/bad/membership', headers=headers, json={'tier': 'vip'}).status_code == 404
    def unavailable(*args):
        raise HTTPException(503, 'ADMIN_AUDIT_UNAVAILABLE')
    monkeypatch.setattr(routes_platform, '_audit_or_fail', unavailable)
    assert client.put(path, headers=headers, json={'tier': 'vip'}).status_code == 503
    with new_session() as db:
        assert db.get(User, uuid.UUID(temp_user)).tier == 'normal'
        assert db.scalar(select(AdminAccessLog).where(AdminAccessLog.action == 'admin.membership.update',
                        AdminAccessLog.actor_id == uuid.UUID(temp_user))) is not None


def test_vip_legacy_resume_returns_to_vip_queue(temp_project, temp_user, stub_provider):
    from fastapi.testclient import TestClient
    from conftest import identity_headers
    from myink.api.main import app
    from myink.db import new_session
    from myink.models import Project, User, Task
    from myink.worker import amqp
    stub_provider('金丹', '金丹')
    tid = uuid.uuid4()
    with new_session() as db:
        uid = uuid.UUID(temp_user)
        db.get(Project, uuid.UUID(temp_project)).user_id = uid
        db.get(User, uid).tier = 'vip'
        db.add(Task(id=tid, project_id=uuid.UUID(temp_project), task_type='batch_generate', status='paused', payload={}))
        db.commit()
    try:
        with amqp.connect() as conn:
            ch = conn.channel()
            amqp.declare_topology(ch)
            ch.queue_purge(amqp.vip_queue())
            response = TestClient(app).post(f'/api/v1/tasks/{tid}/resume', headers=identity_headers(str(uid)))
            assert response.status_code == 200, response.text
            _, _, body = ch.basic_get(amqp.vip_queue(), auto_ack=True)
            assert body is not None
            import json
            assert json.loads(body)['task_id'] == str(tid)
    finally:
        with new_session() as db:
            db.query(Task).filter_by(id=tid).delete()
            db.commit()
