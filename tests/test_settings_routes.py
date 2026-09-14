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
from aiink.api import routes_settings
from aiink.api.routes_settings import (ModelConnectionBody, SettingsBody, get_project_settings,
                                       put_project_settings)
from aiink.db import tenant_session
from aiink.memory.repository import get_settings
from aiink.models import GlobalAuditReport, ProjectSettings
from aiink.providers import make_chain
from aiink.providers.connections import CONNECTIONS_KEY
from aiink.providers.credentials import decrypt_api_key

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


def test_settings_omitting_routes_preserves_them(temp_project):
    """省略 model_routes = 保留现值（与 connections 对称），显式 {} 才清空。

    旧写法 `body.model_routes or {}` 分不清「没传」与「传空」：只改连接的客户端（或任何
    绕过前端的调用）会静默清空全部分角色路由。
    """
    put_project_settings(temp_project, SettingsBody(model_routes={"writer": "deepseek-v4-pro"}))
    assert put_project_settings(temp_project, SettingsBody())["model_routes"] == \
        {"writer": "deepseek-v4-pro"}
    assert put_project_settings(temp_project, SettingsBody(model_routes={}))["model_routes"] == {}


def test_custom_model_connection_is_encrypted_redacted_and_routable(temp_project):
    cid = str(uuid.uuid4())
    result = put_project_settings(temp_project, SettingsBody(
        model_connections=[ModelConnectionBody(
            id=cid, name="私有 OpenAI", protocol="openai",
            base_url="https://models.example.com/v1/", model="novel-pro",
            api_key="secret-value",
        )],
        model_routes={"writer": f"custom:{cid}"},
    ))

    assert result["model_routes"] == {"writer": f"custom:{cid}"}
    assert result["model_connections"] == [{
        "id": cid, "name": "私有 OpenAI", "protocol": "openai",
        "base_url": "https://models.example.com/v1", "model": "novel-pro",
        "has_api_key": True,
    }]
    assert "secret-value" not in repr(result)
    with tenant_session(temp_project) as db:
        stored = get_settings(db, uuid.UUID(temp_project)).model_routes
        encrypted = stored[CONNECTIONS_KEY][cid]["api_key_encrypted"]
    assert encrypted != "secret-value"
    assert decrypt_api_key(encrypted) == "secret-value"

    chain = make_chain("writer", project_id=temp_project)
    assert chain.chain == ["novel-pro", "deepseek-v4-flash", "deepseek-v4-pro"]
    assert chain.providers[0].name() == "openai-compatible"
    assert chain.providers[1].name() == "deepseek"


def test_updating_custom_connection_with_blank_key_preserves_secret(temp_project):
    cid = str(uuid.uuid4())
    put_project_settings(temp_project, SettingsBody(
        model_connections=[ModelConnectionBody(
            id=cid, name="Claude", protocol="anthropic",
            base_url="https://api.anthropic.com", model="claude-sonnet", api_key="first-key",
        )],
        model_routes={"planner": f"custom:{cid}"},
    ))
    put_project_settings(temp_project, SettingsBody(
        model_connections=[ModelConnectionBody(
            id=cid, name="Claude 新名称", protocol="anthropic",
            base_url="https://api.anthropic.com/v1", model="claude-sonnet",
        )],
        model_routes={"planner": f"custom:{cid}"},
    ))

    chain = make_chain("planner", project_id=temp_project)
    assert chain.providers[0].name() == "anthropic"
    assert get_project_settings(temp_project)["model_connections"][0]["name"] == "Claude 新名称"


def test_custom_connection_validation_rejects_missing_key_and_unsafe_url(temp_project):
    cid = str(uuid.uuid4())
    with pytest.raises(HTTPException, match="必须填写 API Key"):
        put_project_settings(temp_project, SettingsBody(
            model_connections=[ModelConnectionBody(
                id=cid, name="无密钥", protocol="openai",
                base_url="https://models.example.com/v1", model="m",
            )],
        ))
    with pytest.raises(HTTPException, match="请求地址不能包含"):
        put_project_settings(temp_project, SettingsBody(
            model_connections=[ModelConnectionBody(
                id=cid, name="错误地址", protocol="openai",
                base_url="https://user:pass@models.example.com/v1?key=x", model="m", api_key="x",
            )],
        ))


# ---- 模型连接探针端点（POST settings/models + settings/test-connection）----

