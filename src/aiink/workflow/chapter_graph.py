"""单章子图（spec/state-flow.md §1 内层循环）。

load_state → recall → plan_chapter → write → extract → validate → audit
  → route_after_audit（混合路由，§6.11 已确认：规则层优先，LLM 兜语义）：
     ① L1 critical / L2 major（规则层）→ rev < 预算 revise / 预算用尽 persist(needs_review)
     ② 预算用尽 → persist(needs_review)
     ③ 采纳 AuditVerdict：pass → persist / rewrite → revise / replan → 回 plan_chapter
     或 replan_batch → 结束单章子图，批次层读 replan_batch 信号回 batch_plan
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from aiink.config import settings
from aiink.workflow import nodes
from aiink.workflow.state import ChapterState


def node_reset_replan(state: ChapterState) -> ChapterState:
    """replan 循环入口：清瞬态（旧 draft/candidates/report/verdict），计 replan_count。

    设计：audit 判 replan → 重新规划本章（plan_chapter）→ 重写 → 重新 extract/validate/audit。
    不清瞬态会让旧草稿/旧 finding 污染新一轮（§6.12 同类问题：残留状态短路）。
    """
    return {
        "draft": None, "candidates": [], "report": None, "unresolved": [],
        "audit_verdict": None, "replan_batch": False,
        "revision_count": 0, "revise_responses": [],
        "replan_count": state.get("replan_count", 0) + 1,
    }


def route_after_audit(state: ChapterState) -> str:
    """混合路由纯函数（spec/state-flow.md §3，2026-08-07 确认）。

    规则层（①L1 critical ②L2 major ③预算）优先——LLM 不能绕过硬约束、不能无限重写；
    LLM 语义层（④采纳 AuditVerdict）只在规则放行时生效。
    """
    if state.get("error"):
        return "fail"
    report = state.get("report") or {}
    l1_critical = (report.get("summary") or {}).get("critical", 0) or 0
    l2_major = (report.get("summary") or {}).get("l2_major", 0) or 0
    budget_exhausted = (
        state.get("revision_count", 0) >= settings.max_revisions
        or state.get("replan_count", 0) >= settings.max_replans
    )
    if l1_critical or l2_major or budget_exhausted:
        # 规则层：L1 critical / L2 major（正文-台账语义矛盾）或预算用尽 → 还能修则修，
        # 否则转人工（persist 按 critical/l2_major 分流进待确认池）
        if (l1_critical or l2_major) and not budget_exhausted:
            return "revise"
        return "needs_review"
    verdict = (state.get("audit_verdict") or {}).get("verdict")
    if verdict == "rewrite":
        return "revise"
    if verdict == "replan":
        return "replan_chapter" if (state.get("audit_verdict") or {}).get("replan_target") == "chapter" \
            else "replan_batch"
    return "persist"  # pass（或缺失 verdict 兜底为放行）


def build_chapter_graph(checkpointer=None):
    g = StateGraph(ChapterState)
    g.add_node("load_state", nodes.node_load_state)
    g.add_node("recall", nodes.node_recall)
    g.add_node("plan_chapter", nodes.node_plan_chapter)
    g.add_node("write", nodes.node_write)
    g.add_node("extract", nodes.node_extract)
    g.add_node("validate", nodes.node_validate)
    g.add_node("audit", nodes.node_audit)
    g.add_node("revise", nodes.node_revise)
    g.add_node("persist", nodes.node_persist)
    g.add_node("reset_replan", node_reset_replan)

    g.add_edge(START, "load_state")
    g.add_edge("load_state", "recall")
    g.add_edge("recall", "plan_chapter")
    g.add_edge("plan_chapter", "write")
    g.add_edge("write", "extract")
    g.add_edge("extract", "validate")
    g.add_edge("validate", "audit")
    g.add_conditional_edges(
        "audit", route_after_audit,
        {
            "persist": "persist",
            "revise": "revise",
            "replan_chapter": "reset_replan",
            "replan_batch": END,   # 单章子图结束，批次层读 replan_batch 信号
            "needs_review": "persist",  # persist 按 critical 决定 awaiting_review/落库（spec §3）
            "fail": END,
        },
    )
    g.add_edge("reset_replan", "plan_chapter")
    g.add_edge("revise", "audit")
    g.add_edge("persist", END)
    return g.compile(checkpointer=checkpointer)
