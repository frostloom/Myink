"""Explicit reporting contracts. Narrative fields are plain text.

除 `AdminInvitationCreated`（邀请码创建响应）外均为只读观测契约。
"""
from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue

T = TypeVar("T")


class AdminPage(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class CaptureLimits(BaseModel):
    max_depth: int
    max_items: int
    max_text: int
    max_bytes: int


class CapturedData(BaseModel):
    data: JsonValue
    truncated: bool
    redacted: bool
    limits: CaptureLimits


class AdminMetrics(BaseModel):
    run_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_est: float = Field(0, description="Estimated cost, not an invoice")
    duration_ms: int = Field(0, description="Sum of measured node durations; 0 can mean unmeasured")


class AdminTaskAverages(BaseModel):
    """两级均值：先按任务汇总，再对任务取平均——不是对 run 行取平均。

    12 次调用的批次任务与 2 次调用的单章任务在这里各占一票；按 run 行平均会让批次凭
    调用次数压过单章任务，均值不再是「单次任务的平均」。无任务（或任务全无 run）时为
    null：「没有任务」与「任务花费为零」要能分开。
    """

    avg_cost_per_task: float | None
    avg_duration_ms_per_task: float | None
    avg_runs_per_task: float | None


class AdminOverview(BaseModel):
    user_count: int
    project_count: int
    chapter_count: int
    task_count: int
    metrics: AdminMetrics
    task_status_counts: dict[str, int]


class AdminUser(BaseModel):
    id: UUID
    username: str
    tier: str
    role: Literal["user", "admin"]
    project_count: int
    chapter_count: int
    word_count: int
    task_count: int
    metrics: AdminMetrics
    task_averages: AdminTaskAverages


class AdminProject(BaseModel):
    id: UUID
    user_id: UUID
    username: str
    title: str
    genre: str
    current_chapter: int
    target_words: int | None
    creation_status: str
    created_at: datetime
    updated_at: datetime
    chapter_count: int
    word_count: int
    task_count: int
    metrics: AdminMetrics
    task_averages: AdminTaskAverages


class AdminChapter(BaseModel):
    id: UUID
    project_id: UUID
    chapter_seq: int
    title: str | None
    status: str
    word_count: int
    created_at: datetime
    updated_at: datetime


class AdminChapterDetail(AdminChapter):
    content: str | None
    summary: str | None
    version: int


class AdminContextCollection(BaseModel):
    items: list[CapturedData]
    total: int
    limit: int
    truncated: bool


class AdminContext(BaseModel):
    project_id: UUID
    settings: CapturedData
    outlines: AdminContextCollection
    events: AdminContextCollection
    facts: AdminContextCollection
    characters: AdminContextCollection
    foreshadows: AdminContextCollection
    threads: AdminContextCollection


class AdminTask(BaseModel):
    id: UUID
    project_id: UUID
    user_id: UUID
    username: str
    project_title: str
    task_type: str
    status: str
    chapter_seq: int | None
    batch_task_id: UUID | None
    retry_count: int
    created_at: datetime
    updated_at: datetime
    metrics: AdminMetrics


class AdminTaskDetail(AdminTask):
    payload: CapturedData
    error: CapturedData
    elapsed_ms: int = Field(description="created_at to updated_at; includes queue/pause/human waits")
    elapsed_includes_waits: Literal[True] = True


class AdminGenerationTask(BaseModel):
    """单次任务的生成账：一本书里一个任务一行（分析页下钻的第二层）。"""

    id: UUID
    task_type: str
    status: str
    chapter_seq: int | None
    batch_task_id: UUID | None
    retry_count: int
    chapter_count: int = Field(description="该任务覆盖的章数：批次按 :ch 线程归章，book 级 run 不计章")
    snapshot_count: int = Field(description="落盘的生成快照数；0 = 该任务早于快照上线，只剩遥测")
    created_at: datetime
    updated_at: datetime
    metrics: AdminMetrics


class AdminSnapshotRef(BaseModel):
    """快照指针。列表只给定位与标量；渲染后的提示词与召回正文只在快照详情接口出。"""

    id: int
    stage: str
    attempt: int
    model_id: str | None
    cost_est: float
    duration_ms: int
    degraded: bool
    created_at: datetime


class AdminTaskChapter(BaseModel):
    """任务内按章的分解（分析页下钻的第三层）。"""

    chapter_seq: int | None
    stages: list[str] = Field(description="该章实际跑过的节点；缺哪个阶段即没跑到或失败")
    metrics: AdminMetrics
    snapshots: list[AdminSnapshotRef]


class AdminSnapshot(BaseModel):
    """一次生成尝试、一个阶段的原始输入留存（选择性）。唯一出正文的读接口。"""

    id: int
    project_id: UUID
    task_id: str
    chapter_seq: int | None
    stage: str
    attempt: int
    model_id: str | None
    input_tokens: int
    output_tokens: int
    cache_hit: bool
    duration_ms: int
    cost_est: float
    retry_count: int
    degraded: bool
    created_at: datetime
    updated_at: datetime
    payload: CapturedData
    snapshot_missing: bool = Field(description="早于快照上线的记录只剩遥测，payload 为空；不做假回填")


class AdminFindingEvidence(BaseModel):
    chapter: int
    quote: str


class AdminSnapshotFinding(BaseModel):
    """一条校验发现 + 它出现在哪一章哪次尝试。事实来源是快照，不是那两张没人写的表。"""

    snapshot_id: int
    task_id: str
    chapter_seq: int | None
    attempt: int
    finding_id: str | None
    conflict_key: str | None
    conflict_type: str | None
    severity: str | None
    scope: str | None
    source: str | None
    confidence: float | None
    suggestion: str | None
    evidence: list[AdminFindingEvidence]


class AdminRun(BaseModel):
    id: int
    project_id: UUID
    user_id: UUID
    username: str
    project_title: str
    task_id: str | None
    node: str
    role: str | None
    model_id: str | None
    input_tokens: int
    output_tokens: int
    cost_est: float
    duration_ms: int
    cache_hit: bool
    degraded: bool
    retry_count: int
    created_at: datetime
    updated_at: datetime


class AdminRunDetail(AdminRun):
    detail: CapturedData
    error: CapturedData
    detail_missing: bool
    prompt_missing: bool


class AdminAccessLogOut(BaseModel):
    id: int
    actor_id: UUID
    action: str
    target: str
    created_at: datetime


class AdminInvitation(BaseModel):
    """邀请码的管理视图。永远不含明文码，也不含摘要——摘要对管理员无用。"""

    id: UUID
    label: str | None
    expires_at: datetime
    max_redemptions: int
    redemption_count: int
    revoked_at: datetime | None
    created_by: UUID | None
    created_by_username: str | None
    created_at: datetime


class AdminInvitationCreated(BaseModel):
    """创建响应：`code` 是全生命周期内唯一一次可见的明文。"""

    id: UUID
    code: str
    label: str | None
    expires_at: datetime
    max_redemptions: int
