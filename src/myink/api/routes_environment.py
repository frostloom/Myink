"""账号级环境配置：模型连接/路由 + 扫榜（不绑具体作品）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from myink.api.auth import require_user
from myink.api.routes_settings import (
    ConnectionProbeBody,
    ModelConnectionBody,
    _assert_host_allowed,
    _clean_base_url,
    audited_admin_probe,
)
from myink.api.schemas import ConnectionTestOut, EnvironmentOut, ModelListOut
from myink.environment import load_environment, load_raw, save_raw
from myink.task_budget import TaskBudgetLimits
from myink.platform_configuration import USER_ROLES
from myink.providers import probe
from myink.providers.connections import (
    pack_model_settings,
    unpack_model_settings,
)

router = APIRouter(prefix="/api/v1", tags=["environment"])


class RankingsBody(BaseModel):
    enabled: bool | None = None
    timeout: int | None = None
    limit: int | None = None


class EnvironmentBody(BaseModel):
    """省略字段保留覆盖，嵌套字段局部更新；恢复默认只移除指定覆盖。"""

    model_routes: dict[str, str] | None = None
    model_connections: list[ModelConnectionBody] | None = None
    rankings: RankingsBody | None = None
    thinking_enabled: bool | None = None
    task_budget: TaskBudgetLimits | None = None
    reset_preferences: list[str] = Field(default_factory=list)

    @field_validator('reset_preferences')
    @classmethod
    def validate_reset_paths(cls, paths):
        supported = {'thinking_enabled', *(f'model_routes.{role}' for role in USER_ROLES)}
        supported.update(f'task_budget.{key}' for key in TaskBudgetLimits.model_fields)
        supported.update(f'rankings.{key}' for key in RankingsBody.model_fields)
        if any(path not in supported for path in paths):
            raise ValueError('Unknown preference reset path')
        return paths


def _validate_rankings(body: RankingsBody, existing: dict) -> dict:
    merged = dict(existing)
    if body.enabled is not None:
        merged["enabled"] = body.enabled
    if body.timeout is not None:
        if not 1 <= body.timeout <= 60:
            raise HTTPException(status_code=400, detail="扫榜超时须为 1–60 秒")
        merged["timeout"] = body.timeout
    if body.limit is not None:
        if not 1 <= body.limit <= 50:
            raise HTTPException(status_code=400, detail="扫榜条数须为 1–50")
        merged["limit"] = body.limit
    return merged


@router.get("/environment", response_model=EnvironmentOut)
def get_environment(user_id: str = Depends(require_user)) -> dict:
    return load_environment(user_id)


@router.put("/environment", response_model=EnvironmentOut)
def put_environment(body: EnvironmentBody, user_id: str = Depends(require_user)) -> dict:
    from myink.platform_configuration import clean_user_routes, validate_user_routes
    if 'model_connections' in body.model_fields_set:
        raise HTTPException(403, 'Platform connections are managed by administrators')
    supplied = {'thinking_enabled'} if 'thinking_enabled' in body.model_fields_set else set()
    for group in ('rankings', 'task_budget', 'model_routes'):
        value = getattr(body, group)
        keys = value.keys() if isinstance(value, dict) else value.model_fields_set if value is not None else ()
        supplied.update(f'{group}.{key}' for key in keys)
    if supplied.intersection(body.reset_preferences):
        raise HTTPException(400, 'Cannot reset and set the same preference')
    raw = load_raw(user_id)
    existing_routes, _ = unpack_model_settings(raw.get('models') or {})
    routes = clean_user_routes(existing_routes)
    if body.model_routes is not None:
        if not body.model_routes:
            routes = {}
        for role, ref in body.model_routes.items():
            if not ref and role in USER_ROLES:
                routes.pop(role, None)
            else:
                routes[role] = ref
    validate_user_routes(routes)
    stored = dict(raw)
    for path in body.reset_preferences:
        group, _, key = path.partition('.')
        if group == 'model_routes':
            routes.pop(key, None)
        elif not key:
            stored.pop(group, None)
        elif isinstance(stored.get(group), dict):
            values = dict(stored[group])
            values.pop(key, None)
            if values:
                stored[group] = values
            else:
                stored.pop(group)
    stored['models'] = pack_model_settings(routes, {})
    if body.rankings is not None:
        existing = stored.get("rankings") if isinstance(stored.get("rankings"), dict) else {}
        stored["rankings"] = _validate_rankings(body.rankings, existing)
    if body.task_budget is not None:
        existing = stored.get('task_budget') if isinstance(stored.get('task_budget'), dict) else {}
        stored['task_budget'] = {**existing, **body.task_budget.model_dump(mode='json', exclude_unset=True)}
    if body.thinking_enabled is not None:
        stored["thinking_enabled"] = bool(body.thinking_enabled)
    try:
        return save_raw(user_id, stored)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _probe_key(user_id: str, body: ConnectionProbeBody) -> str:
    from myink.api.routes_platform import probe_key
    return probe_key(body)



@router.post("/environment/models", response_model=ModelListOut, dependencies=[Depends(audited_admin_probe)])
def list_environment_models(
    body: ConnectionProbeBody, user_id: str = Depends(require_user),
) -> dict:
    base_url = _clean_base_url(body.base_url)
    _assert_host_allowed(base_url)
    api_key = _probe_key(user_id, body)
    models, error = probe.list_models(body.protocol, base_url, api_key)
    return {"ok": error is None, "models": models, "error": error}


@router.post("/environment/test-connection", response_model=ConnectionTestOut, dependencies=[Depends(audited_admin_probe)])
def test_environment_connection(
    body: ConnectionProbeBody, user_id: str = Depends(require_user),
) -> dict:
    model = (body.model or "").strip()
    if not model or len(model) > 160:
        raise HTTPException(status_code=400, detail="模型 id 长度必须为 1–160")
    base_url = _clean_base_url(body.base_url)
    _assert_host_allowed(base_url)
    api_key = _probe_key(user_id, body)
    ok, latency_ms, reply, error = probe.test_connection(body.protocol, base_url, api_key, model)
    return {"ok": ok, "latency_ms": latency_ms, "reply": reply, "error": error}
