"""Pydantic 契约模型（spec/schema.md 12 个 Schema 的代码映射）。"""

from aiink.schemas.contract import (
    AuditVerdict,
    ChapterPlan,
    Character,
    CharacterPresence,
    CharacterState,
    Event,
    EvidenceItem,
    Fact,
    Finding,
    Foreshadow,
    MutationCandidate,
    PlotThread,
    Relation,
    RetrievedContext,
    Scene,
    ValidationReport,
)

__all__ = [
    "CharacterState",
    "Character",
    "Scene",
    "CharacterPresence",
    "ChapterPlan",
    "Event",
    "Fact",
    "Relation",
    "Foreshadow",
    "PlotThread",
    "EvidenceItem",
    "Finding",
    "MutationCandidate",
    "ValidationReport",
    "AuditVerdict",
    "RetrievedContext",
]
