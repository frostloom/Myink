"""Project writing settings and configurable model connections."""

from __future__ import annotations

import ipaddress
import socket
import uuid
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, SecretStr

from myink.api.auth import require_owner, require_admin, _AuthenticatedUser
from myink.api.schemas import ConnectionTestOut, ModelListOut, ProjectSettingsOut
from myink.db import tenant_session
from myink.memory.repository import get_settings
from myink.models import ProjectSettings
from myink.providers import probe
from myink.genre_catalog import public_pack
from myink.providers.credentials import encrypt_api_key

router = APIRouter(prefix="/api/v1", tags=["settings"])


def _pid(project_id: str) -> uuid.UUID:
    return uuid.UUID(project_id)


def audited_admin_probe(request: Request, response: Response,
                        actor: _AuthenticatedUser = Depends(require_admin)):
    from myink.api.routes_admin import _audit_or_fail
    response.headers['Cache-Control'] = 'no-store'
    _audit_or_fail(actor, request, 'admin.configuration.legacy_probe')


class ModelConnectionBody(BaseModel):
    id: str
    name: str
    protocol: Literal["openai", "anthropic"]
    base_url: str
    model: str
    api_key: SecretStr | None = None
    input_price: float | None = None
    output_price: float | None = None


class SettingsBody(BaseModel):
    """两个字段都是「省略 = 保留现值，显式传（含 {} / []）= 整体替换」。

    原先 model_routes 省略会被当成空字典覆盖，只改连接的客户端会静默丢掉全部分角色配置。
    """

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


def _unsafe_address(raw: str) -> bool:
    """判据是「不是全球可路由」，而不是列举内网段。

    列举法会漏掉 100.64.0.0/10：它既不属 private 也不属 reserved，却正是 CGNAT 与
    阿里云元数据 100.100.100.200 所在的段，只有 is_global 能识别。多播是唯一反例
    （is_global 为 True），所以单独补一条。
    """
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return True  # 解析不出（含 zone id 等）→ 保守拒绝
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_multicast or not ip.is_global


def _assert_host_allowed(base_url: str) -> None:
    """出站地址守卫：只放行全球可路由的地址。

    原先私有段与回环**刻意放行**，为的是本地推理服务（如 127.0.0.1:11434 Ollama）；
    现已确认本部署不用本地模型，改为一律拒绝——非全球可路由的地址里含云元数据
    （169.254.169.254、阿里云 100.100.100.200）与内网服务，正是 SSRF 的目标。

    探针与保存共用本守卫：只在探针拦而保存不拦等于没拦——地址落库后由 worker 在生成时
    真打出去，探针那道检查形同虚设。

    解析后才判（域名解析到内网同样拒绝）；解析失败不在此处改写成另一种错误，交给探针
    自己报「连不上」，让失败原因来自真实请求。
    """
    host = urlsplit(base_url).hostname
    if not host:
        raise HTTPException(status_code=400, detail="请求地址缺少主机名")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return
    if any(_unsafe_address(info[4][0]) for info in infos):
        raise HTTPException(status_code=400, detail="请求地址指向内网/保留地址，已拒绝")


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


def _price_fields(item: ModelConnectionBody) -> dict:
    if item.input_price is None and item.output_price is None:
        return {}
    if item.input_price is None or item.output_price is None:
        raise HTTPException(status_code=400, detail="输入价与输出价须同时填写")
    for label, value in (("输入价", item.input_price), ("输出价", item.output_price)):
        if value < 0 or value > 10_000:
            raise HTTPException(status_code=400, detail=f"{label}须为 0–10000（¥/百万 token）")
    return {"input_price": float(item.input_price), "output_price": float(item.output_price)}


def connection_record(item: ModelConnectionBody, existing_connections: dict) -> tuple[str, dict]:
    cid, name, base_url, model = _validate_connection(item)
    _assert_host_allowed(base_url)
    raw_key = item.api_key.get_secret_value().strip() if item.api_key else ""
    encrypted = encrypt_api_key(raw_key) if raw_key else existing_connections.get(cid, {}).get("api_key_encrypted")
    if not encrypted:
        raise HTTPException(status_code=400, detail=f"新模型连接“{name}”必须填写 API Key")
    return cid, {
        "name": name, "protocol": item.protocol, "base_url": base_url,
        "model": model, "api_key_encrypted": encrypted, **_price_fields(item),
    }


def _response(st: ProjectSettings | None) -> dict:
    if st is None:
        return {
            "style_profile": {}, "skill_pack": None, "genre_pack": {},
            "model_routes": {}, "model_connections": [], "version": 0,
        }
    return {
        "style_profile": {
            key: value for key, value in (st.style_profile or {}).items()
            if key not in ("fatigue_words", "fatigue_patterns")
        },
        "skill_pack": st.skill_pack,
        "genre_pack": public_pack(st.genre_pack),
        "model_routes": {},
        "model_connections": [],
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
    if body.model_fields_set & {'model_connections', 'model_routes'}:
        raise HTTPException(403, 'Project model configuration is managed by administrators')
    return get_project_settings(project_id)



def _probe_key(project_id: str, body: ConnectionProbeBody) -> str:
    from myink.api.routes_platform import probe_key
    return probe_key(body)



@router.post("/projects/{project_id}/settings/models",
             dependencies=[Depends(require_owner), Depends(audited_admin_probe)], response_model=ModelListOut)
def list_connection_models(project_id: str, body: ConnectionProbeBody) -> dict:
    base_url = _clean_base_url(body.base_url)
    _assert_host_allowed(base_url)
    api_key = _probe_key(project_id, body)
    models, error = probe.list_models(body.protocol, base_url, api_key)
    return {"ok": error is None, "models": models, "error": error}


@router.post("/projects/{project_id}/settings/test-connection",
             dependencies=[Depends(require_owner), Depends(audited_admin_probe)], response_model=ConnectionTestOut)
def test_model_connection(project_id: str, body: ConnectionProbeBody) -> dict:
    model = (body.model or "").strip()
    if not model or len(model) > 160:
        raise HTTPException(status_code=400, detail="模型 id 长度必须为 1–160")
    base_url = _clean_base_url(body.base_url)
    _assert_host_allowed(base_url)
    api_key = _probe_key(project_id, body)
    ok, latency_ms, reply, error = probe.test_connection(body.protocol, base_url, api_key, model)
    return {"ok": ok, "latency_ms": latency_ms, "reply": reply, "error": error}
