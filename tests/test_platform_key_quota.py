"""Platform-owned credentials and quota policy; legacy personal connections cannot bypass either."""
from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import myink.config as config
from conftest import identity_headers
from myink.api import routes_book, routes_short_creation, routes_tasks
from myink.api.main import app
from myink.db import ensure_user_environment, new_session
from myink.environment import save_raw
from myink.models import ShortCreationSession, User
from myink.providers import make_chain, make_user_chain, platform_key_active
from myink.providers.connections import CUSTOM_ROUTE_PREFIX, pack_model_settings
from myink.short import creation

client = TestClient(app)
ensure_user_environment()

# 换掉这几个模块的 `settings`，`platform_model_configured()` 才是真的、额度数字才跟着变。
# 它每次调用都重新 `from myink.config import settings`，所以打 `myink.config` 那一处就够它看见；
# 各路由模块自己 import 的那份要单独换。
_PLATFORM_MODULES = (config, routes_book, routes_short_creation, routes_tasks)


@pytest.fixture
def platform(monkeypatch):
    """装上「部署方配了内置密钥」，返回一个改额度数字的开关。"""
    def _apply(**overrides):
        patched = replace(config.settings,
                          platform_model_api_key="sk-platform",
                          platform_model_base_url="https://platform.example.com/v1",
                          platform_model_name="platform-pro",
                          platform_model_protocol="openai",
                          **overrides)
        for module in _PLATFORM_MODULES:
            monkeypatch.setattr(module, "settings", patched)
        return patched

    from myink.providers.openai_compatible import OpenAICompatibleProvider
    from myink.providers.base import ModelResponse
    monkeypatch.setattr(OpenAICompatibleProvider, 'generate',
                        lambda *args, **kwargs: ModelResponse(content='', model_id='platform-pro',
                                                              error='isolated platform failure'))
    return _apply


def _install_connection(user: str, routes: dict) -> None:
    """Seed legacy storage directly; the writer API no longer accepts credentials."""
    cid = str(uuid.uuid4())
    save_raw(user, {'models': pack_model_settings(
        {role: f'custom:{cid}' for role in routes},
        {cid: {'name': 'Legacy', 'protocol': 'openai', 'base_url': 'https://models.example.com/v1',
               'model': 'legacy-model', 'api_key_encrypted': 'legacy-ciphertext'}},
    )})


def _used(user: str, column: str) -> int:
    with new_session() as db:
        return getattr(db.get(User, uuid.UUID(user)), column)


# ---- 凭据层：什么时候轮到平台密钥 ----

def test_without_a_platform_key_everything_stays_unconfigured(temp_user):
    """没配密钥：链照旧是 unconfigured，也不认为账号「在吃平台密钥」。"""
    from myink.platform_readiness import PlatformNotReady
    with pytest.raises(PlatformNotReady):
        make_user_chain("planner", temp_user)
    assert platform_key_active(temp_user, "user") is False


def test_the_platform_key_serves_an_account_without_any_connection(temp_user, platform):
    platform()
    assert make_user_chain("planner", temp_user).chain == ["platform-pro"]
    assert platform_key_active(temp_user, "user") is True


def test_a_legacy_connection_cannot_bypass_platform_routing_or_quota(temp_user, platform):
    platform()
    _install_connection(temp_user, {'writer': None})
    assert make_user_chain('validator_l2', temp_user).chain == ['platform-pro']
    assert platform_key_active(temp_user, 'user') is True


def test_a_role_that_is_never_configurable_does_not_reach_the_platform_key(temp_user, platform):
    """压根不该调模型的角色（不在这里的 CONFIGURABLE_ROLES / 继承表里）不该拿到平台密钥。

    `_project_primary` 对这类角色也返回 None，所以 make_chain 里那道角色判据不是多余的——
    少了它，「角色不可配」与「该调但没配路由」就分不开，后者才轮到平台密钥。
    """
    platform()
    assert make_chain("不存在的角色", None).chain == ["unconfigured"]


def test_a_broken_legacy_connection_is_ignored_and_still_metered(temp_user, platform):
    platform()
    _install_connection(temp_user, {'planner': None})
    assert make_user_chain('planner', temp_user).chain == ['platform-pro']
    assert platform_key_active(temp_user, 'user') is True


def test_admin_is_never_on_the_platform_key(platform):
    """admin 永久豁免，否则部署方自己没法测。判据在碰数据库之前就短路了。"""
    platform()
    assert platform_key_active(uuid.uuid4(), "admin") is False


# ---- 计费层：建书扣一次终身额度 ----

def _create(user: str, **overrides):
    return client.post("/api/v1/projects", headers=identity_headers(user), json={
        "title": f"免费长篇-{uuid.uuid4().hex[:6]}", "premise": "梗概",
        "chapter_count": 50, "storyline": "线", **overrides})


def test_the_lifetime_quota_stops_the_fourth_free_book(temp_user, platform):
    platform(platform_long_quota=3, books_per_day_max=1000)
    for _ in range(3):
        assert _create(temp_user).status_code == 200
    blocked = _create(temp_user)
    assert blocked.status_code == 429, blocked.text
    assert blocked.json() == {"error": "PLATFORM_QUOTA_EXCEEDED"}
    assert _used(temp_user, "platform_long_used") == 3


def test_a_resend_with_the_same_request_id_is_not_charged_twice(temp_user, platform):
    """前端重试就是拿同一个 request_id 再发一次；返回的是同一本书，额度也只能吃一次。"""
    platform(platform_long_quota=1, books_per_day_max=1000)
    body = {"request_id": str(uuid.uuid4())}
    first = _create(temp_user, **body)
    second = _create(temp_user, **body)
    assert first.status_code == second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    assert _used(temp_user, "platform_long_used") == 1


