"""Bounded, deterministic edits. All locations refer to the unchanged original."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Patch:
    target: str
    replacement: str


@dataclass(frozen=True)
class ApplyResult:
    content: str
    applied: bool
    applied_count: int
    skipped_count: int
    rejected_reason: str | None = None
    # 真正应用成功的补丁（模型申报的原文；仅空白可能与实际命中位置不同）。
    # 只记个数的话，「这次修订改了什么」在事后无从查证——快照留的就是这份片段。
    applied_spans: tuple[Patch, ...] = ()


def parse_patches(raw: str) -> list[Patch]:
    if re.search(r"(?im)^\s*===\s*(?:CONTENT|REVISED_CONTENT)\s*===\s*$", raw):
        return []
    section = re.search(r"(?ims)^\s*===\s*PATCHES\s*===\s*\n(.*?)(?=^\s*===|\Z)", raw)
    if not section:
        return []
    text = section[1].replace("\r\n", "\n")
    boundaries = list(re.finditer(r"(?im)^--- PATCH[^\n]*", text))
    if not boundaries or text[:boundaries[0].start()].strip():
        return []  # No trustworthy start boundary: reject the entire response.
    patches = []
    for index, boundary in enumerate(boundaries):
        end = boundaries[index + 1].start() if index + 1 < len(boundaries) else len(text)
        block = re.fullmatch(
            r"(?is)--- PATCH \d+ ---[ \t]*\nTARGET_TEXT:[ \t]*\n(.*?)"
            r"\nREPLACEMENT_TEXT:[ \t]*\n(.*?)\n--- END PATCH ---\s*",
            text[boundary.start():end],
        )
        # Empty targets are never applied. Retain malformed declarations in the
        # denominator without letting a regex borrow fields from the next block.
        patches.append(Patch(block[1].strip("\n"), block[2].strip("\n"))
                       if block else Patch("", ""))
    return patches


def _occurrences(text: str, target: str) -> list[int]:
    found = []
    start = 0
    while len(found) < 2:
        pos = text.find(target, start)
        if pos < 0:
            break
        found.append(pos)
        start = pos + 1
    return found


def _locate(original: str, target: str) -> tuple[int, int] | None:
    matches = _occurrences(original, target)
    if len(matches) == 1:
        return matches[0], matches[0] + len(target)
    if matches:  # Ambiguous exact text cannot be rescued by fuzzy matching.
        return None
    needle = "".join(c for c in target if not c.isspace())
    if len(needle) < 10:
        return None
    positions = [i for i, c in enumerate(original) if not c.isspace()]
    compact = "".join(original[i] for i in positions)
    matches = _occurrences(compact, needle)
    if len(matches) != 1:
        return None
    start = matches[0]
    return positions[start], positions[start + len(needle) - 1] + 1


def apply_patches(original: str, patches: list[Patch]) -> ApplyResult:
    edits: list[tuple[int, int, Patch]] = []
    for patch in patches:
        if not patch.target.strip() or max(len(patch.target), len(patch.replacement)) > 600:
            continue
        span = _locate(original, patch.target)
        if span is None:
            continue
        start, end = span
        if original[start:end] == patch.replacement:
            continue
        if any(start < b and end > a for a, b, _ in edits):
            continue
        edits.append((start, end, patch))
    count = len(edits)
    skipped = len(patches) - count
    if not count or count * 2 < len(patches):
        return ApplyResult(original, False, 0, len(patches), "补丁为空、未命中或应用率不足 50%")
    # Bound both removal and insertion; a tiny target cannot expand to a new chapter.
    touched = sum(max(end - start, len(patch.replacement)) for start, end, patch in edits)
    if touched > max(100, int(len(original) * 0.3)):
        return ApplyResult(original, False, 0, len(patches), "补丁超出局部修改范围")
    content = original
    for start, end, patch in sorted(edits, key=lambda edit: edit[0], reverse=True):
        content = content[:start] + patch.replacement + content[end:]
    return ApplyResult(content, True, count, skipped,
                       applied_spans=tuple(patch for _, _, patch in edits))


def resolve_revise_mode(state: dict) -> str:
    report = state.get("report") or {}
    rules = report.get("findings") or []
    summary = report.get("summary") or {}
    # Missing rule evidence is not evidence that a hard blocker is local.
    if (summary.get("critical") or 0) > sum(f.get("severity") == "critical" for f in rules):
        return "full"
    if (summary.get("l2_major") or 0) > sum(
        f.get("severity") == "major" and f.get("source") == "L2" for f in rules
    ):
        return "full"
    findings = [*rules, *(state.get("unresolved") or []),
                *((state.get("audit_verdict") or {}).get("findings") or [])]
    blockers = [f for f in findings if f.get("severity") in ("critical", "major")]
    return "patch" if blockers and all(f.get("scope") == "local" for f in blockers) else "full"
