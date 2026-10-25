"""Stable proposal identity shared by review and correction paths."""
from __future__ import annotations

def same_proposal(kind: str, left: dict, right: dict) -> bool:
    """只按明确语义字段去重，不用相似度把未来的合法变化误封。"""
    import re
    fields = {"character_card": ("name",), "character_state": ("character_id", "field", "new_value"),
              "relation_change": ("source_id", "target_id", "relation_type"),
              "fact": ("content",), "event": ("summary",)}.get(kind)
    def normalize(value):
        return re.sub(r"[\s，。！？、；：,.!?;:]", "", str(value or "")).casefold()
    if fields:
        return all(normalize(left.get(k)) == normalize(right.get(k)) for k in fields)
    return left == right

