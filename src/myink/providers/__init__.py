"""Model providers and project-scoped routing with a default fallback chain."""

from __future__ import annotations

import uuid
from typing import Any

from myink.providers.anthropic import AnthropicProvider
from myink.providers.base import (
    CONFIGURABLE_ROLES,
    DEFAULT_ROUTES,
    MODEL_REGISTRY,
    FallbackChain,
    MissingModelProvider,
    ModelProvider,
    ModelResponse,
    ModelSpec,
    effective_cost,
    estimate_cost,
    lookup_prices,
)
from myink.providers.connections import CUSTOM_ROUTE_PREFIX, price_table, unpack_model_settings
from myink.providers.credentials import decrypt_api_key
from myink.providers.deepseek import DeepSeekProvider
from myink.providers.openai_compatible import OpenAICompatibleProvider
from myink.providers.prices import DEEPSEEK_PRICES

# 测试可替换此单例以注入 stub。生产路径不再用它打 .env DeepSeek。
_BUILTIN_PROVIDER = DeepSeekProvider()
default_provider = _BUILTIN_PROVIDER
_UNCONFIGURED = MissingModelProvider()

# 审核/摘要未单独配置时，沿用用户已填的可配置角色。
_ROLE_INHERIT: dict[str, tuple[str, ...]] = {
    "audit": ("validator_l2", "writer", "planner", "extract"),
    "summarize": ("extract", "writer", "planner"),
}

# 账号级角色继承：建书对话与文风提取发生在还没有书的时刻，用户往往只配过少数几个角色。
# 与项目级 _ROLE_INHERIT 分开维护——那张表服务于生成管道，这张服务于建书前。
_USER_ROLE_FALLBACK: dict[str, tuple[str, ...]] = {
    "planner": ("writer", "extract"),   # 建书对话是用户第一次接触产品，planner 没配也得能用
    "extract": ("planner", "writer"),
}


def _no_model_chain(thinking: bool) -> FallbackChain:
    if default_provider is not _BUILTIN_PROVIDER:
        return FallbackChain(default_provider, ["stub"], thinking_enabled=thinking)
    return FallbackChain(_UNCONFIGURED, ["unconfigured"], thinking_enabled=thinking)


def _chain_from_override(override: dict, thinking: bool) -> FallbackChain:
    """override（一条路由配置）→ 可用的模型链。make_chain 与 make_user_chain 共用。

    原样搬自 make_chain 内联的那段：api_key 解密 → 协议/model 取用 → prices 表。
    """
    api_key = decrypt_api_key(str(override.get("api_key_encrypted", "")))
    if not api_key:
        return _no_model_chain(thinking)
    protocol = override.get("protocol")
    if protocol == "openai":
        provider: ModelProvider = OpenAICompatibleProvider(
            api_key=api_key, base_url=str(override.get("base_url", "")))
    elif protocol == "anthropic":
        provider = AnthropicProvider(api_key=api_key, base_url=str(override.get("base_url", "")))
    else:
        return _no_model_chain(thinking)
    model = str(override.get("model", "")).strip()
    if not model:
        return _no_model_chain(thinking)
    return FallbackChain(
        provider, [model], providers=[provider], thinking_enabled=thinking,
        prices=price_table(override),
    )


def make_chain(role: str, project_id=None, db=None) -> FallbackChain:
    """只走用户环境/作品里的自备连接；未配置则明确报错，不再回落内置 DeepSeek。"""
    thinking = _thinking_enabled(project_id, db) if project_id is not None else False
    # 测试替换了 default_provider：整条链走 stub，避免本机账号环境打到真实模型。
    if default_provider is not _BUILTIN_PROVIDER:
        return FallbackChain(default_provider, ["stub"], thinking_enabled=thinking)
    override = _project_primary(role, project_id, db) if project_id is not None else None
    if not isinstance(override, dict):
        return _no_model_chain(thinking)
    return _chain_from_override(override, thinking)


