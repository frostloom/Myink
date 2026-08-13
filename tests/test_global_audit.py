"""全局审计抽样人设漂移 L2 测试（§8.6 阶段 3 长线治理切片 1）。

mock LLM（不依赖真实 DeepSeek key）。验证：
- 窗口推进：每 K 章触发、续后不重审、below_threshold 短路零成本；
- 确定性采样：名提及扫描 cap、零提及短路（不喂无证据角色）；
- 正例（样例 12 踹门骂街无铺垫）检出 + 负例 0 误报 + 语义负例（有变故铺垫）；
- 0 误报兜底：normalize_and_verify_findings 确定性核验守卫（引文逐字子串等）——
  过度标记 stub 被全丢弃，独立于 LLM 行为的负例保证；
- LLM/解析失败非阻塞：status=failed 报告 + marker 推进；
- 手动端点（200/400/502）+ 批次接线（batch_summary 暴露指标）+ 检出/误报指标。

桩设计（test_reflexion 模板）：模块级 fixture 幂等补表（活 demo 库缺新表不依赖 re-init）；
LLM 单点注入 = monkeypatch `aiink.validation.global_audit.make_chain`（不在 batch_graph
再 import，防双桩点）；全批测试额外桩 bg_mod.make_chain + default_provider（章节点）。
temp_project 不带 characters，测试必须自种 Character（personality 为人设漂移基线）。
"""

from __future__ import annotations

import json
import types
import uuid

import pytest
from fastapi import HTTPException

from aiink.db import tenant_session
from aiink.models import Chapter, Character, GlobalAuditReport
from aiink.providers.base import ModelResponse
from aiink.validation import global_audit as ga

from test_flow import StubProvider


@pytest.fixture(scope="module", autouse=True)
def _ensure_audit_reports_table():
    """幂等补 global_audit_reports 表（活 demo 库跑过 init 的缺新表，不依赖重跑 aiink init）。"""
    from aiink.db import ensure_global_audit_reports

    ensure_global_audit_reports()


# ---- 种子辅助（temp_project 不带 characters，必须自种）----


def _seed_character(pid: str, name: str, personality: str, aliases: list | None = None) -> None:
    with tenant_session(pid) as db:
        db.add(Character(project_id=uuid.UUID(pid), name=name, aliases=aliases or [],
                         race="人族", origin="test", realm_cap="金丹",
                         personality=personality, base_attrs={}))
        db.commit()


def _seed_chapter(pid: str, seq: int, content: str) -> None:
    with tenant_session(pid) as db:
        db.add(Chapter(project_id=uuid.UUID(pid), chapter_seq=seq, title=f"第{seq}章",
                       content=content, status="confirmed", version=1))
        db.commit()


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


def _install_audit_stub(monkeypatch, stub):
    """单点注入：patch aiink.validation.global_audit.make_chain（全局审计唯一桩点）。"""
    monkeypatch.setattr(ga, "make_chain", lambda role: _Chain(stub))


# ---- 1. 窗口推进：K 门槛 / 续后不重审 ----


def test_window_threshold_triggers(temp_project):
    """窗口长度 >= K → [last+1, current]；长度 < K → None（短路零成本）。"""
    for seq in range(1, 6):
        _seed_chapter(temp_project, seq, f"正文第{seq}章")
    with tenant_session(temp_project) as db:
        assert ga.window_for_batch(db, temp_project, K=10) is None, "5 < 10 应短路"
    for seq in range(6, 11):
        _seed_chapter(temp_project, seq, f"正文第{seq}章")
    with tenant_session(temp_project) as db:
        assert ga.window_for_batch(db, temp_project, K=10) == (1, 10), "10 >= 10 应触发"


def test_window_resumes_after_prior_report(temp_project):
    """上次审计后新写满 K 章才续审：不重审 [1,10]，从上次 marker 之后开始。"""
    for seq in range(1, 21):
        _seed_chapter(temp_project, seq, f"林砚静观云海。第{seq}章。")
    with tenant_session(temp_project) as db:
        ga.record_report(db, project_id=temp_project, window=(1, 10), findings=[], sampled=[],
                         status="completed", error=None, source="batch")
        db.commit()
    with tenant_session(temp_project) as db:
        win = ga.window_for_batch(db, temp_project, K=10)
    assert win == (11, 20), f"应续后不重审，实际 {win}"


