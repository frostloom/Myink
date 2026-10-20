"""Readiness rejects unusable effective routes before accounting or model I/O."""
from dataclasses import replace
import uuid

import pytest

from myink import platform_configuration as pc, providers
from myink.providers.credentials import encrypt_api_key


@pytest.fixture
def policy(monkeypatch):
    config = pc.empty_configuration()
    config['version'] = 1
    config['connections'] = {'good': dict(enabled=True, user_visible=True, protocol='openai',
        base_url='https://models.example.test/v1', model='novel', api_key_encrypted=encrypt_api_key('secret-value'))}
    config['model_routes'] = {'writer': 'custom:good'}
    monkeypatch.setattr(pc, 'load_configuration', lambda: config)
    return config


def test_saved_empty_and_invalid_credentials_fail_closed(policy):
    from myink.platform_readiness import readiness
    policy['connections']['good']['api_key_encrypted'] = 'invalid-secret-value'
    result = readiness()
    assert not result['ready']
    assert len(result['checks']) == 6
    assert {c['reason'] for c in result['checks']} == {'credential_unavailable'}
    assert 'secret-value' not in repr(result)
    policy['model_routes'] = {}
    assert {c['reason'] for c in readiness()['checks']} == {'model_unconfigured'}


def test_effective_selection_and_internal_role_fallback(policy):
    from myink.platform_readiness import readiness
    policy['connections']['bad'] = {**policy['connections']['good'], 'model': ''}
    result = readiness(selections={'writer': 'custom:bad', 'extract': 'custom:bad'})
    checks = {c['role']: c for c in result['checks']}
    assert not checks['writer']['ready']
    assert checks['extract']['ready']  # Internal roles never use user writer selection.
    policy['connections']['bad']['user_visible'] = False
    assert readiness(selections={'writer': 'custom:bad'})['ready']
    policy['connections']['good']['enabled'] = False
    assert not readiness()['ready']


@pytest.mark.parametrize('field,value,reason', [('protocol','ftp','protocol_invalid'),
    ('base_url','http://127.0.0.1/v1','address_invalid'), ('base_url','https://user:secret@host/v1','address_invalid'),
    ('model','','model_invalid')])
def test_local_invalid_config_is_diagnostic_without_network(monkeypatch, policy, field, value, reason):
    from myink.platform_readiness import readiness
    monkeypatch.setattr('socket.getaddrinfo', lambda *a, **kw: pytest.fail('readiness must not resolve DNS'))
    policy['connections']['good'][field] = value
    assert {c['reason'] for c in readiness()['checks']} == {reason}


def test_deployment_fallback_only_before_first_save(monkeypatch, policy):
    from myink.platform_readiness import readiness
    import myink.config as config
    monkeypatch.setattr(config, 'settings', replace(config.settings, platform_model_api_key='deployment-secret',
        platform_model_base_url='https://models.example.test', platform_model_name='model', platform_model_protocol='openai'))
    policy['connections'] = {}
    policy['model_routes'] = {}
    assert not readiness()['ready']
    policy['version'] = 0
    assert readiness()['ready']


def test_runtime_rechecks_after_diagnostic_and_preserves_injected_provider(policy, monkeypatch):
    from myink.platform_readiness import PlatformNotReady, readiness
    assert readiness()['ready']
    policy['connections']['good']['enabled'] = False
    with pytest.raises(PlatformNotReady):
        providers._central_chain('writer', {}, False)
    monkeypatch.setattr(providers, 'default_provider', providers.MissingModelProvider())
    assert providers.make_user_chain('writer', uuid.uuid4()).chain == ['stub']


@pytest.mark.parametrize('task_type', ['chapter_generate', 'batch_generate', 'short_generate'])
def test_enqueue_not_ready_precedes_budget_and_gates(policy, monkeypatch, task_type):
    from myink.platform_readiness import PlatformNotReady
    from myink.worker.enqueue import enqueue
    policy['connections']['good']['enabled'] = False
    monkeypatch.setattr('myink.environment.packed_models', lambda uid: {})
    monkeypatch.setattr('myink.task_budget.snapshot_budget', lambda uid: pytest.fail('must not snapshot budget'))
    with pytest.raises(PlatformNotReady):
        enqueue(user_id=str(uuid.uuid4()), project_id=str(uuid.uuid4()), task_type=task_type,
                payload={}, quota_n=1, cost_est=1, priority=1)


