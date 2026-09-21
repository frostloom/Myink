"""限流器（网关退役后搬到 Python 的两个：进程内令牌桶 + 按 IP 的认证限流）。

conftest 的 `_no_rate_limits` 夹具在整套测试里把两个阈值抬到无穷大——否则共用同一个
TestClient 地址的几百次请求会到处 429。这里把阈值调回真实值，专测限流器本身。
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from myink.api.main import app
from myink.api.ratelimit import client_ip
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
        assert client.post("/internal/v1/auth/token", json=_BAD_LOGIN).status_code == 401
    blocked = client.post("/internal/v1/auth/token", json=_BAD_LOGIN)
    assert blocked.status_code == 429
    assert blocked.json() == {"error": "auth_rate_limited"}
    assert blocked.headers["retry-after"] == "60"


def test_auth_rate_limit_buckets_by_stamped_client_ip(monkeypatch):
    """两个客户端 IP 各有一个桶：一个被拒不影响另一个。"""
    import myink.api.ratelimit as rl

    monkeypatch.setattr(rl, "AUTH_RATE_MAX", 1)
    _forget("203.0.113.7", "203.0.113.8")
    first = client.post("/internal/v1/auth/token", json=_BAD_LOGIN,
                        headers={"X-Myink-Client-IP": "203.0.113.7"})
    assert first.status_code == 401
    again = client.post("/internal/v1/auth/token", json=_BAD_LOGIN,
                        headers={"X-Myink-Client-IP": "203.0.113.7"})
    assert again.status_code == 429
    other = client.post("/internal/v1/auth/token", json=_BAD_LOGIN,
                        headers={"X-Myink-Client-IP": "203.0.113.8"})
    assert other.status_code == 401


def test_auth_rate_limit_fails_closed_when_redis_is_down(monkeypatch):
    """Redis 不可用 → 503 而不是放行：这个限流器挡的是密码爆破。"""
    import myink.api.ratelimit as rl

    def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(rl, "get_redis", _boom)
    response = client.post("/internal/v1/auth/token", json=_BAD_LOGIN)
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
