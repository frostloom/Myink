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


def has_own_model_connections(packed) -> bool:
    """这个账号有没有自备模型连接（不看路由，看连接本身）。

    凭据层与计费层共用这一条判据：**只有零自备连接才走平台密钥，也才受免费额度约束**。
    两边判据一旦不一致就会漏钱——比如「有连接但某个角色没配路由」这种半配置状态，
    如果取凭据时吃了平台密钥、记账时却认为他有自己的 key，就是无限量白用。
    """
    _routes, connections = unpack_model_settings(packed or {})
    return bool(connections)


def platform_model_configured() -> bool:
    """部署方到底配没配内置密钥（三项全填才算，任一为空即回落现状）。

    凭据层与计费层共用这一条：没配 key 时 `_platform_chain` 返回 None、`platform_key_active`
    返回 False。两边判据必须一致——只顾一边就会出现「没配 key 却按免费额度把用户拦住」，
    那时用户手里既没有平台密钥也没有自备密钥，纯粹是被一个不存在的额度卡死。
    """
    from myink.config import settings

    return bool(settings.platform_model_api_key and settings.platform_model_base_url
                and settings.platform_model_name)


def platform_key_active(user_id, role: str) -> bool:
    """这个账号此刻是不是在吃部署方内置的密钥。

    三个条件缺一不可：部署方配了 key、账号一个自备连接都没有、`role != admin`（否则自己没法测）。
    与 `_fallback_chain` 取凭据时的判据是同一套，改一处必须改另一处。
    """
    from myink.environment import packed_models

    if role == "admin":
        return False
    if not platform_model_configured():
        return False
    return not has_own_model_connections(packed_models(user_id))


def _provider_for(protocol, api_key: str, base_url: str) -> ModelProvider | None:
    """协议名 → provider 实例。认不出返回 None（调用方各自决定怎么回落）。"""
    if protocol == "openai":
        return OpenAICompatibleProvider(api_key=api_key, base_url=base_url)
    if protocol == "anthropic":
        return AnthropicProvider(api_key=api_key, base_url=base_url)
    return None


def _platform_chain(thinking: bool) -> FallbackChain | None:
    """部署方内置密钥的模型链；没配全就返回 None（回落现状）。

    **不走 `decrypt_api_key`**：平台 key 是进程配置里的明文，不是库里的密文，
    走解密那条路纯属绕远，还会让人误以为它跟用户的连接存在同一个地方。
    """
    from myink.config import settings

    if not platform_model_configured():
        return None
    provider = _provider_for(settings.platform_model_protocol, settings.platform_model_api_key,
                             settings.platform_model_base_url)
    if provider is None:
        return None
    return FallbackChain(provider, [settings.platform_model_name], providers=[provider],
                         thinking_enabled=thinking)


def _fallback_chain(thinking: bool, packed) -> FallbackChain:
    """「这个角色压根没找到任何自备路由」时的出口。

    有自备连接 → 原样报 unconfigured（与今天逐字节相同：半配置状态不该悄悄吃平台的钱，
    也不该掩盖用户自己的配置错误）。零连接 → 试平台密钥，没配再回落 unconfigured。
    """
    if has_own_model_connections(packed):
        return _no_model_chain(thinking)
    chain = _platform_chain(thinking)
    return chain if chain is not None else _no_model_chain(thinking)


def _chain_from_override(override: dict, thinking: bool) -> FallbackChain:
    """override（一条路由配置）→ 可用的模型链。make_chain 与 make_user_chain 共用。

    原样搬自 make_chain 内联的那段：api_key 解密 → 协议/model 取用 → prices 表。

    三条失败路径**刻意不回落平台密钥**：用户配了连接但解不开 / 协议不认 / 模型为空，
    那是他自己的配置问题，掩盖它等于既掩盖错误又替他付钱。
    """
    api_key = decrypt_api_key(str(override.get("api_key_encrypted", "")))
    if not api_key:
        return _no_model_chain(thinking)
    provider = _provider_for(override.get("protocol"), api_key, str(override.get("base_url", "")))
    if provider is None:
        return _no_model_chain(thinking)
    model = str(override.get("model", "")).strip()
    if not model:
        return _no_model_chain(thinking)
    return FallbackChain(
        provider, [model], providers=[provider], thinking_enabled=thinking,
        prices=price_table(override),
    )


def make_chain(role: str, project_id=None, db=None) -> FallbackChain:
    """自备连接优先；一个都没有时回落部署方内置密钥（没配就是原来的 unconfigured）。"""
    thinking = _thinking_enabled(project_id, db) if project_id is not None else False
    # 测试替换了 default_provider：整条链走 stub，避免本机账号环境打到真实模型。
    if default_provider is not _BUILTIN_PROVIDER:
        return FallbackChain(default_provider, ["stub"], thinking_enabled=thinking)
    override, packed = (_project_primary(role, project_id, db) if project_id is not None
                        else (None, None))
    if not isinstance(override, dict):
        # 角色本就不可配时 _project_primary 也返回 None，不补这一道就分不清
        # 「这个角色不该调模型」与「该调但没配路由」，后者才轮到平台密钥。
        if role not in CONFIGURABLE_ROLES and role not in _ROLE_INHERIT:
            return _no_model_chain(thinking)
        return _fallback_chain(thinking, packed)
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
    找不到就按 _USER_ROLE_FALLBACK 退一步，再没有就轮到平台密钥（没配仍是 unconfigured）。
    """
    from myink.environment import packed_models, thinking_enabled_for_user

    thinking = thinking_enabled_for_user(user_id)
    if default_provider is not _BUILTIN_PROVIDER:      # 测试桩：与 make_chain 同一条短路
        return FallbackChain(default_provider, ["stub"], thinking_enabled=thinking)
    if role not in CONFIGURABLE_ROLES and role not in _USER_ROLE_FALLBACK:
        return _no_model_chain(thinking)
    packed = packed_models(user_id)
    override = _lookup_user_override(role, packed or {})
    if override is None:
        return _fallback_chain(thinking, packed)
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


def _project_primary(role: str, project_id, db) -> tuple[dict[str, Any] | None, dict | None]:
    """作品主路由，外加该作品所有者的 packed models。

    返回两个值是因为「这个角色没配路由」与「这个账号一个连接都没有」是两件事：
    前者仍然不该吃平台密钥，后者才轮到。角色不可配时 override 为 None、packed 也是 None。
    """
    if role not in CONFIGURABLE_ROLES and role not in _ROLE_INHERIT:
        return None, None
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
    packed = packed_models(owner)
    if owner is not None:
        hit = _lookup_override(role, packed)
        if hit is not None:
            return hit, packed
    if st is None:
        return None, packed
    return _lookup_override(role, st.model_routes), packed


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
    "has_own_model_connections",
    "lookup_prices",
    "make_chain",
    "make_user_chain",
    "platform_key_active",
    "platform_model_configured",
]