def test_probe_endpoints_forward_inline_key_and_shape(temp_project, monkeypatch):
    """未保存的新连接：明文 key 直达探针；返回契约形状（ok/models/error、ok/latency/reply/error）。"""
    seen: dict = {}

    def fake_list(protocol, base_url, api_key):
        seen["list"] = (protocol, base_url, api_key)
        return ["novel-pro", "novel-mini"], None

    def fake_test(protocol, base_url, api_key, model):
        seen["test"] = (protocol, base_url, api_key, model)
        return True, 42, "pong", None

    monkeypatch.setattr(routes_settings.probe, "list_models", fake_list)
    monkeypatch.setattr(routes_settings.probe, "test_connection", fake_test)

    out = routes_settings.list_connection_models(temp_project, routes_settings.ConnectionProbeBody(
        protocol="openai", base_url="https://models.example.com/v1/", api_key="inline-key"))
    assert out == {"ok": True, "models": ["novel-pro", "novel-mini"], "error": None}
    assert seen["list"] == ("openai", "https://models.example.com/v1", "inline-key")  # 去尾斜杠

    res = routes_settings.test_model_connection(temp_project, routes_settings.ConnectionProbeBody(
        protocol="anthropic", base_url="https://api.anthropic.com", model="claude-x", api_key="k2"))
    assert res == {"ok": True, "latency_ms": 42, "reply": "pong", "error": None}
    assert seen["test"] == ("anthropic", "https://api.anthropic.com", "k2", "claude-x")


def test_probe_reuses_stored_connection_key_when_blank(temp_project, monkeypatch):
    """已保存连接留空 key：用 connection_id 取密文解密后调探针。"""
    cid = str(uuid.uuid4())
    put_project_settings(temp_project, SettingsBody(
        model_connections=[ModelConnectionBody(
            id=cid, name="私有", protocol="openai",
            base_url="https://models.example.com/v1", model="novel-pro", api_key="stored-secret")]))
    seen: dict = {}

    def fake_list(protocol, base_url, api_key):
        seen["key"] = api_key
        return ["novel-pro"], None

    monkeypatch.setattr(routes_settings.probe, "list_models", fake_list)
    out = routes_settings.list_connection_models(temp_project, routes_settings.ConnectionProbeBody(
        protocol="openai", base_url="https://models.example.com/v1", connection_id=cid))

    assert out["ok"] is True and seen["key"] == "stored-secret"


def test_probe_rejects_bad_url_missing_key_and_missing_model(temp_project, monkeypatch):
    """非法地址 / 无密钥 / 缺模型 id → 400，且不触达真实探针。"""
    def boom(*_args, **_kwargs):
        raise AssertionError("不应触达探针")

    monkeypatch.setattr(routes_settings.probe, "list_models", boom)
    monkeypatch.setattr(routes_settings.probe, "test_connection", boom)

    with pytest.raises(HTTPException):
        routes_settings.list_connection_models(temp_project, routes_settings.ConnectionProbeBody(
            protocol="openai", base_url="not-a-url", api_key="k"))
    with pytest.raises(HTTPException, match="API Key"):
        routes_settings.list_connection_models(temp_project, routes_settings.ConnectionProbeBody(
            protocol="openai", base_url="https://models.example.com/v1"))
    with pytest.raises(HTTPException, match="模型 id"):
        routes_settings.test_model_connection(temp_project, routes_settings.ConnectionProbeBody(
            protocol="openai", base_url="https://models.example.com/v1", api_key="k"))


def test_probe_rejects_metadata_and_link_local_hosts(temp_project, monkeypatch):
    """探针地址守卫：云元数据/链路本地/多播/未指定一律 400，且不触达探针。"""
    def boom(*_args, **_kwargs):
        raise AssertionError("不应触达探针")

    monkeypatch.setattr(routes_settings.probe, "list_models", boom)
    for risky in ("http://169.254.169.254/latest/meta-data", "http://[fe80::1]:8080/v1",
                  "http://0.0.0.0/v1", "http://239.1.1.1/v1"):
        with pytest.raises(HTTPException, match="链路本地"):
            routes_settings.list_connection_models(temp_project, routes_settings.ConnectionProbeBody(
                protocol="openai", base_url=risky, api_key="k"))


def test_probe_allows_loopback_and_private_hosts(temp_project, monkeypatch):
    """回环与私有段刻意放行：本地推理服务（127.0.0.1:11434 Ollama）是本功能主场景。"""
    seen: dict = {}

    def fake_list(protocol, base_url, api_key):
        seen["url"] = base_url
        return ["m"], None

    monkeypatch.setattr(routes_settings.probe, "list_models", fake_list)
    for local in ("http://127.0.0.1:11434/v1", "http://192.168.1.20:8000/v1"):
        assert routes_settings.list_connection_models(
            temp_project, routes_settings.ConnectionProbeBody(
                protocol="openai", base_url=local, api_key="k"))["ok"] is True
    assert seen["url"] == "http://192.168.1.20:8000/v1"


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
