"""Proposal identity must not erase meaningful numeric or identifier punctuation."""
import pytest

from myink.memory.candidate_identity import same_proposal
from myink.memory.correction import diff_changeset


def _candidate(kind, value):
    payload = ({"content": value} if kind == "fact" else
               {"summary": value} if kind == "event" else
               {"character_id": "character-1", "field": "knowledge", "new_value": value})
    return {"kind": kind, "payload": payload, "confidence": .9}


@pytest.mark.parametrize("kind", ["fact", "event", "character_state"])
@pytest.mark.parametrize("left,right", [
    ("长剑重1.5斤", "长剑重15斤"),
    ("密码为1:23", "密码为12:3"),
    ("密码为1：23", "密码为12：3"),
    ("暗号为A.B", "暗号为AB"),
    ("口令为甲，乙", "口令为甲乙"),
])
def test_extraction_keeps_proposals_with_distinct_meaningful_punctuation(kind, left, right):
    candidates = [_candidate(kind, left), _candidate(kind, right)]
    result = diff_changeset([], candidates)
    assert result["add"] == candidates
    assert result["keep"] == 0


@pytest.mark.parametrize("kind", ["fact", "event", "character_state"])
def test_extraction_still_deduplicates_spacing_sentence_endings_and_metadata(kind):
    first = _candidate(kind, "不能升级。")
    second = _candidate(kind, " 不能 升级！ ")
    second["confidence"] = .6
    second["payload"]["confidence"] = .6
    result = diff_changeset([], [first, second])
    assert result["add"] == [first]


def test_rejected_proposal_does_not_block_a_different_decimal_value():
    rejected = {"content": "灵力值为1.5"}
    revised = {"content": "灵力值为15"}
    assert not same_proposal("fact", rejected, revised)
