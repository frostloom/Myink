"""账号级环境配置：模型连接/路由 + 扫榜（存在 users.environment JSON）。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from myink.config import settings
from myink.db import new_session
from myink.models import User
from myink.providers.connections import unpack_model_settings
from myink.user_defaults import effective_preferences, overridden_fields, platform_defaults


def default_rankings() -> dict[str, Any]:
    return platform_defaults()["rankings"]


def merge_rankings(raw: Any) -> dict[str, Any]:
    return effective_preferences({"rankings": raw})["rankings"]


def preferences_for_user(user_id=None) -> dict[str, Any]:
    return effective_preferences(load_raw(user_id) if user_id is not None else {})


def load_raw(user_id: str | uuid.UUID) -> dict[str, Any]:
    with new_session() as db:
        user = db.get(User, uuid.UUID(str(user_id)))
        raw = user.environment if user is not None else None
        return dict(raw) if isinstance(raw, dict) else {}


def packed_models(user_id: str | uuid.UUID | None) -> dict[str, Any] | None:
    if user_id is None:
        return None
    raw = load_raw(user_id)
    models = raw.get("models")
    return models if isinstance(models, dict) else None


def load_environment(user_id: str | uuid.UUID) -> dict[str, Any]:
    raw = load_raw(user_id)
    routes, _ = unpack_model_settings(raw.get("models") if isinstance(raw.get("models"), dict) else {})
    from myink.platform_configuration import catalog, clean_user_routes
    routes = clean_user_routes(routes)
    preferences = effective_preferences(raw)
    return {
        "model_routes": routes,
        "model_connections": [],
        "available_models": catalog()["models"],
        **preferences,
        "overridden_fields": sorted(overridden_fields(raw) + [f"model_routes.{role}" for role in routes]),
    }


def thinking_enabled_for_user(user_id: str | uuid.UUID | None) -> bool:
    return preferences_for_user(user_id)["thinking_enabled"]


def save_raw(user_id: str | uuid.UUID, env: dict[str, Any]) -> dict[str, Any]:
    uid = uuid.UUID(str(user_id))
    with new_session() as db:
        user = db.get(User, uid)
        if user is None:
            raise LookupError(f"用户不存在: {uid}")
        user.environment = env
        db.commit()
    return load_environment(uid)


@dataclass
class RankingsSettingsView:
    """供 RankingsService 消费的设置视图（字段名对齐 config.settings）。"""

    rankings_enabled: bool
    rankings_timeout: int
    rankings_limit: int
    rankings_cache_ttl: int


def rankings_view_for_user(user_id: str | uuid.UUID | None) -> RankingsSettingsView:
    """Runtime resolves current platform defaults and account overrides."""
    merged = preferences_for_user(user_id)["rankings"]
    return RankingsSettingsView(
        rankings_enabled=merged["enabled"],
        rankings_timeout=merged["timeout"],
        rankings_limit=merged["limit"],
        rankings_cache_ttl=int(settings.rankings_cache_ttl),
    )
