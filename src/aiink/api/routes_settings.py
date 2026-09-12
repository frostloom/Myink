"""Project writing settings and configurable model connections."""

from __future__ import annotations

import uuid
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, SecretStr

from aiink.api.auth import require_owner
from aiink.api.schemas import ConnectionTestOut, ModelListOut, ProjectSettingsOut
from aiink.db import tenant_session
from aiink.memory.repository import get_settings
from aiink.models import ProjectSettings
from aiink.providers import CONFIGURABLE_ROLES, MODEL_REGISTRY, probe
from aiink.providers.connections import (
    CUSTOM_ROUTE_PREFIX,
    pack_model_settings,
    public_connections,
    unpack_model_settings,
)
from aiink.providers.credentials import decrypt_api_key, encrypt_api_key

router = APIRouter(prefix="/internal/v1", tags=["settings"])


def _pid(project_id: str) -> uuid.UUID:
    return uuid.UUID(project_id)


class ModelConnectionBody(BaseModel):
    id: str
    name: str
    protocol: Literal["openai", "anthropic"]
    base_url: str
    model: str
    api_key: SecretStr | None = None


class SettingsBody(BaseModel):
    """Routes are fully replaced; omitted connections preserve the current list."""

    model_routes: dict[str, str] | None = None
    model_connections: list[ModelConnectionBody] | None = None


class ConnectionProbeBody(BaseModel):
    """探针请求：未保存的新连接直接传明文 api_key；已保存连接可只给 connection_id 复用密钥。"""

    protocol: Literal["openai", "anthropic"]
    base_url: str
    model: str | None = None
    api_key: SecretStr | None = None
    connection_id: str | None = None


def _clean_base_url(base_url: str) -> str:
    base_url = base_url.strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="请求地址必须是有效的 http/https 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(status_code=400, detail="请求地址不能包含账号、密码、查询参数或片段")
    return base_url


def _validate_connection(item: ModelConnectionBody) -> tuple[str, str, str, str]:
    try:
        cid = str(uuid.UUID(item.id))
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="模型连接 id 必须是 UUID") from exc
    name = item.name.strip()
    model = item.model.strip()
    if not name or len(name) > 80:
        raise HTTPException(status_code=400, detail="模型连接名称长度必须为 1–80")
    if not model or len(model) > 160:
        raise HTTPException(status_code=400, detail="模型 id 长度必须为 1–160")
    return cid, name, _clean_base_url(item.base_url), model


def _response(st: ProjectSettings | None) -> dict:
    if st is None:
        return {
            "style_profile": {}, "skill_pack": None, "model_routes": {},
            "model_connections": [], "version": 0,
        }
    routes, connections = unpack_model_settings(st.model_routes)
    return {
        "style_profile": st.style_profile or {},
        "skill_pack": st.skill_pack,
        "model_routes": routes,
        "model_connections": public_connections(connections),
        "version": st.version or 0,
    }


@router.get("/projects/{project_id}/settings",
            dependencies=[Depends(require_owner)], response_model=ProjectSettingsOut)
def get_project_settings(project_id: str) -> dict:
    with tenant_session(project_id) as db:
        return _response(get_settings(db, _pid(project_id)))


@router.put("/projects/{project_id}/settings",
            dependencies=[Depends(require_owner)], response_model=ProjectSettingsOut)
def put_project_settings(project_id: str, body: SettingsBody) -> dict:
    routes = body.model_routes or {}
    with tenant_session(project_id) as db:
        st = get_settings(db, _pid(project_id))
        _, existing_connections = unpack_model_settings(st.model_routes if st else None)
        connections = existing_connections
        if body.model_connections is not None:
            connections = {}
            seen: set[str] = set()
            for item in body.model_connections:
                cid, name, base_url, model = _validate_connection(item)
                if cid in seen:
                    raise HTTPException(status_code=400, detail=f"模型连接 id 重复: {cid}")
                seen.add(cid)
                raw_key = item.api_key.get_secret_value().strip() if item.api_key else ""
                encrypted = encrypt_api_key(raw_key) if raw_key else existing_connections.get(cid, {}).get("api_key_encrypted")
                if not encrypted:
                    raise HTTPException(status_code=400, detail=f"新模型连接“{name}”必须填写 API Key")
                connections[cid] = {
                    "name": name, "protocol": item.protocol, "base_url": base_url,
                    "model": model, "api_key_encrypted": encrypted,
                }

        for role, model_ref in routes.items():
            if role not in CONFIGURABLE_ROLES:
                raise HTTPException(status_code=400,
                                    detail=f"不可配置的 role: {role}（仅 {sorted(CONFIGURABLE_ROLES)}）")
            if model_ref in MODEL_REGISTRY:
                continue
            if model_ref.startswith(CUSTOM_ROUTE_PREFIX) and model_ref[len(CUSTOM_ROUTE_PREFIX):] in connections:
                continue
            raise HTTPException(status_code=400, detail=f"未知模型: {model_ref}")

        stored = pack_model_settings(routes, connections)
        if st is None:
            st = ProjectSettings(project_id=_pid(project_id), model_routes=stored, version=1)
            db.add(st)
        else:
            st.model_routes = stored
            st.version = (st.version or 1) + 1
        result = _response(st)
        db.commit()
        return result


def _probe_key(project_id: str, body: ConnectionProbeBody) -> str:
    """明文 api_key 优先；否则用 connection_id 取已存密文解密。都没有 → 400。"""
    raw = body.api_key.get_secret_value().strip() if body.api_key else ""
    if raw:
        return raw
    if body.connection_id:
        with tenant_session(project_id) as db:
            st = get_settings(db, _pid(project_id))
            _, connections = unpack_model_settings(st.model_routes if st else None)
        stored = connections.get(body.connection_id, {}).get("api_key_encrypted")
        if stored:
            key = decrypt_api_key(str(stored))
            if key:
                return key
    raise HTTPException(status_code=400, detail="需要填写 API Key（或选择已保存密钥的连接）")


@router.post("/projects/{project_id}/settings/models",
             dependencies=[Depends(require_owner)], response_model=ModelListOut)
def list_connection_models(project_id: str, body: ConnectionProbeBody) -> dict:
    base_url = _clean_base_url(body.base_url)
    api_key = _probe_key(project_id, body)
    models, error = probe.list_models(body.protocol, base_url, api_key)
    return {"ok": error is None, "models": models, "error": error}


@router.post("/projects/{project_id}/settings/test-connection",
             dependencies=[Depends(require_owner)], response_model=ConnectionTestOut)
def test_model_connection(project_id: str, body: ConnectionProbeBody) -> dict:
    model = (body.model or "").strip()
    if not model or len(model) > 160:
        raise HTTPException(status_code=400, detail="模型 id 长度必须为 1–160")
    base_url = _clean_base_url(body.base_url)
    api_key = _probe_key(project_id, body)
    ok, latency_ms, reply, error = probe.test_connection(body.protocol, base_url, api_key, model)
    return {"ok": ok, "latency_ms": latency_ms, "reply": reply, "error": error}
