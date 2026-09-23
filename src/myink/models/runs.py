"""任务与运行记录模型。

agent_runs 每节点一行全字段（§6.8 任务成本透明）：
节点、角色、model_id（含降级后实际）、输入/输出 token（思考 token 计入输出）、
缓存命中标记、耗时、成本估算、重试、降级、错误 —— 前端节点时间线数据源。

generation_snapshots 每阶段一行原始输入留存（选择性）：渲染后的提示词按节留下
有分析价值的部分，供运维排障逐章回看「当时喂进去的是什么」。
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from myink.models.base import Base, TimestampMixin, UUIDPkMixin

TASK_STATUSES = ("queued", "running", "paused", "awaiting_plan", "awaiting_review", "failed", "cancelled", "done")
TASK_TYPES = ("chapter_generate", "batch_generate", "validate", "outline_generate")

# 留快照的阶段（与 workflow/nodes.py 的挂点一一对应）。
# revise 一并留下：它带着上轮的校验/审计发现，是「改不对」时唯一的输入凭据。
SNAPSHOT_STAGES = ("recall", "plan_cast", "plan_chapter", "write", "validate", "audit", "patch", "revise")


class Task(Base, UUIDPkMixin, TimestampMixin):
    """异步任务（队列最终态由 DB 承载，Redis 只放可重建数据，§5.3/§6.12）。"""

    __tablename__ = "tasks"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(128), comment="request_id→task_id→thread_id 链路")
    batch_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, comment="批次归属（thread_id=batch_task_id）")
    chapter_seq: Mapped[int | None] = mapped_column(Integer, comment="单章任务的目标章节")


class AgentRun(Base, TimestampMixin):
    """每节点执行记录（§6.8）。id 用自增（观测数据，无租户语义，不参与 RLS 查询热点）。"""

    __tablename__ = "agent_runs"
    __table_args__ = (
        # 任务详情/成本聚合（§6.8）：全部查询按 task_id 前缀 + id 增量扫（routes_tasks/observer/
        # processor 无一条按 project_id 查——观测表无 RLS，故组合索引前缀用 task_id 而非 project_id）。
        # 前缀 LIKE 在默认 collation 下走 btree 范围扫；若将来 collation 非 C 需换 pg_trgm/text_pattern_ops。
        Index("ix_agent_runs_task_id", "task_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    # thread_id（单章=task_id；批次内= batch_task_id:ch{seq}），字符串标识，非严格 uuid
    # 不设 index=True：__table_args__ 组合索引 ix_agent_runs_task_id(task_id,id) 左前缀已覆盖
    # 按 task_id 查询；同名单列索引会在 create_all fresh 库时与组合索引同名冲突（DuplicateTable）
    task_id: Mapped[str | None] = mapped_column(String(128))
    node: Mapped[str] = mapped_column(String(64), nullable=False, comment="load_state/recall/plan_chapter/write/extract/validate/revise/persist/batch_plan/...")
    role: Mapped[str | None] = mapped_column(String(32), comment="Planner/Writer/Memory/Validator")
    model_id: Mapped[str | None] = mapped_column(String(64), comment="含降级后的实际模型")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="思考 token 计入输出")
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="缓存命中（价差 50 倍）")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_est: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, comment="成本估算（¥）")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    # 节点关键产物（debug 回放，§6.8）：audit 行→audit_verdict；write/audit 工具轮→tool_trace；
    # 确定性节点（recall/validate/persist/load_state）→执行统计。纯观测字段，不影响执行语义。
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class GenerationSnapshot(Base, TimestampMixin):
    """一次生成尝试、每个阶段一行的原始输入留存（§6.8 分析口径）。

    与 agent_runs 的分工：agent_runs 记「花了多少」（每次 LLM 调用一行，含重试与降级），
    本表记「当时喂进去的是什么」（渲染后的提示词分节、召回块指针、生效的硬规则与文风版本），
    供运维排障逐章对账。标量列与 agent_runs 同口径，故单章成本/耗时不必回表 join
    （同一节点多次重试在 agent_runs 里是多行，join 会重复计数）。

    唯一键 (task_id, chapter_seq, stage, attempt) 让重跑同一章同一阶段覆盖而非堆行；
    chapter_seq 可空（全书级阶段尚无），PostgreSQL 里 NULL 互不相等，故无章节的行不受唯一约束。
    不给 tasks 设 FK：批次线程 id 是合成串 {batch_id}:ch{seq}，agent_runs 也是这么松关联的。
    """

    __tablename__ = "generation_snapshots"
    __table_args__ = (
        Index("uq_generation_snapshots_key", "task_id", "chapter_seq", "stage", "attempt", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True, comment="租户键，RLS 过滤依据")
    task_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="thread_id（单章=task_id；批次=batch:ch{seq}）")
    chapter_seq: Mapped[int | None] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(24), nullable=False, comment="/".join(SNAPSHOT_STAGES))
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="同阶段第几次尝试（重规划/重写递增）")
    model_id: Mapped[str | None] = mapped_column(String(64), comment="含降级后的实际模型")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_est: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, comment="成本估算（¥）")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 分节留存（选择性，见 snapshot.py 的投影规则）：只存有分析/提升价值的部分，
    # 逐字节相同的静态素材只留长度 + sha256；任何省略都在 payload 里显式标记。
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
