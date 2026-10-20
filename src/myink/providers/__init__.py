"""Model providers and project-scoped routing with a default fallback chain."""

from __future__ import annotations

import uuid

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
from myink.providers.connections import price_table, unpack_model_settings
from myink.providers.credentials import decrypt_api_key
from myink.providers.deepseek import DeepSeekProvider
from myink.providers.openai_compatible import OpenAICompatibleProvider
from myink.providers.prices import DEEPSEEK_PRICES

# 测试可替换此单例以注入 stub。生产路径不再用它打 .env DeepSeek。
_BUILTIN_PROVIDER = DeepSeekProvider()
default_provider = _BUILTIN_PROVIDER
_UNCONFIGURED = MissingModelProvider()

def _no_model_chain(thinking: bool) -> FallbackChain:
    if default_provider is not _BUILTIN_PROVIDER:
        return FallbackChain(default_provider, ["stub"], thinking_enabled=thinking)
    return FallbackChain(_UNCONFIGURED, ["unconfigured"], thinking_enabled=thinking)


def platform_model_configured() -> bool:
    """Whether the pre-configuration deployment fallback has complete credentials."""
    from myink.config import settings

    return bool(settings.platform_model_api_key and settings.platform_model_base_url
                and settings.platform_model_name)


def platform_key_active(user_id, role: str) -> bool:
    """All enabled platform models use platform quotas; admins remain exempt.

    Legacy user credentials never exempt an account from centralized accounting.
    """
    if role == 'admin':
        return False
    from myink.platform_configuration import load_configuration
    config = load_configuration()
    return any(rec.get('enabled', True) for rec in config['connections'].values()) or (
        not config['version'] and platform_model_configured())



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


def _chain_from_override(override: dict, thinking: bool) -> FallbackChain:
    """Build a chain from an administrator-managed encrypted model connection.

    Invalid stored credentials fail closed instead of trying deployment credentials.
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


def _central_chain(role, selections, thinking):
    from myink.platform_configuration import load_configuration, resolve_connection
    config = load_configuration()
    if role not in CONFIGURABLE_ROLES:
        return _no_model_chain(thinking)
    from myink.platform_readiness import require_ready
    require_ready((role,), selections=selections, config=config)
    override = resolve_connection(role, selections, config)
    if override is not None:
        chain = _chain_from_override(override, thinking)
    elif config['version'] == 0:
        chain = _platform_chain(thinking) or _no_model_chain(thinking)
    else:
        chain = _no_model_chain(thinking)
    chain.system_addition = config['prompts'].get(role, '')
    return chain


def make_chain(role: str, project_id=None, db=None) -> FallbackChain:
    if default_provider is not _BUILTIN_PROVIDER:
        return FallbackChain(default_provider, ['stub'])
    from myink.environment import packed_models, thinking_enabled_for_user
    from myink.models import Project
    from myink.db import tenant_session
    thinking = _thinking_enabled(project_id, db) if project_id else thinking_enabled_for_user(None)
    owner = None
    if project_id:
        if db is None:
            with tenant_session(str(project_id)) as session:
                project = session.get(Project, uuid.UUID(str(project_id)))
                owner = project.user_id if project else None
        else:
            project = db.get(Project, uuid.UUID(str(project_id)))
            owner = project.user_id if project else None
    routes, _ = unpack_model_settings(packed_models(owner)) if owner else ({}, {})
    return _central_chain(role, routes, thinking)


def make_user_chain(role: str, user_id: str | uuid.UUID) -> FallbackChain:
    from myink.environment import packed_models, thinking_enabled_for_user
    thinking = thinking_enabled_for_user(user_id)
    if default_provider is not _BUILTIN_PROVIDER:
        return FallbackChain(default_provider, ['stub'], thinking_enabled=thinking)
    routes, _ = unpack_model_settings(packed_models(user_id))
    return _central_chain(role, routes, thinking)


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
    return thinking_enabled_for_user(owner)


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
    "platform_key_active",
    "platform_model_configured",
]
