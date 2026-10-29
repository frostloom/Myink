"""Correction dedup excludes metadata, never semantic changes to a proposal."""
import uuid

import pytest

from myink.db import tenant_session
from myink.models import MemoryCandidate
from myink.memory.correction import apply_changeset_to_pool, diff_changeset

SID, TID = str(uuid.uuid4()), str(uuid.uuid4())
CASES = [
    ("relation_change", {"source_id": SID, "target_id": TID, "relation_type": "ally", "valid_to": 4},
     {"source_id": SID, "target_id": TID, "relation_type": "ally", "valid_to": None}),
    ("fact", {"content": "固定事实", "is_hard": False}, {"content": "固定事实", "is_hard": True}),
    ("fact", {"content": "固定事实", "category": "身份"}, {"content": "固定事实", "category": "归属"}),
    ("event", {"summary": "拿走钥匙", "participants": ["张三"]}, {"summary": "拿走钥匙", "participants": ["李四"]}),
]


@pytest.mark.parametrize("kind,old,new", CASES)
@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_correction_pool_keeps_materially_changed_proposals(temp_project, kind, old, new, status):
    with tenant_session(temp_project) as db:
        db.add(MemoryCandidate(project_id=temp_project, source_chapter=1, kind=kind, payload=old, status=status))
        db.flush()
        result = apply_changeset_to_pool(db, project_id=uuid.UUID(temp_project), chapter_seq=1,
            changeset={"add": [{"kind": kind, "payload": new}], "remove": [], "keep": 0})
        assert result["add_to_pool"] == 1
        assert result["duplicates_skipped"] == 0


@pytest.mark.parametrize("kind,old,new", CASES)
def test_same_extraction_keeps_materially_distinct_payloads(kind, old, new):
    candidates = [{"kind": kind, "payload": old}, {"kind": kind, "payload": new}]
    assert diff_changeset([], candidates)["add"] == candidates


@pytest.mark.parametrize("boundary", ["extraction", "pool"])
def test_foreshadow_confidence_metadata_is_not_a_second_proposal(temp_project, boundary):
    payload = {"description": "玉佩发光", "trigger": {"actor": "主角"}}
    first = {"kind": "foreshadow", "payload": {**payload, "confidence": .9}}
    second = {"kind": "foreshadow", "payload": {**payload, "confidence": .8}}
    if boundary == "extraction":
        assert diff_changeset([], [first, second])["add"] == [first]
    else:
        with tenant_session(temp_project) as db:
            db.add(MemoryCandidate(project_id=temp_project, source_chapter=1, status="pending", **first))
            db.flush()
            result = apply_changeset_to_pool(db, project_id=uuid.UUID(temp_project), chapter_seq=1,
                changeset={"add": [second], "remove": [], "keep": 0})
            assert result["add_to_pool"] == 0
            assert result["duplicates_skipped"] == 1
