"""Authenticated cross-user reporting, plus admin-only invitation management.

Reporting uses ADMIN_DATABASE_URL with a read-only transaction. Production must
provide that connection; a dedicated BYPASSRLS reporting role with SELECT-only
grants should replace the migration role in a future deployment hardening step.
Audit writes always use the ordinary application connection, separately.
Writes (invitation create/revoke) never reuse the reporting session: they take
their own `new_session()` so the read-only guarantee stays intact.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import Integer, String, and_, case, cast, column, func, or_, select, text, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from myink import invitations as invitations_mod
from myink.admin_observability import capture
from myink.api.admin_schemas import (
    AdminAccessLogOut, AdminChapter, AdminChapterDetail, AdminContext,
    AdminGenerationTask, AdminInvitation, AdminInvitationCreated, AdminOverview, AdminPage,
    AdminProject, AdminRun, AdminRunDetail, AdminSnapshot, AdminSnapshotFinding, AdminTask,
    AdminTaskChapter, AdminTaskDetail, AdminUser,
)
from myink.api.auth import _AuthenticatedUser, require_admin
from myink.api.schemas import OkOut
from myink.db import get_admin_engine, new_session
from myink.models import (
    AdminAccessLog, AgentRun, Chapter, Character, Event, Fact, Foreshadow, GenerationSnapshot,
    Invitation, PlotThread, Project, ProjectSettings, Task, User, VolumeOutline,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
Search = Annotated[str | None, Query(max_length=128)]
_METRIC_FIELDS = ("input_tokens", "output_tokens", "cost_est", "duration_ms")
# 路径参数里没有租户语义的自增主键（其余都是 uuid）。
_INT_PATH_PARAMS = frozenset({"run_id", "snapshot_id"})


@contextmanager
def admin_read_session():
    """Narrow reporting session; never use from owner routes or workers."""
    with Session(get_admin_engine(), autoflush=False, expire_on_commit=False) as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        try:
            yield db
        finally:
            db.rollback()


def write_access_log(actor_id: uuid.UUID, action: str, target: str) -> None:
    with new_session() as db:
        db.add(AdminAccessLog(actor_id=actor_id, action=action, target=target))
        db.commit()


def _safe_target(request: Request) -> str:
    # Only canonical identifiers, never query text/headers supplied by a caller.
    ids = []
    for key, raw in request.path_params.items():
        try:
            value = str(int(raw)) if key in _INT_PATH_PARAMS else str(uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            value = "invalid"
        ids.append(f"{key}={value}")
    for key in ("user_id", "project_id"):
        raw = request.query_params.get(key)
        if raw:
            try:
                ids.append(f"{key}={uuid.UUID(raw)}")
            except ValueError:
                pass
    return ",".join(ids) or "collection"


def reporting_db(request: Request, actor: _AuthenticatedUser = Depends(require_admin)):
    try:
        write_access_log(actor.id, request.scope["route"].name, _safe_target(request))
    except Exception:
        raise HTTPException(503, "ADMIN_AUDIT_UNAVAILABLE") from None
    with admin_read_session() as db:
        yield db


DB = Annotated[Session, Depends(reporting_db)]


def _metric_columns(*conditions):
    def scalar(expression):
        return select(expression).where(*conditions).correlate(Project, Task, User).scalar_subquery()
    return [scalar(func.count(AgentRun.id)).label("run_count"), *[
        scalar(func.coalesce(func.sum(getattr(AgentRun, field)), 0)).label(field)
        for field in _METRIC_FIELDS
    ]]


def _task_runs(task_id, project_id):
    tid = cast(task_id, String)
    return and_(AgentRun.project_id == project_id,
                or_(AgentRun.task_id == tid, AgentRun.task_id.like(tid + ":ch%")))


def _nested_metrics(row):
    result = dict(row)
    result["metrics"] = {key: result.pop(key) for key in ("run_count", *_METRIC_FIELDS)}
    averages = {key: result.pop(key) for key in _TASK_AVERAGE_FIELDS if key in result}
    if averages:
        result["task_averages"] = {key: round(value, 6) if isinstance(value, float) else value
                                   for key, value in averages.items()}
    return result


# ---- 分析下钻：用户 → 书 → 任务 → 章 → 快照 ----------------------------------------
# 核心是两级聚合：先按任务汇总，再对任务求平均。按 run 行平均会让 12 次调用的批次任务
# 凭调用次数压过 2 次调用的单章任务，得到的就不是「单次任务的平均」。

_TASK_AVERAGE_FIELDS = ("avg_cost_per_task", "avg_duration_ms_per_task", "avg_runs_per_task")


def _snapshot_scope(task_id):
    """快照的线程前缀匹配，与 _task_runs 同口径（批次 = `{batch}:ch{seq}`）。"""
    tid = cast(task_id, String)
    return or_(GenerationSnapshot.task_id == tid,
               GenerationSnapshot.task_id.like(tid + ":ch%"))


def _chapter_count():
    """任务覆盖的章数：批次按 `{batch}:ch{seq}` 归章；book 级 run（batch_plan 用裸
    batch_id）不是章——有 :ch 线程时把这类线程扣掉，否则每批凭空多出一章；单章任务
    的 run 全挂在裸 task_id 上，自身算一章。
    """
    total = func.count(func.distinct(AgentRun.task_id))
    book_level = func.count(func.distinct(AgentRun.task_id)).filter(
        AgentRun.task_id.notlike("%:ch%"))
    has_chapter_threads = func.count().filter(AgentRun.task_id.like("%:ch%")) > 0
    return (total - case((has_chapter_threads, book_level), else_=0)).label("chapter_count")


def _per_task_totals():
    """每个任务一行（Σ成本/耗时/tokens、调用次数、覆盖章数）——两级聚合的中间层。"""
    return (select(Task.id.label("task_id"), Task.project_id.label("project_id"),
                   func.count(AgentRun.id).label("run_count"),
                   func.coalesce(func.sum(AgentRun.input_tokens), 0).label("input_tokens"),
                   func.coalesce(func.sum(AgentRun.output_tokens), 0).label("output_tokens"),
                   func.coalesce(func.sum(AgentRun.cost_est), 0.0).label("cost_est"),
                   func.coalesce(func.sum(AgentRun.duration_ms), 0).label("duration_ms"),
                   _chapter_count())
            .select_from(Task).join(AgentRun, _task_runs(Task.id, Task.project_id))
            .group_by(Task.id, Task.project_id).subquery("per_task"))


def _task_average_columns(scope):
    """per-task 两级均值列。scope(per_task) 把中间层限定到外层这一行（某个用户 / 某本书）。

    没有任务（或任务全无 run）时 SQL 的 avg 回 NULL——「没有任务」与「花费为零」要能分开。
    """
    per_task = _per_task_totals()

    def scalar(expression):
        return (select(expression).select_from(per_task).where(scope(per_task))
                .correlate(Project, User).scalar_subquery())

    return [
        scalar(func.avg(per_task.c.cost_est)).label("avg_cost_per_task"),
        scalar(func.avg(per_task.c.duration_ms)).label("avg_duration_ms_per_task"),
        scalar(func.avg(per_task.c.run_count)).label("avg_runs_per_task"),
    ]


def _page(db, stmt, limit, offset, transform=dict):
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.limit(limit).offset(offset)).mappings()
    return {"items": [transform(row) for row in rows], "total": total, "limit": limit, "offset": offset}


def _exists(db, model, identifier):
    if db.scalar(select(model.id).where(model.id == identifier)) is None:
        raise HTTPException(404, "NOT_FOUND")


def _count(model, condition):
    return select(func.count(model.id)).where(condition).correlate(Project, User).scalar_subquery()


def _word_count(condition):
    return select(func.coalesce(func.sum(func.length(Chapter.content)), 0)).where(condition).correlate(Project, User).scalar_subquery()


@router.get("/overview", response_model=AdminOverview, name="admin.overview")
def overview(db: DB):
    counts = {name: db.scalar(select(func.count(model.id))) for name, model in (
        ("user_count", User), ("project_count", Project), ("chapter_count", Chapter), ("task_count", Task))}
    metrics = db.execute(select(*_metric_columns())).mappings().one()
    return {**counts, "metrics": dict(metrics), "task_status_counts": dict(db.execute(
        select(Task.status, func.count(Task.id)).group_by(Task.status)).all())}


@router.get("/users", response_model=AdminPage[AdminUser], name="admin.users")
def users(db: DB, q: Search = None, limit: Limit = 25, offset: Offset = 0):
    owned = select(Project.id).where(Project.user_id == User.id).correlate(User)
    stmt = select(User.id, User.username, User.tier, User.role,
                  _count(Project, Project.user_id == User.id).label("project_count"),
                  _count(Chapter, Chapter.project_id.in_(owned)).label("chapter_count"),
                  _word_count(Chapter.project_id.in_(owned)).label("word_count"),
                  _count(Task, Task.project_id.in_(owned)).label("task_count"),
                  *_metric_columns(AgentRun.project_id.in_(owned)),
                  *_task_average_columns(lambda per_task: per_task.c.project_id.in_(owned))
                  ).order_by(User.created_at.desc(), User.id.desc())
    if q:
        stmt = stmt.where(or_(User.username.icontains(q, autoescape=True), cast(User.id, String) == q))
    return _page(db, stmt, limit, offset, _nested_metrics)


def _project_statement():
    """列表与详情共用同一组列，跳页后看到的数字必须与列表行一致（列不一致就会漂）。"""
    return (select(Project.id, Project.user_id, User.username, Project.title, Project.genre,
                   Project.current_chapter, Project.target_words, Project.creation_status,
                   Project.created_at, Project.updated_at,
                   _count(Chapter, Chapter.project_id == Project.id).label("chapter_count"),
                   _word_count(Chapter.project_id == Project.id).label("word_count"),
                   _count(Task, Task.project_id == Project.id).label("task_count"),
                   *_metric_columns(AgentRun.project_id == Project.id),
                   *_task_average_columns(lambda per_task: per_task.c.project_id == Project.id)
                   ).join(User, User.id == Project.user_id))


@router.get("/projects", response_model=AdminPage[AdminProject], name="admin.projects")
def projects(db: DB, user_id: uuid.UUID | None = None, q: Search = None, limit: Limit = 25, offset: Offset = 0):
    stmt = _project_statement()
    if user_id:
        stmt = stmt.where(Project.user_id == user_id)
    if q:
        stmt = stmt.where(or_(Project.title.icontains(q, autoescape=True), cast(Project.id, String) == q))
    return _page(db, stmt.order_by(Project.created_at.desc(), Project.id.desc()), limit, offset, _nested_metrics)


@router.get("/projects/{project_id}", response_model=AdminProject, name="admin.project")
def project(project_id: uuid.UUID, db: DB):
    row = db.execute(_project_statement().where(Project.id == project_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "NOT_FOUND")
    return _nested_metrics(row)


def _chapter_columns():
    return [Chapter.id, Chapter.project_id, Chapter.chapter_seq, Chapter.title, Chapter.status,
            func.coalesce(func.length(Chapter.content), 0).label("word_count"), Chapter.created_at, Chapter.updated_at]


@router.get("/projects/{project_id}/chapters", response_model=AdminPage[AdminChapter], name="admin.chapters")
def chapters(project_id: uuid.UUID, db: DB, limit: Limit = 25, offset: Offset = 0):
    _exists(db, Project, project_id)
    return _page(db, select(*_chapter_columns()).where(Chapter.project_id == project_id)
                 .order_by(Chapter.chapter_seq, Chapter.id), limit, offset)


@router.get("/projects/{project_id}/chapters/{chapter_id}", response_model=AdminChapterDetail, name="admin.chapter")
def chapter(project_id: uuid.UUID, chapter_id: uuid.UUID, db: DB):
    row = db.execute(select(*_chapter_columns(), Chapter.content, Chapter.summary, Chapter.version)
                     .where(Chapter.project_id == project_id, Chapter.id == chapter_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "NOT_FOUND")
    return dict(row)


@router.get("/projects/{project_id}/context", response_model=AdminContext, name="admin.context")
def context(project_id: uuid.UUID, db: DB, limit: Limit = 25):
    _exists(db, Project, project_id)
    row = db.execute(select(ProjectSettings.world_rules, ProjectSettings.style_profile,
                            ProjectSettings.genre_pack, ProjectSettings.hard_constraints, ProjectSettings.version)
                     .where(ProjectSettings.project_id == project_id)).mappings().first()
    result = {"project_id": project_id, "settings": capture(dict(row) if row else None)}
    # Fixed explicit field allowlists; new schema columns never leak automatically.
    collections = (
        ("outlines", VolumeOutline, ("volume_seq", "title", "outline")),
        ("events", Event, ("summary", "participants", "source_chapter", "confidence")),
        ("facts", Fact, ("content", "category", "is_hard", "source_chapter", "confirm_status")),
        ("characters", Character, ("name", "race", "origin", "realm_cap", "personality", "base_attrs")),
        ("foreshadows", Foreshadow, ("description", "status", "planted_chapter", "resolved_chapter", "trigger")),
        ("threads", PlotThread, ("name", "kind", "status", "priority", "last_progress_chapter")),
    )
    for key, model, fields in collections:
        condition = model.project_id == project_id
        total = db.scalar(select(func.count(model.id)).where(condition))
        rows = db.execute(select(cast(model.id, String).label("id"), *[getattr(model, f) for f in fields])
                          .where(condition).order_by(model.created_at.desc(), model.id.desc()).limit(limit)).mappings()
        items = [capture(dict(item)) for item in rows]
        result[key] = {"items": items, "total": total, "limit": limit,
                       "truncated": total > limit or any(item["truncated"] for item in items)}
    return result


def _task_statement(detail=False):
    columns = [Task.id, Task.project_id, Project.user_id, User.username, Project.title.label("project_title"),
               Task.task_type, Task.status, Task.chapter_seq, Task.batch_task_id, Task.retry_count,
               Task.created_at, Task.updated_at, *_metric_columns(_task_runs(Task.id, Task.project_id))]
    if detail:
        columns += [Task.payload, Task.error]
    return select(*columns).join(Project, Project.id == Task.project_id).join(User, User.id == Project.user_id)


@router.get("/tasks", response_model=AdminPage[AdminTask], name="admin.tasks")
def tasks(db: DB, user_id: uuid.UUID | None = None, project_id: uuid.UUID | None = None,
          status: Annotated[str | None, Query(max_length=32)] = None, limit: Limit = 25, offset: Offset = 0):
    stmt = _task_statement()
    if user_id:
        stmt = stmt.where(Project.user_id == user_id)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if status:
        stmt = stmt.where(Task.status == status)
    return _page(db, stmt.order_by(Task.created_at.desc(), Task.id.desc()), limit, offset, _nested_metrics)


@router.get("/tasks/{task_id}", response_model=AdminTaskDetail, name="admin.task")
def task(task_id: uuid.UUID, db: DB):
    row = db.execute(_task_statement(True).where(Task.id == task_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "NOT_FOUND")
    result = _nested_metrics(row)
    result.update(payload=capture(result["payload"]), error=capture(result["error"]),
                  elapsed_ms=max(0, int((row["updated_at"]-row["created_at"]).total_seconds()*1000)),
                  elapsed_includes_waits=True)
    return result


def _run_statement(detail=False):
    fields = ("id", "project_id", "task_id", "node", "role", "model_id", "input_tokens", "output_tokens",
              "cost_est", "duration_ms", "cache_hit", "degraded", "retry_count", "created_at", "updated_at")
    columns = [getattr(AgentRun, f) for f in fields]
    if detail:
        columns += [AgentRun.detail, AgentRun.error]
    return select(*columns, Project.user_id, User.username, Project.title.label("project_title"))\
        .join(Project, Project.id == AgentRun.project_id).join(User, User.id == Project.user_id)


@router.get("/tasks/{task_id}/runs", response_model=AdminPage[AdminRun], name="admin.task_runs")
def task_runs(task_id: uuid.UUID, db: DB, limit: Limit = 25, offset: Offset = 0):
    pid = db.scalar(select(Task.project_id).where(Task.id == task_id))
    if pid is None:
        raise HTTPException(404, "NOT_FOUND")
    return _page(db, _run_statement().where(_task_runs(str(task_id), pid))
                 .order_by(AgentRun.id), limit, offset)


@router.get("/tasks/{task_id}/chapters", response_model=AdminPage[AdminTaskChapter],
            name="admin.task_chapters")
def task_chapters(task_id: uuid.UUID, db: DB, limit: Limit = 25, offset: Offset = 0):
    """任务内按章的分解：每章成本/耗时/tokens + 跑过的节点 + 快照指针。

    章节清单由 agent_runs 驱动；快照按章号挂上去（两个写点出自同一个漏斗，有 run 才会有
    快照，反之不会）。批次任务里 book 级 run（batch_plan）不归章——它没有章号，成本仍计在
    该任务自己的 metrics 里，所以各章之和可以小于任务总额。
    """
    row = db.execute(select(Task.project_id, Task.chapter_seq).where(Task.id == task_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "NOT_FOUND")
    project_id, single_chapter = row["project_id"], row["chapter_seq"]
    thread = func.nullif(func.split_part(AgentRun.task_id, ":ch", 2), "")
    if single_chapter is None:
        # 批次的章号全在 :ch 线程上；带不出章号的 run 是 book 级的，不列进来
        chapter = cast(thread, Integer).label("chapter_seq")
        condition = (thread.isnot(None),)
    else:
        # 单章任务的 run 挂在裸 task_id 上，thread 为空，归到本任务的目标章号
        chapter = func.coalesce(cast(thread, Integer), single_chapter).label("chapter_seq")
        condition = ()
    stmt = (select(chapter,
                   func.count(AgentRun.id).label("run_count"),
                   func.coalesce(func.sum(AgentRun.input_tokens), 0).label("input_tokens"),
                   func.coalesce(func.sum(AgentRun.output_tokens), 0).label("output_tokens"),
                   func.coalesce(func.sum(AgentRun.cost_est), 0.0).label("cost_est"),
                   func.coalesce(func.sum(AgentRun.duration_ms), 0).label("duration_ms"),
                   func.array_agg(func.distinct(AgentRun.node)).label("stages"))
            .where(*condition, _task_runs(str(task_id), project_id))
            .group_by(chapter).order_by(chapter))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.limit(limit).offset(offset)).mappings().all()
    # 快照指针：只给定位与标量，正文留在快照详情接口
    refs: dict[int, list[dict]] = {}
    sequences = [item["chapter_seq"] for item in rows]
    if sequences:
        for ref in db.execute(select(
                GenerationSnapshot.id, GenerationSnapshot.stage, GenerationSnapshot.attempt,
                GenerationSnapshot.chapter_seq, GenerationSnapshot.model_id,
                GenerationSnapshot.cost_est, GenerationSnapshot.duration_ms,
                GenerationSnapshot.degraded, GenerationSnapshot.created_at)
                .where(GenerationSnapshot.project_id == project_id,
                       GenerationSnapshot.chapter_seq.in_(sequences),
                       _snapshot_scope(str(task_id)))
                .order_by(GenerationSnapshot.stage, GenerationSnapshot.attempt)).mappings():
            refs.setdefault(ref["chapter_seq"], []).append(dict(ref))
    items = [{**_nested_metrics(dict(item)), "stages": sorted(set(item["stages"] or [])),
              "snapshots": refs.get(item["chapter_seq"], [])} for item in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/projects/{project_id}/generation-tasks", response_model=AdminPage[AdminGenerationTask],
            name="admin.generation_tasks")
def generation_tasks(project_id: uuid.UUID, db: DB, limit: Limit = 25, offset: Offset = 0):
    """一本书的任务清单：每个任务一行 Σ成本/耗时/tokens 与覆盖章数、快照数。

    列表不 select 任何 JSON blob（2C4G 上要轻）；正文只在 /snapshots/{id} 出。
    """
    _exists(db, Project, project_id)
    per_task = _per_task_totals()
    snapshots = (select(func.count(GenerationSnapshot.id)).where(_snapshot_scope(Task.id))
                 .correlate(Task).scalar_subquery())
    stmt = (select(Task.id, Task.task_type, Task.status, Task.chapter_seq, Task.batch_task_id,
                   Task.retry_count, Task.created_at, Task.updated_at,
                   func.coalesce(per_task.c.run_count, 0).label("run_count"),
                   func.coalesce(per_task.c.input_tokens, 0).label("input_tokens"),
                   func.coalesce(per_task.c.output_tokens, 0).label("output_tokens"),
                   func.coalesce(per_task.c.cost_est, 0.0).label("cost_est"),
                   func.coalesce(per_task.c.duration_ms, 0).label("duration_ms"),
                   func.coalesce(per_task.c.chapter_count, 0).label("chapter_count"),
                   snapshots.label("snapshot_count"))
            .select_from(Task).outerjoin(per_task, per_task.c.task_id == Task.id)
            .where(Task.project_id == project_id)
            .order_by(Task.created_at.desc(), Task.id.desc()))
    return _page(db, stmt, limit, offset, _nested_metrics)


@router.get("/snapshots/{snapshot_id}", response_model=AdminSnapshot, name="admin.snapshot")
def snapshot(snapshot_id: int, db: DB):
    """一次生成尝试、一个阶段的原始输入留存；本模块唯一出正文的读接口。"""
    row = db.execute(select(
        GenerationSnapshot.id, GenerationSnapshot.project_id, GenerationSnapshot.task_id,
        GenerationSnapshot.chapter_seq, GenerationSnapshot.stage, GenerationSnapshot.attempt,
        GenerationSnapshot.model_id, GenerationSnapshot.input_tokens, GenerationSnapshot.output_tokens,
        GenerationSnapshot.cache_hit, GenerationSnapshot.duration_ms, GenerationSnapshot.cost_est,
        GenerationSnapshot.retry_count, GenerationSnapshot.degraded, GenerationSnapshot.created_at,
        GenerationSnapshot.updated_at, GenerationSnapshot.payload)
        .where(GenerationSnapshot.id == snapshot_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "NOT_FOUND")
    result = dict(row)
    payload = result["payload"]
    captured = capture(payload)
    previous = payload.get("_capture") if isinstance(payload, dict) else None
    if isinstance(previous, dict):
        captured["truncated"] |= bool(previous.get("truncated"))
        captured["redacted"] |= bool(previous.get("redacted"))
    result.update(payload=captured, snapshot_missing=payload is None)
    return result


def _finding_row(row) -> dict:
    """把 JSONB 里的那条发现摊平；形状对不上的证据条目直接丢，不让一条脏数据毁掉整页。"""
    value = row["finding"] if isinstance(row["finding"], dict) else {}
    evidence = [{"chapter": item["chapter"], "quote": item["quote"]}
                for item in (value.get("evidence") or [])
                if isinstance(item, dict) and isinstance(item.get("chapter"), int)
                and isinstance(item.get("quote"), str)]
    return {"snapshot_id": row["snapshot_id"], "task_id": row["task_id"],
            "chapter_seq": row["chapter_seq"], "attempt": row["attempt"],
            "finding_id": value.get("finding_id"), "conflict_key": value.get("conflict_key"),
            "conflict_type": value.get("conflict_type"), "severity": value.get("severity"),
            "scope": value.get("scope"), "source": value.get("source"),
            "confidence": value.get("confidence"), "suggestion": value.get("suggestion"),
            "evidence": evidence}


@router.get("/projects/{project_id}/findings", response_model=AdminPage[AdminSnapshotFinding],
            name="admin.findings")
def findings(project_id: uuid.UUID, db: DB, severity: Annotated[str | None, Query(max_length=16)] = None,
             chapter_seq: Annotated[int | None, Query(ge=1)] = None, limit: Limit = 25, offset: Offset = 0):
    """跨章复查同一类校验发现（改进硬规则质量的输入）。

    事实来源是 validate 快照的 payload.findings，不是 validation_reports/findings 那两张
    建了从没写过的表。用 jsonb_array_elements 展开后按发现分页，不是按快照分页。
    """
    _exists(db, Project, project_id)
    evidence = func.jsonb_array_elements(
        cast(GenerationSnapshot.payload, JSONB).op("->")("findings")).table_valued(
            column("value", JSONB)).alias("finding")
    stmt = (select(GenerationSnapshot.id.label("snapshot_id"), GenerationSnapshot.task_id,
                   GenerationSnapshot.chapter_seq, GenerationSnapshot.attempt,
                   evidence.c.value.label("finding"))
            .select_from(GenerationSnapshot).join(evidence, true())
            .where(GenerationSnapshot.project_id == project_id,
                   GenerationSnapshot.stage == "validate"))
    if severity:
        stmt = stmt.where(evidence.c.value["severity"].astext == severity)
    if chapter_seq is not None:
        stmt = stmt.where(GenerationSnapshot.chapter_seq == chapter_seq)
    return _page(db, stmt.order_by(GenerationSnapshot.chapter_seq.desc(), GenerationSnapshot.id),
                 limit, offset, _finding_row)


@router.get("/runs", response_model=AdminPage[AdminRun], name="admin.runs")
def runs(db: DB, user_id: uuid.UUID | None = None, project_id: uuid.UUID | None = None,
         node: Annotated[str | None, Query(max_length=64)] = None, limit: Limit = 25, offset: Offset = 0):
    stmt = _run_statement()
    if user_id:
        stmt = stmt.where(Project.user_id == user_id)
    if project_id:
        stmt = stmt.where(AgentRun.project_id == project_id)
    if node:
        stmt = stmt.where(AgentRun.node == node)
    return _page(db, stmt.order_by(AgentRun.id.desc()), limit, offset)


@router.get("/runs/{run_id}", response_model=AdminRunDetail, name="admin.run")
def run(run_id: int, db: DB):
    row = db.execute(_run_statement(True).where(AgentRun.id == run_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "NOT_FOUND")
    result = dict(row)
    detail = result["detail"]
    captured = capture(detail)
    previous = detail.get("_capture") if isinstance(detail, dict) else None
    if isinstance(previous, dict):
        captured["truncated"] |= bool(previous.get("truncated"))
        captured["redacted"] |= bool(previous.get("redacted"))
    result.update(detail=captured, error=capture(result["error"]), detail_missing=detail is None,
                  prompt_missing=not isinstance(detail, dict) or "messages" not in detail)
    return result


@router.get("/access-logs", response_model=AdminPage[AdminAccessLogOut], name="admin.access_logs")
def access_logs(db: DB, limit: Limit = 25, offset: Offset = 0):
    return _page(db, select(AdminAccessLog.id, AdminAccessLog.actor_id, AdminAccessLog.action,
                            AdminAccessLog.target, AdminAccessLog.created_at)
                 .order_by(AdminAccessLog.id.desc()), limit, offset)


# --- 邀请码管理：本模块唯一的写操作。------------------------------------------------
# 写路径不能用 `DB`——reporting_db 的事务是 SET TRANSACTION READ ONLY，且走 superuser
# 的 ADMIN_DATABASE_URL。这里改用 require_admin + new_session()（应用连接、受 RLS 约束），
# 并自己补一次审计写（失败关闭，与 reporting_db 的 ADMIN_AUDIT_UNAVAILABLE 语义一致）。


class InvitationCreateBody(BaseModel):
    expires_days: int = Field(7, ge=1, le=365)
    max_redemptions: int = Field(1, ge=1, le=1000)
    label: str | None = Field(None, max_length=64, description="便于分发的备注，可空")
    code: str | None = Field(
        None, max_length=64, description="自定义码面；留空则生成 256 位随机码"
    )


def _audit_or_fail(actor: _AuthenticatedUser, request: Request, action: str) -> None:
    try:
        write_access_log(actor.id, action, _safe_target(request))
    except Exception:
        raise HTTPException(503, "ADMIN_AUDIT_UNAVAILABLE") from None


@router.get("/invitations", response_model=AdminPage[AdminInvitation], name="admin.invitations")
def invitations(db: DB, limit: Limit = 25, offset: Offset = 0):
    """只读列表。刻意不返回摘要（对管理员无用），明文码仅创建时可见一次。"""
    creator = aliased(User)
    return _page(db, select(
        Invitation.id, Invitation.label, Invitation.expires_at, Invitation.max_redemptions,
        Invitation.redemption_count, Invitation.revoked_at, Invitation.created_by,
        creator.username.label("created_by_username"), Invitation.created_at,
    ).outerjoin(creator, creator.id == Invitation.created_by)
     .order_by(Invitation.created_at.desc()), limit, offset)


@router.post("/invitations", response_model=AdminInvitationCreated, status_code=201,
             name="admin.create_invitation")
def create_invitation_endpoint(
    request: Request,
    body: InvitationCreateBody,
    actor: _AuthenticatedUser = Depends(require_admin),
):
    _audit_or_fail(actor, request, "admin.create_invitation")
    expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_days)
    try:
        with new_session() as db:
            invitation, code = invitations_mod.create_invitation(
                db, expires_at=expires_at, max_redemptions=body.max_redemptions,
                token=body.code, label=body.label, created_by=actor.id,
            )
            db.commit()
            return {
                "id": invitation.id, "code": code, "label": invitation.label,
                "expires_at": invitation.expires_at,
                "max_redemptions": invitation.max_redemptions,
            }
    except IntegrityError:
        raise HTTPException(409, "INVITATION_CODE_TAKEN") from None
    except ValueError as exc:
        raise HTTPException(400, f"INVALID_INVITATION: {exc}") from None


@router.post("/invitations/{invitation_id}/revoke", response_model=OkOut,
             name="admin.revoke_invitation")
def revoke_invitation_endpoint(
    invitation_id: uuid.UUID,
    request: Request,
    actor: _AuthenticatedUser = Depends(require_admin),
):
    _audit_or_fail(actor, request, "admin.revoke_invitation")
    with new_session() as db:
        if not invitations_mod.revoke_invitation(db, invitation_id):
            raise HTTPException(404, "NOT_FOUND")
        db.commit()
    return {"ok": True}
