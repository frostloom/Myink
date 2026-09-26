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

模式 A（monkeypatch myink.providers.default_provider）：make_chain 调用时读全局单例，
与 test_flow stub_provider 同款。
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete as sa_delete

from conftest import identity_headers
from myink.api.main import app
from myink.db import new_session, tenant_session
from myink.memory.repository import get_settings
from myink.models import AgentRun, ProjectSettings, StyleLibraryItem, User
from myink.providers.base import ModelProvider, ModelResponse
from myink.style_extract import (
    _split_sentences,
    analyze_sample_stats,
    extract_style_profile,
    merge_style_draft,
    validate_profile,
)
from myink.workflow.prompts import _style_section

client = TestClient(app)

_SAMPLE_1 = (
    "夜色如墨，城墙上的风裹着血腥气。林砚握紧剑柄，指尖发白，却没有退后半步。\n"
    "「你来了。」他声音很轻，像怕惊动什么。\n"
    "远处传来马蹄声，由远及近，卷起一片烟尘。他眯起眼，看着那道越来越近的身影，嘴角勾起一抹冷笑。"
)

_STYLE_PAYLOAD = {
    "pov": "第三人称限知，以主角林砚视角为主",
    "narrative_voice": "克制的冷调，用短句与名词收束，避免形容词堆叠。例句：「他握紧剑柄，指尖发白，却没有退后半步。」",
    "dialogue_style": "对话短促，口语化，角色腔调有区分。例句：「你来了。」他声音很轻。",
    "scene_description": "偏重视觉与听觉，环境服务于压迫感。例句：「夜色如墨，城墙上的风裹着血腥气。」",
    "transitions": "场景靠声音切入（马蹄声由远及近），不做时间跳接。",
    "pacing": "短句为主，动作段落节奏紧，高潮处反而放长句。",
    "diction": "冷色调意象，血腥与金属意象反复出现，少用成语。",
    "emotional_expression": "情绪靠动作外化，几乎不写内心独白。",
    "distinctive_habits": "常用「没有退后半步」这类否定式收束动作。",
    "sentence_style": "长短句交错，动作描写紧凑，段落偏短",
    "lexicon_tendency": "冷色调意象，血腥与金属意象反复出现",
    "dialogue": "对话短促，口语化，角色腔调有区分",
    "forbidden": ["“嘴角勾起一抹冷笑”类表情套语"],
    "reference_excerpts": ["「你来了。」他声音很轻，像怕惊动什么。"],
}


def _demo_user_id() -> uuid.UUID:
    with new_session() as db:
        u = db.query(User).filter(User.username == "demo").first()
        assert u is not None, "请先运行 `myink init --seed`（demo 用户未建）"
        return u.id


def _h(uid: str | uuid.UUID | None) -> dict:
    """请求头：真 HS256 Bearer（None → 不带，测 fail closed）。"""
    return identity_headers(uid)


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
    import myink.providers as providers_mod

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
    assert draft["narrative_voice"] == _STYLE_PAYLOAD["narrative_voice"], "文笔八维进草稿"
    assert draft["distinctive_habits"] == _STYLE_PAYLOAD["distinctive_habits"]
    assert draft["sentence_len_dist"] == stats["sentence_len_dist"], "统计字段保留"
    assert draft["frequent_words"] == stats["frequent_words"]
    assert "extract_error" not in draft


def test_merge_keeps_prose_dimensions_and_drops_non_string_ones():
    """文笔八维进草稿；同一键给了非字符串（模型偶尔会）就不收，不覆盖统计层产出。"""
    stats = analyze_sample_stats([_SAMPLE_1])
    draft = merge_style_draft(stats, {
        "narrative_voice": "冷调",
        "pacing": "短句为主",
        "diction": ["不是字符串"],          # 形状不符 → 丢
        "frequent_words": ["模型瞎给的"],   # 统计层产出 → 不被 LLM 覆盖
    })
    assert draft["narrative_voice"] == "冷调"
    assert draft["pacing"] == "短句为主"
    assert "diction" not in draft
    assert draft["frequent_words"] == stats["frequent_words"]


