"""阶段 4 二次切片核心新功能回归（评审 M1 补齐）：每 Agent 模型路由 / 创作设置端点 / 审计读端点。

- make_chain 消费 project_settings.model_routes（§6.10）：命中合法模型 → 置链首 + 默认链
  去重兜底；非可配置角色 / 未配置 / 非法模型 → 默认链；
- settings GET/PUT 全量替换 + 非法 role/model 400 + 空 dict 清空；
- global-audit 列表/详情形状对齐（列表只带计数、详情带 findings/抽样角色）。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from aiink.api.routes_global_audit import get_global_audit, list_global_audits
from aiink.api.routes_settings import (SettingsBody, get_project_settings,
                                       put_project_settings)
from aiink.db import tenant_session
from aiink.memory.repository import get_settings
from aiink.models import GlobalAuditReport, ProjectSettings
from aiink.providers import make_chain

FINDING = {"conflict_type": "persona_drift", "severity": "hint", "scope": "local",
           "source": "audit", "evidence": [{"chapter": 1, "quote": "……"}],
           "suggestion": None, "conflict_key": "persona:test"}


def _set_routes(pid: str, routes: dict[str, str]) -> None:
    """直写 model_routes（绕过 PUT 校验，测试 make_chain 对脏数据的兜底）。"""
    with tenant_session(pid) as db:
        st = get_settings(db, uuid.UUID(pid))
        if st is None:
            st = ProjectSettings(project_id=uuid.UUID(pid), model_routes=routes, version=1)
            db.add(st)
        else:
            st.model_routes = routes
        db.commit()


# ---- 每 Agent 模型路由（§6.10）----

def test_make_chain_override_puts_primary_head_with_default_fallback(temp_project):
    """项目级 writer→pro：链首为 pro、默认链其余去重兜底；未配置角色走默认链。"""
    _set_routes(temp_project, {"writer": "deepseek-v4-pro"})
    assert make_chain("writer", project_id=temp_project).chain == \
        ["deepseek-v4-pro", "deepseek-v4-flash"]
    # 未配置的 role 不受影响
    assert make_chain("planner", project_id=temp_project).chain == \
        ["deepseek-v4-flash", "deepseek-v4-pro"]
    # db=None（自开会话）与复用调用方会话结果一致
    with tenant_session(temp_project) as db:
        assert make_chain("writer", project_id=temp_project, db=db).chain == \
            ["deepseek-v4-pro", "deepseek-v4-flash"]


def test_make_chain_ignores_invalid_or_absent_model_route(temp_project):
    """非法模型 id / 空路由 → 回落默认链（脏数据不炸链、不静默换模型）。"""
    _set_routes(temp_project, {"writer": "not-a-model", "extract": "deepseek-v4-pro"})
    assert make_chain("writer", project_id=temp_project).chain == \
        ["deepseek-v4-flash", "deepseek-v4-pro"]
    assert make_chain("extract", project_id=temp_project).chain == \
        ["deepseek-v4-pro", "deepseek-v4-flash"]


def test_make_chain_non_configurable_roles_ignore_override(temp_project):
    """audit 不在可配置集（§6.10）→ 即使直写 model_routes 也走默认链（PUT 同闸双保险）。"""
    _set_routes(temp_project, {"audit": "deepseek-v4-pro"})
    assert make_chain("audit", project_id=temp_project).chain == \
        ["deepseek-v4-flash", "deepseek-v4-pro"]
    # 完全未配置任何路由
    _set_routes(temp_project, {})
    assert make_chain("writer", project_id=temp_project).chain == \
        ["deepseek-v4-flash", "deepseek-v4-pro"]


# ---- 创作设置端点（GET/PUT）----

def test_settings_roundtrip_full_replace(temp_project):
    """PUT 全量替换 + version 递增；空 dict 清空回落默认链。"""
    g0 = get_project_settings(temp_project)
    assert g0["model_routes"] == {} and g0["version"] == 0

    put_project_settings(temp_project, SettingsBody(model_routes={"planner": "deepseek-v4-pro"}))
    g1 = get_project_settings(temp_project)
    assert g1["model_routes"] == {"planner": "deepseek-v4-pro"} and g1["version"] == 1

    # 再 PUT 另一角色 → 全量替换（planner 被清）+ version 递增
    put_project_settings(temp_project, SettingsBody(model_routes={"extract": "deepseek-v4-pro"}))
    g2 = get_project_settings(temp_project)
    assert g2["model_routes"] == {"extract": "deepseek-v4-pro"} and g2["version"] == 2

    put_project_settings(temp_project, SettingsBody(model_routes={}))
    g3 = get_project_settings(temp_project)
    assert g3["model_routes"] == {} and g3["version"] == 3


def test_settings_rejects_invalid_role_and_model(temp_project):
    """非法 role（非可配置集）/ 非法模型 id → 400 且不污染现值。"""
    with pytest.raises(HTTPException) as e1:
        put_project_settings(temp_project, SettingsBody(model_routes={"audit": "deepseek-v4-pro"}))
    assert e1.value.status_code == 400
    with pytest.raises(HTTPException) as e2:
        put_project_settings(temp_project, SettingsBody(model_routes={"writer": "not-a-model"}))
    assert e2.value.status_code == 400
    assert get_project_settings(temp_project)["model_routes"] == {}


# ---- 审计读端点（列表/详情）----

def test_global_audit_read_endpoints_shape(temp_project):
    """列表项只带计数、详情带 findings 明细/抽样角色——前端类型对齐的形状契约。"""
    assert list_global_audits(temp_project) == []

    with tenant_session(temp_project) as db:
        db.add(GlobalAuditReport(
            project_id=uuid.UUID(temp_project), window_start=1, window_end=3,
            audited_up_to_chapter=3, trigger="manual", status="completed",
            sampled_characters=[{"character_id": "c1", "name": "林晚"}],
            findings=[FINDING], summary={"sampled": 1, "findings": 1, "chapters": 3},
            error=None))
        db.flush()
        rid = str(db.query(GlobalAuditReport).filter(
            GlobalAuditReport.project_id == uuid.UUID(temp_project)).first().id)
        db.commit()

    lst = list_global_audits(temp_project)
    assert len(lst) == 1
    assert lst[0]["findings"] == 1  # 计数（前端 summary 形状）
    assert lst[0]["window_start"] == 1 and lst[0]["trigger"] == "manual"

    det = get_global_audit(temp_project, rid)
    assert det["findings"] == [FINDING]  # 明细（详情形状）
    assert det["sampled_characters"][0]["name"] == "林晚"
    assert det["summary"]["chapters"] == 3
