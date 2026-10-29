"""Proposal identities for review decisions and full correction payloads."""
from __future__ import annotations

import re

_IDENTITY_FIELDS = {
    "character_card": ("name",),
    "character_state": ("character_id", "field", "new_value"),
    "relation_change": ("source_id", "target_id", "relation_type"),
    "fact": ("content",),
    "event": ("summary",),
}
_CORRECTION_METADATA = frozenset({"confidence", "source_chapter", "evidence"})


def _normalize(value):
    # Internal punctuation can encode a decimal, time, password or identifier.
    text = re.sub(r"\s+", "", str(value or "")).casefold()
    return text.rstrip("。！？.!?；;")


def same_proposal(kind: str, left: dict, right: dict) -> bool:
    """Coarse identity for author review/rejection, preserving its original contract."""
    fields = _IDENTITY_FIELDS.get(kind)
    if fields:
        return all(_normalize(left.get(k)) == _normalize(right.get(k)) for k in fields)
    return left == right


def same_correction_proposal(kind: str, left: dict, right: dict) -> bool:
    """Ignore only explicit metadata; every other payload field remains semantic."""
    left = {k: v for k, v in left.items() if k not in _CORRECTION_METADATA}
    right = {k: v for k, v in right.items() if k not in _CORRECTION_METADATA}
    if left.keys() != right.keys():
        return False
    text_fields = _IDENTITY_FIELDS.get(kind, ("description",) if kind == "foreshadow" else ())
    for key, value in left.items():
        other = right[key]
        if key in text_fields and isinstance(value, str) and isinstance(other, str):
            if _normalize(value) != _normalize(other):
                return False
        elif value != other:
            return False
    return True