def test_extract_prompt_asks_for_prose_dimensions():
    """抽取的口径是「写作文笔」：八维必须落到提示词里，且明确不提炼题材与情节（§7.12）。"""
    from myink.workflow.prompts import SYSTEM_STYLE_EXTRACT

    for key in ("narrative_voice", "dialogue_style", "scene_description", "transitions",
                "pacing", "diction", "emotional_expression", "distinctive_habits"):
        assert key in SYSTEM_STYLE_EXTRACT, f"提示词缺文笔维度 {key}"
    assert "原文例句" in SYSTEM_STYLE_EXTRACT, "八维必须要求原文例句佐证"
    assert "不要**提炼题材" in SYSTEM_STYLE_EXTRACT, "必须挡住题材/情节混进文风档案"


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
        f"/api/v1/projects/{temp_project}/style-samples",
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
    r = client.post(f"/api/v1/projects/{temp_project}/style-samples", headers=headers,
                    json={"samples": ["", "  "]})
    assert r.status_code == 400
    # 超过 2 篇 → 400
    r = client.post(f"/api/v1/projects/{temp_project}/style-samples", headers=headers,
                    json={"samples": ["a", "b", "c"]})
    assert r.status_code == 400
    # 总量超限 → 400
    r = client.post(f"/api/v1/projects/{temp_project}/style-samples", headers=headers,
                    json={"samples": ["很" * 13_000]})
    assert r.status_code == 400


# ---- 端点：PUT 确认落库 + version 递增 / 无行新建 ----


def test_put_style_profile_persists_and_increments_version(temp_project):
    """确认落库 + version 递增（相对断言，不依赖 demo 初始 state；读回一致，§7.6）。"""
    headers = _h(_demo_user_id())
    url = f"/api/v1/projects/{temp_project}/style-profile"
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
        f"/api/v1/projects/{temp_project}/style-profile",
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
    url = f"/api/v1/projects/{temp_project}/style-samples"
    body = {"samples": [_SAMPLE_1]}
    assert client.post(url, headers=_h(uuid.uuid4()), json=body).status_code == 401   # 未知账号
    assert client.post(url, json=body).status_code == 403                             # 缺失身份
    assert client.post(f"/api/v1/projects/{uuid.uuid4()}/style-samples",
                       headers=_h(_demo_user_id()), json=body).status_code == 404     # 项目不存在


def test_put_style_profile_ownership(temp_project):
    url = f"/api/v1/projects/{temp_project}/style-profile"
    body = {"profile": {"pov": "x"}}
    assert client.put(url, headers=_h(uuid.uuid4()), json=body).status_code == 401
    assert client.put(url, json=body).status_code == 403
    assert client.put(f"/api/v1/projects/{uuid.uuid4()}/style-profile",
                      headers=_h(_demo_user_id()), json=body).status_code == 404


# ---- 注入渲染（_style_section：新增键 + 既有键零回归）----


