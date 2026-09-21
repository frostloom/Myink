"""身份边界（§14.1 ③）：业务路由只认自己验过的 Bearer。

网关时代 Python 直接读 `X-Myink-User` 明文头，因为它假定「能连上来的只有网关」。
现在 Python 自己验签、自己查库，这个文件把那条边界钉死——重点是两类静默越权：
新路由忘了挂守卫，以及明文头被重新当成身份采信。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import delete

from conftest import TEST_JWT_SECRET, identity_headers
from myink.api import main as api_main
from myink.api.main import app
from myink.db import new_session
from myink.models import AgentRun, Project, User

client = TestClient(app)

# 不需要身份就能访问的路径：两个探针，以及两个签发端点
# （没有令牌才需要拿令牌，它们靠 by-IP 的 auth_rate_limit 挡爆破）。
OPEN_PATHS = {
    "/healthz", "/readyz",
    "/api/v1/auth/register", "/api/v1/auth/token",
}

# 依赖闭包里出现任一名字即视为「挂了身份守卫」。
# `_bearer`（HTTPBearer auto_error=False）刻意不在列：它只是「取一下凭证」，凭证缺失时回
# None 而不是拒绝——真正做判断的是下面这些。
_GUARDS = {
    "current_user", "current_identity", "require_user", "require_owner",
    "require_admin", "_authenticated_user", "_decode_bearer",
}

_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _business_routes() -> list[tuple[str, str]]:
    """业务路由全集，取自 OpenAPI schema。

    不要直接遍历 `app.routes`：这个 FastAPI 版本把 `include_router` 收成了
    `_IncludedRouter` 容器，不再展开成 `APIRoute`，那样遍历会静默退化成只剩 app 级路由
    （`test_sweep_actually_covers_the_business_surface` 就是防这个）。仓库里没有任何
    `include_in_schema=False`，所以 schema 就是全集。
    """
    routes = []
    for path, operations in app.openapi()["paths"].items():
        if path in OPEN_PATHS:
            continue
        for method in operations:
            if method.upper() in _METHODS:
                routes.append((method.upper(), path))
    return routes


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), path)


def _guard_names(dependant) -> set[str]:
    """递归展开依赖闭包里的可调用名（装饰器级 dependencies= 也长在这棵树上）。"""
    names: set[str] = set()
    for sub in dependant.dependencies:
        names.add(getattr(sub.call, "__name__", type(sub.call).__name__))
        names |= _guard_names(sub)
    return names


def _declared_routes() -> list[APIRoute]:
    """业务路由对象，来自两处：app 自带的，以及 13 个路由器上的。

    不从 `app.routes` 取后者：这个 FastAPI 版本把 `include_router` 收成 `_IncludedRouter`
    容器，不展开成 `APIRoute`，只遍历 app.routes 会静默漏掉全部路由器路由。
    """
    routes = [r for r in app.routes if isinstance(r, APIRoute)]
    for value in vars(api_main).values():
        if isinstance(value, APIRouter):
            routes.extend(r for r in value.routes if isinstance(r, APIRoute))
    return routes


@pytest.fixture
def accounts():
    """两个真账号各带一本自己的书（auth_version 取列默认值 1）。"""
    with new_session() as db:
        users = [User(username=f"bnd-{uuid.uuid4().hex}") for _ in range(2)]
        db.add_all(users)
        db.flush()
        books = [Project(user_id=u.id, title=f"bnd-book-{u.id}") for u in users]
        db.add_all(books)
        db.commit()
        rows = [(u.id, b.id) for u, b in zip(users, books)]
    try:
        yield rows
    finally:
        with new_session() as db:
            db.execute(delete(AgentRun).where(AgentRun.project_id.in_([b for _, b in rows])))
            db.execute(delete(Project).where(Project.id.in_([b for _, b in rows])))
            db.execute(delete(User).where(User.id.in_([u for u, _ in rows])))
            db.commit()


def _claims(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    claims = {"sub": str(uuid.uuid4()), "iss": "myink", "tier": "normal", "ver": 1,
              "iat": now, "exp": now + timedelta(seconds=300)}
    claims.update(overrides)
    return claims


def test_every_business_route_rejects_anonymous_and_forged_identity(accounts):
    """遍历业务路由：每条对「无凭证」和「伪造明文头」都必须关门。

    将来有人加了路由却忘了挂 current_user / require_*，这里直接点名。
    回 200 且空列表是允许的——`GET /projects` 的 fail-closed 就是回空；真正要拦的是「回了数据」。
    """
    uid_a, _ = accounts[0]
    forged = {"X-Myink-User": str(uid_a)}
    offenders = []
    for method, path in _business_routes():
        url = _fill(path)
        for label, headers in (("无凭证", {}), ("伪造明文头", forged)):
            response = client.request(method, url, json={}, headers=headers)
            if response.status_code in (401, 403):
                continue
            if response.status_code == 422:
                # 请求体校验先于端点体执行。`current_user` 对「没带凭证」是**返回 None**
                # 而不是抛，所以像 POST /projects 这种把 403 写在端点里的路由，会先撞上
                # 「缺 title」的 422。422 同样一个字节数据都没吐，算关门。
                # 代价是这条路让「守卫有没有挂」在这类路由上不可见——由下面的结构化测试补。
                continue
            if response.status_code == 200 and response.json() == []:
                continue
            offenders.append(f"{method} {url} [{label}] -> {response.status_code} {response.text[:100]}")
    assert not offenders, "身份边界漏了：\n" + "\n".join(offenders)


def test_every_business_route_has_an_identity_dependency():
    """结构化补强：每条业务路由的依赖闭包里必须有一个守卫。

    上面那个遍历会把 422 当关门，于是「忘挂守卫、但恰好要求请求体」的路由在那里看不出来。
    这条不看响应，只看装配——也正是它能发现 /skill-presets、/genre-packs 那类
    「网关时代挂在 secured 里、换成 Caddy 直连后守卫丢失」的静默越权。
    """
    unguarded = sorted(
        f"{sorted(route.methods)} {route.path}"
        for route in _declared_routes()
        if route.path not in OPEN_PATHS and not (_guard_names(route.dependant) & _GUARDS)
    )
    assert not unguarded, "这些业务路由没挂身份守卫：\n" + "\n".join(unguarded)


def test_the_structural_sweep_actually_sees_the_routers():
    """防止 _declared_routes 因为装配方式变化而静默退化成只剩 app 级那 5 条。"""
    paths = {route.path for route in _declared_routes()}
    assert len(paths) > 50, f"只看到 {len(paths)} 条路由，路由器可能没被取到"
    assert "/api/v1/projects/{project_id}/chapters" in paths
    assert "/api/v1/skill-presets" in paths


def test_sweep_actually_covers_the_business_surface():
    """防止上面的遍历因为路由装配方式变化而静默退化成空循环。"""
    paths = {path for _, path in _business_routes()}
    assert len(paths) > 50, f"只扫到 {len(paths)} 条业务路由，遍历可能坏了"
    assert "/api/v1/projects/{project_id}/chapters" in paths


@pytest.mark.parametrize("method,suffix,body", [
    ("GET", "/chapters", None),
    ("GET", "/creation", None),
    ("GET", "/tasks", None),
    ("GET", "/outline", None),
    ("PUT", "", {"target_words": 3000}),
    ("DELETE", "", None),
])
def test_foreign_account_gets_403(accounts, method, suffix, body):
    """跨账号是 403（身份本身有效，只是不拥有这本）——与「未知账号 401」是两回事。"""
    (_, book_a), (uid_b, _) = accounts
    response = client.request(method, f"/api/v1/projects/{book_a}{suffix}",
                              json=body, headers=identity_headers(uid_b))
    assert response.status_code == 403, f"{method} {suffix} -> {response.status_code}"


def test_forged_plaintext_header_cannot_override_or_elevate(accounts):
    """明文头既不能覆盖令牌身份，也不能提权。"""
    (uid_a, book_a), (uid_b, _) = accounts
    spoofed_own = {**identity_headers(uid_a), "X-Myink-User": str(uid_b)}
    assert client.get(f"/api/v1/projects/{book_a}/chapters",
                      headers=spoofed_own).status_code == 200
    spoofed_foreign = {**identity_headers(uid_b), "X-Myink-User": str(uid_a)}
    assert client.get(f"/api/v1/projects/{book_a}/chapters",
                      headers=spoofed_foreign).status_code == 403


def test_logout_revokes_the_session_immediately(accounts):
    """登出 → auth_version++ → 同一个令牌马上失效。

    撤销检查现在就在 Python 里（`_load_identity` 比对 auth_version），
    不再是网关每次请求回调 `/auth/session` 的那一次 HTTP 往返。
    """
    uid_a, book_a = accounts[0]
    headers = identity_headers(uid_a)
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert client.get(f"/api/v1/projects/{book_a}/chapters", headers=headers).status_code == 401


@pytest.mark.parametrize("claims", [
    pytest.param(_claims(), id="签名合法但账号不存在"),
    pytest.param(_claims(exp=datetime.now(timezone.utc) - timedelta(seconds=1)), id="已过期"),
    pytest.param(_claims(iss="not-myink"), id="issuer 不符"),
    pytest.param(_claims(sub="not-a-uuid"), id="sub 不是 UUID"),
    pytest.param(_claims(ver=0), id="ver < 1"),
    pytest.param(_claims(ver="1"), id="ver 不是整数"),
    pytest.param(_claims(ver=True), id="ver 是 bool（int 的子类，必须显式拒）"),
    pytest.param({k: v for k, v in _claims().items() if k != "ver"}, id="缺 ver"),
    pytest.param({k: v for k, v in _claims().items() if k != "exp"}, id="缺 exp"),
])
def test_bad_bearer_is_rejected_with_401(accounts, claims):
    token = jwt.encode(claims, TEST_JWT_SECRET, algorithm="HS256")
    response = client.get(f"/api/v1/projects/{accounts[0][1]}/chapters",
                          headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.parametrize("algorithm", ["HS512", "none"])
def test_token_signed_with_another_algorithm_is_rejected(accounts, algorithm):
    """只认 HS256：换算法（含 alg=none）一律不通过。"""
    if algorithm == "none":
        token = jwt.encode(_claims(), key="", algorithm="none")
    else:
        token = jwt.encode(_claims(), TEST_JWT_SECRET, algorithm=algorithm)
    response = client.get(f"/api/v1/projects/{accounts[0][1]}/chapters",
                          headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.parametrize("scheme", ["Basic", "Token"])
def test_non_bearer_authorization_scheme_is_ignored(accounts, scheme):
    """非 bearer 方案一律当成「没带凭证」→ 403（不是 401）。"""
    response = client.get(f"/api/v1/projects/{accounts[0][1]}/chapters",
                          headers={"Authorization": f"{scheme} abc"})
    assert response.status_code == 403
