"""限流器（网关退役后搬到 Python 的两个：进程内令牌桶 + 按 IP 的认证限流）。

conftest 的 `_no_rate_limits` 夹具在整套测试里把两个阈值抬到无穷大——否则共用同一个
TestClient 地址的几百次请求会到处 429。这里把阈值调回真实值，专测限流器本身。
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete as sa_delete
from starlette.requests import Request

from myink.api.main import app
from myink.api.ratelimit import client_ip
from myink.db import new_session
from myink.invitations import create_invitation
from myink.models import Invitation, Project, User
from myink.worker.redis_client import get_redis

client = TestClient(app)

_BAD_LOGIN = {"username": "nobody", "password": "wrong password 1"}


def _auth_key(ip: str) -> str:
    return "rate:auth:" + hashlib.sha256(ip.encode()).hexdigest()


def _forget(*ips: str) -> None:
    """清计数：整套测试共用一个 Redis，别的用例可能已经把这个键顶起来过。"""
    keys = [_auth_key(ip) for ip in ips] or [_auth_key("testclient")]
    get_redis().delete(*keys)


def _request(headers: dict[str, str], peer: str | None = "10.0.0.1") -> Request:
    return Request({
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 12345) if peer else None,
    })


@pytest.mark.parametrize("headers,peer,expected", [
    ({"X-Myink-Client-IP": "203.0.113.9"}, "10.0.0.1", "203.0.113.9"),   # 边缘盖章 → 用它
    ({"X-Myink-Client-IP": "::1"}, "10.0.0.1", "::1"),                    # v6 也认
    ({"X-Myink-Client-IP": "not-an-ip"}, "10.0.0.1", "10.0.0.1"),         # 值非法 → 退回直连
    ({"X-Myink-Client-IP": ""}, "10.0.0.1", "10.0.0.1"),                  # 空值 → 退回直连
    ({"X-Myink-Client-IP": "1.2.3.4, 5.6.7.8"}, "10.0.0.1", "10.0.0.1"),  # 逗号列表不是单 IP
    ({}, "10.0.0.1", "10.0.0.1"),                                         # 没有头 → 直连地址
    ({}, None, "unknown"),                                               # 都没有 → 兜底
])
def test_client_ip_reads_only_a_stamped_single_address(headers, peer, expected):
    assert client_ip(_request(headers, peer)) == expected


def test_auth_rate_limit_trips_at_threshold(monkeypatch):
    """第 N+1 次尝试被拒（与网关 auth.go 的 `n > 20` 同形），并带 Retry-After。"""
    import myink.api.ratelimit as rl

    monkeypatch.setattr(rl, "AUTH_RATE_MAX", 3)
    _forget()
    for _ in range(3):
        assert client.post("/api/v1/auth/token", json=_BAD_LOGIN).status_code == 401
    blocked = client.post("/api/v1/auth/token", json=_BAD_LOGIN)
    assert blocked.status_code == 429
    assert blocked.json() == {"error": "auth_rate_limited"}
    assert blocked.headers["retry-after"] == "60"


def test_auth_rate_limit_buckets_by_stamped_client_ip(monkeypatch):
    """两个客户端 IP 各有一个桶：一个被拒不影响另一个。"""
    import myink.api.ratelimit as rl

    monkeypatch.setattr(rl, "AUTH_RATE_MAX", 1)
    _forget("203.0.113.7", "203.0.113.8")
    first = client.post("/api/v1/auth/token", json=_BAD_LOGIN,
                        headers={"X-Myink-Client-IP": "203.0.113.7"})
    assert first.status_code == 401
    again = client.post("/api/v1/auth/token", json=_BAD_LOGIN,
                        headers={"X-Myink-Client-IP": "203.0.113.7"})
    assert again.status_code == 429
    other = client.post("/api/v1/auth/token", json=_BAD_LOGIN,
                        headers={"X-Myink-Client-IP": "203.0.113.8"})
    assert other.status_code == 401


def test_auth_rate_limit_fails_closed_when_redis_is_down(monkeypatch):
    """Redis 不可用 → 503 而不是放行：这个限流器挡的是密码爆破。"""
    import myink.api.ratelimit as rl

    def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(rl, "get_redis", _boom)
    response = client.post("/api/v1/auth/token", json=_BAD_LOGIN)
    assert response.status_code == 503
    assert response.json() == {"error": "auth_unavailable"}


def test_app_installs_the_global_token_bucket(monkeypatch):
    """全局令牌桶确实挂在 app 上（验证装配，而不是只单测那个类）。"""
    import myink.api.ratelimit as rl

    monkeypatch.setattr(rl, "settings", replace(rl.settings, rate_per_sec=0, rate_burst=1))
    monkeypatch.setattr(app, "middleware_stack", None)  # 逼 Starlette 按新配置重建
    assert client.get("/healthz").status_code == 200
    blocked = client.get("/healthz")
    assert blocked.status_code == 429
    assert blocked.json() == {"error": "rate_limited"}


# --- 账号维度（网关时代没有的那一层） -----------------------------------------

def _account_key(username: str) -> str:
    from myink.api.ratelimit import _account_key as key

    return key(username)


def _forget_accounts(*usernames: str) -> None:
    get_redis().delete(*[_account_key(name) for name in usernames])


@contextmanager
def _registered_account(*, password: str = "correct horse battery 1"):
    """建一个真账号：验密成功那条路径需要它（IP 桶此时已被抬到无穷大）。"""
    username = f"acct-{uuid.uuid4().hex[:12]}"
    with new_session() as db:
        invitation, code = create_invitation(
            db, expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        db.commit()
        invitation_id = invitation.id
    created = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password, "invitation_code": code},
    )
    assert created.status_code == 201, created.text
    user_id = uuid.UUID(created.json()["user_id"])
    try:
        yield {"username": username, "password": password, "user_id": user_id}
    finally:
        with new_session() as db:
            db.execute(sa_delete(Project).where(Project.user_id == user_id))
            db.execute(sa_delete(User).where(User.id == user_id))
            db.execute(sa_delete(Invitation).where(Invitation.id == invitation_id))
            db.commit()


def test_account_bucket_trips_across_different_client_ips(monkeypatch):
    """换代理池绕不过去：同一个账号从三个不同地址试密码，第 N+1 次照样被拒。

    IP 桶单独看是过不了的——每个地址只试了一次。
    """
    import myink.api.ratelimit as rl

    monkeypatch.setattr(rl, "AUTH_ACCOUNT_MAX", 2)
    monkeypatch.setattr(rl, "AUTH_RATE_MAX", 10**9)
    username = f"victim-{uuid.uuid4().hex[:8]}"
    body = {"username": username, "password": "wrong password 1"}
    _forget_accounts(username)
    try:
        for hop in ("203.0.113.1", "203.0.113.2"):
            assert client.post("/api/v1/auth/token", json=body,
                               headers={"X-Myink-Client-IP": hop}).status_code == 401
        blocked = client.post("/api/v1/auth/token", json=body,
                              headers={"X-Myink-Client-IP": "203.0.113.3"})
        assert blocked.status_code == 429
        assert blocked.json() == {"error": "auth_rate_limited"}
        assert blocked.headers["retry-after"] == "60"
    finally:
        _forget_accounts(username)


def test_account_bucket_is_per_account(monkeypatch):
    """一个账号被刷满了，不牵连别的账号。"""
    import myink.api.ratelimit as rl

    monkeypatch.setattr(rl, "AUTH_ACCOUNT_MAX", 1)
    monkeypatch.setattr(rl, "AUTH_RATE_MAX", 10**9)
    first, second = f"a-{uuid.uuid4().hex[:8]}", f"b-{uuid.uuid4().hex[:8]}"
    _forget_accounts(first, second)
    try:
        wrong = {"password": "wrong password 1"}
        assert client.post("/api/v1/auth/token",
                           json={**wrong, "username": first}).status_code == 401
        assert client.post("/api/v1/auth/token",
                           json={**wrong, "username": first}).status_code == 429
        assert client.post("/api/v1/auth/token",
                           json={**wrong, "username": second}).status_code == 401
    finally:
        _forget_accounts(first, second)


def test_successful_login_clears_the_account_counter(monkeypatch):
    """密码对了先清计数再放行——正常用户不会被自己刚才的输错拖住。"""
    import myink.api.ratelimit as rl

    monkeypatch.setattr(rl, "AUTH_ACCOUNT_MAX", 3)
    monkeypatch.setattr(rl, "AUTH_RATE_MAX", 10**9)
    with _registered_account() as account:
        username = account["username"]
        _forget_accounts(username)
        try:
            for _ in range(2):
                assert client.post(
                    "/api/v1/auth/token",
                    json={"username": username, "password": "wrong password 1"},
                ).status_code == 401
            assert get_redis().get(_account_key(username)) is not None
            ok = client.post("/api/v1/auth/token",
                             json={"username": username, "password": account["password"]})
            assert ok.status_code == 200
            assert get_redis().get(_account_key(username)) is None
        finally:
            _forget_accounts(username)


def test_account_guard_fails_closed_when_redis_is_down(monkeypatch):
    """账号桶与 IP 桶同一条纪律：Redis 不可用就 503，绝不放行。"""
    import myink.api.ratelimit as rl

    def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(rl, "get_redis", _boom)
    with pytest.raises(rl.ApiError) as raised:
        rl.account_auth_guard("someone")
    assert (raised.value.status_code, raised.value.code) == (503, "auth_unavailable")


def _mfa_bucket_key(account: str) -> str:
    from myink.api.ratelimit import _mfa_key as key

    return key(account)


def _forget_mfa(*accounts: str) -> None:
    get_redis().delete(*[_mfa_bucket_key(account) for account in accounts])


def test_second_factor_bucket_trips_per_account(monkeypatch):
    """验码桶比登录更紧，而且按**账号 id** 分：一个人被刷满不牵连另一个账号。

    键用 id 而不是用户名——验码请求里只有挑战票，拿不到用户名。所以这里直接测函数，
    不走 HTTP：要走到那个桶得先有一张签名有效的挑战票（那属于 test_mfa.py 的正路）。
    """
    import myink.api.ratelimit as rl

    monkeypatch.setattr(rl, "MFA_MAX", 3)
    first, second = f"acct-{uuid.uuid4().hex}", f"acct-{uuid.uuid4().hex}"
    _forget_mfa(first, second)
    try:
        for _ in range(3):
            rl.mfa_failed(first)
        with pytest.raises(rl.ApiError) as raised:
            rl.mfa_guard(first)
        assert (raised.value.status_code, raised.value.code) == (429, "auth_rate_limited")
        assert raised.value.headers["Retry-After"] == "60"

        rl.mfa_guard(second)  # 另一个账号不受牵连
        rl.mfa_cleared(first)  # 验过了就清计数，正常用户不被自己刚才输错的一次拖住
        rl.mfa_guard(first)
    finally:
        _forget_mfa(first, second)


def test_second_factor_guard_fails_closed_when_redis_is_down(monkeypatch):
    import myink.api.ratelimit as rl

    def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(rl, "get_redis", _boom)
    with pytest.raises(rl.ApiError) as raised:
        rl.mfa_guard("someone")
    assert (raised.value.status_code, raised.value.code) == (503, "auth_unavailable")