# ---- 2. 确定性采样 ----


def test_sample_characters_mention_scan(temp_project):
    """窗口内名提及扫描：只取提及角色、按提及数降序（同名升序）cap。"""
    _seed_character(temp_project, "林砚", "谨慎隐忍")
    _seed_character(temp_project, "苏晚", "温婉")
    _seed_character(temp_project, "赵恒", "豪迈")
    _seed_character(temp_project, "路人丁", "沉默", aliases=["阿丁"])
    _seed_chapter(temp_project, 1, "林砚与苏晚对坐，赵恒立于一旁。林砚开口：……")
    _seed_chapter(temp_project, 2, "阿丁默默退下。")
    with tenant_session(temp_project) as db:
        sampled = ga.sample_characters(db, temp_project, (1, 2))
    names = [s["name"] for s in sampled]
    assert names[0] == "林砚", f"提及最多应排第一，实际 {names}"
    assert len(names) == 3, f"cap 3，实际 {names}"


def test_sample_characters_zero_mention_shortcircuit(temp_project, monkeypatch):
    """零提及 → 采样为空 → 短路落空报告并推进 marker（不喂无证据角色防幻觉凑数）。"""
    _seed_character(temp_project, "林砚", "谨慎隐忍")
    _seed_chapter(temp_project, 1, "山间雾气弥漫，无人言语。")
    # 必炸桩：零提及若走到 LLM 就证明短路失效
    monkeypatch.setattr(ga, "make_chain", lambda role: (_ for _ in ()).throw(
        AssertionError("零提及应短路，不调 LLM")))
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (1, 1), source="manual")
        db.flush()
    assert rep["status"] == "completed"
    assert rep["findings"] == [] and rep["sampled_characters"] == []
    assert rep["audited_up_to_chapter"] == 1, "短路也应推进 marker（有界防每批重审）"


# ---- 3. 正例（样例 12）/ 负例 0 误报 / 语义负例 ----


def test_persona_positive_sample12(temp_project, monkeypatch):
    """样例 12：林砚谨慎隐忍，ch12 无变故铺垫踹门骂街 → stub 检出 1 条 persona finding。"""
    _seed_character(temp_project, "林砚", "谨慎隐忍、谋定后动")
    for seq in range(1, 11):
        _seed_chapter(temp_project, seq, f"林砚静观云海，谋定后动。第{seq}章。")
    _seed_chapter(temp_project, 12, "林砚一脚踹开房门，破口大骂：'都给我滚！'")
    drift = {"character": "林砚", "drift_type": "persona", "chapter": 12,
             "evidence": [{"quote": "一脚踹开房门，破口大骂"}],
             "reason": "无变故铺垫，突然暴怒辱骂", "confidence": 0.85}
    _install_audit_stub(monkeypatch, AuditStub(findings=[drift]))
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (1, 12), source="manual")
        db.flush()
    assert rep["status"] == "completed"
    assert len(rep["findings"]) == 1, f"应检出 1 条，实际 {rep['findings']}"
    f = rep["findings"][0]
    assert f["conflict_type"] == "persona" and f["severity"] == "hint"
    assert f["scope"] == "local" and f["source"] == "L2"
    assert f["conflict_key"] == "persona:林砚:12"
    assert f["evidence"][0]["chapter"] == 12
    assert f["evidence"][0]["quote"] == "一脚踹开房门，破口大骂"
    rows = _report_rows(temp_project)
    assert len(rows) == 1 and rows[0].status == "completed"
    assert rows[0].audited_up_to_chapter == 12


def test_persona_negative_zero_false_positive(temp_project, monkeypatch):
    """一致性章 + stub 空数组 → 0 findings（阴性窗口无检出）。"""
    _seed_character(temp_project, "林砚", "谨慎隐忍、谋定后动")
    for seq in range(1, 11):
        _seed_chapter(temp_project, seq, f"林砚静观云海，谋定后动。第{seq}章。")
    _install_audit_stub(monkeypatch, AuditStub(findings=[]))
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (1, 10), source="manual")
        db.flush()
    assert rep["status"] == "completed"
    assert rep["findings"] == [] and rep["summary"]["findings"] == 0


