"""Admin-managed invitations: keyed digest, custom code face, label, revoke, audit."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from myink import invitations as invitations_mod
from myink.api import auth
from myink.api.main import app
from myink.config import settings
from myink.db import get_admin_engine, new_session
from myink.invitations import hash_invitation_token
from myink.models import Invitation, User

client = TestClient(app, raise_server_exceptions=False)
PREFIX = "/api/v1/admin/invitations"
ADMIN_SECRET = "admin-test-secret-at-least-32-characters"
PASSWORD = "correct horse battery 1"


@pytest.fixture
def admin_actor(monkeypatch):
    monkeypatch.setattr(auth, "settings", replace(settings, jwt_secret=ADMIN_SECRET))
    Invitation.__table__.create(get_admin_engine(), checkfirst=True)
    with new_session() as db:
        actor = User(username=f"inv-admin-{uuid.uuid4().hex}", role="admin")
        other = User(username=f"inv-user-{uuid.uuid4().hex}", role="user")
        db.add_all([actor, other])
        db.commit()
    try:
        yield actor, other
    finally:
        with new_session() as db:
            db.query(Invitation).filter(Invitation.created_by == actor.id).delete()
            db.query(User).filter(User.id.in_([actor.id, other.id])).delete()
            db.commit()


def bearer(user):
    return {"Authorization": "Bearer " + auth.create_access_token(user.id, auth_version=user.auth_version)}


def _mine(actor) -> list[dict]:
    """本测试的邀请码：每次 fixture 都是新管理员，故 created_by 即本测试的全部产出。"""
    page = client.get(PREFIX + "?limit=100", headers=bearer(actor))
    assert page.status_code == 200, page.text
    return [row for row in page.json()["items"] if row["created_by"] == str(actor.id)]


def test_digest_is_keyed_hmac_not_a_bare_hash(monkeypatch):
    monkeypatch.setattr(invitations_mod, "settings", replace(settings, jwt_secret="key-one-at-least-32-bytes-long-aaa"))
    keyed = hash_invitation_token("SHORTCODE")
    assert len(keyed) == 64
    assert keyed == hash_invitation_token("  SHORTCODE  ")  # 两边都 strip，同码同摘要
    assert keyed != hashlib.sha256(b"SHORTCODE").hexdigest()  # 不是裸摘要：短码不可离线爆破
    monkeypatch.setattr(invitations_mod, "settings", replace(settings, jwt_secret="key-two-at-least-32-bytes-long-bbb"))
    assert hash_invitation_token("SHORTCODE") != keyed


def test_admin_creates_custom_code_with_label_and_list_never_leaks_it(admin_actor):
    actor, _ = admin_actor
    code = f"MYINK-{uuid.uuid4().hex[:8].upper()}"
    created = client.post(PREFIX, headers=bearer(actor), json={
        "expires_days": 3, "max_redemptions": 5, "label": "  内测第 2 批  ", "code": code})
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["code"] == code  # 明文只在此刻可见一次
    assert payload["label"] == "内测第 2 批"
    assert payload["max_redemptions"] == 5
    remaining = datetime.fromisoformat(payload["expires_at"]) - datetime.now(timezone.utc)
    assert timedelta(days=2, hours=23) < remaining <= timedelta(days=3)

    listing = client.get(PREFIX + "?limit=100", headers=bearer(actor))
    row = next(r for r in listing.json()["items"] if r["id"] == payload["id"])
    assert (row["label"], row["redemption_count"], row["max_redemptions"]) == ("内测第 2 批", 0, 5)
    assert row["revoked_at"] is None and row["created_by_username"] == actor.username
    assert "token_digest" not in row and "code" not in row
    with new_session() as db:
        stored = db.get(Invitation, uuid.UUID(payload["id"]))
        assert stored is not None
        assert stored.created_by == actor.id
        assert code not in listing.text and stored.token_digest not in listing.text


def test_duplicate_custom_code_conflicts(admin_actor):
    actor, _ = admin_actor
    code = f"DUP-{uuid.uuid4().hex[:8]}"
    assert client.post(PREFIX, headers=bearer(actor), json={"code": code}).status_code == 201
    duplicate = client.post(PREFIX, headers=bearer(actor), json={"code": code})
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "INVITATION_CODE_TAKEN"}
    assert len(_mine(actor)) == 1


@pytest.mark.parametrize("code,status", [("abc", 400), ("a" * 64, 201), ("a" * 65, 422)])
def test_custom_code_length_bounds(admin_actor, code, status):
    actor, _ = admin_actor
    response = client.post(PREFIX, headers=bearer(actor), json={"code": code})
    assert response.status_code == status, response.text
    if status == 400:
        assert response.json()["detail"].startswith("INVALID_INVITATION")


@pytest.mark.parametrize("body", [{"max_redemptions": 0}, {"max_redemptions": 1001},
                                  {"expires_days": 0}, {"expires_days": 366}])
def test_create_body_bounds(admin_actor, body):
    actor, _ = admin_actor
    response = client.post(PREFIX, headers=bearer(actor), json=body)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("identity,status", [("missing", 401), ("forged", 401), ("user", 403)])
def test_invitation_endpoints_reject_non_admins(admin_actor, identity, status):
    actor, other = admin_actor
    headers = ({} if identity == "missing"
               else {"X-Myink-User": str(actor.id)} if identity == "forged"
               else bearer(other))
    for method, path in (("get", PREFIX), ("post", PREFIX), ("post", f"{PREFIX}/{uuid.uuid4()}/revoke")):
        response = client.request(method, path, headers=headers, json={} if method == "post" else None)
        assert response.status_code == status, (method, path, response.text)
        assert response.headers["cache-control"] == "no-store"


def test_admin_happy_path_reaches_create_list_and_revoke(admin_actor):
    actor, _ = admin_actor
    assert client.get(PREFIX, headers=bearer(actor)).status_code == 200
    assert client.post(PREFIX, headers=bearer(actor), json={}).status_code == 201
    unknown = client.post(f"{PREFIX}/{uuid.uuid4()}/revoke", headers=bearer(actor))
    assert unknown.status_code == 404 and unknown.json() == {"detail": "NOT_FOUND"}
    assert client.post(f"{PREFIX}/not-a-uuid/revoke", headers=bearer(actor)).status_code == 422


def test_revoke_is_idempotent(admin_actor):
    actor, _ = admin_actor
    created = client.post(PREFIX, headers=bearer(actor), json={"code": f"REV-{uuid.uuid4().hex[:8]}"}).json()
    first = client.post(f"{PREFIX}/{created['id']}/revoke", headers=bearer(actor))
    assert first.status_code == 200 and first.json() == {"ok": True}
    revoked_at = next(r for r in _mine(actor) if r["id"] == created["id"])["revoked_at"]
    assert revoked_at is not None
    assert client.post(f"{PREFIX}/{created['id']}/revoke", headers=bearer(actor)).status_code == 200
    assert next(r for r in _mine(actor) if r["id"] == created["id"])["revoked_at"] == revoked_at


def test_invitation_writes_are_audited(admin_actor):
    actor, _ = admin_actor
    created = client.post(PREFIX, headers=bearer(actor), json={"code": f"AUD-{uuid.uuid4().hex[:8]}"}).json()
    assert client.post(f"{PREFIX}/{created['id']}/revoke", headers=bearer(actor)).status_code == 200
    logs = client.get("/api/v1/admin/access-logs?limit=100", headers=bearer(actor)).json()["items"]
    mine = [row for row in logs if row["actor_id"] == str(actor.id)]
    assert {"admin.create_invitation", "admin.revoke_invitation"} <= {row["action"] for row in mine}
    assert next(r for r in mine if r["action"] == "admin.create_invitation")["target"] == "collection"
    assert next(r for r in mine if r["action"] == "admin.revoke_invitation")["target"] == f"invitation_id={created['id']}"


def test_write_audit_fails_closed_so_no_code_is_minted(admin_actor, monkeypatch):
    from myink.api import routes_admin

    actor, _ = admin_actor
    boom = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Bearer DO-NOT-EXPOSE"))
    monkeypatch.setattr(routes_admin, "write_access_log", boom)
    response = client.post(PREFIX, headers=bearer(actor), json={"code": f"FAILD-{uuid.uuid4().hex[:8]}"})
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
    assert "DO-NOT-EXPOSE" not in response.text
    with new_session() as db:
        assert db.scalar(select(Invitation.id).where(Invitation.created_by == actor.id)) is None


def test_custom_code_registers_an_account_and_revocation_blocks_the_rest(admin_actor):
    actor, _ = admin_actor
    code = f"E2E-{uuid.uuid4().hex[:8].upper()}"
    created = client.post(PREFIX, headers=bearer(actor), json={"code": code, "max_redemptions": 2}).json()
    username = f"invited-{uuid.uuid4().hex[:8]}"
    try:
        registered = client.post("/api/v1/auth/register",
                                 json={"username": username, "password": PASSWORD, "invitation_code": code})
        assert registered.status_code == 201, registered.text
        assert registered.json()["role"] == "user"
        row = next(r for r in _mine(actor) if r["id"] == created["id"])
        assert (row["redemption_count"], row["max_redemptions"]) == (1, 2)

        assert client.post(f"{PREFIX}/{created['id']}/revoke", headers=bearer(actor)).status_code == 200
        blocked = client.post("/api/v1/auth/register", json={
            "username": f"blocked-{uuid.uuid4().hex[:8]}", "password": PASSWORD, "invitation_code": code})
        assert blocked.status_code == 403
        assert blocked.json() == {"detail": "INVITATION_REVOKED"}
    finally:
        with new_session() as db:
            db.query(User).filter(User.username == username).delete()
            db.commit()
