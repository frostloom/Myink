"""Guest credentials are browser scoped; upgrading revokes every guest credential."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from myink.api.main import app
from myink.db import new_session
from myink.models import User, Project, Invitation, GuestIdentity
from test_auth import _issue_invitation

IP = {"X-Myink-Client-IP": "203.0.113.7"}


@pytest.fixture
def browsers():
    clients = [TestClient(app), TestClient(app)]
    with new_session() as db:
        existing = set(db.scalars(select(User.id)))
    yield clients
    with new_session() as db:
        db.execute(delete(Project).where(Project.user_id.in_(select(User.id).where(User.id.not_in(existing)))))
        db.execute(delete(User).where(User.id.not_in(existing)))
        db.commit()


def guest(browser, **kwargs):
    response = browser.post('/api/v1/auth/guest', headers=IP, json=kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def test_browser_credentials_restore_only_their_own_identity(browsers):
    a, b = browsers
    first, second = guest(a), guest(b, is_guest=False, role='admin')
    assert first['user_id'] != second['user_id']
    assert first['is_guest'] is True
    cookie = a.cookies.get('myink_guest')
    with new_session() as db:
        stored = db.get(GuestIdentity, uuid.UUID(first['user_id']))
        assert stored.recovery_digest != cookie
        assert len(stored.original_ip_key) == 64
        assert db.get(User, stored.user_id).password_hash is None
    assert second['role'] == 'user'
    assert second['is_guest'] is True
    assert guest(a, restore_only=True)['user_id'] == first['user_id']
    token = {'Authorization': 'Bearer ' + first['token']}
    assert a.get('/api/v1/auth/session', headers=token).json()['is_guest'] is True
    assert a.post('/api/v1/auth/password', headers=token, json={'current_password':'', 'new_password':'a secure new password 1'}).status_code == 403


def test_restore_only_never_creates_and_invalid_ip_fails(browsers):
    a, _ = browsers
    assert a.post('/api/v1/auth/guest', headers=IP, json={'restore_only':True}).status_code == 401
    a.cookies.set('myink_guest', 'invalid')
    assert a.post('/api/v1/auth/guest', headers=IP, json={'restore_only':True}).status_code == 401
    assert a.post('/api/v1/auth/guest', headers={'X-Myink-Client-IP':'unknown'}, json={}).status_code == 503


def test_invitation_upgrade_preserves_projects_and_revokes_guest_credentials(browsers):
    a, _ = browsers
    identity = guest(a)
    old_cookie = a.cookies.get('myink_guest')
    uid = uuid.UUID(identity['user_id'])
    bearer = {'Authorization':'Bearer ' + identity['token']}
    username = 'upgraded-' + uuid.uuid4().hex[:12]
    with new_session() as db:
        project = Project(user_id=uid, title='guest draft', genre='fantasy', target_words=10000)
        db.add(project)
        db.commit()
        pid = project.id
    body = {'username':username, 'password':'a secure password 123', 'invitation_code':'invalid'}
    assert a.post('/api/v1/auth/register', headers=bearer, json=body).status_code == 403
    assert a.get('/api/v1/auth/session', headers=bearer).json()['is_guest'] is True
    invitation_id, body['invitation_code'] = _issue_invitation()
    try:
        result = a.post('/api/v1/auth/register', headers=bearer, json=body)
        assert result.status_code == 201, result.text
        assert result.json()['user_id'] == str(uid)
        assert result.json()['is_guest'] is False
        assert a.get('/api/v1/auth/session', headers=bearer).status_code == 401
        a.cookies.set('myink_guest', old_cookie)
        assert a.post('/api/v1/auth/guest', headers=IP, json={'restore_only':True}).status_code == 401
        with new_session() as db:
            assert db.get(Project, pid).user_id == uid
    finally:
        with new_session() as db:
            db.execute(delete(Project).where(Project.id == pid))
            db.execute(delete(User).where(User.id == uid))
            db.execute(delete(Invitation).where(Invitation.id == invitation_id))
            db.commit()


def test_ip_key_normalizes_and_rejects_unknown():
    from myink.guests import ip_key
    assert ip_key('2001:db8::1') == ip_key('2001:0db8:0:0:0:0:0:1')
    assert ip_key('::ffff:192.0.2.1') == ip_key('192.0.2.1')
    assert ip_key('192.0.2.1') != ip_key('192.0.2.2')
    for raw in ('unknown', '', '1.2.3.4, 5.6.7.8', 'fe80::1%en0'):
        with pytest.raises(ValueError):
            ip_key(raw)


def test_regular_bearer_registration_creates_a_separate_regular_account():
    from test_auth import _registered_account, client
    with _registered_account() as existing:
        invitation_id, invitation_code = _issue_invitation()
        new_id = None
        try:
            result = client.post('/api/v1/auth/register',
                headers={'Authorization': 'Bearer ' + existing['token']},
                json={'username': 'new-' + uuid.uuid4().hex[:12],
                      'password': 'another secure password 123',
                      'invitation_code': invitation_code})
            assert result.status_code == 201, result.text
            new_id = uuid.UUID(result.json()['user_id'])
            assert str(new_id) != existing['user_id']
            assert result.json()['is_guest'] is False
            session = client.get('/api/v1/auth/session',
                headers={'Authorization': 'Bearer ' + existing['token']})
            assert session.status_code == 200
            assert session.json()['username'] == existing['username']
            assert session.json()['is_guest'] is False
        finally:
            with new_session() as db:
                if new_id is not None:
                    db.execute(delete(User).where(User.id == new_id))
                db.execute(delete(Invitation).where(Invitation.id == invitation_id))
                db.commit()