def test_negative_justified_change(temp_project, monkeypatch):
    """语义负例：转变有变故铺垫（师门血仇）→ LLM 判不漂移 → 0 findings（漏报优于误报）。"""
    _seed_character(temp_project, "林砚", "谨慎隐忍、谋定后动")
    for seq in range(1, 12):
        _seed_chapter(temp_project, seq, f"林砚静观云海。第{seq}章。")
    _seed_chapter(temp_project, 12, "得知师门被灭，林砚盛怒之下踹门而入。")
    _install_audit_stub(monkeypatch, AuditStub(findings=[]))
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (1, 12), source="manual")
        db.flush()
    assert rep["findings"] == []


def test_overflagging_guard_zero_false_positive(temp_project, monkeypatch):
    """0 误报兜底测试：过度标记 stub（引文非子串/角色未采样/章越窗/drift 错/置信度低）
    全被确定性守卫丢弃 → 0 findings。独立于 LLM 行为的负例保证。"""
    _seed_character(temp_project, "林砚", "谨慎隐忍、谋定后动")
    _seed_chapter(temp_project, 1, "林砚立于船头，静观云海。")
    bad = [
        {"character": "林砚", "drift_type": "persona", "chapter": 1,
         "evidence": [{"quote": "这段引文根本不在正文里"}], "reason": "r", "confidence": 0.9},  # 引文非子串
        {"character": "路人甲", "drift_type": "persona", "chapter": 1,
         "evidence": [{"quote": "林砚立于船头"}], "reason": "r", "confidence": 0.9},  # 角色未采样
        {"character": "林砚", "drift_type": "persona", "chapter": 99,
         "evidence": [{"quote": "林砚立于船头"}], "reason": "r", "confidence": 0.9},  # 章越窗
        {"character": "林砚", "drift_type": "style", "chapter": 1,
         "evidence": [{"quote": "林砚立于船头"}], "reason": "r", "confidence": 0.9},  # drift_type 错
        {"character": "林砚", "drift_type": "persona", "chapter": 1,
         "evidence": [{"quote": "林砚立于船头"}], "reason": "r", "confidence": 0.4},  # 置信度过低
    ]
    _install_audit_stub(monkeypatch, AuditStub(findings=bad))
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (1, 1), source="manual")
        db.flush()
    assert rep["status"] == "completed"
    assert rep["findings"] == [], f"守卫应全丢弃 5 条坏 finding，实际 {rep['findings']}"


# ---- 4. LLM 失败非阻塞 + 报告落库/marker 推进 ----


def test_llm_failure_non_blocking(temp_project, monkeypatch):
    """LLM error → 不 raise、status=failed 报告、findings=[]、marker 推进（非阻塞+有界）。"""
    _seed_character(temp_project, "林砚", "谨慎隐忍")
    _seed_chapter(temp_project, 1, "林砚立于船头。")
    _install_audit_stub(monkeypatch, AuditStub(error="audit 判定失败"))
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (1, 1), source="manual")
        db.flush()
    assert rep["status"] == "failed"
    assert rep["error"] == "audit 判定失败"
    assert rep["findings"] == []
    assert rep["audited_up_to_chapter"] == 1, "失败也推进 marker，防每批重审毒窗口"
    rows = _report_rows(temp_project)
    assert len(rows) == 1 and rows[0].status == "failed" and rows[0].error == "audit 判定失败"