def test_style_section_renders_new_keys():
    profile = {
        "pov": "第三人称限知",
        "sentence_style": "长短句交错",
        "lexicon_tendency": "冷色调意象",
        "forbidden": ["“嘴角勾起一抹冷笑”类套语"],
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
    assert "高频词节制（避免机械复用）：夜色、冷笑" in section
    assert "凝望" not in section
    assert "节奏参考" in section and "对话占比约 40%" in section


def test_style_section_renders_prose_dimensions():
    """文笔八维按中文维度名注入写作提示词（§7.12：样本提来的文笔要真的用得上）。"""
    profile = {
        "narrative_voice": "克制的冷调，靠短句收束",
        "dialogue_style": "对话短促，角色腔调有区分",
        "distinctive_habits": "常用否定式收束动作",
    }
    section = _style_section(profile, None)
    assert "文笔要求（照样本提炼，逐条贴合；引文只作示范，不得照抄）：" in section
    assert "- 叙事声音与语气：克制的冷调，靠短句收束" in section
    assert "- 对话风格：对话短促，角色腔调有区分" in section
    assert "- 独特习惯：常用否定式收束动作" in section
    # 没给的维度不占行（八维全缺时整段不出现）。
    assert "场景描写特征" not in section
    assert "文笔要求" not in _style_section({"pov": "第三人称"}, None)


def test_style_section_legacy_keys_unchanged():
    """既有键渲染；fatigue_words 即使残留也不进提示。"""
    profile = {"pov": "第三人称限知视角", "fatigue_words": ["凝望"], "forbidden": ["套语"]}
    section = _style_section(profile, None)
    assert "凝望" not in section
    assert "高频词节制" not in section
    assert "表述禁忌（必须避免）：套语。" in section
    assert "风格示范" not in section, "无 reference_excerpts → 不渲染示范段"
    assert "节奏参考" not in section, "无节奏基线字段 → 不渲染节奏行"


# ---- 审计整改（2026-08-14，commit 186e93c 审计整改切片）----


def _style_run_count() -> int:
    """style_extract 节点的 agent_runs 行数（观测表无 RLS，new_session 可查）。"""
    with new_session() as db:
        return db.query(AgentRun).filter(AgentRun.node == "style_extract").count()


def test_split_sentences_no_semicolon_boundary():
    """S3：中文分号是句内并列不作句边界（口径收紧，2026-08-14 审计整改）。"""
    assert _split_sentences("他缓缓走来；她抬头。") == ["他缓缓走来；她抬头"]
    assert _split_sentences("他缓缓走来。她抬头；两人对视。") == ["他缓缓走来", "她抬头；两人对视"]


def test_style_samples_does_not_persist(temp_project, style_stub):
    """S6：「不落库」的 DB 断言——POST 草稿不改 settings 行/档案。"""
    style_stub(_STYLE_PAYLOAD)
    headers = _h(_demo_user_id())
    with tenant_session(temp_project) as db:
        before = get_settings(db, uuid.UUID(temp_project))
        before_profile = None if before is None else dict(before.style_profile or {})
    resp = client.post(
        f"/api/v1/projects/{temp_project}/style-samples", headers=headers,
        json={"samples": [_SAMPLE_1]},
    )
    assert resp.status_code == 200
    with tenant_session(temp_project) as db:
        after = get_settings(db, uuid.UUID(temp_project))
    if before is None:
        assert after is None, "POST 不应新建 settings 行"
    else:
        assert dict(after.style_profile or {}) == before_profile, "POST 不应改动 style_profile"


def test_style_samples_records_agent_run(temp_project, style_stub):
    """W3：extract 调用记 agent_runs（§6.8 成本透明；成功路径 error 空）。"""
    style_stub(_STYLE_PAYLOAD)
    before = _style_run_count()
    resp = client.post(
        f"/api/v1/projects/{temp_project}/style-samples",
        headers=_h(_demo_user_id()),
        json={"samples": [_SAMPLE_1]},
    )
    assert resp.status_code == 200
    assert _style_run_count() == before + 1, "本次 POST 应恰好新增一行 agent_runs"
    with new_session() as db:
        ok = db.query(AgentRun).filter(AgentRun.node == "style_extract",
                                       AgentRun.error.is_(None)).first()
        assert ok is not None, "成功路径应存在 error 为空的 agent_runs 行"


def test_style_samples_degraded_http(temp_project, style_stub):
    """S6+W3：HTTP 全路径降级——LLM 抛错 → 200 统计层草稿 + extract_error + 降级记 error 行。"""
    style_stub(raise_error=True)
    before = _style_run_count()
    resp = client.post(
        f"/api/v1/projects/{temp_project}/style-samples",
        headers=_h(_demo_user_id()),
        json={"samples": [_SAMPLE_1]},
    )
    assert resp.status_code == 200, "LLM 失败不 500（§6.12）"
    draft = resp.json()["draft"]
    assert "provider down" in draft["extract_error"]
    assert "pov" not in draft, "LLM 失败不应有语义字段"
    assert _style_run_count() == before + 1, "降级调用也应新增 agent_runs 行"
    with new_session() as db:
        err = db.query(AgentRun).filter(AgentRun.node == "style_extract",
                                        AgentRun.error.isnot(None)).first()
        assert err is not None and "provider down" in err.error, "降级应记 error 行（§6.12 可观测）"


def test_put_drops_fatigue_keys(temp_project):
    """确认落库时丢掉 fatigue_words / fatigue_patterns，不保留旧值。"""
    headers = _h(_demo_user_id())
    url = f"/api/v1/projects/{temp_project}/style-profile"
    r = client.put(url, headers=headers, json={
        "profile": {"pov": "预设包", "fatigue_words": ["凝望"], "fatigue_patterns": ["不是.{0,20}而是"]},
    })
    assert r.status_code == 200
    assert "fatigue_words" not in r.json()["style_profile"]
    assert "fatigue_patterns" not in r.json()["style_profile"]
    r = client.put(url, headers=headers, json={"profile": {"pov": "样本草稿确认", "source": "sample"}})
    assert r.status_code == 200
    with tenant_session(temp_project) as db:
        st = get_settings(db, uuid.UUID(temp_project))
        assert "fatigue_words" not in st.style_profile
        assert st.style_profile["pov"] == "样本草稿确认"


def test_put_strips_extract_error(temp_project):
    """S7：草稿降级诊断键 extract_error 不落库（瞬态提示非档案内容）。"""
    headers = _h(_demo_user_id())
    r = client.put(
        f"/api/v1/projects/{temp_project}/style-profile", headers=headers,
        json={"profile": {"pov": "v", "extract_error": "provider down"}},
    )
    assert r.status_code == 200
    assert "extract_error" not in r.json()["style_profile"]
    with tenant_session(temp_project) as db:
        st = get_settings(db, uuid.UUID(temp_project))
        assert "extract_error" not in st.style_profile


def test_style_section_str_list_keys_safe():
    """S5：列表键为字符串时不逐字展开（join/unpack 前 _profile_list 类型守卫）。"""
    profile = {"frequent_words": "夜色冷笑",
               "forbidden": "套语", "reference_excerpts": "你来了。"}
    section = _style_section(profile, None)
    assert "高频词节制（避免机械复用）：夜色冷笑" in section
    assert "表述禁忌（必须避免）：套语。" in section
    assert "风格示范" in section and "你来了。" in section


# ---- 账号级记账（建书时导入文章：还没有 project_id 也能提取）----


def test_extract_style_profile_records_an_account_level_run(temp_user, style_stub):
    """没有 project_id、只有 user_id 时也要能提取并记账（建书时的文风导入走这条路）。"""
    style_stub(_STYLE_PAYLOAD)
    with new_session() as db:
        profile, err = extract_style_profile(
            [_SAMPLE_1], analyze_sample_stats([_SAMPLE_1]), user_id=temp_user, db=db)
        db.commit()
        assert err is None and isinstance(profile, dict)
        row = db.query(AgentRun).filter(AgentRun.user_id == uuid.UUID(temp_user)).first()
    assert row is not None and row.project_id is None and row.node == "style_extract"


def test_extract_style_profile_without_any_owner_still_extracts():
    """不记账的纯提取（既有用法）不能被归属检查误伤。"""
    profile, err = extract_style_profile([_SAMPLE_1], analyze_sample_stats([_SAMPLE_1]))
    assert isinstance(profile, dict)


def test_extract_style_profile_with_db_but_no_owner_is_rejected():
    """有 db 就必须有归属：错误是归属检查的消息，不是 uuid 解析错（守卫必须先于选链）。"""
    with new_session() as db:
        with pytest.raises(ValueError, match="db 非 None"):
            extract_style_profile([_SAMPLE_1], analyze_sample_stats([_SAMPLE_1]), db=db)


def test_ownerless_extraction_routes_through_the_account_level_chain(temp_user, monkeypatch):
    """有 user_id 无 project_id 必须走 make_user_chain（不是 make_chain(project_id=None)）。

    单纯装 style_stub 分辨不出来：make_chain 与 make_user_chain 在桩下返回同一条链。
    这里盯调用本身。链未配置（无桩）→ 返回降级 error 即可，本测试只问「哪个构造函数被调」。
    """
    import myink.providers as providers_mod

    called = []
    real = providers_mod.make_user_chain
    monkeypatch.setattr(providers_mod, "make_user_chain",
                        lambda role, uid: (called.append((role, uid)), real(role, uid))[1])
    extract_style_profile([_SAMPLE_1], analyze_sample_stats([_SAMPLE_1]), user_id=temp_user)
    assert called == [("extract", temp_user)]


def test_resolve_style_selection_prefers_builtin_then_library(temp_user):
    """选择器的值 → (档案, skill_pack 标记, 展示名)：内置走预设，其余走自己的库。"""
    from myink.api.routes_style import resolve_style_selection

    with new_session() as db:
        uid = uuid.UUID(temp_user)
        profile, skill_pack, name = resolve_style_selection(db, uid, "builtin:xianxia-jiuzhou")
        assert skill_pack == "xianxia-jiuzhou", "内置项 id 同时当 skill_pack 标记"
        assert name == "九州问天"
        assert profile, "内置预设也要把档案带出来"

        item = StyleLibraryItem(user_id=uid, name="渡口白描",
                                profile={"pov": "限知"}, sample_chars=10)
        db.add(item)
        db.commit()
        profile, skill_pack, name = resolve_style_selection(db, uid, str(item.id))
        assert profile == {"pov": "限知"}
        assert skill_pack is None, "库里的一项不是题材包，不能留 skill_pack 标记"
        assert name == "渡口白描"


def test_resolve_style_selection_404s_on_garbage(temp_user):
    from myink.api.routes_style import resolve_style_selection

    with new_session() as db:
        for bad in ("builtin:nope", "not-a-uuid", str(uuid.uuid4())):
            with pytest.raises(HTTPException) as exc:
                resolve_style_selection(db, uuid.UUID(temp_user), bad)
            assert exc.value.status_code == 404


def test_resolve_style_selection_will_not_read_a_stranger_item(temp_user):
    """别人的档也要 404 —— 不能因为 id 真实存在就把档案交出去。"""
    from myink.api.routes_style import resolve_style_selection

    with new_session() as db:
        other = User(username=f"style-{uuid.uuid4().hex[:8]}")
        db.add(other)
        db.commit()
        other_id = other.id
    try:
        with new_session() as db:
            item = StyleLibraryItem(user_id=other_id, name="别人家的",
                                    profile={"pov": "全知"}, sample_chars=5)
            db.add(item)
            db.commit()
            item_id = item.id
        with new_session() as db, pytest.raises(HTTPException) as exc:
            resolve_style_selection(db, uuid.UUID(temp_user), str(item_id))
        assert exc.value.status_code == 404
    finally:
        with new_session() as db:
            db.execute(sa_delete(StyleLibraryItem).where(StyleLibraryItem.user_id == other_id))
            db.execute(sa_delete(User).where(User.id == other_id))
            db.commit()
