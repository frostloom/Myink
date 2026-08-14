"""全局审计桥段重复 L2「区分呼应 vs 重复」测试（§8.6 阶段 3 长线治理切片 2，conflict-samples.md 样例 14/32/37）。

mock LLM（不依赖真实 DeepSeek key）。验证：
- 确定性抽样：窗口事件 vs 历史向量近邻 → 候选对，呼应词表预滤除（样例 32 词表命中 → 排除）、
  零事件/零对短路（不喂 LLM 无证据候选）；
- 正例（样例 14 偷懒重复）LLM 判 repeat → style/hint/local/L2 落库检出；负例（stub 判 echo /
  空数组）0 误报；样例 37（无词表标记的刻意呼应）→ 守卫丢弃 verdict=echo → 0（L2 相对 L1 的精度提升）；
- 0 误报兜底：normalize_and_verify_bridge_findings 确定性核验守卫（引文逐字子串 / verdict=repeat /
  事件在采样对 / 置信度 ≥0.6）——过度标记 stub 被全丢弃，独立于 LLM 行为；
- 双维度编排：run_global_audit 一次调用跑 persona + bridge（2 次 LLM 调用、报告 findings 混排、
  summary 按维度拆）；单维度失败不阻塞另一维度（部分成功 → completed + summary["errors"]）；
- LLM/解析失败非阻塞：status=failed 报告 + marker 推进。

桩设计（test_global_audit 模板）：模块级 fixture 幂等补表；LLM 单点注入 = monkeypatch
`aiink.validation.global_audit.make_chain`；embedder 用 DeterministicFakeEmbedder（3-gram 特征哈希，
共享子串 → 高余弦相似，test_bridge_repeat 同款）+ 额外 patch 本模块 get_embedder。
"""

from __future__ import annotations

import json
import uuid

import pytest

from aiink.db import tenant_session
from aiink.memory.vector_store import PgvectorStore
from aiink.models import Chapter, Character, Event, GlobalAuditReport
from aiink.providers.base import ModelResponse
from aiink.validation import global_audit as ga

# 样例 14/32/37 数据：ch5 拍卖会打脸（历史事件），ch15 当前章同款桥段
CH5 = "拍卖会上林砚被嘲讽亮出身份打脸"
CUR_IDENT = CH5  # 向量距离 0.0（假 embedder 同字符串）
CH15_REPEAT = "同样的拍卖厅，同样的叫价，同样的嘲笑，林砚再次亮出令全场寂静的底牌。"
CH15_MARKED = "同样的拍卖厅，同样的叫价——林砚暗想：这一幕与当年何其相似。他亮出底牌，这次却非争锋，只为引蛇出洞。"
CH15_UNMARKED_ECHO = "拍卖厅叫价声再起。林砚不动声色举牌，等那条藏在暗处的蛇自己上钩。"
QUOTE_REPEAT = "林砚再次亮出令全场寂静的底牌。"


@pytest.fixture(scope="module", autouse=True)
def _ensure_audit_reports_table():
    """幂等补 global_audit_reports 表（活 demo 库跑过 init 的缺新表，不依赖重跑 aiink init）。"""
    from aiink.db import ensure_global_audit_reports

    ensure_global_audit_reports()


class DeterministicFakeEmbedder:
    """确定性假 bge-m3：3-gram 特征哈希 → 1024 维单位向量（test_bridge_repeat 同款）。"""

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


# ---- 种子辅助（temp_project 不带 characters/events，必须自种）----


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
    """历史/窗口事件 + 向量入库（test_bridge_repeat._seed_event 同款造数）。"""
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


def _report_rows(pid: str) -> list[GlobalAuditReport]:
    with tenant_session(pid) as db:
        return db.query(GlobalAuditReport).filter(
            GlobalAuditReport.project_id == uuid.UUID(pid)).order_by(
            GlobalAuditReport.window_start).all()


# ---- LLM 桩（单点：aiink.validation.global_audit.make_chain）----