def test_report_persisted_and_marker_advances(temp_project, monkeypatch):
    """跑后行存在 + audited_up_to=window_end + 下次窗口从其后开始（跨批累计）。"""
    _seed_character(temp_project, "林砚", "谨慎隐忍")
    for seq in range(1, 11):
        _seed_chapter(temp_project, seq, f"林砚静观云海。第{seq}章。")
    _install_audit_stub(monkeypatch, AuditStub(findings=[]))
    with tenant_session(temp_project) as db:
        rep = ga.run_global_audit(db, temp_project, (1, 10), source="batch",
                                  source_batch_task_id="b0")
        db.flush()
    assert rep["status"] == "completed" and rep["audited_up_to_chapter"] == 10
    rows = _report_rows(temp_project)
    assert len(rows) == 1
    assert rows[0].trigger == "batch" and rows[0].source_batch_task_id == "b0"
    assert rows[0].summary == {"sampled": 1, "findings": 0, "chapters": 10}
    # marker 推进：写到 ch12（差 8 章 < K）→ 不审；写到 ch21（差 11 ≥ K）→ 从 11 起
    for seq in (11, 12):
        _seed_chapter(temp_project, seq, f"林砚静观云海。第{seq}章。")
    with tenant_session(temp_project) as db:
        assert ga.window_for_batch(db, temp_project, K=10) is None
    _seed_chapter(temp_project, 21, "林砚静观云海。第21章。")
    with tenant_session(temp_project) as db:
        assert ga.window_for_batch(db, temp_project, K=10) == (11, 21)


# ---- 5. 全批接线：batch_summary 暴露全局审计指标（BatchState 字段 + 节点接线）----


def test_batch_summary_surfaces_metrics(temp_project, monkeypatch):
    """全批：global_audit 节点在 reflexion 后触发 → batch_summary 含窗口/状态/检出。"""
    import aiink.providers as providers_mod
    import aiink.workflow.batch_graph as bg_mod
    from aiink.workflow.batch_graph import build_batch_graph
    from aiink.workflow.chapter_graph import build_chapter_graph

    _seed_character(temp_project, "林砚", "谨慎隐忍、谋定后动")
    # audit_interval → 1：窗口 2 章 ≥ 1 触发（默认 10 会 below_threshold，测不到接线）
    monkeypatch.setattr(bg_mod, "settings", types.SimpleNamespace(audit_interval=1))
    audit_stub = AuditStub(findings=[])
    _install_audit_stub(monkeypatch, audit_stub)
    # 单章子图（write 正文带"林砚"提及，供采样）+ batch_plan
    monkeypatch.setattr(providers_mod, "default_provider", StubProvider("金丹", "金丹"))
    monkeypatch.setattr(bg_mod, "make_chain", lambda role: _Chain(_BatchPlanStub()))

    thread = str(uuid.uuid4())
    result = build_batch_graph(build_chapter_graph()).invoke(
        {"project_id": temp_project, "batch_task_id": thread, "size": 2,
         "position": 0, "start_chapter": 1},
        config={"configurable": {"thread_id": thread}},
    )
    summary = result.get("batch_summary") or {}
    assert summary.get("status") == "done", f"批次应完成，实际 {summary}"
    ga_metric = summary.get("global_audit") or {}
    assert ga_metric.get("window_start") == 1 and ga_metric.get("window_end") == 2
    assert ga_metric.get("status") == "completed"
    assert ga_metric.get("findings") == []
    assert audit_stub.calls == 1, "每批至多 1 次审计判定（成本有界）"


class _BatchPlanStub:
    """批次级 stub：仅处理 batch_plan（reflexion 因无发现短路，不调 LLM）。"""

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False,
                 tools=None, disable_thinking=False):
        sys = messages[0].get("content", "") if messages else ""
        if "批次规划" in sys:
            return ModelResponse(content=('{"chapters":[{"goal":"推进主线A","outline_advance":"卷纲推进"},'
                                          '{"goal":"推进主线B","outline_advance":"卷纲推进"}]}'),
                                 model_id=model_id, input_tokens=50, output_tokens=80, duration_ms=30)
        raise AssertionError(f"不应调用: {sys[:30]}")


