from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from .contracts import Receipt

@dataclass(frozen=True)
class AdministratorContext:
    experiment_id: str
    plan_id: str
    budget_scope_id: str
    evidence_summary: str
    role: str = 'myink-administrator'

@dataclass(frozen=True)
class EngineSession:
    engine: str
    config_hash: str
    phase: str
    session_path: Path
    resume: bool = False
    verified_session_sha256: str | None = None

class Engine(Protocol):
    def run_phase(self, *, phase: str, prompt: str, context: AdministratorContext, session: EngineSession, deadline: datetime, tools: list[str]) -> Receipt: ...
    def stop_phase(self, *, session: EngineSession, reason: str) -> Receipt: ...