def _lookup_user_override(role: str, packed: dict) -> dict[str, Any] | None:
    hit = _from_packed(role, packed)
    if hit is not None:
        return hit
    for inherited in _USER_ROLE_FALLBACK.get(role, ()):
        hit = _from_packed(inherited, packed)
        if hit is not None:
            return hit
    return None


def make_user_chain(role: str, user_id: str | uuid.UUID) -> FallbackChain:
    """账号级模型链：建书对话 / 文风提取这类「还没有书」的调用走它。

    与 make_chain 的差别只有起点：路由从 users.environment 里找（项目级覆盖此刻不存在），
    找不到就按 _USER_ROLE_FALLBACK 退一步，再没有就是 unconfigured。
    """
    from myink.environment import packed_models, thinking_enabled_for_user

    thinking = thinking_enabled_for_user(user_id)
    if default_provider is not _BUILTIN_PROVIDER:      # 测试桩：与 make_chain 同一条短路
        return FallbackChain(default_provider, ["stub"], thinking_enabled=thinking)
    if role not in CONFIGURABLE_ROLES and role not in _USER_ROLE_FALLBACK:
        return _no_model_chain(thinking)
    override = _lookup_user_override(role, packed_models(user_id) or {})
    if override is None:
        return _no_model_chain(thinking)
    return _chain_from_override(override, thinking)


def _from_packed(role: str, packed) -> dict[str, Any] | None:
    routes, connections = unpack_model_settings(packed)
    route = routes.get(role)
    if route and route.startswith(CUSTOM_ROUTE_PREFIX):
        return connections.get(route[len(CUSTOM_ROUTE_PREFIX):])
    return None


def _lookup_override(role: str, packed) -> dict[str, Any] | None:
    hit = _from_packed(role, packed)
    if hit is not None:
        return hit
    for alias in _ROLE_INHERIT.get(role, ()):
        hit = _from_packed(alias, packed)
        if hit is not None:
            return hit
    return None


def _thinking_enabled(project_id, db) -> bool:
    from myink.environment import thinking_enabled_for_user
    from myink.models import Project

    pid = uuid.UUID(str(project_id))
    if db is None:
        from myink.db import tenant_session
        with tenant_session(str(pid)) as session:
            proj = session.get(Project, pid)
            owner = proj.user_id if proj is not None else None
    else:
        proj = db.get(Project, pid)
        owner = proj.user_id if proj is not None else None
    return thinking_enabled_for_user(owner) if owner is not None else False


def _project_primary(role: str, project_id, db) -> dict[str, Any] | None:
    if role not in CONFIGURABLE_ROLES and role not in _ROLE_INHERIT:
        return None
    from myink.db import tenant_session
    from myink.environment import packed_models
    from myink.memory.repository import get_settings
    from myink.models import Project

    pid = uuid.UUID(str(project_id))
    if db is None:
        with tenant_session(str(pid)) as session:
            proj = session.get(Project, pid)
            owner = proj.user_id if proj is not None else None
            st = get_settings(session, pid)
    else:
        proj = db.get(Project, pid)
        owner = proj.user_id if proj is not None else None
        st = get_settings(db, pid)
    if owner is not None:
        hit = _lookup_override(role, packed_models(owner))
        if hit is not None:
            return hit
    if st is None:
        return None
    return _lookup_override(role, st.model_routes)


__all__ = [
    "AnthropicProvider",
    "CONFIGURABLE_ROLES",
    "DEFAULT_ROUTES",
    "MODEL_REGISTRY",
    "DEEPSEEK_PRICES",
    "FallbackChain",
    "MissingModelProvider",
    "ModelProvider",
    "ModelResponse",
    "ModelSpec",
    "DeepSeekProvider",
    "OpenAICompatibleProvider",
    "default_provider",
    "effective_cost",
    "estimate_cost",
    "lookup_prices",
    "make_chain",
    "make_user_chain",
]
