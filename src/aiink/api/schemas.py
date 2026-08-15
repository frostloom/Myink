"""HTTP 响应契约模型（response_model 单一事实源，阶段 5 契约测试形式化）。

字段从各路由手拼 dict 提取（main.py / routes_*.py），挂到路由装饰器 response_model=
后由 FastAPI 生成完整 OpenAPI schema；`aiink contract export` 导出到
spec/api-openapi.json。命名统一 `*Out` 后缀，避免与 `aiink.models` 的 ORM 重名。

自由形状字段（payload / style_profile / summary / evidence / findings / detail /
invalidation）用 `dict` / `list[dict]` 松类型——契约价值在字段名存在 + 形状稳定，
不做深层枚举（避免误伤现有响应）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuthResponse(BaseModel):
    token: str
    user_id: str
    expires_in: int


class ProjectOut(BaseModel):
    id: str
    title: str
    genre: str
    current_chapter: int


class ChapterMetaOut(BaseModel):
    id: str
    chapter_seq: int
    title: str | None = None
    status: str


class ChapterDetailOut(ChapterMetaOut):
    content: str | None = None
    summary: str | None = None


class ChapterVersionOut(BaseModel):
    version: int
    title: str | None = None
    content: str | None = None
    summary: str | None = None
    reason: str | None = None
    created_at: str | None = None


class ChapterVersionsOut(BaseModel):
    chapter_id: str
    chapter_seq: int
    current_version: int
    versions: list[ChapterVersionOut] = Field(default_factory=list)


class ContentUpdateOut(BaseModel):
    chapter_id: str
    chapter_seq: int
    status: str
    version: int


class CorrectMemoryOut(BaseModel):
    chapter_seq: int
    changeset: dict = Field(default_factory=dict)
    pool: dict = Field(default_factory=dict)
    no_op: bool


class DeletedChapterOut(BaseModel):
    chapter_seq: int
    title: str | None = None
    invalidation: dict = Field(default_factory=dict)


class DeleteChapterOut(BaseModel):
    deleted: list[DeletedChapterOut] = Field(default_factory=list)
    current_chapter: int


class AgentRunOut(BaseModel):
    node: str
    model_id: str | None = None
    input_tokens: int
    output_tokens: int
    cache_hit: bool
    duration_ms: int
    cost_est: float
    retry_count: int
    degraded: bool
    error: str | None = None
    detail: dict | None = None


class TaskProgressOut(BaseModel):
    current: int
    total: int


class TaskDetailOut(BaseModel):
    task_id: str
    task_type: str
    status: str
    payload: dict = Field(default_factory=dict)
    error: str | None = None
    retry_count: int
    trace_id: str | None = None
    chapter_seq: int | None = None
    batch_task_id: str | None = None
    created_at: str | None = None
    progress: TaskProgressOut | None = None
    runs: list[AgentRunOut] = Field(default_factory=list)


class TaskControlOut(BaseModel):
    task_id: str
    status: str
    message: str | None = None


class MemoryCandidateOut(BaseModel):
    candidate_id: str
    kind: str
    source_chapter: int
    payload: dict = Field(default_factory=dict)
    confidence: float
    status: str
    created_at: str | None = None


class CandidateActionOut(BaseModel):
    candidate_id: str
    status: str


class WritingLessonOut(BaseModel):
    lesson_id: str
    category: str
    lesson_type: str
    content: str
    evidence: list[dict] = Field(default_factory=list)
    confidence: float
    source_chapter: int
    status: str
    recurrence_count: int
    last_recurrence_at: int | None = None
    created_at: str | None = None


class LessonActionOut(BaseModel):
    lesson_id: str
    status: str


class ProjectSettingsOut(BaseModel):
    style_profile: dict = Field(default_factory=dict)
    skill_pack: str | None = None
    model_routes: dict = Field(default_factory=dict)
    version: int


class SkillPresetOut(BaseModel):
    id: str
    name: str
    genre: str
    style_profile: dict = Field(default_factory=dict)


class StyleDraftOut(BaseModel):
    draft: dict = Field(default_factory=dict)


class StyleProfileOut(BaseModel):
    style_profile: dict = Field(default_factory=dict)
    skill_pack: str | None = None
    version: int


class AuditRunOut(BaseModel):
    window_start: int
    window_end: int
    audited_up_to_chapter: int
    status: str
    sampled_characters: list[dict] = Field(default_factory=list)
    findings: list[dict] = Field(default_factory=list)
    error: str | None = None
    summary: dict = Field(default_factory=dict)


class GlobalAuditSummaryOut(BaseModel):
    report_id: str
    window_start: int
    window_end: int
    audited_up_to_chapter: int
    trigger: str
    status: str
    sampled: int
    findings: int
    chapters: int
    bridge: dict | None = None
    style: dict | None = None
    error: str | None = None
    created_at: str | None = None


class GlobalAuditDetailOut(GlobalAuditSummaryOut):
    """详情：列表项 + 抽样角色 + findings 明细（覆盖 Summary 的 int 计数为 list，同前端 Omit 模式）。"""

    sampled_characters: list[dict] = Field(default_factory=list)
    findings: list[dict] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
