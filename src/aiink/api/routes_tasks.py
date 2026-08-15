"""任务内部端点：查询（单条 + 项目历史列表）/ 批次控制（pause/resume/cancel）。

- 查询：tasks + agent_runs 无 RLS（观测/队列表），new_session 普通连接可查（§14）。
- `GET /projects/{pid}/tasks`：项目任务历史（最近 50 条倒序，轻量摘要不含 runs）——前端
  切书后展示过往任务，点开任一条再走 `GET /tasks/{id}` 拿完整节点流转（agent_runs）。
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

from fastapi import APIRouter, Depends, HTTPException

from aiink.api.auth import require_owner
from aiink.api.schemas import TaskControlOut, TaskDetailOut, TaskSummaryOut
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


def _batch_done_chapters(db, task_id: str) -> int:
    """批次已完成章数（§阶段2 派生口径）：该批 persist 节点去重章数——不能按任意
    agent_runs 计数（load_state 也写 run，章刚启动就被计为完成，评审 A7）。"""
    runs = db.query(AgentRun).filter(
        AgentRun.task_id.like(f"{task_id}:ch%"),
        AgentRun.node == "persist",
    ).all()
    return len({r.task_id for r in runs})


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
            data["progress"] = {"current": _batch_done_chapters(db, task_id), "total": size}
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
            # 总花费（§6.8 成本透明，前端「每章总花费」）：单章 = 该章任务全部节点；
            # 批次 = 全批（task_id 前缀与 runs 同口径）。runs 已加载，求和免额外查询。
            data["cost_total"] = round(sum(r.cost_est for r in runs), 6)
        return data


@router.get("/tasks/{task_id}", response_model=TaskDetailOut)
def get_task(task_id: str) -> dict:
    return _task_payload(task_id)


@router.get("/projects/{project_id}/tasks",
            dependencies=[Depends(require_owner)], response_model=list[TaskSummaryOut])
def list_project_tasks(project_id: str) -> list[dict]:
    """项目任务历史（最近 50 条，倒序）：前端切书后展示过往任务，点开再拉详情拿流转。

    轻量摘要不含 runs（重量留给 GET /tasks/{id}）；批次进度派生（persist 去重章数）。
    require_owner 归属断言由依赖挂载（§14.1 ③）；tasks 无 RLS 观测表，new_session 可查。
    """
    pid = _task_uuid(project_id)
    with new_session() as db:
        tasks = (
            db.query(Task)
            .filter(Task.project_id == pid)
            .order_by(Task.created_at.desc())
            .limit(50)
            .all()
        )
        # 每任务总花费（§6.8 成本透明）：agent_runs.cost_est 按 task_id 前缀聚合——
        # 单章任务 task_id=裸 uuid；批次任务每章 run= {batch_id}:ch{seq} + 裸 batch_id
        # （batch_plan/reflexion）。统一按「:」前段分桶，等价 _task_payload 的 LIKE 口径。
        # 一次查询取全部（项目级量级小，观测表无 RLS），避免逐任务子查询。
        runs = db.query(AgentRun.task_id, AgentRun.cost_est).filter(AgentRun.project_id == pid).all()
        cost_by_task: dict[str, float] = {}
        for tid, cost in runs:
            if not tid:
                continue
            prefix = tid.split(":")[0]
            cost_by_task[prefix] = cost_by_task.get(prefix, 0.0) + (cost or 0.0)
        result = []
        for t in tasks:
            item: dict = {
                "task_id": str(t.id),
                "task_type": t.task_type,
                "status": t.status,
                "chapter_seq": t.chapter_seq,
                "batch_size": None,
                "batch_current": None,
                "cost_total": round(cost_by_task.get(str(t.id), 0.0), 6),
                "error": t.error,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            if t.task_type == "batch_generate" and t.payload:
                item["batch_size"] = int(t.payload.get("size", 0))
                item["batch_current"] = _batch_done_chapters(db, str(t.id))
            result.append(item)
        return result


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
