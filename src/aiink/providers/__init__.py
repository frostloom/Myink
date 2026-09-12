"""Model providers and project-scoped routing with a default fallback chain."""

from __future__ import annotations

import uuid
from typing import Any

from aiink.providers.anthropic import AnthropicProvider
from aiink.providers.base import (
    CONFIGURABLE_ROLES,
    DEFAULT_ROUTES,
    DEEPSEEK_PRICES,
    MODEL_REGISTRY,
    FallbackChain,
    ModelProvider,
    ModelResponse,
    ModelSpec,
)
from aiink.providers.connections import CUSTOM_ROUTE_PREFIX, unpack_model_settings
from aiink.providers.credentials import decrypt_api_key
from aiink.providers.deepseek import DeepSeekProvider
from aiink.providers.openai_compatible import OpenAICompatibleProvider

default_provider = DeepSeekProvider()


def make_chain(role: str, project_id=None, db=None) -> FallbackChain:
    """Build a project route and retain the built-in DeepSeek chain as fallback."""
    route = DEFAULT_ROUTES.get(role, DEFAULT_ROUTES["extract"])
    override = _project_primary(role, project_id, db) if project_id is not None else None
    if override is None:
        return FallbackChain(default_provider, route)
    if isinstance(override, str):
        chain = [override] + [model for model in route if model != override]
        return FallbackChain(default_provider, chain)

    api_key = decrypt_api_key(str(override.get("api_key_encrypted", "")))
    if not api_key:
        return FallbackChain(default_provider, route)
    protocol = override.get("protocol")
    if protocol == "openai":
        provider: ModelProvider = OpenAICompatibleProvider(
            api_key=api_key, base_url=str(override.get("base_url", "")))
    elif protocol == "anthropic":
        provider = AnthropicProvider(api_key=api_key, base_url=str(override.get("base_url", "")))
    else:
        return FallbackChain(default_provider, route)
    model = str(override.get("model", "")).strip()
    if not model:
        return FallbackChain(default_provider, route)
    return FallbackChain(
        provider,
        [model, *route],
        providers=[provider, *([default_provider] * len(route))],
    )


def _project_primary(role: str, project_id, db) -> str | dict[str, Any] | None:
    if role not in CONFIGURABLE_ROLES:
        return None
    from aiink.db import tenant_session
    from aiink.memory.repository import get_settings

    pid = uuid.UUID(str(project_id))
    if db is None:
        with tenant_session(str(pid)) as session:
            st = get_settings(session, pid)
    else:
        st = get_settings(db, pid)
    if st is None:
        return None
    routes, connections = unpack_model_settings(st.model_routes)
    route = routes.get(role)
    if route in MODEL_REGISTRY:
        return route
    if route and route.startswith(CUSTOM_ROUTE_PREFIX):
        return connections.get(route[len(CUSTOM_ROUTE_PREFIX):])
    return None


__all__ = [
    "AnthropicProvider",
    "CONFIGURABLE_ROLES",
    "DEFAULT_ROUTES",
    "MODEL_REGISTRY",
    "DEEPSEEK_PRICES",
    "FallbackChain",
    "ModelProvider",
    "ModelResponse",
    "ModelSpec",
    "DeepSeekProvider",
    "OpenAICompatibleProvider",
    "default_provider",
    "make_chain",
]