def test_below_threshold_no_report(temp_project, monkeypatch):
    """节点层：窗口 < K → below_threshold 短路、零报告行、不调 LLM。"""
    import aiink.workflow.batch_graph as bg_mod

    _seed_chapter(temp_project, 1, "林砚静观云海。")
    # 必炸桩：若 below_threshold 还调 LLM 即证明短路失效
    monkeypatch.setattr(ga, "make_chain", lambda role: (_ for _ in ()).throw(
        AssertionError("below_threshold 应短路，不调 LLM")))
    out = bg_mod.node_global_audit({"project_id": temp_project, "batch_task_id": "b0",
                                    "size": 5, "position": 0, "start_chapter": 1})
    assert out == {"global_audit": {"triggered": False, "reason": "below_threshold"}}
    assert len(_report_rows(temp_project)) == 0, "below_threshold 不应落报告行"


# ---- 6. §16 检出率/误报率指标：阳性 missed==0、阴性 collateral==0 ----


def test_metric_missed_collateral(temp_project, monkeypatch):
    """「人设漂移检出率/误报率」：阳性窗口全检出（missed==0）、阴性窗口 0 误报（collateral==0）。"""
    _seed_character(temp_project, "林砚", "谨慎隐忍、谋定后动")
    for seq in range(1, 11):
        _seed_chapter(temp_project, seq, f"林砚静观云海，谋定后动。第{seq}章。")
    _seed_chapter(temp_project, 12, "林砚一脚踹开房门，破口大骂。")

    # 阴性窗口 [1,10]：stub 空 → 0 检出 → collateral==0
    _install_audit_stub(monkeypatch, AuditStub(findings=[]))
    with tenant_session(temp_project) as db:
        rep1 = ga.run_global_audit(db, temp_project, (1, 10), source="manual")
        db.flush()
    collateral = len(rep1["findings"])
    assert collateral == 0, "阴性窗口误报"

    # 阳性窗口 [11,12]：stub 返回 ch12 人设漂移 → 检出 1（期望 1）→ missed==0
    drift = {"character": "林砚", "drift_type": "persona", "chapter": 12,
             "evidence": [{"quote": "一脚踹开房门，破口大骂"}],
             "reason": "无变故铺垫突然暴怒", "confidence": 0.9}
    _install_audit_stub(monkeypatch, AuditStub(findings=[drift]))
    with tenant_session(temp_project) as db:
        rep2 = ga.run_global_audit(db, temp_project, (11, 12), source="manual")
        db.flush()
    expected = 1
    missed = expected - len(rep2["findings"])
    assert rep2["findings"][0]["evidence"][0]["chapter"] == 12
    assert missed == 0, "阳性样例未检出"


# ---- 7. 手动端点（同步，镜像 correct_chapter_memory）----


def test_endpoint_global_audit(temp_project, monkeypatch):
    from aiink.api.routes_global_audit import trigger_global_audit

    _seed_character(temp_project, "林砚", "谨慎隐忍、谋定后动")
    _seed_chapter(temp_project, 1, "林砚静观云海。")
    _seed_chapter(temp_project, 2, "林砚谋定后动。")
    _install_audit_stub(monkeypatch, AuditStub(findings=[]))
    rep = trigger_global_audit(temp_project)
    assert rep["status"] == "completed"
    assert rep["window_start"] == 1 and rep["window_end"] == 2
    assert rep["findings"] == []
    rows = _report_rows(temp_project)
    assert len(rows) == 1 and rows[0].trigger == "manual"


def test_endpoint_no_chapters_400(temp_project, monkeypatch):
    from aiink.api.routes_global_audit import trigger_global_audit

    with pytest.raises(HTTPException) as ei:
        trigger_global_audit(temp_project)
    assert ei.value.status_code == 400


def test_endpoint_llm_failure_502(temp_project, monkeypatch):
    from aiink.api.routes_global_audit import trigger_global_audit

    _seed_character(temp_project, "林砚", "谨慎隐忍")
    _seed_chapter(temp_project, 1, "林砚静观云海。")
    _install_audit_stub(monkeypatch, AuditStub(error="audit 判定失败"))
    with pytest.raises(HTTPException) as ei:
        trigger_global_audit(temp_project)
    assert ei.value.status_code == 502
    # 502 时 failed 报告已落库（非阻塞，marker 已推进）
    rows = _report_rows(temp_project)
    assert len(rows) == 1 and rows[0].status == "failed"
