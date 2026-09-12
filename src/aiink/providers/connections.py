"""Storage helpers for project-scoped model connections.

Connections share the existing JSON settings column under a reserved key, so older
databases need no schema migration. Public API responses always remove encrypted keys.
"""

from __future__ import annotations

from typing import Any

from aiink.providers.base import CONFIGURABLE_ROLES

CONNECTIONS_KEY = "__model_connections__"
CUSTOM_ROUTE_PREFIX = "custom:"


def unpack_model_settings(value: dict | None) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    raw = value if isinstance(value, dict) else {}
    routes = {
        role: model_id for role, model_id in raw.items()
        if role in CONFIGURABLE_ROLES and isinstance(model_id, str)
    }
    stored = raw.get(CONNECTIONS_KEY, {})
    connections = {
        str(cid): item for cid, item in stored.items()
        if isinstance(cid, str) and isinstance(item, dict)
    } if isinstance(stored, dict) else {}
    return routes, connections


def pack_model_settings(routes: dict[str, str], connections: dict[str, dict[str, Any]]) -> dict:
    packed: dict[str, Any] = dict(routes)
    if connections:
        packed[CONNECTIONS_KEY] = connections
    return packed


def public_connections(connections: dict[str, dict[str, Any]]) -> list[dict]:
    return [
        {
            "id": cid,
            "name": str(item.get("name", "")),
            "protocol": str(item.get("protocol", "")),
            "base_url": str(item.get("base_url", "")),
            "model": str(item.get("model", "")),
            "has_api_key": bool(item.get("api_key_encrypted")),
        }
        for cid, item in connections.items()
    ]
