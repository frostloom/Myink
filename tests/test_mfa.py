"""`/admin` 的第二因子（§2.8）：TOTP 认器、挑战票、开启/关闭与命令行兜底。

这一层护的是全站**唯一**能跨用户读数据的地方（admin 走 `myink_report` 连接绕过 RLS）。
三条边界必须钉住：

① 开了第二因子的账号，光有密码换不到令牌——只换到一张 5 分钟的挑战票；
② 挑战票不是 access token：issuer 与 access token 不同，过不了 `current_identity`；
③ 开启/关闭都自增 `auth_version`。少了这一条就白做——`/auth/session` 是滑动续期，
   标签页开着令牌就永不过期，于是攻击者用密码拿到的、**开启之前**签发的令牌会一直有效，
   第二因子整个被绕过去。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update
from typer.testing import CliRunner

from myink.api.main import app
from myink.cli import app as cli_app
from myink.db import new_session
from myink.invitations import create_invitation
from myink.models import Invitation, Project, User

client = TestClient(app)
runner = CliRunner()

PASSWORD = "correct horse battery 1"
AUTH_SHAPE = {"token", "user_id", "username", "tier", "role", "expires_in"}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _now(secret: str) -> str:
    return pyotp.TOTP(secret).now()


def _login(username: str) -> dict:
    """密码那一步。开了第二因子的账号回的是挑战票，也走这里。"""
    response = client.post("/api/v1/auth/token", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _exchange(username: str, secret: str) -> str:
    """走一遍「密码 → 挑战票 → 验码 → 令牌」，返回一张真能用的 access token。"""
    challenge = _login(username)
    response = client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": challenge["mfa_token"], "code": _now(secret)},
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


@contextmanager
def _account(*, role: str = "admin") -> Iterator[dict]:
    """注册一个真账号，按需提成管理员。

    role 是每请求从库里读的（令牌里没有 role 声明），所以直接改列即可，注册拿到的那张
    令牌不作废——本文件里「令牌被作废」只应该由第二因子那条路径造成。
    """
    username = f"mfa-{uuid.uuid4().hex[:12]}"
    with new_session() as db:
        invitation, code = create_invitation(
            db, expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        db.commit()
        invitation_id = invitation.id
    created = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": PASSWORD, "invitation_code": code},
    )
    assert created.status_code == 201, created.text
    user_id = uuid.UUID(created.json()["user_id"])
    if role != "user":
        with new_session() as db:
            db.execute(update(User).where(User.id == user_id).values(role=role))
            db.commit()
    try:
        yield {"username": username, "user_id": user_id, "token": created.json()["token"]}
    finally:
        with new_session() as db:
            db.execute(delete(Project).where(Project.user_id == user_id))
            db.execute(delete(User).where(User.id == user_id))
            db.execute(delete(Invitation).where(Invitation.id == invitation_id))
            db.commit()


@contextmanager
def _account_with_second_factor(*, role: str = "admin") -> Iterator[dict]:
    """开好第二因子的账号，外加一张确实有效的令牌（走完整登录 + 验码拿到的）。"""
    with _account(role=role) as account:
        enrolled = client.post(
            "/api/v1/auth/mfa/enroll",
            json={"password": PASSWORD},
            headers=_bearer(account["token"]),
        )
        assert enrolled.status_code == 200, enrolled.text
        secret = enrolled.json()["secret"]
        confirmed = client.post(
            "/api/v1/auth/mfa/confirm",
            json={"code": _now(secret)},
            headers=_bearer(account["token"]),
        )
        assert confirmed.status_code == 200, confirmed.text
        yield {**account, "secret": secret, "token": _exchange(account["username"], secret)}


def _totp_columns(user_id: uuid.UUID) -> tuple[str | None, object]:
    with new_session() as db:
        user = db.get(User, user_id)
        assert user is not None
        return user.totp_secret, user.totp_confirmed_at


def test_an_admin_without_a_second_factor_logs_in_exactly_as_before():
    """功能是「可开启」不是「强制开启」：没开的账号一个字都不该变。"""
    with _account() as account:
        data = _login(account["username"])
        assert set(data) == AUTH_SHAPE
        assert data["role"] == "admin"


def test_enrolling_requires_the_account_password_again():
    """光有令牌就够的话，偷到令牌的人能绑上自己的认证器，实现持久化占坑。"""
    with _account() as account:
        response = client.post(
            "/api/v1/auth/mfa/enroll",
            json={"password": "not the password"},
            headers=_bearer(account["token"]),
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "INVALID_CREDENTIALS"
        assert _totp_columns(account["user_id"]) == (None, None)


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/v1/auth/mfa", None),
    ("POST", "/api/v1/auth/mfa/enroll", {"password": PASSWORD}),
    ("POST", "/api/v1/auth/mfa/confirm", {"code": "000000"}),
    ("POST", "/api/v1/auth/mfa/disable", {"code": "000000"}),
])
def test_every_second_factor_endpoint_is_admin_only(method: str, path: str, body: dict | None):
    with _account(role="user") as account:
        response = client.request(method, path, json=body, headers=_bearer(account["token"]))
        assert response.status_code == 403
        assert response.json()["detail"] == "ADMIN_REQUIRED"


def test_status_reports_whether_the_second_factor_is_confirmed():
    with _account() as account:
        assert client.get(
            "/api/v1/auth/mfa", headers=_bearer(account["token"])
        ).json() == {"enabled": False}

    with _account_with_second_factor() as account:
        assert client.get(
            "/api/v1/auth/mfa", headers=_bearer(account["token"])
        ).json() == {"enabled": True}


def test_enrol_confirm_and_then_login_demands_a_code():
    """全流程，含三处易错点：待确认不算开启、挑战票不是令牌、开启踢掉存量会话。"""
    with _account() as account:
        token = account["token"]
        enrolled = client.post(
            "/api/v1/auth/mfa/enroll", json={"password": PASSWORD}, headers=_bearer(token))
        assert enrolled.status_code == 200, enrolled.text
        secret = enrolled.json()["secret"]
        assert enrolled.json()["otpauth_uri"].startswith("otpauth://totp/")

        # 待确认状态：密钥已落库，但登录方式还没变，所以登录照旧直接令牌。
        stored, confirmed = _totp_columns(account["user_id"])
        assert stored is not None and confirmed is None
        assert set(_login(account["username"])) == AUTH_SHAPE

        rejected = client.post(
            "/api/v1/auth/mfa/confirm", json={"code": "000000"}, headers=_bearer(token))
        assert rejected.status_code == 401
        assert rejected.json()["detail"] == "MFA_INVALID"
        assert _totp_columns(account["user_id"])[1] is None

        ok = client.post(
            "/api/v1/auth/mfa/confirm", json={"code": _now(secret)}, headers=_bearer(token))
        assert ok.status_code == 200, ok.text
        assert _totp_columns(account["user_id"])[1] is not None

        # ③ 开启自增 auth_version：开启之前签发的令牌（就是手里这张）当场失效。
        assert client.get("/api/v1/projects", headers=_bearer(token)).status_code == 401

        # ① 密码对了也只换到挑战票。
        challenge = _login(account["username"])
        assert set(challenge) == {"mfa_required", "mfa_token", "expires_in"}
        assert challenge["mfa_required"] is True
        assert challenge["expires_in"] == 300

        # ② 挑战票换不来任何受保护路由，包括它自己那组管理员端点。
        for path in ("/api/v1/projects", "/api/v1/auth/mfa"):
            assert client.get(path, headers=_bearer(challenge["mfa_token"])).status_code == 401

        wrong = client.post("/api/v1/auth/mfa/verify", json={
            "mfa_token": challenge["mfa_token"], "code": "000000"})
        assert wrong.status_code == 401
        assert wrong.json()["detail"] == "MFA_INVALID"

        exchanged = client.post("/api/v1/auth/mfa/verify", json={
            "mfa_token": challenge["mfa_token"], "code": _now(secret)})
        assert exchanged.status_code == 200, exchanged.text
        assert set(exchanged.json()) == AUTH_SHAPE
        assert client.get(
            "/api/v1/projects", headers=_bearer(exchanged.json()["token"])
        ).status_code == 200


def test_a_non_numeric_code_is_rejected_instead_of_crashing():
    with _account_with_second_factor() as account:
        challenge = _login(account["username"])
        response = client.post("/api/v1/auth/mfa/verify", json={
            "mfa_token": challenge["mfa_token"], "code": "abcdef"})
        assert response.status_code == 401


def test_the_challenge_is_void_once_the_password_changes():
    """挑战票里带着签发时的 ver，改密自增之后它在途作废。"""
    with _account_with_second_factor() as account:
        challenge = _login(account["username"])
        changed = client.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": "a much better password 2"},
            headers=_bearer(account["token"]),
        )
        assert changed.status_code == 200, changed.text
        stale = client.post("/api/v1/auth/mfa/verify", json={
            "mfa_token": challenge["mfa_token"], "code": _now(account["secret"])})
        assert stale.status_code == 401


def test_an_enabled_second_factor_must_be_closed_before_re_enrolling():
    """不给重新注册：那等于用一次不带验证码的请求把第二因子换掉。"""
    with _account_with_second_factor() as account:
        response = client.post(
            "/api/v1/auth/mfa/enroll",
            json={"password": PASSWORD},
            headers=_bearer(account["token"]),
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "MFA_ALREADY_ENABLED"


def test_disabling_needs_a_valid_code():
    with _account_with_second_factor() as account:
        response = client.post(
            "/api/v1/auth/mfa/disable", json={"code": "000000"}, headers=_bearer(account["token"]))
        assert response.status_code == 401
        assert response.json()["detail"] == "MFA_INVALID"
        assert _totp_columns(account["user_id"])[1] is not None


def test_disabling_clears_the_secret_and_revokes_every_session():
    with _account_with_second_factor() as account:
        live = account["token"]
        response = client.post(
            "/api/v1/auth/mfa/disable",
            json={"code": _now(account["secret"])},
            headers=_bearer(live),
        )
        assert response.status_code == 200, response.text
        assert _totp_columns(account["user_id"]) == (None, None)
        assert client.get("/api/v1/projects", headers=_bearer(live)).status_code == 401
        # 关掉之后又能只凭密码进去了。
        assert set(_login(account["username"])) == AUTH_SHAPE


def test_the_cli_is_the_way_back_when_the_authenticator_is_lost():
    """认器丢了没有恢复码，唯一入口是服务器上的 `myink mfa-disable <用户名>`。"""
    with _account_with_second_factor() as account:
        result = runner.invoke(cli_app, ["mfa-disable", account["username"]])
        assert result.exit_code == 0, result.output
        assert _totp_columns(account["user_id"]) == (None, None)
        assert client.get("/api/v1/projects", headers=_bearer(account["token"])).status_code == 401
        assert set(_login(account["username"])) == AUTH_SHAPE


def test_the_cli_reports_an_unknown_account():
    result = runner.invoke(cli_app, ["mfa-disable", f"nobody-{uuid.uuid4().hex[:8]}"])
    assert result.exit_code == 1