class _Chain:
    """audit 链包装（仿 test_reflexion._Chain，传给 make_chain 的 lambda）。"""

    def __init__(self, provider):
        self.provider = provider

    def generate(self, messages, *, json_mode=False, max_tokens=None, temperature=None, tools=None):
        return self.provider.generate(messages, model_id="stub", max_tokens=max_tokens,
                                      temperature=temperature, json_mode=json_mode, tools=tools)


class AuditStub:
    """全局审计 stub：返回预置 findings（或 error / 空数组），记录调用数。"""

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


class _FirstFailStub:
    """首次调用必错（persona 维度挂）→ 之后成功（bridge 维度）。"""

    def __init__(self, findings, error):
        self.findings = findings
        self.error = error
        self.calls = 0

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False,
                 tools=None, disable_thinking=False):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(content="", model_id=model_id, error=self.error,
                                 input_tokens=50, output_tokens=0, duration_ms=30)
        return ModelResponse(content=json.dumps({"findings": self.findings}, ensure_ascii=False),
                             model_id=model_id, input_tokens=50, output_tokens=80, duration_ms=30)


def _install_audit_stub(monkeypatch, stub):
    """单点注入：patch aiink.validation.global_audit.make_chain（全局审计唯一桩点）。"""
    monkeypatch.setattr(ga, "make_chain", lambda role, **_kwargs: _Chain(stub))


# ---- 1. 桥段候选抽样：向量近邻 / 零事件短路 / 词表预滤除 ----


def test_sample_bridge_pairs_returns_candidates(temp_project):
    """窗口事件 vs 历史向量近邻（dist≈0.0 且章距 10）→ 1 对候选，含历史章/摘要/距离。"""
    hist_id = _seed_event(temp_project, CH5, 5)
    _seed_event(temp_project, CUR_IDENT, 15)
    _seed_chapter(temp_project, 15, CH15_REPEAT)
    with tenant_session(temp_project) as db:
        pairs = ga.sample_bridge_pairs(db, temp_project, (6, 15))
    assert len(pairs) == 1, f"应恰 1 对候选，实际 {pairs}"
    p = pairs[0]
    assert p["history_event_id"] == str(hist_id)
    assert p["history_chapter"] == 5 and p["chapter"] == 15
    assert p["dist"] < 0.3, "同字符串向量距离应≈0"


def test_sample_bridge_pairs_zero_events_shortcircuit(temp_project):
    """窗口内无事件 → 空表（调用方短路，不喂 LLM 无证据候选）。"""
    _seed_chapter(temp_project, 15, CH15_REPEAT)
    with tenant_session(temp_project) as db:
        assert ga.sample_bridge_pairs(db, temp_project, (6, 15)) == []


def test_sample_bridge_pairs_excludes_marker_chapter(temp_project):
    """当前章正文含呼应标记（样例 32）→ L1 已豁免的对，L2 预滤除不重审。"""
    _seed_event(temp_project, CH5, 5)
    _seed_event(temp_project, CUR_IDENT, 15)
    _seed_chapter(temp_project, 15, CH15_MARKED)  # 「这一幕…与当年何其相似」→ 词表命中
    with tenant_session(temp_project) as db:
        assert ga.sample_bridge_pairs(db, temp_project, (6, 15)) == []


# ---- 2. 正例（样例 14）检出 / 负例 0 误报 ----

BRIDGE_REPEAT = {"event": "pair_1", "verdict": "repeat", "chapter": 15,
                 "evidence": QUOTE_REPEAT, "reason": "结构雷同、无新意无新目的", "confidence": 0.85}


def test_bridge_positive_sample14(temp_project, monkeypatch):
    """样例 14 偷懒重复：LLM 判 repeat + 逐字引文 → style/hint/local/L2 落库 + marker 推进。"""
    _seed_event(temp_project, CH5, 5)
    _seed_event(temp_project, CUR_IDENT, 15)
    _seed_chapter(temp_project, 15, CH15_REPEAT)
    stub = AuditStub(findings=[BRIDGE_REPEAT])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 15), source="manual")
    assert rep["status"] == "completed"
    assert stub.calls == 1, "仅桥段维度 1 次 LLM 调用（persona 无角色短路）"
    assert len(rep["findings"]) == 1, f"应检出 1 条，实际 {rep['findings']}"
    f = rep["findings"][0]
    assert f["conflict_type"] == "style" and f["severity"] == "hint"
    assert f["scope"] == "local" and f["source"] == "L2"
    assert f["evidence"][0]["chapter"] == 15 and f["evidence"][0]["quote"] == QUOTE_REPEAT
    assert f["conflict_key"].startswith("bridge:") and f["confidence"] == 0.85
    assert rep["summary"]["bridge"] == {"pairs": 1, "findings": 1}
    rows = _report_rows(temp_project)
    assert len(rows) == 1 and rows[0].status == "completed"
    assert rows[0].audited_up_to_chapter == 15, "marker 应推进到窗口末尾"


