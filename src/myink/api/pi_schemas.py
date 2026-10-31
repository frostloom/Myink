"""Administrator Pi views; no paths, credentials or host commands in the API."""
from datetime import datetime
from typing import Annotated, Literal
import uuid
from pydantic import BaseModel, ConfigDict, Field, StrictInt

Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
Image = Annotated[str, Field(pattern=r'^sha256:[0-9a-f]{64}$')]
Count = Annotated[StrictInt, Field(ge=0)]


class PiChange(BaseModel):
    path: str = Field(max_length=4096)
    category: Literal['production', 'test', 'docs', 'config']
    added: Count | None
    deleted: Count | None


class PiChecker(BaseModel):
    passed: bool
    tests: Count | None = None
    failures: Count | None = None
    errors: Count | None = None
    skipped: Count | None = None


class PiReview(BaseModel):
    kind: str = Field(max_length=160)
    sha256: Digest


class PiEvaluation(BaseModel):
    sdk_verified: bool
    checker: PiChecker
    independent_review: PiReview
    model_requests: Count
    known_cost_microyuan: Count | None
    tool_count: Count
    evidence_domain: Literal['online_business', 'real_provider_fixed_input', 'offline', 'synthetic', 'unknown']
    online_improvement_proven: bool


class PiComparison(BaseModel):
    anchor: Literal['verified_deployment']
    day_offset: Literal[1]
    status: Literal['planned']
    online_improvement_proven: Literal[False]
    test_cases: list[str] = Field(max_length=128)


class PiCandidate(BaseModel):
    package_sha256: Digest
    image_id: Image
    source_sha256: Digest
    comparison_sha256: Digest
    baseline_sha256: Digest
    changes: list[PiChange] = Field(max_length=128)
    evaluation: PiEvaluation
    comparison: PiComparison
    publication_available: bool


class PiDeployment(BaseModel):
    deployment_id: str = Field(max_length=128)
    deployed_at: datetime
    image_id: Image
    source_sha256: Digest
    comparison_sha256: Digest


class PiOperation(BaseModel):
    request_id: uuid.UUID
    actor_id: uuid.UUID
    cycle_id: uuid.UUID
    package_sha256: Digest
    decision: Literal['publish', 'defer']
    status: Literal['recording', 'queued', 'running', 'deferred', 'succeeded', 'failed', 'uncertain']
    created_at: datetime
    completed_at: datetime | None
    reason: str | None = Field(None, max_length=160)


class PiExecutor(BaseModel):
    service_state: str = Field(max_length=64)
    timer_state: str = Field(max_length=64)
    last_result: str | None = Field(None, max_length=64)
    next_check: str | None = Field(None, max_length=128)


class PiStatus(BaseModel):
    schema_version: Literal[1]
    mode: Literal['ACTUAL', 'SIMULATED']
    observed_at: datetime
    phase: Literal['idle', 'preparing', 'awaiting_approval', 'awaiting_deployment', 'observing', 'blocked']
    cycle_id: uuid.UUID | None
    task_id: str | None = Field(None, max_length=160)
    package_sha256: Digest | None
    candidate: PiCandidate | None
    deployment: PiDeployment | None
    next_assessment_at: datetime | None = None
    latest_operation: PiOperation | None
    executor: PiExecutor


class PiDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: uuid.UUID
    cycle_id: uuid.UUID
    package_sha256: Digest
    image_id: Image
    source_sha256: Digest
    comparison_sha256: Digest
    decision: Literal['publish', 'defer']


class PiDaily(BaseModel):
    schema_version: Literal[1]
    authority: Literal['audit_only']
    day: str
    timezone: Literal['Asia/Shanghai']
    event_count: Count
    unknown_occurrence_count: Count
    release_state: Literal['unknown', 'deployed', 'rolled_back', 'no_release']
    release_runs: list[dict]
    runs: list[str]
    versions: list[dict]
    change_scope: list[dict]
    next_tests: list[dict]
    known_cost_microyuan: Count | None
    observed_samples: Count | None
    sample_windows: list[dict]
