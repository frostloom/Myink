"""任务内部端点：查询 / 批次控制（pause/resume/cancel）。

- 查询：tasks + agent_runs 无 RLS（观测/队列表），new_session 普通连接可查（§14）。
- pause/resume/cancel（§6.12 暂停 vs 取消）：
  - pause    → status=paused（保留 Checkpointer 现场；真正节点级中断是阶段 3）
  - resume   → status in (failed/paused) → 置 queued + XADD 一条 batch_resume 消息
               （同 task_id → thread_id 断点续跑，§6.12）
  - cancel   → status=cancelled（尽力而为，不回滚已落库；runner 终态守卫不回写）
- resume 的 XADD 复用 worker 的队列 key 约定（queue:tasks），网关 dispatcher 不会重复
  XADD（它只重投 queue:delay / XAUTOCLAIM PENDING）。
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException

from aiink.api.schemas import TaskControlOut, TaskDetailOut
from aiink.config import settings
from aiink.db import new_session
from aiink.models import AgentRun, Task
from aiink.worker.redis_client import get_redis, stream_name

router = APIRouter(prefix="/internal/v1", tags=["tasks"])

# resume 放行的前置状态（§6.12：失败续跑 / 暂停续跑 / critical 转人工后放行）
_RESUMABLE = {"failed", "paused", "queued", "awaiting_review"}


def _task_uuid(raw: str) -> uuid.UUID:
    """非法 task_id → 400（评审 A4：pause/resume/cancel 统一不 500）。"""
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"任务 id 非法: {raw}") from exc


def _task_payload(task_id: str, with_runs: bool = True) -> dict:
    """组装任务详情（status/payload/error/progress/最近 agent_runs）。"""
    with new_session() as db:
        task = db.get(Task, _task_uuid(task_id))
        if task is None:
            raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
        data = {
            "task_id": str(task.id),
            "task_type": task.task_type,
            "status": task.status,
            "payload": task.payload,
            "error": task.error,
            "retry_count": task.retry_count,
            "trace_id": task.trace_id,
            "chapter_seq": task.chapter_seq,
            "batch_task_id": str(task.batch_task_id) if task.batch_task_id else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        }
        # 批次进度 i/N 是派生量（§阶段2 状态机统一）：已完成章 = 该章 persist 节点执行过。
        # 不能按「任意 agent_runs」计数——load_state 也会写 run，章刚启动就被计为完成（评审 A7）。
        if task.task_type == "batch_generate" and task.payload:
            size = int(task.payload.get("size", 0))
            runs = db.query(AgentRun).filter(
                AgentRun.task_id.like(f"{task_id}:ch%"),
                AgentRun.node == "persist",
            ).all()
            done_chapters = len({r.task_id for r in runs})
            data["progress"] = {"current": done_chapters, "total": size}
        if with_runs:
            runs = (
                db.query(AgentRun)
                .filter(AgentRun.task_id.like(f"{task_id}%"))
                .order_by(AgentRun.id)
                .limit(200)
                .all()
            )
            data["runs"] = [
                {
                    "node": r.node,
                    "model_id": r.model_id,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "cache_hit": r.cache_hit,
                    "duration_ms": r.duration_ms,
                    "cost_est": r.cost_est,
                    "retry_count": r.retry_count,
                    "degraded": r.degraded,
                    "error": r.error,
                    "detail": r.detail,
                }
                for r in runs
            ]
        return data


@router.get("/tasks/{task_id}", response_model=TaskDetailOut)
def get_task(task_id: str) -> dict:
    return _task_payload(task_id)


@router.post("/tasks/{task_id}/pause", response_model=TaskControlOut)
def pause_task(task_id: str) -> dict:
    with new_session() as db:
        task = db.get(Task, _task_uuid(task_id))
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status in ("done", "failed", "cancelled"):
            raise HTTPException(status_code=409, detail=f"任务已终态，不可暂停: {task.status}")
        task.status = "paused"
        db.commit()
    return {"task_id": task_id, "status": "paused"}


@router.post("/tasks/{task_id}/resume", response_model=TaskControlOut)
def resume_task(task_id: str) -> dict:
    with new_session() as db:
        task = db.get(Task, _task_uuid(task_id))
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status not in _RESUMABLE:
            raise HTTPException(status_code=409, detail=f"当前状态不可续跑: {task.status}")
        task.status = "queued"
        task.error = None
        payload = dict(task.payload)
        db.commit()
    # XADD 续跑消息（同 task_id → thread_id 断点续跑，§6.12）。
    # 按任务类型分流：批次 → batch_resume（batch 图整批续跑）；单章 → chapter_resume
    # （chapter 图续跑该章，critical 转人工后 resume 走此路径重跑放行）。
    resume_type = "batch_resume" if task.task_type == "batch_generate" else "chapter_resume"
    body = {
        "task_id": task_id,
        "task_type": resume_type,
        "project_id": str(task.project_id),
        "user_id": "",  # 阶段 3 归属断言补齐
        "payload": {**payload, "position": 0},
        "trace_id": task.trace_id or task_id,
        "request_id": task_id,
        "retry_count": 0,
        "created_at": "",
    }
    get_redis().xadd(stream_name(), {"body": json.dumps(body)})
    return {"task_id": task_id, "status": "queued", "message": "已投递续跑消息"}


@router.post("/tasks/{task_id}/cancel", response_model=TaskControlOut)
def cancel_task(task_id: str) -> dict:
    with new_session() as db:
        task = db.get(Task, _task_uuid(task_id))
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status in ("done", "cancelled"):
            raise HTTPException(status_code=409, detail=f"任务已终态: {task.status}")
        task.status = "cancelled"
        db.commit()
    # 尽力而为：worker 启动前幂等检查跳过 / runner 终态守卫不回写（§6.12）
    return {"task_id": task_id, "status": "cancelled"}