def test_bridge_negative_echo_no_finding(temp_project, monkeypatch):
    """stub 判无偷懒重复（空数组）→ 0 findings（落空报告但 completed + marker 推进）。"""
    _seed_event(temp_project, CH5, 5)
    _seed_event(temp_project, CUR_IDENT, 15)
    _seed_chapter(temp_project, 15, CH15_REPEAT)
    stub = AuditStub(findings=[])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 15), source="manual")
    assert rep["status"] == "completed" and rep["findings"] == []
    rows = _report_rows(temp_project)
    assert len(rows) == 1 and rows[0].audited_up_to_chapter == 15


def test_bridge_negative_sample37_unmarked_echo(temp_project, monkeypatch):
    """样例 37 无词表标记的刻意呼应（L1 会误报）：LLM 判 echo → 守卫丢弃 → 0（L2 精度提升）。"""
    _seed_event(temp_project, CH5, 5)
    _seed_event(temp_project, CUR_IDENT, 15)
    _seed_chapter(temp_project, 15, CH15_UNMARKED_ECHO)  # 无任何 _CALLBACK_MARKERS 词，目的不同
    stub = AuditStub(findings=[{"event": "pair_1", "verdict": "echo", "chapter": 15,
                                "evidence": "林砚不动声色举牌", "reason": "引蛇出洞，目的不同", "confidence": 0.9}])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 15), source="manual")
    assert rep["status"] == "completed" and rep["findings"] == [], "刻意呼应不得检出"


# ---- 3. 确定性核验守卫（0 误报兜底，独立于 LLM 行为）----


def test_bridge_guard_drops_bad_evidence(temp_project, monkeypatch):
    """引文非当前章正文逐字子串 → 守卫丢弃 → 0（LLM 乱编也过不了核验）。"""
    _seed_event(temp_project, CH5, 5)
    _seed_event(temp_project, CUR_IDENT, 15)
    _seed_chapter(temp_project, 15, CH15_REPEAT)
    bad = dict(BRIDGE_REPEAT, evidence="林砚在黑市查探玉佩真相")  # 不在 ch15 正文
    stub = AuditStub(findings=[bad])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 15), source="manual")
    assert stub.calls == 1 and rep["findings"] == [], "守卫应丢弃非逐字引文"
    assert rep["status"] == "completed", "LLM 成功仅核验过滤，非失败"


def test_bridge_guard_drops_low_confidence(temp_project, monkeypatch):
    """置信度 < 0.6 → 丢弃（宁缺毋滥）。"""
    _seed_event(temp_project, CH5, 5)
    _seed_event(temp_project, CUR_IDENT, 15)
    _seed_chapter(temp_project, 15, CH15_REPEAT)
    stub = AuditStub(findings=[dict(BRIDGE_REPEAT, confidence=0.4)])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 15), source="manual")
    assert rep["findings"] == []


def test_bridge_guard_drops_wrong_verdict(temp_project, monkeypatch):
    """verdict != repeat（echo/缺失）→ 守卫丢弃，不进 findings。"""
    _seed_event(temp_project, CH5, 5)
    _seed_event(temp_project, CUR_IDENT, 15)
    _seed_chapter(temp_project, 15, CH15_REPEAT)
    stub = AuditStub(findings=[dict(BRIDGE_REPEAT, verdict="echo")])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 15), source="manual")
    assert rep["findings"] == []