def test_short_queue_requires_audit_but_not_planner(policy, monkeypatch):
    from myink.platform_readiness import require_operation_ready, PlatformNotReady
    monkeypatch.setattr('myink.environment.packed_models', lambda uid: {})
    policy['connections']['broken'] = {**policy['connections']['good'], 'api_key_encrypted': 'bad'}
    policy['model_routes']['planner'] = 'custom:broken'
    require_operation_ready('short_generate', 'owner')
    with pytest.raises(PlatformNotReady):
        require_operation_ready('chapter_generate', 'owner')
    policy['model_routes']['audit'] = 'custom:broken'
    with pytest.raises(PlatformNotReady):
        require_operation_ready('short_generate', 'owner')


def test_admin_readiness_is_audited_private_and_public_failure_generic(temp_user, policy, monkeypatch):
    from fastapi.testclient import TestClient
    from conftest import identity_headers
    from myink.api.main import app
    from myink.db import new_session
    from myink.models import User
    from myink.api import routes_platform
    from myink.platform_readiness import PlatformNotReady
    client = TestClient(app)
    headers = identity_headers(temp_user)
    assert client.get('/api/v1/admin/configuration/readiness', headers=headers).status_code == 403
    with new_session() as db:
        db.get(User, uuid.UUID(temp_user)).role = 'admin'
        db.commit()
    audits = []
    monkeypatch.setattr(routes_platform, '_audit_or_fail', lambda *a: audits.append(a[2]))
    response = client.get('/api/v1/admin/configuration/readiness', headers=headers)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['ready']
    assert audits == ['admin.configuration.readiness']
    assert 'api_key' not in response.text and 'example.test' not in response.text
    def unavailable(*a):
        raise PlatformNotReady()
    monkeypatch.setattr('myink.api.routes_platform.catalog', unavailable)
    response = client.get('/api/v1/model-catalog', headers=headers)
    assert response.status_code == 503
    assert response.json() == {'error': 'PLATFORM_NOT_READY'}


@pytest.mark.parametrize('operation', ['dialogue', 'style'])
def test_account_unready_never_enters_reservation(policy, monkeypatch, operation):
    from myink import book_setup, style_extract
    from myink.platform_readiness import PlatformNotReady
    policy['connections']['good']['enabled'] = False
    monkeypatch.setattr('myink.environment.packed_models', lambda uid: {})
    monkeypatch.setattr('myink.model_admission.get_redis', lambda: pytest.fail('must not reserve account cost'))
    with pytest.raises(PlatformNotReady):
        if operation == 'dialogue':
            book_setup.generate_short_creation_turn([], {}, user_id=uuid.uuid4())
        else:
            style_extract.extract_style_profile(['文章。'], {}, user_id=uuid.uuid4())


def test_short_commit_unready_keeps_book_and_quota_unchanged(temp_user, policy):
    from fastapi.testclient import TestClient
    from conftest import identity_headers
    from myink.api.main import app
    from myink.db import new_session
    from myink.models import User, ShortCreationSession
    from myink.short import creation
    policy['connections']['good']['enabled'] = False
    card = {field:'有' for field in creation.REQUIRED_CARD_FIELDS} | {'working_title':'测试', 'genre':'现实主义',
        'chapter_count':3, 'chars_per_chapter':4000}
    with new_session() as db:
        session = ShortCreationSession(user_id=uuid.UUID(temp_user), status='active', card=card)
        db.add(session)
        db.commit()
        sid = session.id
        before = db.get(User, uuid.UUID(temp_user)).platform_short_used
    response = TestClient(app).post(f'/api/v1/short/creation/sessions/{sid}/commit', json={}, headers=identity_headers(temp_user))
    assert response.status_code == 503
    assert response.json() == {'error':'PLATFORM_NOT_READY'}
    with new_session() as db:
        assert db.get(ShortCreationSession,sid).book_id is None
        assert db.get(User, uuid.UUID(temp_user)).platform_short_used == before


def test_unready_legacy_resume_does_not_change_state_or_publish(policy, temp_project, monkeypatch):
    from myink.api.routes_tasks import resume_task
    from myink.db import tenant_session
    from myink.models import Task, Project
    from myink.platform_readiness import PlatformNotReady
    policy['connections']['good']['enabled'] = False
    tid = uuid.uuid4()
    with tenant_session(temp_project) as db:
        uid = str(db.get(Project,uuid.UUID(temp_project)).user_id)
        db.add(Task(id=tid, project_id=uuid.UUID(temp_project), task_type='short_generate', payload={}, status='paused'))
    published = []
    monkeypatch.setattr('myink.worker.amqp.publish', lambda *a,**kw: published.append(a))
    with pytest.raises(PlatformNotReady):
        resume_task(str(tid), user_id=uid)
    assert published == []
    with tenant_session(temp_project) as db:
        assert db.get(Task,tid).status == 'paused'


