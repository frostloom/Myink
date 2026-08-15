"""项目任务历史列表测试（GET /projects/{pid}/tasks，阶段 4 任务视图）。

范围：
- 形状：task_id/task_type/status/chapter_seq/batch_size/batch_current/error/created_at；
- 降序：created_at 新的在前（显式设 created_at 断言排序）；
- 批次进度派生：payload.size → batch_size，该批 persist 节点去重章数 → batch_current；
- 空项目 → []（不 500）；越权矩阵（伪造他人 403 / 缺失身份 403 / 项目不存在 404 / id 非法 400）。

模式：tasks 无 RLS 观测表，new_session 直插；身份头仿 test_book_setup `_h(uid)`。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import delete as sa_delete

from aiink.api.main import app
from aiink.db import new_session
from aiink.models import AgentRun, Task, User

client = TestClient(app)


def _demo_user_id() -> uuid.UUID:
    with new_session() as db:
        u = db.query(User).filter(User.username == "demo").first()
        assert u is not None, "请先运行 `aiink init`（demo 用户未建）"
        return u.id


def _h(uid: str | uuid.UUID | None) -> dict:
    return {"X-AiInk-User": str(uid)} if uid is not None else {}


def _add_task(pid, *, task_type="chapter_generate", status="done", chapter_seq=None,
              payload=None, created_at=None) -> str:
    """插一条任务（观测表无 RLS，new_session 直写），返回 task_id。"""
    with new_session() as db:
        t = Task(project_id=uuid.UUID(pid), task_type=task_type, status=status,
                 payload=payload or {}, chapter_seq=chapter_seq)
        if created_at is not None:
            t.created_at = created_at
        db.add(t)
        db.commit()
        return str(t.id)


def _cleanup(tids: list[str], pid: str) -> None:
    """删任务 + 关联 agent_runs（无 FK 级联，手动清）。"""
    with new_session() as db:
        for tid in tids:
            db.execute(sa_delete(AgentRun).where(AgentRun.task_id.like(f"{tid}%")))
        db.execute(sa_delete(Task).where(Task.project_id == uuid.UUID(pid)))
        db.commit()


def test_list_tasks_shape_and_desc_order(temp_project):
    now = datetime.now(timezone.utc)
    tids = [
        _add_task(temp_project, task_type="chapter_generate", status="done",
                  chapter_seq=1, created_at=now),
        _add_task(temp_project, task_type="chapter_generate", status="failed",
                  chapter_seq=2, created_at=now - timedelta(minutes=5)),
    ]
    try:
        resp = client.get(f"/internal/v1/projects/{temp_project}/tasks", headers=_h(_demo_user_id()))
        assert resp.status_code == 200
        items = resp.json()
        assert [i["task_id"] for i in items] == [tids[0], tids[1]], "created_at 新的在前"
        first = items[0]
        assert first["task_type"] == "chapter_generate"
        assert first["status"] == "done"
        assert first["chapter_seq"] == 1
        assert first["batch_size"] is None and first["batch_current"] is None, "单章无批次进度"
        assert first["error"] is None and first["created_at"] is not None
        assert set(first) == {"task_id", "task_type", "status", "chapter_seq",
                              "batch_size", "batch_current", "error", "created_at"}
    finally:
        _cleanup(tids, temp_project)


def test_list_tasks_empty_project_returns_empty(temp_project):
    resp = client.get(f"/internal/v1/projects/{temp_project}/tasks", headers=_h(_demo_user_id()))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_tasks_batch_progress_derived(temp_project):
    """批次进度 = payload.size 与 persist 节点去重章数（retry 同章不重复计数）。"""
    tid = _add_task(temp_project, task_type="batch_generate", status="running",
                    payload={"size": 3})
    with new_session() as db:
        pid = uuid.UUID(temp_project)
        # ch1 persist 一次、ch2 persist 两次（重试）→ 去重 current=2
        for ch, node in [("ch1", "persist"), ("ch2", "persist"), ("ch2", "persist"), ("ch2", "recall")]:
            db.add(AgentRun(project_id=pid, task_id=f"{tid}:{ch}", node=node))
        db.commit()
    try:
        resp = client.get(f"/internal/v1/projects/{temp_project}/tasks", headers=_h(_demo_user_id()))
        item = next(i for i in resp.json() if i["task_id"] == tid)
        assert item["batch_size"] == 3
        assert item["batch_current"] == 2, "persist 去重章数，非任意 run 计数"
    finally:
        _cleanup([tid], temp_project)


def test_list_tasks_ownership_matrix(temp_project):
    """越权矩阵：缺失身份 403 / 伪造他人 403（§14.1 ③ fail closed）。"""
    url = f"/internal/v1/projects/{temp_project}/tasks"
    assert client.get(url).status_code == 403
    assert client.get(url, headers=_h("00000000-0000-0000-0000-000000000000")).status_code == 403


def test_list_tasks_project_missing_404():
    pid = uuid.uuid4()
    resp = client.get(f"/internal/v1/projects/{pid}/tasks", headers=_h(_demo_user_id()))
    assert resp.status_code == 404


def test_list_tasks_invalid_project_id_400():
    resp = client.get("/internal/v1/projects/not-a-uuid/tasks", headers=_h(_demo_user_id()))
    assert resp.status_code == 400
