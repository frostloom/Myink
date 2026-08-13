"""文风样本提取测试（§7.12 文风档案闭环：统计层 + LLM 提炼 → 草稿 → 确认落库）。

范围：
- 统计层：句长三档分布和≈1、对话密度∈[0,1]、段落结构、高频词串确定性（纯函数无 DB）；
- 提炼/合并：stub provider → 语义字段齐全、统计字段保留；LLM 抛错/坏 JSON → 只统计层 +
  extract_error（§6.12 降级）；
- 端点（TestClient + temp_project + 身份头）：POST style-samples 返回草稿（不落库）、
  PUT style-profile 落库 + version 递增 / 无行新建、参数校验 400、validate 轻归一；
- 越权矩阵：伪造他人 403 / 缺失身份 403 / 项目不存在 404（require_owner 挂载确认）；
- 注入：确认落库后 _style_section 渲染含 lexicon_tendency / reference_excerpts /
  frequent_words / 节奏基线；既有键渲染不变（L1/L2 零回归锚点）。

模式 A（monkeypatch aiink.providers.default_provider）：make_chain 调用时读全局单例，
与 test_flow stub_provider 同款。
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from aiink.api.main import app
from aiink.db import new_session, tenant_session
from aiink.memory.repository import get_settings
from aiink.models import ProjectSettings, User
from aiink.providers.base import ModelProvider, ModelResponse
from aiink.style_extract import (
    analyze_sample_stats,
    extract_style_profile,
    merge_style_draft,
    validate_profile,
)
from aiink.workflow.prompts import _style_section

client = TestClient(app)

_SAMPLE_1 = (
    "夜色如墨，城墙上的风裹着血腥气。林砚握紧剑柄，指尖发白，却没有退后半步。\n"
    "「你来了。」他声音很轻，像怕惊动什么。\n"
    "远处传来马蹄声，由远及近，卷起一片烟尘。他眯起眼，看着那道越来越近的身影，嘴角勾起一抹冷笑。"
)

_STYLE_PAYLOAD = {
    "pov": "第三人称限知，以主角林砚视角为主",
    "sentence_style": "长短句交错，动作描写紧凑，段落偏短",
    "lexicon_tendency": "冷色调意象，血腥与金属意象反复出现",
    "dialogue": "对话短促，口语化，角色腔调有区分",
    "forbidden": ["“嘴角勾起一抹冷笑”类表情套语"],
    "reference_excerpts": ["「你来了。」他声音很轻，像怕惊动什么。"],
}


def _demo_user_id() -> uuid.UUID:
    with new_session() as db:
        u = db.query(User).filter(User.username == "demo").first()
        assert u is not None, "请先运行 `aiink init`（demo 用户未建）"
        return u.id


def _h(uid: str | uuid.UUID | None) -> dict:
    """请求头：X-AiInk-User = 网关已验证的 JWT sub（None → 不带，测 fail closed）。"""
    return {"X-AiInk-User": str(uid)} if uid is not None else {}


class _StyleStub(ModelProvider):
    """假 provider：文风提炼返回固定 JSON；可配坏原文 / 抛异常（测降级，§6.12）。"""

    def __init__(self, payload: dict | None = None, *, raw: str | None = None, raise_error: bool = False):
        self._payload = payload
        self._raw = raw
        self._raise_error = raise_error
        self.calls = 0

    def name(self) -> str:
        return "style-stub"

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False,
                 tools=None, disable_thinking=False):
        self.calls += 1
        if self._raise_error:
            raise RuntimeError("provider down")
        content = self._raw if self._raw is not None else json.dumps(self._payload or {}, ensure_ascii=False)
        return ModelResponse(content=content, model_id=model_id, input_tokens=10, output_tokens=20)


@pytest.fixture
def style_stub(monkeypatch):
    import aiink.providers as providers_mod

    def _install(payload: dict | None = None, *, raw: str | None = None, raise_error: bool = False) -> _StyleStub:
        stub = _StyleStub(payload, raw=raw, raise_error=raise_error)
        monkeypatch.setattr(providers_mod, "default_provider", stub)
        return stub

    return _install


# ---- 统计层（纯函数、确定性）----


def test_stats_wellformed_and_deterministic():
    stats = analyze_sample_stats([_SAMPLE_1])
    dist = stats["sentence_len_dist"]
    assert round(dist["short"] + dist["mid"] + dist["long"], 3) == pytest.approx(1.0)
    assert dist["avg"] > 0
    assert 0.0 <= stats["dialogue_ratio"] <= 1.0
    assert stats["para_stats"]["count"] == 3
    assert stats["para_stats"]["avg_len"] > 0
    assert stats["frequent_words"], "高频词串不应为空（样本含重复字串）"
    assert analyze_sample_stats([_SAMPLE_1]) == analyze_sample_stats([_SAMPLE_1]), "统计层必须确定性"


# ---- 提炼 / 合并（纯函数 + stub provider）----


def test_extract_and_merge_keeps_semantic_and_stats(style_stub):
    stub = style_stub(_STYLE_PAYLOAD)
    stats = analyze_sample_stats([_SAMPLE_1])
    llm_profile, err = extract_style_profile([_SAMPLE_1], stats)
    assert err is None
    assert stub.calls == 1, "样本提炼应只调一次 LLM（便宜快模型，§7.12）"
    draft = merge_style_draft(stats, llm_profile)
    assert draft["source"] == "sample"
    assert draft["pov"] == _STYLE_PAYLOAD["pov"]
    assert draft["forbidden"] == _STYLE_PAYLOAD["forbidden"]
    assert draft["reference_excerpts"] == _STYLE_PAYLOAD["reference_excerpts"]
    assert draft["sentence_len_dist"] == stats["sentence_len_dist"], "统计字段保留"
    assert draft["frequent_words"] == stats["frequent_words"]
    assert "extract_error" not in draft


def test_extract_fallback_on_provider_error(style_stub):
    style_stub(raise_error=True)
    stats = analyze_sample_stats([_SAMPLE_1])
    llm_profile, err = extract_style_profile([_SAMPLE_1], stats)
    assert err is not None and "provider down" in err
    draft = merge_style_draft(stats, llm_profile, extract_error=err)
    assert draft["extract_error"] == err
    assert "pov" not in draft, "LLM 失败不应有语义字段"
    assert draft["sentence_len_dist"] == stats["sentence_len_dist"], "降级仍回统计层草稿"


def test_extract_fallback_on_bad_json(style_stub):
    style_stub(raw="{not-json")
    stats = analyze_sample_stats([_SAMPLE_1])
    llm_profile, err = extract_style_profile([_SAMPLE_1], stats)
    assert err is not None and "parse_error" in err
    draft = merge_style_draft(stats, llm_profile, extract_error=err)
    assert "extract_error" in draft


def test_validate_profile_normalizes_types():
    with pytest.raises(ValueError):
        validate_profile("not-a-dict")
    with pytest.raises(ValueError):
        validate_profile(None)
    cleaned = validate_profile({"pov": "第三人称", "forbidden": ["a", None, "b"],
                                "ratio": 0.4, "nested": {"avg": 18.0}, "drop": None})
    assert cleaned == {"pov": "第三人称", "forbidden": ["a", "b"], "ratio": 0.4,
                       "nested": {"avg": 18.0}}


# ---- 端点：POST 草稿（不落库）----


def test_style_samples_returns_draft(temp_project, style_stub):
    stub = style_stub(_STYLE_PAYLOAD)
    resp = client.post(
        f"/internal/v1/projects/{temp_project}/style-samples",
        headers=_h(_demo_user_id()),
        json={"samples": [_SAMPLE_1]},
    )
    assert resp.status_code == 200
    draft = resp.json()["draft"]
    assert draft["source"] == "sample"
    assert draft["pov"] == _STYLE_PAYLOAD["pov"]
    assert draft["sentence_len_dist"]["avg"] > 0
    assert stub.calls == 1


def test_style_samples_rejects_bad_input(temp_project):
    headers = _h(_demo_user_id())
    # 空样本 → 400
    r = client.post(f"/internal/v1/projects/{temp_project}/style-samples", headers=headers,
                    json={"samples": ["", "  "]})
    assert r.status_code == 400
    # 超过 2 篇 → 400
    r = client.post(f"/internal/v1/projects/{temp_project}/style-samples", headers=headers,
                    json={"samples": ["a", "b", "c"]})
    assert r.status_code == 400
    # 总量超限 → 400
    r = client.post(f"/internal/v1/projects/{temp_project}/style-samples", headers=headers,
                    json={"samples": ["很" * 13_000]})
    assert r.status_code == 400


# ---- 端点：PUT 确认落库 + version 递增 / 无行新建 ----


def test_put_style_profile_persists_and_increments_version(temp_project):
    """确认落库 + version 递增（相对断言，不依赖 demo 初始 state；读回一致，§7.6）。"""
    headers = _h(_demo_user_id())
    url = f"/internal/v1/projects/{temp_project}/style-profile"
    r1 = client.put(url, headers=headers, json={"profile": {"pov": "第一版", "source": "sample"}})
    assert r1.status_code == 200
    assert r1.json()["style_profile"]["source"] == "sample"
    v1 = r1.json()["version"]
    r2 = client.put(url, headers=headers, json={"profile": {"pov": "第二版"}})
    assert r2.status_code == 200
    assert r2.json()["version"] == v1 + 1, "每次确认 version 递增（乐观版本号）"
    with tenant_session(temp_project) as db:
        st = get_settings(db, uuid.UUID(temp_project))
        assert st.style_profile["pov"] == "第二版", "确认后整档案覆盖落库"
        assert st.version == v1 + 1


def test_put_style_profile_creates_settings_when_missing(temp_project):
    with tenant_session(temp_project) as db:
        db.query(ProjectSettings).filter(ProjectSettings.project_id == uuid.UUID(temp_project)).delete()
        db.commit()
    resp = client.put(
        f"/internal/v1/projects/{temp_project}/style-profile",
        headers=_h(_demo_user_id()),
        json={"profile": {"pov": "作者个人风格"}},
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 1, "无既有行 → 新建从 version=1 起"
    with tenant_session(temp_project) as db:
        st = get_settings(db, uuid.UUID(temp_project))
        assert st.style_profile["pov"] == "作者个人风格"
        assert st.version == 1


# ---- 越权矩阵（require_owner 挂载确认，§14.5）----


def test_style_samples_ownership(temp_project):
    url = f"/internal/v1/projects/{temp_project}/style-samples"
    body = {"samples": [_SAMPLE_1]}
    assert client.post(url, headers=_h(uuid.uuid4()), json=body).status_code == 403   # 伪造他人
    assert client.post(url, json=body).status_code == 403                             # 缺失身份
    assert client.post(f"/internal/v1/projects/{uuid.uuid4()}/style-samples",
                       headers=_h(_demo_user_id()), json=body).status_code == 404     # 项目不存在


def test_put_style_profile_ownership(temp_project):
    url = f"/internal/v1/projects/{temp_project}/style-profile"
    body = {"profile": {"pov": "x"}}
    assert client.put(url, headers=_h(uuid.uuid4()), json=body).status_code == 403
    assert client.put(url, json=body).status_code == 403
    assert client.put(f"/internal/v1/projects/{uuid.uuid4()}/style-profile",
                      headers=_h(_demo_user_id()), json=body).status_code == 404


# ---- 注入渲染（_style_section：新增键 + 既有键零回归）----


def test_style_section_renders_new_keys():
    profile = {
        "pov": "第三人称限知",
        "sentence_style": "长短句交错",
        "lexicon_tendency": "冷色调意象",
        "forbidden": ["“嘴角勾起一抹冷笑”类套语"],
        "fatigue_words": ["凝望", "目光"],
        "frequent_words": ["夜色", "冷笑"],
        "dialogue": "对话短促",
        "reference_excerpts": ["「你来了。」他声音很轻，像怕惊动什么。"],
        "sentence_len_dist": {"short": 0.3, "mid": 0.6, "long": 0.1, "avg": 18.0},
        "dialogue_ratio": 0.4,
    }
    section = _style_section(profile, None)
    assert "叙事视角" in section and "第三人称限知" in section
    assert "词汇修辞倾向" in section and "冷色调意象" in section
    assert "风格示范" in section and "你来了。" in section
    assert "凝望、目光、夜色、冷笑" in section, "fatigue_words + frequent_words 去重合并"
    assert "节奏参考" in section and "对话占比约 40%" in section


def test_style_section_legacy_keys_unchanged():
    """既有键（无样本提取字段）渲染与原输出一致——L1/L2 文风检测零回归锚点（样例 15/38/39）。"""
    profile = {"pov": "第三人称限知视角", "fatigue_words": ["凝望"], "forbidden": ["套语"]}
    section = _style_section(profile, None)
    assert "高频词节制（避免机械复用）：凝望" in section
    assert "表述禁忌（必须避免）：套语。" in section
    assert "风格示范" not in section, "无 reference_excerpts → 不渲染示范段"
    assert "节奏参考" not in section, "无节奏基线字段 → 不渲染节奏行"
