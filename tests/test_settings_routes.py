"""Project settings redact legacy credentials; platform owns model configuration.

Legacy probe helpers retain their validation coverage; HTTP admin enforcement is
covered in test_platform_configuration. Global audit reporting remains unchanged.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from myink.api.routes_global_audit import get_global_audit, list_global_audits
from myink.api import routes_settings
from myink.api.routes_settings import (ModelConnectionBody, SettingsBody, get_project_settings,
                                       put_project_settings)
from myink.db import new_session, tenant_session
from myink.memory.repository import get_settings
from myink.models import GlobalAuditReport, Project, ProjectSettings, User
from myink.providers import make_chain

FINDING = {"conflict_type": "persona_drift", "severity": "hint", "scope": "local",
           "source": "audit", "evidence": [{"chapter": 1, "quote": "……"}],
           "suggestion": None, "conflict_key": "persona:test"}


def _isolate_from_account_env(pid: str) -> None:
    """临时书挂到空账号，避免演示用户的环境配置抢掉项目级 make_chain。"""
    _set_routes(pid, {})
    with new_session() as db:
        user = User(username=f"iso-{uuid.uuid4().hex[:8]}")
        db.add(user)
        db.flush()
        db.get(Project, uuid.UUID(pid)).user_id = user.id
        db.commit()


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


# ---- Project settings cannot bypass centralized model policy ----

def test_make_chain_without_platform_model_does_not_use_builtin(temp_project):
    _isolate_from_account_env(temp_project)
    from myink.platform_readiness import PlatformNotReady
    with pytest.raises(PlatformNotReady):
        make_chain('writer', project_id=temp_project)
    with tenant_session(temp_project) as db:
        with pytest.raises(PlatformNotReady):
            make_chain('writer', project_id=temp_project, db=db)


def test_make_chain_ignores_legacy_project_credentials(temp_project):
    _isolate_from_account_env(temp_project)
    cid = str(uuid.uuid4())
    from myink.providers.connections import pack_model_settings
    from myink.providers.credentials import encrypt_api_key
    _set_routes(temp_project, pack_model_settings({'writer': f'custom:{cid}'}, {
        cid: {'name': 'Legacy', 'protocol': 'openai', 'base_url': 'https://models.example.com',
              'model': 'legacy-pro', 'api_key_encrypted': encrypt_api_key('legacy-secret')}}))
    from myink.platform_readiness import PlatformNotReady
    with pytest.raises(PlatformNotReady):
        make_chain('writer', project_id=temp_project)
    response = get_project_settings(temp_project)
    assert response['model_routes'] == {}
    assert response['model_connections'] == []
    assert 'legacy-secret' not in repr(response)
    assert 'api_key_encrypted' not in repr(response)


@pytest.mark.parametrize('payload', [
    {'model_routes': {}}, {'model_connections': []},
    {'model_routes': {'writer': 'not-a-model'}},
    {'model_routes': {'not-a-role': 'custom:x'}},
])
def test_project_settings_rejects_any_model_mutation(temp_project, payload):
    before = get_project_settings(temp_project)
    with pytest.raises(HTTPException) as error:
        put_project_settings(temp_project, SettingsBody(**payload))
    assert error.value.status_code == 403
    assert get_project_settings(temp_project) == before


def test_empty_project_settings_preserves_existing_data(temp_project):
    before = get_project_settings(temp_project)
    assert put_project_settings(temp_project, SettingsBody()) == before


def test_connection_validation_requires_key_and_rejects_credential_urls():
    cid = str(uuid.uuid4())
    with pytest.raises(HTTPException, match='必须填写 API Key'):
        routes_settings.connection_record(ModelConnectionBody(
            id=cid, name='No key', protocol='openai', base_url='https://8.8.8.8/v1', model='m'), {})
    with pytest.raises(HTTPException, match='请求地址不能包含'):
        routes_settings.connection_record(ModelConnectionBody(
            id=cid, name='URL credentials', protocol='openai',
            base_url='https://user:pass@models.example.com/v1?key=x', model='m', api_key='x'), {})


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
    from myink.providers.credentials import encrypt_api_key
    monkeypatch.setattr('myink.api.routes_platform.load_configuration', lambda: {
        'connections': {cid: {'api_key_encrypted': encrypt_api_key('stored-secret')}}})
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
    with pytest.raises(HTTPException, match="(?i)API Key"):
        routes_settings.list_connection_models(temp_project, routes_settings.ConnectionProbeBody(
            protocol="openai", base_url="https://models.example.com/v1"))
    with pytest.raises(HTTPException, match="模型 id"):
        routes_settings.test_model_connection(temp_project, routes_settings.ConnectionProbeBody(
            protocol="openai", base_url="https://models.example.com/v1", api_key="k"))


def test_probe_rejects_non_global_hosts(temp_project, monkeypatch):
    """出站地址守卫：云元数据/内网/回环/多播/保留一律 400，且不触达探针。

    100.100.100.200 是阿里云元数据，落在 100.64.0.0/10——既不属 private 也不属 reserved，
    列举式判据会漏掉它，只有「非全球可路由」拦得住。这条用例就是防判据退回列举法。
    """
    def boom(*_args, **_kwargs):
        raise AssertionError("不应触达探针")

    monkeypatch.setattr(routes_settings.probe, "list_models", boom)
    for risky in ("http://169.254.169.254/latest/meta-data",
                  "http://100.100.100.200/latest/meta-data",
                  "http://[fe80::1]:8080/v1", "http://127.0.0.1:11434/v1",
                  "http://192.168.1.20:8000/v1", "http://10.0.0.5/v1",
                  "http://0.0.0.0/v1", "http://239.1.1.1/v1"):
        with pytest.raises(HTTPException, match="内网/保留地址"):
            routes_settings.list_connection_models(temp_project, routes_settings.ConnectionProbeBody(
                protocol="openai", base_url=risky, api_key="k"))


def test_probe_allows_global_hosts(temp_project, monkeypatch):
    """全球可路由地址照常放行（本地/内网地址已不再放行——本部署不用本地模型）。"""
    seen: dict = {}

    def fake_list(protocol, base_url, api_key):
        seen["url"] = base_url
        return ["m"], None

    monkeypatch.setattr(routes_settings.probe, "list_models", fake_list)
    for public in ("http://8.8.8.8/v1", "https://models.example.com/v1"):
        assert routes_settings.list_connection_models(
            temp_project, routes_settings.ConnectionProbeBody(
                protocol="openai", base_url=public, api_key="k"))["ok"] is True
    assert seen["url"] == "https://models.example.com/v1"


def test_platform_connection_record_rejects_non_global_model_host():
    for risky in ('http://169.254.169.254/latest/meta-data', 'http://100.100.100.200/latest/meta-data',
                  'http://127.0.0.1:11434/v1', 'http://192.168.1.20:8000/v1'):
        with pytest.raises(HTTPException, match='内网/保留地址'):
            routes_settings.connection_record(ModelConnectionBody(
                id=str(uuid.uuid4()), name='Risky', protocol='openai',
                base_url=risky, model='m', api_key='k'), {})


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
