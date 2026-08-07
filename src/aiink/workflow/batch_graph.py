"""批次主图（spec/state-flow.md §1 外层循环 + plan.md §6.11 自动写作批次）。

batch_plan（Planner 一次产出 N 章推进蓝图，N 是规划单元不是重复次数）
→ 单章子图 ×N（每章后状态桥：上章 persist 沉淀 → 下章 recall 连续推进）
→ route_after_chapter：
   - 本章 audit 判 replan(batch) → replan_batch（回 batch_plan 重规划剩余章，§6.11）
   - critical 未解决 → batch_paused（暂停批次等人工，§6.11 已确认）
   - 单章失败（重试+降级后） → 抛 BatchChapterError 中断批次（不走到 END，见下方续跑说明）
   - 还有下章 → next_chapter（状态桥 → 再跑子图）
   - 批次数到 N → batch_end（批次汇总）

批次级共享上下文（§6.11 共享池）：recall 稳定部分（hard_facts）批次内首章组装、
桥回 batch state，后续章复用——省重复组装 + 章间版本一致。

续跑（§6.12 任务层）：batch 图 thread_id = batch_task_id；每章子图用派生
thread（batch_task_id:ch{seq}）。章失败抛 BatchChapterError → batch 线程
checkpoint 停在 chapter 节点（position 未推进、图未达 END），任务置 failed；
同 thread 再 invoke（resume_thread）从失败章续跑，已完成章不重跑，成功后
batch_end 将任务置 done。单章子图 thread 因失败已走完（优雅 error → END），
续跑时该章从开头重跑，批次级「不重跑已完成章」不受影响。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from langgraph.graph import END, START, StateGraph

from aiink.db import tenant_session
from aiink.providers import make_chain
from aiink.workflow import nodes, prompts
from aiink.workflow.state import BatchState, ChapterState

logger = logging.getLogger(__name__)


class BatchChapterError(Exception):
    """单章失败中断批次（spec/state-flow.md §5：从失败章续跑）。

    设计：批次图遇到章失败（优雅 error 或子图异常）**抛异常而非返回状态**——
    LangGraph 只在图未达 END 时支持同 thread 再 invoke 从断点续跑；若让批次
    优雅走到 batch_end，图已 END，续跑会从头重跑整个批次。抛异常使 batch 线程
    checkpoint 停在 chapter 节点（position 未推进），续跑从失败章继续、不重跑
    已完成章。任务状态由 runner 的 generate_batch catch 后置 failed。
    """


_BATCH_PLAN_PROMPT = """你是长篇网文创作系统的【批次规划 Agent】。为接下来 N 章做整体推进蓝图（N 是规划单元，不是重复次数——N 章要系统性推进主线/支线/伏笔/大纲，不能各自为政）。
输出严格 JSON：
{"chapters": [{"goal": "本章推进目标（哪条线/收哪些伏笔/新种钩子）", "outline_advance": "大纲推进段"}, ...]}  共 N 项"""


def _batch_plan_messages(batch: dict) -> list[dict]:
    return [
        {"role": "system", "content": _BATCH_PLAN_PROMPT},
        {"role": "user", "content": f"起点章 {batch['start_chapter']}，N={batch['size']}。请输出 {batch['size']} 章推进蓝图（严格 JSON）。"},
    ]


def node_batch_plan(state: BatchState) -> BatchState:
    pid = state["project_id"]
    with tenant_session(pid) as db:
        messages = _batch_plan_messages(state)
        resp = make_chain("planner").generate(messages, json_mode=True)
        nodes.record_run(db, project_id=pid, task_id=state.get("batch_task_id"),
                         node="batch_plan", role="Planner", resp=resp, error=resp.error)
        if resp.error:
            return {"batch_failed": True, "error": resp.error}
    try:
        data = nodes._parse_json(resp.content)
        chapters = data.get("chapters", [])
    except (json.JSONDecodeError, KeyError) as exc:
        return {"batch_failed": True, "error": f"batch_plan 输出解析失败: {exc}"}
    for i, c in enumerate(chapters):
        c["seq"] = state["start_chapter"] + i
    return {"batch_plan": {"chapters": chapters}}


def make_chapter_runner(chapter_graph):
    """返回 chapter 节点函数：构造 ChapterState → invoke 单章子图 → 结果桥回批次（状态桥）。"""

    def node_run_chapter(state: BatchState) -> BatchState:
        plan = (state.get("batch_plan") or {}).get("chapters") or []
        position = state.get("position", 0)
        if position >= len(plan):
            return {"batch_failed": True, "error": "position 越界"}
        item = plan[position]
        chapter_seq = item["seq"]
        # 每章派生 thread，与 batch 主 thread 隔离（§6.12 续跑语义）
        thread_id = f"{state['batch_task_id']}:ch{chapter_seq}"

        chapter_input: ChapterState = {
            "project_id": state["project_id"],
            "chapter_seq": chapter_seq,
            "task_id": thread_id,
            "batch_goal": item.get("goal"),
            # 批次级共享上下文（§6.11 共享池）：稳定部分（hard_facts）传后续章复用
            "shared_context": state.get("shared_context"),
        }
        try:
            result = chapter_graph.invoke(
                chapter_input, config={"configurable": {"thread_id": thread_id}}
            )
        except Exception as exc:  # 子图异常 → 抛中断，batch checkpoint 停在 chapter 节点可续跑
            logger.exception("单章 %s 失败", chapter_seq)
            raise BatchChapterError(f"单章 {chapter_seq} 失败: {exc}") from exc
        if result.get("error"):  # 子图优雅失败（error 返回非异常）→ 同样中断批次，不走到 batch_end
            logger.error("单章 %s 失败: %s", chapter_seq, result["error"])
            raise BatchChapterError(f"单章 {chapter_seq} 失败: {result['error']}")
        # 首章 recall 组装共享上下文 → 桥回批次，后续章复用（§6.11）
        shared = result.get("shared_context") or state.get("shared_context")
        return {"current": result, "position": position, "shared_context": shared}

    return node_run_chapter


def node_reset_replan_batch(state: BatchState) -> BatchState:
    """replan(batch) 回 batch_plan 前清信号：position 回退到本章（不推进），重规划剩余章。

    设计：audit 判 replan_target=batch → 批次蓝图走偏，整批剩余章重规划。重置
    replan_batch 信号 + 保留 position（batch_plan 重规划后本章重跑）；不重跑已完成章。
    """
    return {"replan_batch": False}


def route_after_chapter(state: BatchState) -> str:
    """批次路由（spec/state-flow.md §3，已确认策略）。"""
    current = state.get("current") or {}
    if state.get("batch_failed") or current.get("error"):
        return "batch_failed"
    if current.get("replan_batch"):  # 审核判 replan(batch) → 回 batch_plan 重规划剩余章（§6.11）
        return "replan_batch"
    if current.get("needs_review"):
        report = current.get("report") or {}
        if (report.get("summary") or {}).get("critical", 0) > 0:
            return "batch_paused"  # critical 暂停批次（污染后续章）
    position = state.get("position", 0)
    if position + 1 < state.get("size", 0):
        return "next_chapter"
    return "batch_done"


def node_batch_end(state: BatchState) -> BatchState:
    """批次收尾：汇总报告 + 更新任务状态（§6.8 批次成本展示）。"""
    pid = state["project_id"]
    status = "failed" if state.get("batch_failed") else "paused" if state.get("batch_paused") else "done"
    position = state.get("position", 0)
    summary = {
        "size": state.get("size"),
        "start_chapter": state.get("start_chapter"),
        "position": position,
        "completed": position + 1 if not state.get("batch_failed") else position,  # 已完成章数
        "status": status,
        "error": state.get("error"),
    }
    with tenant_session(pid) as db:
        from aiink.models import AgentRun, Task
        runs = db.query(AgentRun).filter(AgentRun.task_id == state["batch_task_id"]).all()
        summary["total_cost"] = round(sum(r.cost_est for r in runs), 6)
        summary["total_duration_ms"] = sum(r.duration_ms for r in runs)
        summary["degraded_runs"] = sum(1 for r in runs if r.degraded)
        task = db.get(Task, uuid.UUID(state["batch_task_id"]))
        if task:
            task.status = status
    logger.info("批次汇总: %s", summary)
    return {"batch_summary": summary}


def build_batch_graph(chapter_graph, checkpointer=None):
    node_run_chapter = make_chapter_runner(chapter_graph)

    g = StateGraph(BatchState)
    g.add_node("batch_plan", node_batch_plan)
    g.add_node("chapter", node_run_chapter)
    g.add_node("bridge", lambda s: {"position": (s.get("position") or 0) + 1})
    g.add_node("reset_replan_batch", node_reset_replan_batch)
    g.add_node("batch_end", node_batch_end)

    g.add_edge(START, "batch_plan")
    g.add_conditional_edges(
        "batch_plan",
        lambda s: "run" if not s.get("batch_failed") else "fail",
        {"run": "chapter", "fail": "batch_end"},
    )
    g.add_conditional_edges(
        "chapter", route_after_chapter,
        {"next_chapter": "bridge", "batch_paused": "batch_end",
         "batch_failed": "batch_end", "batch_done": "batch_end",
         "replan_batch": "reset_replan_batch"},
    )
    g.add_edge("bridge", "chapter")
    # replan(batch) → 回 batch_plan 重规划剩余章（position 保留本章，不推进）
    g.add_edge("reset_replan_batch", "batch_plan")
    g.add_edge("batch_end", END)
    return g.compile(checkpointer=checkpointer)