def test_unready_budget_resume_does_not_extend_or_publish(policy, temp_project, monkeypatch):
    from myink.task_budget import ensure_task_budget, budget_view, extend_and_resume_budget, ResumeBudgetBody
    from myink.db import tenant_session
    from myink.models import Task, Project
    from myink.platform_readiness import PlatformNotReady
    policy['connections']['good']['enabled'] = False
    tid = uuid.uuid4()
    with tenant_session(temp_project) as db:
        uid = str(db.get(Project,uuid.UUID(temp_project)).user_id)
        db.add(Task(id=tid, project_id=uuid.UUID(temp_project), task_type='short_generate', payload={}, status='paused'))
    ensure_task_budget(str(tid),temp_project,uid,{'max_requests':2})
    published = []
    monkeypatch.setattr('myink.worker.amqp.publish_once', lambda *a,**kw: published.append(a))
    with pytest.raises(PlatformNotReady):
        extend_and_resume_budget(str(tid),uid, ResumeBudgetBody(operation_id=uuid.uuid4(),add_requests=2))
    assert budget_view(str(tid))['limits']['max_requests'] == 2
    assert published == []


def test_unready_manual_plan_confirm_preserves_awaiting_state(policy, temp_project, monkeypatch):
    from myink.api.routes_tasks import confirm_task_plan, PlanConfirmBody
    from myink.db import tenant_session
    from myink.models import Task
    from myink.platform_readiness import PlatformNotReady
    policy['connections']['good']['enabled'] = False
    tid = uuid.uuid4()
    with tenant_session(temp_project) as db:
        db.add(Task(id=tid, project_id=uuid.UUID(temp_project), task_type='chapter_generate',
            payload={'mode':'manual'}, status='awaiting_plan'))
    with pytest.raises(PlatformNotReady):
        confirm_task_plan(str(tid), PlanConfirmBody(plan={}, expected_attempt=1))
    with tenant_session(temp_project) as db:
        assert db.get(Task,tid).status == 'awaiting_plan'


@pytest.mark.parametrize('defaults', [{'thinking_enabled':'private-invalid-value'}, {'task_budget':{'max_requests':-1}}, {'rankings':{'timeout':999}}, None])
def test_corrupt_defaults_report_fixed_reason_and_fail_runtime_safely(policy, monkeypatch, defaults):
    from myink.platform_readiness import readiness, PlatformNotReady
    policy['user_defaults'] = defaults
    result = readiness()
    assert not result['ready']
    assert len(result['checks']) == 6
    assert {check['reason'] for check in result['checks']} == {'defaults_invalid'}
    assert 'private-invalid-value' not in repr(result)
    monkeypatch.setattr('myink.environment.load_raw', lambda uid: {})
    with pytest.raises(PlatformNotReady):
        providers.make_user_chain('writer', uuid.uuid4())



def test_budget_operation_replay_survives_later_unready_policy(policy, temp_project, monkeypatch):
    from myink.task_budget import ensure_task_budget, budget_view, extend_and_resume_budget, ResumeBudgetBody
    from myink.db import tenant_session
    from myink.models import Task, Project
    tid = uuid.uuid4()
    with tenant_session(temp_project) as db:
        uid = str(db.get(Project,uuid.UUID(temp_project)).user_id)
        db.add(Task(id=tid, project_id=uuid.UUID(temp_project), task_type='short_generate', payload={}, status='paused'))
    ensure_task_budget(str(tid),temp_project,uid,{'max_requests':2})
    published = []
    monkeypatch.setattr('myink.worker.amqp.publish_once', lambda *a,**kw: published.append(a))
    body = ResumeBudgetBody(operation_id=uuid.uuid4(),add_requests=2)
    assert extend_and_resume_budget(str(tid),uid,body)['status'] == 'queued'
    policy['connections']['good']['enabled'] = False
    assert extend_and_resume_budget(str(tid),uid,body)['status'] == 'queued'
    assert len(published) == 1
    assert budget_view(str(tid))['limits']['max_requests'] == 4
