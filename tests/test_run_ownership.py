"""记账归属：每条 agent_runs 至少属于一本书或一个账号。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete as sa_delete, select

from myink.db import new_session
from myink.models import AgentRun, User
from myink.providers.base import ModelResponse
from myink.workflow import nodes


def _resp() -> ModelResponse:
    return ModelResponse(content="{}", model_id="m", input_tokens=1, output_tokens=2, duration_ms=5)


def test_record_run_accepts_account_only_ownership():
    with new_session() as db:
        user = User(username=f"own-{uuid.uuid4().hex[:8]}")
        db.add(user)
        db.commit()
        uid = user.id
    try:
        with new_session() as db:
            nodes.record_run(db, user_id=uid, node="short_creation", role="Planner", resp=_resp())
            db.commit()
        with new_session() as db:
            row = db.scalar(select(AgentRun).where(AgentRun.user_id == uid))
            assert row is not None
            assert row.project_id is None
            assert row.node == "short_creation"
    finally:
        with new_session() as db:
            db.execute(sa_delete(AgentRun).where(AgentRun.user_id == uid))
            db.execute(sa_delete(User).where(User.id == uid))
            db.commit()


def test_record_run_refuses_a_row_with_no_owner():
    with new_session() as db:
        with pytest.raises(ValueError, match="记账不能没有归属"):
            nodes.record_run(db, node="short_creation", role="Planner", resp=_resp())


def test_owner_ids_normalizes_both_forms():
    pid, uid = nodes._owner_ids(project_id=None, user_id=uuid.uuid4())
    assert pid is None and isinstance(uid, uuid.UUID)
