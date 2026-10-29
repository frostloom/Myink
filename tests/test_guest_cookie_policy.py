"""Transport policy must survive an HTTP hop from a Docker TLS proxy."""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from myink.api import auth
from myink.config import Settings
from myink import guests


@pytest.mark.parametrize("site, app_env, scheme, forwarded, secure", [
    ("myink.example.com", "dev", "http", "https", True),
    ("https://203.0.113.1", "dev", "http", "http", True),
    ("myink.example.com", "dev", "http", "http", True),
    ("http://localhost", "prod", "http", "http", True),
    ("http://localhost", "dev", "https", "http", True),
    ("http://localhost", "dev", "http", "https", False),
    ("http://127.0.0.1:8100", "dev", "http", "http", False),
    ("http://[::1]:8100", "test", "http", "http", False),
    ("http://myink.example.com", "dev", "http", "http", True),
    ("http://localhost.evil.example", "dev", "http", "http", True),
])
def test_guest_recovery_cookie_transport_policy(monkeypatch, site, app_env, scheme, forwarded, secure):
    monkeypatch.setenv("SITE_ADDRESS", site)
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("JWT_SECRET", "test-cookie-secret-at-least-32-bytes-long")
    monkeypatch.setattr(auth, "settings", Settings())
    monkeypatch.setattr(guests, "settings", auth.settings)
    uid = UUID("de9243a1-6d20-4629-90b8-f6b66bd9c2b4")
    user = SimpleNamespace(id=uid, username="guest-cookie", is_guest=True,
                           tier="normal", role="user", auth_version=1)
    # Only persistence is stubbed: the route, JWT and Set-Cookie are real.
    class Session:
        def scalar(self, statement):
            return SimpleNamespace(user_id=uid)
        def get(self, model, key):
            return user
        def commit(self):
            pass
    @contextmanager
    def session():
        yield Session()
    monkeypatch.setattr(auth, "new_session", session)
    app = FastAPI()
    app.include_router(auth.router)
    app.dependency_overrides[auth.auth_rate_limit] = lambda: None
    proxy = ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1,::1")
    with TestClient(proxy, base_url=f"{scheme}://myink.example.com", client=("172.18.0.5", 3456)) as client:
        response = client.post("/api/v1/auth/guest", json={"restore_only": True}, headers={
            "Cookie": "myink_guest=existing-recovery-secret",
            "X-Forwarded-Proto": forwarded,
            "Forwarded": "proto=http;host=localhost",
            "X-Forwarded-Host": "localhost",
        })
    assert response.status_code == 200, response.text
    assert response.json()["user_id"] == str(uid)
    cookie = response.headers["set-cookie"]
    assert ("; Secure" in cookie) is secure
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Path=/api/v1/auth/guest" in cookie
