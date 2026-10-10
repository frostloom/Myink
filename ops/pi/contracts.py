from dataclasses import dataclass, field
from typing import Any, Literal

Record = dict[str, Any]


@dataclass(frozen=True)
class Identity:
    deployment_id: str
    generation: int
    owner: str
    image_ids: dict[str, str]
    commit_sha: str | None = None
    schema_id: str | None = None
    config_hash: str | None = None
    schema_version: int = field(default=1, init=False)


@dataclass(frozen=True)
class Receipt:
    operation_id: str
    status: Literal['done', 'failed', 'uncertain', 'blocked']
    evidence: Record
    schema_version: int = field(default=1, init=False)
