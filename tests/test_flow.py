"""端到端流程测试（mock LLM，不依赖真实 DeepSeek key）。

验证（conflict-samples.md 样例 1/3 的代码级落地）：
- 单章子图全链路：load→recall→plan→write→extract→validate→persist/needs_review；
- L1 校验能检出战力越界（林砚 realm_cap=金丹，extract 出元婴 → critical → 转人工）；
- 正常流：候选不越界 → persist 自动放行落库；
- 批次图：batch_plan → 单章 ×N → batch_end（汇总成本/耗时）；
- agent_runs 每节点记录（§6.8）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from aiink.db import new_session, tenant_session
from aiink.models import AgentRun, Chapter, Fact, Task
from aiink.providers.base import ModelProvider, ModelResponse
from aiink.workflow.batch_graph import build_batch_graph
from aiink.workflow.chapter_graph import build_chapter_graph
from aiink.workflow.runner import generate_batch, generate_chapter, get_graphs, new_task, resume_thread


class StubProvider(ModelProvider):
    """按 role/节点返回预置 JSON 的假 provider。"""

    def __init__(self, realm_from: str, realm_to: str):
        self.realm_from = realm_from
        self.realm_to = realm_to

    def name(self) -> str:
        return "stub"

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False):
        user_content = "\n".join(m.get("content", "") for m in messages)
        node = self._infer_node(messages)
        if node == "plan":
            content = (
                '{"goals":["推进主线"],"scenes":[],"characters":[],'
                '"hooks_to_plant":[],"hooks_to_resolve":[],'
                '"expected_events":["林砚在黑市查探玉佩真相"],"hard_constraints":[]}'
            )
        elif node == "audit":
            # 审核中枢默认 pass（正常流自动放行）；异常分支由子类覆写
            content = (
                '{"verdict":"pass","findings":[],"reasons":["章节符合计划"],'
                '"confidence":0.9}'
            )
        elif node == "write":
            content = '{"content":"林砚在黑市隐秘查探，玉佩气息若隐若现。夜色沉沉。"}'
        elif node == "extract":
            content = (
                '{"candidates":['
                '{"kind":"event","source_chapter":1,"confidence":0.9,"payload":{"summary":"林砚于黑市查探玉佩真相",'
                '"participants":["林砚"],"source_chapter":1,"confidence":0.9}},'
                f'{{"kind":"character_state","source_chapter":1,"confidence":0.9,"payload":{{"character_id":"林砚",'
                f'"field":"realm","old_value":"{self.realm_from}","new_value":"{self.realm_to}",'
                f'"source_chapter":1,"confidence":0.9}}}},'
                '{"kind":"foreshadow","source_chapter":1,"confidence":0.9,"payload":{"description":"玉佩气息异常，疑似与玉佩真相有关",'
                '"trigger":{"actor":"林砚","action":"发现","object":"玉佩"},"source_chapter":1,"confidence":0.9}}'
                ']}'
            )
        elif node == "revise":
            content = '{"content":"修订后正文","responses":[]}'
        else:
            content = "{}"
        return ModelResponse(content=content, model_id=model_id, input_tokens=100,
                             output_tokens=200, duration_ms=50)


def _infer_node(messages):
    # 用 system 唯一标记判定节点（不能用泛词如"修订"——write 注入的召回上下文
    # 可能带旧章内容里的"修订"字样，会把 write 误判成 revise，stub 就永远不触发失败）
    sys = messages[0]["content"] if messages else ""
    if "规划 Agent" in sys:
        return "plan"
    if "记忆抽取" in sys:
        return "extract"
    if "修订 Agent" in sys:
        return "revise"
    if "审核中枢" in sys:
        return "audit"
    return "write"


StubProvider._infer_node = staticmethod(_infer_node)


@pytest.fixture
def project_id():
    """取 demo project（seed 已在 init 建立）。"""
    with new_session() as db:
        row = db.execute(text("SELECT id FROM projects WHERE title='九州问天'")).first()
        assert row is not None, "请先运行 `aiink init`"
        return str(row.id)


@pytest.fixture
def stub_provider(monkeypatch):
    import aiink.providers as providers_mod

    def _install(realm_from, realm_to):
        stub = StubProvider(realm_from, realm_to)
        monkeypatch.setattr(providers_mod, "default_provider", stub)
        return stub

    return _install


class FakeEmbedder:
    """假 bge-m3：encode 返回固定 1024 维向量（不走模型加载，测试快）。"""

    def encode(self, texts):
        return [[0.0] * 1024 for _ in texts]


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    """全测试 mock 掉 bge-m3：persist 向量化/recall 语义召回都走假实现，不加载真实模型。"""
    fake = FakeEmbedder()
    monkeypatch.setattr("aiink.workflow.nodes.get_embedder", lambda: fake)
    monkeypatch.setattr("aiink.memory.recall.get_embedder", lambda: fake)
    return fake


def _reset_runs(project_id):
    with new_session() as db:
        db.execute(text("DELETE FROM agent_runs WHERE project_id=:p"), {"p": project_id})
        db.commit()


def test_chapter_flow_auto_confirm(project_id, stub_provider):
    """正常流：候选不越界 → persist 自动放行落库（章节 confirmed）。"""
    stub_provider("金丹", "金丹")  # 林砚 金丹→金丹，不越界
    _reset_runs(project_id)

    graph = build_chapter_graph()
    thread = str(uuid.uuid4())
    result = graph.invoke(
        {"project_id": project_id, "chapter_seq": 1, "task_id": thread},
        config={"configurable": {"thread_id": thread}},
    )
    assert result.get("error") is None, result.get("error")
    assert result.get("needs_review") is False
    assert result.get("persisted") is True

    with tenant_session(project_id) as db:
        ch = db.execute(text("SELECT status FROM chapters WHERE chapter_seq=1")).scalar()
        assert ch == "confirmed", "自动放行应落库且章节 confirmed"
        ev = db.execute(text("SELECT count(*) FROM events WHERE source_chapter=1")).scalar()
        assert ev >= 1, "事件候选应落库"
        fs = db.execute(text("SELECT count(*) FROM foreshadows WHERE planted_chapter=1")).scalar()
        assert fs >= 1, "extract 应产伏笔候选且落库（§7.9 伏笔链路）"
        emb = db.execute(
            text("SELECT count(*) FROM embeddings WHERE project_id=:p AND level='event'"),
            {"p": project_id},
        ).scalar()
        assert emb >= 1, "事件向量应落库（§15 最小向量召回，bge-m3）"
        runs = db.query(AgentRun).filter(AgentRun.task_id == thread).all()
        nodes = {r.node for r in runs}
        assert {"plan_chapter", "write", "extract"} <= nodes, "agent_runs 应记录每节点"
        assert all(r.cost_est >= 0 for r in runs)


def test_recall_context_has_foreshadows(project_id, stub_provider, fake_embedder):
    """伏笔链路闭环：recall 上下文应带开放伏笔 + 活跃剧情线（§7.9 plan_chapter 输入）。"""
    from aiink.memory.recall import build_context

    stub_provider("金丹", "金丹")
    # 先跑一章种下伏笔（stub extract 产 foreshadow 候选）
    graph = build_chapter_graph()
    thread = str(uuid.uuid4())
    graph.invoke({"project_id": project_id, "chapter_seq": 1, "task_id": thread},
                 config={"configurable": {"thread_id": thread}})

    with tenant_session(project_id) as db:
        ctx = build_context(db, project_id=project_id, chapter_seq=2, participants=["林砚"])
    assert any("玉佩" in f["description"] for f in ctx.open_foreshadows), (
        "recall 应带刚种下的开放伏笔，实际 %s" % ctx.open_foreshadows
    )
    assert len(ctx.plot_threads) >= 1, "recall 应带活跃剧情线（seed 有 2 条）"


def test_chapter_flow_power_violation(project_id, stub_provider):
    """样例 1：林砚 金丹→元婴，超过 realm_cap=金丹 → L1 critical → needs_review 转人工。"""
    stub_provider("金丹", "元婴")
    _reset_runs(project_id)

    graph = build_chapter_graph()
    thread = str(uuid.uuid4())
    result = graph.invoke(
        {"project_id": project_id, "chapter_seq": 2, "task_id": thread},
        config={"configurable": {"thread_id": thread}},
    )
    assert result.get("error") is None
    assert result.get("needs_review") is True, "越界应转人工确认"
    report = result.get("report") or {}
    types = {f["conflict_type"] for f in report.get("findings", [])}
    sev = {f["severity"] for f in report.get("findings", [])}
    assert "power" in types and "critical" in sev, f"应检出战力越界 critical，实际 {types}/{sev}"

    with tenant_session(project_id) as db:
        ch = db.execute(text("SELECT status FROM chapters WHERE chapter_seq=2")).scalar()
        assert ch == "awaiting_review", "critical 冲突章节应等待人工"


def test_batch_flow(project_id, stub_provider, monkeypatch):
    """批次：batch_plan（2 章）→ 单章 ×2 → batch_end 汇总。"""
    stub_provider("金丹", "金丹")

    import aiink.workflow.batch_graph as bg_mod

    # batch_plan 节点走 batch_graph.make_chain → 换批次 stub（返回 N 章蓝图）
    # 单章子图仍走 nodes.make_chain → default_provider（stub_provider 已换成单章 stub）
    batch_stub = BatchStubProvider("金丹", "金丹")
    monkeypatch.setattr(bg_mod, "make_chain", lambda role: _Chain(batch_stub))

    chapter_graph = build_chapter_graph()
    batch_graph = build_batch_graph(chapter_graph)
    thread = str(uuid.uuid4())
    result = batch_graph.invoke(
        {"project_id": project_id, "batch_task_id": thread, "size": 2,
         "position": 0, "start_chapter": 3},
        config={"configurable": {"thread_id": thread}},
    )
    summary = result.get("batch_summary") or {}
    assert summary.get("status") == "done", f"批次应完成，实际 {summary}"
    assert summary.get("completed") == 2, "应完成 2 章"


def test_batch_failure_and_resume(project_id, monkeypatch):
    """§6.12 批次失败续跑（spec/state-flow.md §5：从失败章续跑，不重跑已完成章）。

    第 2 章 write 失败 → generate_batch 抛 BatchChapterError 中断（非 END）、
    任务 failed；resume_thread 同 thread 续跑 → 失败章重试成功 → 批次 done，
    ch3（已完成）write 不重跑、ch4（失败）write 恰好重试一次。
    """
    import aiink.providers as providers_mod
    import aiink.workflow.batch_graph as bg_mod

    stub = BatchFailStub("金丹", "金丹")
    monkeypatch.setattr(providers_mod, "default_provider", stub)          # 单章节点链
    monkeypatch.setattr(bg_mod, "make_chain", lambda role: _Chain(stub))  # batch_plan 节点
    # writer 降级链打成单模型：write 失败一次即定（fallback 会掩盖失败、干扰计数语义）
    monkeypatch.setitem(providers_mod.DEFAULT_ROUTES, "writer", ["deepseek-v4-flash"])

    tid = new_task(project_id=project_id, task_type="batch_generate",
                   payload={"start": 3, "size": 2})
    result = generate_batch(project_id=project_id, size=2, start_chapter=3, batch_task_id=tid)
    assert result.get("batch_failed") is True, f"批次应中断失败，实际 {result}"
    assert "单章 4 失败" in result.get("error", ""), result
    assert stub.write_calls == 2, f"首次批次应 ch3(1)+ch4(1)=2 次 write，实际 {stub.write_calls}"
    with new_session() as db:
        assert db.get(Task, uuid.UUID(tid)).status == "failed", "批次失败任务应为 failed"

    _, batch_graph = get_graphs()
    final = resume_thread(batch_graph, tid, {
        "project_id": project_id, "batch_task_id": tid, "size": 2,
        "position": 0, "start_chapter": 3,  # position=0 故意传旧值：续跑应以 checkpoint 为准
    })
    summary = final.get("batch_summary") or {}
    assert summary.get("status") == "done", f"续跑后批次应完成，实际 {summary}"
    assert summary.get("completed") == 2
    assert stub.write_calls == 3, f"已完成章不应重跑（续跑只补 ch4 一次 write），实际 {stub.write_calls}"
    with new_session() as db:
        assert db.get(Task, uuid.UUID(tid)).status == "done", "续跑成功任务应为 done"

    with tenant_session(project_id) as db:
        w3 = db.execute(text(
            "SELECT count(*) FROM agent_runs WHERE task_id LIKE :p AND node='write'"),
            {"p": f"{tid}:ch3%"}).scalar()
        w4 = db.execute(text(
            "SELECT count(*) FROM agent_runs WHERE task_id LIKE :p AND node='write'"),
            {"p": f"{tid}:ch4%"}).scalar()
        assert w3 == 1, "已完成章 ch3 的 write 不应重跑"
        assert w4 == 2, "失败章 ch4 应恰好重试一次（1 失败 + 1 成功）"


def test_task_status_done(project_id, stub_provider):
    """runner.generate_chapter 成功后任务终态应为 done（§6.8 任务状态可观测）。"""
    stub_provider("金丹", "金丹")
    tid = new_task(project_id=project_id, task_type="chapter_generate",
                   payload={"seq": 11}, chapter_seq=11)
    r = generate_chapter(project_id=project_id, chapter_seq=11, task_id=tid)
    assert r.get("error") is None, r.get("error")
    with new_session() as db:
        assert db.get(Task, uuid.UUID(tid)).status == "done"


def test_audit_rewrite_loop(project_id, monkeypatch):
    """审核中枢驱动修订：audit 判 rewrite → revise 逐条修 → 回 audit pass → persist。

    验证 §6.5（触发源从校验报告改为审核中枢 verdict）+ 混合路由 rewrite 分支。
    """
    import aiink.providers as providers_mod

    stub = AuditRewriteStub("金丹", "金丹", rewrite_times=1)
    monkeypatch.setattr(providers_mod, "default_provider", stub)
    _reset_runs(project_id)

    graph = build_chapter_graph()
    thread = str(uuid.uuid4())
    result = graph.invoke(
        {"project_id": project_id, "chapter_seq": 1, "task_id": thread},
        config={"configurable": {"thread_id": thread}},
    )
    assert result.get("error") is None, result.get("error")
    assert stub.audit_calls == 2, f"audit 应跑 2 次（首判 rewrite + 修订后 pass），实际 {stub.audit_calls}"
    assert stub.revise_calls == 1, "rewrite 应触发 1 次 revise"
    assert result.get("persisted") is True
    assert (result.get("audit_verdict") or {}).get("verdict") == "pass"


def test_audit_replan_chapter(project_id, monkeypatch):
    """审核判 replan(chapter) → 回 plan_chapter 重规划本章 → 重写 → pass → persist。

    验证混合路由 replan 分支 + replan_count 预算。
    """
    import aiink.providers as providers_mod

    stub = AuditReplanStub("金丹", "金丹")
    monkeypatch.setattr(providers_mod, "default_provider", stub)
    _reset_runs(project_id)

    graph = build_chapter_graph()
    thread = str(uuid.uuid4())
    result = graph.invoke(
        {"project_id": project_id, "chapter_seq": 1, "task_id": thread},
        config={"configurable": {"thread_id": thread}},
    )
    assert result.get("error") is None, result.get("error")
    assert stub.audit_calls == 2, f"audit 应跑 2 次（首判 replan + 重规划后 pass），实际 {stub.audit_calls}"
    assert stub.plan_calls == 2, "replan 后 plan_chapter 应重跑一次（共 2 次）"
    assert result.get("replan_count") == 1, "replan_count 应为 1"
    assert result.get("persisted") is True


def test_batch_shared_context(project_id, monkeypatch):
    """批次级共享上下文（§6.11 共享池）：hard_facts 稳定部分批次内只组装一次。

    用 repo.get_hard_facts 调用计数验证——2 章批次只查 1 次硬约束，第 2 章复用缓存。
    """
    import aiink.providers as providers_mod
    import aiink.memory.recall as recall_mod
    import aiink.workflow.batch_graph as bg_mod

    stub = BatchStubProvider("金丹", "金丹")
    monkeypatch.setattr(providers_mod, "default_provider", stub)
    monkeypatch.setattr(bg_mod, "make_chain", lambda role: _Chain(stub))

    original = recall_mod.repo.get_hard_facts
    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(recall_mod.repo, "get_hard_facts", counting)

    chapter_graph = build_chapter_graph()
    batch_graph = build_batch_graph(chapter_graph)
    thread = str(uuid.uuid4())
    result = batch_graph.invoke(
        {"project_id": project_id, "batch_task_id": thread, "size": 2,
         "position": 0, "start_chapter": 3},
        config={"configurable": {"thread_id": thread}},
    )
    summary = result.get("batch_summary") or {}
    assert summary.get("status") == "done", f"批次应完成，实际 {summary}"
    assert summary.get("completed") == 2
    assert calls["n"] == 1, (
        f"hard_facts 批次内应只查 1 次（第 1 章组装、第 2 章复用共享池），实际 {calls['n']}"
    )


def test_audit_replan_batch(project_id, monkeypatch):
    """批次蓝图走偏：第 1 章 audit 判 replan(batch) → 批次层回 batch_plan 重规划 → 剩余章照跑。

    验证 §6.11 replan 自适应（batch 粒度）+ 混合路由的 replan_batch 批次边。
    """
    import aiink.providers as providers_mod
    import aiink.workflow.batch_graph as bg_mod

    stub = AuditReplanBatchStub("金丹", "金丹")
    monkeypatch.setattr(providers_mod, "default_provider", stub)
    monkeypatch.setattr(bg_mod, "make_chain", lambda role: _Chain(stub))
    _reset_runs(project_id)

    chapter_graph = build_chapter_graph()
    batch_graph = build_batch_graph(chapter_graph)
    thread = str(uuid.uuid4())
    result = batch_graph.invoke(
        {"project_id": project_id, "batch_task_id": thread, "size": 2,
         "position": 0, "start_chapter": 3},
        config={"configurable": {"thread_id": thread}},
    )
    summary = result.get("batch_summary") or {}
    assert summary.get("status") == "done", f"批次应完成，实际 {summary}"
    assert stub.batch_plan_calls == 2, f"batch_plan 应重规划一次（共 2 次），实际 {stub.batch_plan_calls}"
    assert stub.audit_calls >= 3, f"audit 应跑（ch3 首判 replan-batch + ch3 重跑 + ch4），实际 {stub.audit_calls}"


def test_audit_rewrite_loop_content_driven(project_id, monkeypatch):
    """审核中枢真实闭环：audit 基于**草稿内容**判 rewrite（非调用次数硬编码）→
    revise 注入 findings 执行修复 → 修订稿送回 audit 复验 pass → 落库的是修订稿。

    比 test_audit_rewrite_loop 严格：后者 stub 按次数返回（第 1 次 rewrite 第 2 次 pass），
    无法证明「真的修了、真的复验通过」；本测试路由由草稿是否含修订标记决定。
    """
    import aiink.providers as providers_mod

    stub = ContentAuditRewriteStub("金丹", "金丹")
    monkeypatch.setattr(providers_mod, "default_provider", stub)
    _reset_runs(project_id)

    graph = build_chapter_graph()
    thread = str(uuid.uuid4())
    result = graph.invoke(
        {"project_id": project_id, "chapter_seq": 1, "task_id": thread},
        config={"configurable": {"thread_id": thread}},
    )
    assert result.get("error") is None, result.get("error")
    assert stub.audit_calls == 2, f"audit 应 2 次（首判 rewrite + 修订稿复验 pass），实际 {stub.audit_calls}"
    assert stub.revise_calls == 1, "rewrite 应真实执行 1 次 revise"
    assert (result.get("audit_verdict") or {}).get("verdict") == "pass"
    assert result.get("persisted") is True
    with tenant_session(project_id) as db:
        content = db.execute(text("SELECT content FROM chapters WHERE chapter_seq=1")).scalar()
        assert "已修订" in content, "落库应为修订后草稿（revise 修复真实生效）"


def test_audit_replan_chapter_content_driven(project_id, monkeypatch):
    """审核中枢真实闭环 replan：audit 基于**草稿内容**判 replan（非次数硬编码）→
    reset_replan 清瞬态 → plan_chapter 重规划 → write 重写（新稿）→ 复验 pass → 落库新稿。

    比 test_audit_replan_chapter 严格：路由由草稿是否含重规划新稿标记决定，
    验证「判 replan → 真实重规划重写 → 复验通过」。
    """
    import aiink.providers as providers_mod

    stub = ContentAuditReplanStub("金丹", "金丹")
    monkeypatch.setattr(providers_mod, "default_provider", stub)
    _reset_runs(project_id)

    graph = build_chapter_graph()
    thread = str(uuid.uuid4())
    result = graph.invoke(
        {"project_id": project_id, "chapter_seq": 1, "task_id": thread},
        config={"configurable": {"thread_id": thread}},
    )
    assert result.get("error") is None, result.get("error")
    assert stub.audit_calls == 2, f"audit 应 2 次（首判 replan + 重规划后复验 pass），实际 {stub.audit_calls}"
    assert stub.plan_calls == 2, "replan 后 plan_chapter 应重规划一次（共 2 次）"
    assert stub.write_calls == 2, "重规划后应真实重写一次（共 2 次）"
    assert result.get("replan_count") == 1
    assert (result.get("audit_verdict") or {}).get("verdict") == "pass"
    with tenant_session(project_id) as db:
        content = db.execute(text("SELECT content FROM chapters WHERE chapter_seq=1")).scalar()
        assert "重规划新稿" in content, "落库应为重规划后新稿"


class BatchStubProvider(StubProvider):
    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False):
        messages = list(messages)
        if "批次规划" in (messages[0].get("content", "") if messages else ""):
            content = '{"chapters":[{"goal":"推进主线A","outline_advance":"卷纲推进"},{"goal":"推进主线B","outline_advance":"卷纲推进"}]}'
            return ModelResponse(content=content, model_id=model_id, input_tokens=50, output_tokens=80, duration_ms=30)
        return super().generate(messages, model_id=model_id, max_tokens=max_tokens,
                                temperature=temperature, json_mode=json_mode)
        user_content = "\n".join(m.get("content", "") for m in messages)
        if "批次规划" in messages[0].get("content", ""):
            content = '{"chapters":[{"goal":"推进主线A","outline_advance":"卷纲推进"},{"goal":"推进主线B","outline_advance":"卷纲推进"}]}'
            return ModelResponse(content=content, model_id=model_id, input_tokens=50, output_tokens=80, duration_ms=30)
        return super().generate(messages, model_id=model_id, max_tokens=max_tokens,
                                temperature=temperature, json_mode=json_mode)


class _Chain:
    def __init__(self, provider):
        self.provider = provider

    def generate(self, messages, *, json_mode=False, max_tokens=None, temperature=None):
        return self.provider.generate(messages, model_id="stub", max_tokens=max_tokens,
                                      temperature=temperature, json_mode=json_mode)


class BatchFailStub(StubProvider):
    """批次 write 第 N 次调用返回 error（测 §6.12 批次失败续跑）。

    fail_on_write=2：批次第 1 章 write 成功、第 2 章 write 失败 → 批次中断。
    failures 只计一次——续跑（同 thread 再 invoke）时该章 write 重跑即成功，
    用来断言「已完成章不重跑、失败章重试」。
    """

    def __init__(self, realm_from, realm_to, fail_on_write=2):
        super().__init__(realm_from, realm_to)
        self.fail_on_write = fail_on_write
        self.write_calls = 0
        self.failures = 0

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False):
        messages = list(messages)
        if "批次规划" in (messages[0].get("content", "") if messages else ""):
            content = '{"chapters":[{"goal":"推进主线A","outline_advance":"卷纲推进"},{"goal":"推进主线B","outline_advance":"卷纲推进"}]}'
            return ModelResponse(content=content, model_id=model_id, input_tokens=50,
                                 output_tokens=80, duration_ms=30)
        if self._infer_node(messages) == "write":
            self.write_calls += 1
            if self.failures == 0 and self.write_calls == self.fail_on_write:
                self.failures += 1
                return ModelResponse(content="", model_id=model_id, error="write 失败",
                                     input_tokens=100, output_tokens=0, duration_ms=50)
        return super().generate(messages, model_id=model_id, max_tokens=max_tokens,
                                temperature=temperature, json_mode=json_mode)


class AuditRewriteStub(StubProvider):
    """审核中枢前 N 次判 rewrite，之后 pass（测 §6.5 修订循环由 verdict 驱动）。

    audit 判 rewrite 时带 L2 finding（critical/major → unresolved），
    revise 注入逐条修 → 回 audit → 本次 pass → persist。
    """

    def __init__(self, realm_from, realm_to, rewrite_times=1):
        super().__init__(realm_from, realm_to)
        self.rewrite_times = rewrite_times
        self.audit_calls = 0
        self.revise_calls = 0

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False):
        messages = list(messages)
        node = self._infer_node(messages)
        if node == "audit":
            self.audit_calls += 1
            if self.audit_calls <= self.rewrite_times:
                content = (
                    '{"verdict":"rewrite","findings":['
                    '{"conflict_key":"a1","conflict_type":"plotline","severity":"major",'
                    '"scope":"structural","evidence":[{"chapter":1,"quote":"主线偏移"}],'
                    '"confidence":0.8,"suggestion":"拉回主线"}],'
                    '"reasons":["本章主线偏移"],"confidence":0.85}'
                )
            else:
                content = '{"verdict":"pass","findings":[],"reasons":["修订后达标"],"confidence":0.9}'
            return ModelResponse(content=content, model_id=model_id, input_tokens=60,
                                 output_tokens=80, duration_ms=30)
        if node == "revise":
            self.revise_calls += 1
        return super().generate(messages, model_id=model_id, max_tokens=max_tokens,
                                temperature=temperature, json_mode=json_mode)


class AuditReplanStub(StubProvider):
    """审核判 replan(chapter) 一次，重规划后 pass（测 §6.5 replan 回 plan_chapter）。"""

    def __init__(self, realm_from, realm_to):
        super().__init__(realm_from, realm_to)
        self.audit_calls = 0
        self.plan_calls = 0

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False):
        messages = list(messages)
        node = self._infer_node(messages)
        if node == "audit":
            self.audit_calls += 1
            if self.audit_calls == 1:
                content = (
                    '{"verdict":"replan","replan_target":"chapter","findings":[],'
                    '"reasons":["本章未按蓝图推进"],"confidence":0.8}'
                )
            else:
                content = '{"verdict":"pass","findings":[],"reasons":["重规划后达标"],"confidence":0.9}'
            return ModelResponse(content=content, model_id=model_id, input_tokens=60,
                                 output_tokens=80, duration_ms=30)
        if node == "plan":
            self.plan_calls += 1
        return super().generate(messages, model_id=model_id, max_tokens=max_tokens,
                                temperature=temperature, json_mode=json_mode)


class AuditReplanBatchStub(StubProvider):
    """审核判 replan(batch)（测 §6.11：批次蓝图走偏 → 回 batch_plan 重规划剩余章）。"""

    def __init__(self, realm_from, realm_to):
        super().__init__(realm_from, realm_to)
        self.audit_calls = 0
        self.batch_plan_calls = 0
        self.bridge_calls = 0

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False):
        messages = list(messages)
        if "批次规划" in (messages[0].get("content", "") if messages else ""):
            self.batch_plan_calls += 1
            content = '{"chapters":[{"goal":"推进主线A","outline_advance":"卷纲推进"},{"goal":"推进主线B","outline_advance":"卷纲推进"}]}'
            return ModelResponse(content=content, model_id=model_id, input_tokens=50,
                                 output_tokens=80, duration_ms=30)
        if self._infer_node(messages) == "audit":
            self.audit_calls += 1
            if self.audit_calls == 1:
                # 第 1 章 audit 判 replan(batch)：蓝图整体走偏，需重规划剩余章
                content = (
                    '{"verdict":"replan","replan_target":"batch","findings":[],'
                    '"reasons":["批次蓝图整体偏离主线"],"confidence":0.8}'
                )
            else:
                content = '{"verdict":"pass","findings":[],"reasons":["重规划后达标"],"confidence":0.9}'
            return ModelResponse(content=content, model_id=model_id, input_tokens=60,
                                 output_tokens=80, duration_ms=30)
        return super().generate(messages, model_id=model_id, max_tokens=max_tokens,
                                temperature=temperature, json_mode=json_mode)


class ContentAuditRewriteStub(StubProvider):
    """内容驱动审核（rewrite 闭环）：audit 看草稿是否含「已修订」标记，含则 pass，不含则 rewrite。

    路由由**草稿内容**决定（而非调用次数硬编码）——证明 audit 判 rewrite 后，
    revise 真的执行修复、修订稿真的送回 audit 复验、pass 才落库。
    """

    def __init__(self, realm_from, realm_to):
        super().__init__(realm_from, realm_to)
        self.audit_calls = 0
        self.revise_calls = 0

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False):
        messages = list(messages)
        node = self._infer_node(messages)
        if node == "audit":
            self.audit_calls += 1
            text = "\n".join(m.get("content", "") for m in messages)
            if "已修订" in text:
                content = '{"verdict":"pass","findings":[],"reasons":["修订后达标"],"confidence":0.9}'
            else:
                content = (
                    '{"verdict":"rewrite","findings":['
                    '{"conflict_key":"a1","conflict_type":"plotline","severity":"major",'
                    '"scope":"structural","evidence":[{"chapter":1,"quote":"主线偏移"}],'
                    '"confidence":0.8,"suggestion":"拉回主线"}],'
                    '"reasons":["本章主线偏移"],"confidence":0.85}'
                )
            return ModelResponse(content=content, model_id=model_id, input_tokens=60,
                                 output_tokens=80, duration_ms=30)
        if node == "revise":
            self.revise_calls += 1
            # 修订稿打上「已修订」标记——audit 据此复验放行
            content = ('{"content":"林砚在黑市隐秘查探，玉佩气息若隐若现。夜色沉沉。已修订",'
                       '"responses":[{"conflict_key":"a1","status":"fixed"}]}')
            return ModelResponse(content=content, model_id=model_id, input_tokens=60,
                                 output_tokens=80, duration_ms=30)
        return super().generate(messages, model_id=model_id, max_tokens=max_tokens,
                                temperature=temperature, json_mode=json_mode)


class ContentAuditReplanStub(StubProvider):
    """内容驱动审核（replan 闭环）：audit 看草稿是否含「重规划新稿」标记，含则 pass，不含则 replan。

    首轮 write 产旧稿 → audit 判 replan(chapter) → reset_replan 清瞬态 →
    plan_chapter 重规划 → write 重写（新稿）→ audit 复验 pass。plan/write 调用计数
    证明重规划链路真实执行，落库断言证明放行的是新稿。
    """

    def __init__(self, realm_from, realm_to):
        super().__init__(realm_from, realm_to)
        self.audit_calls = 0
        self.plan_calls = 0
        self.write_calls = 0

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False):
        messages = list(messages)
        node = self._infer_node(messages)
        if node == "audit":
            self.audit_calls += 1
            text = "\n".join(m.get("content", "") for m in messages)
            if "重规划新稿" in text:
                content = '{"verdict":"pass","findings":[],"reasons":["重规划后达标"],"confidence":0.9}'
            else:
                content = (
                    '{"verdict":"replan","replan_target":"chapter","findings":[],'
                    '"reasons":["本章未按蓝图推进"],"confidence":0.8}'
                )
            return ModelResponse(content=content, model_id=model_id, input_tokens=60,
                                 output_tokens=80, duration_ms=30)
        if node == "plan":
            self.plan_calls += 1
        if node == "write":
            self.write_calls += 1
            if self.write_calls == 1:
                # 首轮：旧稿（不含标记）→ 触发 replan
                content = '{"content":"林砚在黑市隐秘查探，玉佩气息若隐若现。夜色沉沉。"}'
            else:
                # 重规划后：新稿带标记 → audit 复验 pass
                content = '{"content":"林砚在黑市隐秘查探，玉佩气息若隐若现。夜色沉沉。重规划新稿"}'
            return ModelResponse(content=content, model_id=model_id, input_tokens=60,
                                 output_tokens=80, duration_ms=30)
        return super().generate(messages, model_id=model_id, max_tokens=max_tokens,
                                temperature=temperature, json_mode=json_mode)
