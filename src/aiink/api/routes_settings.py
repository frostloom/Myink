"""创作设置端点（阶段 4 设置页：文风档案展示 / 每 Agent 模型路由表）。

- GET /projects/{pid}/settings：读 project_settings（style_profile / skill_pack /
  model_routes / version）——设置页渲染与编辑前快照；
- PUT /projects/{pid}/settings：全量替换 model_routes（§6.10 每 Agent 模型路由，
  可配置角色 = planner/writer/validator_l2/extract，role→model_id 单主模型，降级链自动
  取默认兜底）+ version 递增（§7.6 乐观版本号）。

文风档案本身的写入走 style-profile 端点（§7.12 确认落库，含 validate_profile 与
fatigue 基线键保留）；本端点只管模型路由，避免职责混叠。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aiink.api.auth import require_owner
from aiink.api.schemas import ProjectSettingsOut
from aiink.db import tenant_session
from aiink.memory.repository import get_settings
from aiink.models import ProjectSettings
from aiink.providers import CONFIGURABLE_ROLES, MODEL_REGISTRY

router = APIRouter(prefix="/internal/v1", tags=["settings"])

# 可配置角色（§6.10）：planner/writer/validator_l2/extract；audit/revise/L1 固定默认链
# （常量定义在 providers/base，make_chain 与 PUT 校验共用同一闸）。


def _pid(project_id: str) -> uuid.UUID:
    """path 里的 project_id 转 uuid（require_owner 已校验格式合法，此处仅类型转换）。"""
    return uuid.UUID(project_id)


@router.get("/projects/{project_id}/settings",
            dependencies=[Depends(require_owner)], response_model=ProjectSettingsOut)
def get_project_settings(project_id: str) -> dict:
    """读创作设置（设置行缺失 → 空默认，页面不 500）。"""
    with tenant_session(project_id) as db:
        st = get_settings(db, _pid(project_id))
    if st is None:
        return {"style_profile": {}, "skill_pack": None, "model_routes": {}, "version": 0}
    return {
        "style_profile": st.style_profile or {},
        "skill_pack": st.skill_pack,
        "model_routes": st.model_routes or {},
        "version": st.version or 0,
    }


class SettingsBody(BaseModel):
    """模型路由表全量替换（缺省 → 清空，回落默认链）。"""

    model_routes: dict[str, str] | None = None


@router.put("/projects/{project_id}/settings",
            dependencies=[Depends(require_owner)], response_model=ProjectSettingsOut)
def put_project_settings(project_id: str, body: SettingsBody) -> dict:
    """全量替换 model_routes：role∈可配置集 + model∈注册表，违规 400；version++。

    全量替换语义（非合并）：前端改前先 GET 拿现值，改完整体回传——空 dict = 清空全部
    路由回落默认链，无歧义。落库前校验防 LLM/手填脏数据进表。
    """
    routes = body.model_routes or {}
    for role, model_id in routes.items():
        if role not in CONFIGURABLE_ROLES:
            raise HTTPException(status_code=400,
                                detail=f"不可配置的 role: {role}（仅 {sorted(CONFIGURABLE_ROLES)}）")
        if model_id not in MODEL_REGISTRY:
            raise HTTPException(status_code=400, detail=f"未知模型 id: {model_id}")
    with tenant_session(project_id) as db:
        st = get_settings(db, _pid(project_id))
        if st is None:
            st = ProjectSettings(project_id=_pid(project_id), model_routes=routes, version=1)
            db.add(st)
        else:
            st.model_routes = routes
            st.version = (st.version or 1) + 1
        db.commit()
    return {
        "style_profile": st.style_profile or {},
        "skill_pack": st.skill_pack,
        "model_routes": st.model_routes or {},
        "version": st.version or 0,
    }