def test_bridge_guard_drops_unknown_pair(temp_project, monkeypatch):
    """event 标识不在候选对集合（pair_9 凭空）→ 守卫丢弃（防 LLM 伪造对编号凑数）。"""
    _seed_event(temp_project, CH5, 5)
    _seed_event(temp_project, CUR_IDENT, 15)
    _seed_chapter(temp_project, 15, CH15_REPEAT)
    stub = AuditStub(findings=[dict(BRIDGE_REPEAT, event="pair_9")])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 15), source="manual")
    assert rep["findings"] == []


# ---- 4. 失败非阻塞 + 双维度编排 ----


def test_bridge_llm_failure_non_blocking(temp_project, monkeypatch):
    """persona 无角色短路 + bridge LLM 挂 → 不 raise、status=failed、marker 推进（非阻塞+有界）。"""
    _seed_event(temp_project, CH5, 5)
    _seed_event(temp_project, CUR_IDENT, 15)
    _seed_chapter(temp_project, 15, CH15_REPEAT)
    stub = AuditStub(error="audit 判定失败")
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (6, 15), source="manual")
    assert rep["status"] == "failed" and rep["findings"] == []
    assert rep["error"] == "audit 判定失败", "单维度失败透传原文"
    rows = _report_rows(temp_project)
    assert len(rows) == 1 and rows[0].status == "failed"
    assert rows[0].audited_up_to_chapter == 15, "失败也推进 marker（防每批重审毒窗口）"


def test_run_global_audit_both_kinds(temp_project, monkeypatch):
    """一次审计跑 persona + bridge 两维度：2 次 LLM 调用、报告 findings 混排、summary 按维度拆。"""
    _seed_character(temp_project, "林砚", "谨慎隐忍、谋定后动")
    _seed_chapter(temp_project, 1, "林砚静观云海。")
    _seed_chapter(temp_project, 12, "林砚一脚踹开雅间木门，指着对方鼻尖破口大骂。")
    _seed_event(temp_project, CH5, 5)
    _seed_event(temp_project, CUR_IDENT, 15)
    _seed_chapter(temp_project, 15, CH15_REPEAT)
    persona_q = "林砚一脚踹开雅间木门，指着对方鼻尖破口大骂。"
    stub = AuditStub(findings=[
        {"character": "林砚", "drift_type": "persona", "chapter": 12,
         "evidence": persona_q, "reason": "谨慎隐忍→无铺垫破口大骂", "confidence": 0.9},
        BRIDGE_REPEAT,
    ])
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (1, 15), source="manual")
    assert stub.calls == 2, f"两维度各 1 次 LLM，实际 {stub.calls}"
    assert rep["status"] == "completed"
    by_type = {f["conflict_type"] for f in rep["findings"]}
    assert by_type == {"persona", "style"}, f"findings 应混排两维度，实际 {rep['findings']}"
    assert rep["summary"]["findings"] == 2
    assert rep["summary"]["bridge"] == {"pairs": 1, "findings": 1}
    assert "errors" not in rep["summary"]


def test_bridge_report_merged_summary(temp_project, monkeypatch):
    """部分成功：persona 挂 + bridge 成功 → completed、persona error 入 summary、桥段检出保留。"""
    _seed_character(temp_project, "林砚", "谨慎隐忍、谋定后动")
    _seed_chapter(temp_project, 1, "林砚静观云海。")
    _seed_event(temp_project, CH5, 5)
    _seed_event(temp_project, CUR_IDENT, 15)
    _seed_chapter(temp_project, 15, CH15_REPEAT)
    stub = _FirstFailStub(findings=[BRIDGE_REPEAT], error="persona 判定失败")
    _install_audit_stub(monkeypatch, stub)
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (1, 15), source="manual")
    assert stub.calls == 2
    assert rep["status"] == "completed", "任一维度成功即 completed（部分成功）"
    assert rep["summary"]["errors"] == {"persona": "persona 判定失败"}
    assert rep["error"] == "persona 判定失败"
    assert len(rep["findings"]) == 1 and rep["findings"][0]["conflict_type"] == "style"
    rows = _report_rows(temp_project)
    assert len(rows) == 1 and rows[0].status == "completed"
    assert rows[0].audited_up_to_chapter == 15