def test_a_refused_creation_does_not_burn_quota(temp_user, platform):
    """当日建书数被拦下时事务整体回滚，免费额度也跟着退回去（不是白吃一次）。"""
    platform(platform_long_quota=3, books_per_day_max=1)
    assert _create(temp_user).status_code == 200
    refused = _create(temp_user)
    assert refused.status_code == 429
    assert refused.json() == {"error": "BOOK_CNT_EXCEEDED"}
    assert _used(temp_user, "platform_long_used") == 1


def test_admin_creates_books_without_spending_the_quota(temp_user, platform):
    platform(platform_long_quota=1, books_per_day_max=1000)
    with new_session() as db:
        db.get(User, uuid.UUID(temp_user)).role = "admin"
        db.commit()
    assert _create(temp_user).status_code == 200
    assert _create(temp_user).status_code == 200
    assert _used(temp_user, "platform_long_used") == 0


def test_without_a_platform_key_books_are_never_capped(temp_user):
    """没配内置密钥 → 不限额。默认那 3 本**只在有密钥时才存在**，否则是把人凭空拦住。"""
    for _ in range(5):
        assert _create(temp_user).status_code == 200
    assert _used(temp_user, "platform_long_used") == 0


def test_legacy_personal_credentials_do_not_bypass_lifetime_quota(temp_user, platform):
    platform(platform_long_quota=1, books_per_day_max=1000)
    _install_connection(temp_user, {'writer': None})
    assert _create(temp_user).status_code == 200
    blocked = _create(temp_user)
    assert blocked.status_code == 429
    assert blocked.json() == {'error': 'PLATFORM_QUOTA_EXCEEDED'}
    assert _used(temp_user, 'platform_long_used') == 1


# ---- 计费层：短篇开写扣一次 ----

def _seed_active_session(user: str) -> str:
    """把一条卡已填满的会话直接摆好（这几条验的是 commit，不验聊到这一步的过程）。"""
    card = creation.merge_user_card(creation.default_card(), {
        "working_title": "最后一班渡船", "genre": "现实", "direction": "渡口要停航",
        "protagonist_pressure": "守着渡口的生计", "conflict_core": "留与走",
        "emotional_payoff": "放下", "plot_sketch": "他最后把船开走了",
    })
    with new_session() as db:
        session = ShortCreationSession(user_id=uuid.UUID(user), status="active", card=card)
        db.add(session)
        db.commit()
        return str(session.id)


def _commit(user: str, sid: str):
    return client.post(f"/api/v1/short/creation/sessions/{sid}/commit", json={},
                       headers=identity_headers(user))


def test_short_commit_is_refused_when_the_short_quota_is_gone(temp_user, platform):
    platform(platform_short_quota=1, books_per_day_max=1000)
    with new_session() as db:
        db.get(User, uuid.UUID(temp_user)).platform_short_used = 1
        db.commit()
    sid = _seed_active_session(temp_user)

    refused = _commit(temp_user, sid)

    assert refused.status_code == 429, refused.text
    assert refused.json() == {"error": "PLATFORM_QUOTA_EXCEEDED"}
    assert _used(temp_user, "platform_short_used") == 1
    # 拦在开写之前：会话还没被标 committed，改造一下卡还能再开一次
    with new_session() as db:
        assert db.get(ShortCreationSession, uuid.UUID(sid)).status == "active"


def test_short_commit_spends_one_and_keeps_it_even_if_the_plan_step_fails(temp_user, platform):
    """额度扣在「书建出来了」那一刻，出方案那步 502 不退还——这是有意接受的。

    书已经落库（重按会复用同一本，不是白扣），而扣减与建行在同一个事务里：建书失败整体
    回滚、额度跟着回来，写成之后才失败就是真花了。
    """
    platform(platform_short_quota=2, books_per_day_max=1000)
    sid = _seed_active_session(temp_user)

    response = _commit(temp_user, sid)

    assert response.status_code == 502, response.text
    assert "PLAN_FAILED" in response.json()["detail"]
    assert _used(temp_user, "platform_short_used") == 1
    with new_session() as db:
        session = db.get(ShortCreationSession, uuid.UUID(sid))
        assert session.book_id is not None      # 书真建出来了，重按复用它


def test_short_recommit_reuses_the_book_and_skips_the_quota_gate(temp_user, platform):
    """「出方案 502 了再按一次」不能被自己的额度挡住。

    书已经落库、额度也已经扣过；重按走的是 `session.book_id` 那条分支，既不建第二本、
    也不再扣一次。额度闸门必须放在那条分支**之后**——放前面的话，额度恰好用完的用户
    重按会看到「免费额度已用完」，而他手上那本书其实已经在书架上了。
    """
    platform(platform_short_quota=1, books_per_day_max=1000)
    sid = _seed_active_session(temp_user)
    first = _commit(temp_user, sid)
    assert first.status_code == 502, first.text

    with new_session() as db:
        first_book = db.get(ShortCreationSession, uuid.UUID(sid)).book_id

    second = _commit(temp_user, sid)            # 额度已满，但这次不建新书

    assert second.status_code == 502, second.text      # 仍是方案那步失败，不是 429
    assert "PLATFORM_QUOTA_EXCEEDED" not in second.text
    assert _used(temp_user, "platform_short_used") == 1
    with new_session() as db:
        assert db.get(ShortCreationSession, uuid.UUID(sid)).book_id == first_book