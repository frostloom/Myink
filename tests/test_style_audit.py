"""全局审计文风漂移 L2「抽样比对」测试（§8.6 阶段 3 长线治理切片 3，conflict-samples.md 样例 38/39）。

mock LLM（不依赖真实 DeepSeek key）。验证：
- 确定性抽样：窗口前已确认章节 = 基线（even-spacing cap 4）、窗口章节采样；基线空（首个窗口）
  或窗口无章 → 维度中性短路（零 LLM 调用，summary 不加 style 键）；
- 正例（样例 38 全书风格漂移）LLM 判 drift → style/hint/local/L2 落库检出；负例（样例 39 场景
  节奏合法变化 → LLM 判 ok / 空数组）0 误报；
- L2 相对 L1 的精度：样例 38 漂移文本规避 fatigue 阈值 → L1 style_repeat_check 0 检出，面级
  漂移由 L2 单独承担（companion 断言）；
- 0 误报兜底：normalize_and_verify_style_findings 确定性核验守卫（引文逐字子串 / verdict=drift /
  chapter 在窗口采样集 / 置信度 ≥0.6）——过度标记 stub 被全丢弃，独立于 LLM 行为；
- 三维度编排：run_global_audit 一次调用跑 persona + bridge + style（3 次 LLM 调用、findings
  三类型混排、summary 按维度拆）；部分成功（persona 成功 + style 挂）→ completed + summary["errors"]；
- LLM/解析失败非阻塞：status=failed 报告 + marker 推进。

桩设计（test_bridge_audit 模板）：模块级 fixture 幂等补表；LLM 单点注入 = monkeypatch
`aiink.validation.global_audit.make_chain`；embedder 用 DeterministicFakeEmbedder + patch
l1/nodes/recall/global_audit 四处 get_embedder（三维集成测试的桥段近邻需要）。
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from aiink.db import tenant_session
from aiink.memory.vector_store import PgvectorStore
from aiink.models import Chapter, Character, Event, GlobalAuditReport, ProjectSettings
from aiink.providers.base import ModelResponse
from aiink.validation import global_audit as ga
from aiink.validation.l1 import L1Validator

REALM_ORDER = ["炼气", "筑基", "金丹", "元婴", "化神", "大乘", "渡劫"]

# 样例 38/39 数据：基线 = 仙侠雅句（既定文风）；窗口 = 网络口语（漂移）或战斗短句（合法变化）
BASE_TMPL = "云海翻涌，林砚负手立于崖巅，目光沉凝。第{n}章。"
DRIFT_TMPL = "林砚拍桌而起：'卧槽，这也太离谱了吧，直接开干！'第{n}章。"
SCENE_TMPL = "剑鸣刺耳。血溅三尺。林砚不退，剑锋再进。第{n}章。"
DRIFT_QUOTE = "林砚拍桌而起：'卧槽，这也太离谱了吧，直接开干！'"  # ch6 正文前缀，逐字可核
# 桥段历史/窗口事件（gap 10 过 _REPEAT_MIN_GAP；无呼应标记词）
CH5 = "拍卖会上林砚被嘲讽亮出身份打脸"
CUR_IDENT = CH5


@pytest.fixture(scope="module", autouse=True)
def _ensure_audit_reports_table():
    """幂等补 global_audit_reports 表（活 demo 库跑过 init 的缺新表，不依赖重跑 aiink init）。"""
    from aiink.db import ensure_global_audit_reports

    ensure_global_audit_reports()


class DeterministicFakeEmbedder:
    """确定性假 bge-m3：3-gram 特征哈希 → 1024 维单位向量（test_bridge_audit 同款）。"""

    def _feat(self, text: str) -> list[float]:
        v = [0.0] * 1024
        for i in range(len(text) - 2):
            ng = text[i:i + 3]
            h = int(__import__("hashlib").sha256(ng.encode("utf-8")).hexdigest()[:8], 16)
            v[h % 1024] += 1.0
        n = (sum(x * x for x in v) ** 0.5) or 1.0
        return [x / n for x in v]

    def encode(self, texts):
        return [self._feat(t) for t in texts]


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    fake = DeterministicFakeEmbedder()
    monkeypatch.setattr("aiink.validation.l1.get_embedder", lambda: fake)
    monkeypatch.setattr("aiink.workflow.nodes.get_embedder", lambda: fake)
    monkeypatch.setattr("aiink.memory.recall.get_embedder", lambda: fake)
    monkeypatch.setattr("aiink.validation.global_audit.get_embedder", lambda: fake)
    return fake


# ---- 种子辅助（temp_project 不带 characters/events/chapters，必须自种）----


def _seed_character(pid: str, name: str, personality: str) -> None:
    with tenant_session(pid) as db:
        db.add(Character(project_id=uuid.UUID(pid), name=name, aliases=[], race="人族",
                         origin="test", realm_cap="金丹", personality=personality, base_attrs={}))
        db.commit()


def _seed_chapter(pid: str, seq: int, content: str) -> None:
    with tenant_session(pid) as db:
        db.add(Chapter(project_id=uuid.UUID(pid), chapter_seq=seq, title=f"第{seq}章",
                       content=content, status="confirmed", version=1))
        db.commit()


def _seed_event(pid: str, summary: str, chapter: int) -> uuid.UUID:
    """历史/窗口事件 + 向量入库（test_bridge_audit._seed_event 同款造数）。"""
    p = uuid.UUID(pid)
    with tenant_session(pid) as db:
        ev = Event(project_id=p, summary=summary, participants=[],
                   source_chapter=chapter, confidence=0.9)
        db.add(ev)
        db.flush()
        PgvectorStore().upsert(db, project_id=p, level="event", source_id=ev.id,
                               source_chapter=chapter, model_version="bge-m3",
                               embedding=DeterministicFakeEmbedder()._feat(summary))
        db.flush()
        return ev.id


def _set_profile(pid: str, profile: dict) -> None:
    """改写该书 project_settings.style_profile（temp_project 克隆 demo 可能为空，显式覆盖以确定输入）。"""
    with tenant_session(pid) as db:
        st = db.execute(select(ProjectSettings).where(
            ProjectSettings.project_id == uuid.UUID(pid))).scalar_one_or_none()
        if st is None:
            db.add(ProjectSettings(project_id=uuid.UUID(pid), world_rules={},
                                   style_profile=profile, hard_constraints=[]))
        else:
            st.style_profile = profile
        db.commit()


def _seed_style_book(pid: str, baseline_n: int, window_n: int,
                     window_texts=None) -> tuple[int, int]:
    """种「窗口前基线章 + 窗口章」，返回窗口元组 (start, end)。

    基线 ch1..N 用仙侠雅句（既定文风）；窗口 ch(N+1).. 用 window_texts(seq)（缺省漂移口语）。
    文本规避 demo fatigue 词与呼应标记词（样例 38 的 L1 companion 断言依赖）。
    """
    for seq in range(1, baseline_n + 1):
        _seed_chapter(pid, seq, BASE_TMPL.format(n=seq))
    start = baseline_n + 1
    for i in range(window_n):
        seq = start + i
        text = window_texts(seq) if window_texts else DRIFT_TMPL.format(n=seq)
        _seed_chapter(pid, seq, text)
    return (start, start + window_n - 1) if window_n else (start, start)


def _report_rows(pid: str) -> list[GlobalAuditReport]:
    with tenant_session(pid) as db:
        return db.query(GlobalAuditReport).filter(
            GlobalAuditReport.project_id == uuid.UUID(pid)).order_by(
            GlobalAuditReport.window_start).all()


# ---- LLM 桩（单点：aiink.validation.global_audit.make_chain）----


class _Chain:
    """audit 链包装（test_bridge_audit 同款，传给 make_chain 的 lambda）。"""

    def __init__(self, provider):
        self.provider = provider

    def generate(self, messages, *, json_mode=False, max_tokens=None, temperature=None, tools=None):
        return self.provider.generate(messages, model_id="stub", max_tokens=max_tokens,
                                      temperature=temperature, json_mode=json_mode, tools=tools)


class AuditStub:
    """全局审计 stub：返回预置 findings（或 error / 空数组），记录调用数与 messages。"""

    def __init__(self, findings=None, error=None):
        self.findings = findings if findings is not None else []
        self.error = error
        self.calls = 0

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False,
                 tools=None, disable_thinking=False):
        self.calls += 1
        if self.error:
            return ModelResponse(content="", model_id=model_id, error=self.error,
                                 input_tokens=50, output_tokens=0, duration_ms=30)
        return ModelResponse(content=json.dumps({"findings": self.findings}, ensure_ascii=False),
                             model_id=model_id, input_tokens=50, output_tokens=80, duration_ms=30)


class _RecordingStub:
    """记录每次调用的 messages（返回空 findings），供提示词组装断言。"""

    def __init__(self):
        self.messages_list: list[list[dict]] = []
        self.calls = 0

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False,
                 tools=None, disable_thinking=False):
        self.calls += 1
        self.messages_list.append(messages)
        return ModelResponse(content=json.dumps({"findings": []}, ensure_ascii=False),
                             model_id=model_id, input_tokens=50, output_tokens=80, duration_ms=30)


class _FailAtStub:
    """第 fail_at 次调用必错，其余成功（部分成功：persona 过、style 挂）。"""

    def __init__(self, findings, error, fail_at):
        self.findings = findings
        self.error = error
        self.fail_at = fail_at
        self.calls = 0

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False,
                 tools=None, disable_thinking=False):
        self.calls += 1
        if self.calls == self.fail_at:
            return ModelResponse(content="", model_id=model_id, error=self.error,
                                 input_tokens=50, output_tokens=0, duration_ms=30)
        return ModelResponse(content=json.dumps({"findings": self.findings}, ensure_ascii=False),
                             model_id=model_id, input_tokens=50, output_tokens=80, duration_ms=30)


def _install_audit_stub(monkeypatch, stub):
    """单点注入：patch aiink.validation.global_audit.make_chain（全局审计唯一桩点）。"""
    monkeypatch.setattr(ga, "make_chain", lambda role, **_kwargs: _Chain(stub))


# ---- 1. 确定性采样边界 + 短路 ----

STYLE_DRIFT = {"chapter": 6, "verdict": "drift", "evidence": DRIFT_QUOTE,
               "aspect": "用词/语气", "reason": "网络口语与仙侠雅句基线系统性偏离", "confidence": 0.85}


def test_even_spaced_indices_boundaries():
    """even-spacing 边界：n≤cap 全取、cap≤1 防除零、n=5 cap=4 → 首尾各留一。"""
    assert ga._even_spaced_indices(5, 4) == [0, 1, 3, 4]
    assert ga._even_spaced_indices(3, 4) == [0, 1, 2]
    assert ga._even_spaced_indices(5, 1) == [0]
    assert ga._even_spaced_indices(0, 4) == []


def test_style_baseline_empty_shortcircuit(temp_project, monkeypatch):
    """窗口 (1,5) 无窗口前章节（首个窗口）→ style 中性短路：calls==0、summary 无 style 键、marker 推进。"""
    _seed_style_book(temp_project, 0, 5)  # 只种窗口 ch1-5，基线空
    stub = AuditStub(findings=[])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (1, 5), source="manual")
    assert stub.calls == 0, "基线空 → style 中性，零 LLM 调用"
    assert rep["status"] == "completed" and rep["findings"] == []
    assert "style" not in rep["summary"], f"style 未跑不得加 summary 键，实际 {rep['summary']}"
    rows = _report_rows(temp_project)
    assert len(rows) == 1 and rows[0].status == "completed"
    assert rows[0].audited_up_to_chapter == 5, "marker 应推进到窗口末尾"


def test_style_window_empty_shortcircuit(temp_project, monkeypatch):
    """基线 ch1-5 有 + 窗口 (6,8) 无章 → style 中性短路：calls==0。"""
    _seed_style_book(temp_project, 5, 0)
    stub = AuditStub(findings=[])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 8), source="manual")
    assert stub.calls == 0 and rep["status"] == "completed" and rep["findings"] == []
    assert "style" not in rep["summary"]


# ---- 2. 正例（样例 38）检出 / 负例（样例 39）0 误报 / L1 增量 ----

def test_style_positive_sample38_drift(temp_project, monkeypatch):
    """样例 38 全书风格漂移：窗口 ch6-10 网络口语 vs 基线 ch1-5 仙侠雅句 → style/hint/local/L2 + marker。"""
    _seed_style_book(temp_project, 5, 5)
    stub = AuditStub(findings=[STYLE_DRIFT])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 10), source="manual")
    assert rep["status"] == "completed"
    assert stub.calls == 1, "仅文风维度 1 次 LLM 调用（无角色/事件短路）"
    assert len(rep["findings"]) == 1, f"应检出 1 条，实际 {rep['findings']}"
    f = rep["findings"][0]
    assert f["conflict_type"] == "style" and f["severity"] == "hint"
    assert f["scope"] == "local" and f["source"] == "L2"
    assert f["evidence"][0]["chapter"] == 6 and f["evidence"][0]["quote"] == DRIFT_QUOTE
    assert f["conflict_key"] == "style_drift:6" and f["confidence"] == 0.85
    assert rep["summary"]["style"] == {"sampled": 4, "findings": 1}, \
        "窗口 5 章 even-spacing cap4 → 采样 4 章（{6,7,9,10}）"
    rows = _report_rows(temp_project)
    assert len(rows) == 1 and rows[0].status == "completed"
    assert rows[0].audited_up_to_chapter == 10


def test_style_l1_not_triggered_on_sample38(temp_project):
    """样例 38 漂移文本规避 fatigue 阈值 → L1 style_repeat_check 0 检出（面级漂移由 L2 单独承担）。"""
    _seed_style_book(temp_project, 5, 5)
    with tenant_session(temp_project) as db:
        ch10 = db.query(Chapter).filter(Chapter.project_id == uuid.UUID(temp_project),
                                        Chapter.chapter_seq == 10).first()
        fs = L1Validator(REALM_ORDER).style_repeat_check(
            db, project_id=uuid.UUID(temp_project), chapter_seq=10, draft=ch10.content)
        assert [f.model_dump(mode="json") for f in fs] == [], "漂移文本不得触发 L1 高频统计"


def test_style_negative_sample39_scene_variation(temp_project, monkeypatch):
    """样例 39 场景节奏合法变化（战斗短句）：内容异于基线但 LLM 判无漂移 → 0 findings、completed。"""
    _seed_style_book(temp_project, 5, 5, window_texts=lambda n: SCENE_TMPL.format(n=n))
    stub = AuditStub(findings=[])  # LLM 判定合法变化不漂移
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 10), source="manual")
    assert rep["status"] == "completed" and rep["findings"] == []
    assert stub.calls == 1, "有候选正常跑（判 ok），非短路"
    assert rep["summary"]["style"] == {"sampled": 4, "findings": 0}


# ---- 3. 确定性核验守卫（0 误报兜底，独立于 LLM 行为）----


def test_style_guard_drops_bad_evidence(temp_project, monkeypatch):
    """引文非该窗口章正文逐字子串 → 守卫丢弃 → 0（LLM 乱编也过不了核验）。"""
    _seed_style_book(temp_project, 5, 5)
    bad = dict(STYLE_DRIFT, evidence="林砚在黑市查探玉佩真相")
    stub = AuditStub(findings=[bad])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 10), source="manual")
    assert stub.calls == 1 and rep["findings"] == [], "守卫应丢弃非逐字引文"
    assert rep["status"] == "completed", "LLM 成功仅核验过滤，非失败"


def test_style_guard_drops_low_confidence(temp_project, monkeypatch):
    """置信度 < 0.6 → 丢弃（宁缺毋滥）。"""
    _seed_style_book(temp_project, 5, 5)
    stub = AuditStub(findings=[dict(STYLE_DRIFT, confidence=0.4)])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 10), source="manual")
    assert rep["findings"] == []


def test_style_guard_drops_wrong_verdict(temp_project, monkeypatch):
    """verdict != drift（ok/缺失）→ 守卫丢弃，不进 findings。"""
    _seed_style_book(temp_project, 5, 5)
    stub = AuditStub(findings=[dict(STYLE_DRIFT, verdict="ok")])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 10), source="manual")
    assert rep["findings"] == []


def test_style_guard_drops_unsampled_chapter(temp_project, monkeypatch):
    """chapter=8 不在窗口采样集 {6,7,9,10} → resolve None → 丢弃（防 LLM 指未抽样章凑数）。"""
    _seed_style_book(temp_project, 5, 5)
    stub = AuditStub(findings=[dict(STYLE_DRIFT, chapter=8)])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 10), source="manual")
    assert rep["findings"] == [], "引文在 ch8 正文内但 ch8 未采样，仍须丢弃"


# ---- 4. 失败非阻塞 + 提示词组装 + 三维度编排 ----


def test_style_llm_failure_non_blocking(temp_project, monkeypatch):
    """persona/bridge 短路 + style LLM 挂 → 不 raise、status=failed、marker 推进（非阻塞+有界）。"""
    _seed_style_book(temp_project, 5, 5)
    stub = AuditStub(error="audit 判定失败")
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 10), source="manual")
    assert rep["status"] == "failed" and rep["findings"] == []
    assert rep["error"] == "audit 判定失败", "单维度失败透传原文"
    rows = _report_rows(temp_project)
    assert len(rows) == 1 and rows[0].status == "failed"
    assert rows[0].audited_up_to_chapter == 10, "失败也推进 marker（防每批重审毒窗口）"


def test_style_messages_assembled(temp_project, monkeypatch):
    """style_audit_messages 组装：user 含 档案块（_style_section 渲染）/基线摘录/窗口摘录（逐字）。"""
    _seed_style_book(temp_project, 5, 5)
    _set_profile(temp_project, {"pov": "第三人称限知", "sentence_style": "长短句结合自然"})
    stub = _RecordingStub()
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        ga.run_global_audit(db, temp_project, (6, 10), source="manual")
    assert stub.calls == 1
    msgs = stub.messages_list[0]
    assert msgs[0]["role"] == "system" and "文风漂移" in msgs[0]["content"]
    user = msgs[1]["content"]
    assert "叙事视角" in user and "句式要求" in user, "档案块应经 _style_section 渲染"
    assert "第 1 章：云海翻涌" in user, "基线摘录逐字"
    assert "第 6 章：林砚拍桌而起" in user, "窗口摘录逐字"


def test_run_global_audit_three_kinds(temp_project, monkeypatch):
    """一次审计跑 persona + bridge + style 三维度：3 次 LLM 调用、findings 三类型混排、summary 按维度拆。"""
    _seed_character(temp_project, "林砚", "谨慎隐忍、谋定后动")
    _seed_style_book(temp_project, 5, 10)  # 基线 ch1-5 + 窗口 ch6-15（含林砚提及 → persona 触发）
    _seed_event(temp_project, CH5, 5)
    _seed_event(temp_project, CUR_IDENT, 15)
    persona_f = {"character": "林砚", "drift_type": "persona", "chapter": 8,
                 "evidence": "这也太离谱了吧", "reason": "谨慎隐忍→无铺垫破口大骂", "confidence": 0.9}
    bridge_f = {"event": "pair_1", "verdict": "repeat", "chapter": 15,
                "evidence": "卧槽，这也太离谱了吧，直接开干！", "reason": "结构雷同、无新意无新目的", "confidence": 0.85}
    style_f = dict(STYLE_DRIFT, chapter=6)
    stub = AuditStub(findings=[persona_f, bridge_f, style_f])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 15), source="manual")
    assert stub.calls == 3, f"三维度各 1 次 LLM，实际 {stub.calls}"
    assert rep["status"] == "completed"
    keys = {f["conflict_key"].split(":")[0] for f in rep["findings"]}
    assert keys == {"persona", "bridge", "style_drift"}, f"findings 应混排三维度，实际 {rep['findings']}"
    assert rep["summary"]["findings"] == 3
    assert rep["summary"]["bridge"] == {"pairs": 1, "findings": 1}
    assert rep["summary"]["style"] == {"sampled": 4, "findings": 1}
    assert "errors" not in rep["summary"]


def test_style_partial_success_merged_summary(temp_project, monkeypatch):
    """部分成功：persona 成功（第 1 次）+ style 挂（第 2 次，bridge 中性）→ completed + errors。"""
    _seed_character(temp_project, "林砚", "谨慎隐忍、谋定后动")
    _seed_style_book(temp_project, 5, 5)
    persona_f = {"character": "林砚", "drift_type": "persona", "chapter": 6,
                 "evidence": "这也太离谱了吧", "reason": "谨慎隐忍→无铺垫破口大骂", "confidence": 0.9}
    stub = _FailAtStub(findings=[persona_f], error="style 判定失败", fail_at=2)
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 10), source="manual")
    assert stub.calls == 2, "persona 第 1 次、style 第 2 次（bridge 无事件中性）"
    assert rep["status"] == "completed", "任一维度成功即 completed（部分成功）"
    assert rep["summary"]["errors"] == {"style": "style 判定失败"}
    assert rep["error"] == "style 判定失败"
    assert len(rep["findings"]) == 1 and rep["findings"][0]["conflict_key"].startswith("persona:")
    rows = _report_rows(temp_project)
    assert len(rows) == 1 and rows[0].status == "completed"
    assert rows[0].audited_up_to_chapter == 10
