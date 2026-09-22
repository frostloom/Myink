"""Deterministic revision must never alter unrelated or ambiguously located text."""
import pytest

from myink.schemas import Finding
from myink.workflow.patches import Patch, apply_patches, parse_patches, resolve_revise_mode


def framed(text):
    return "前文不动。" * 30 + text + "后文不动。" * 30


def test_exact_patch_preserves_surroundings():
    result = apply_patches(framed("他握着旧剑。"), [Patch("他握着旧剑。", "他握着青剑。")])
    assert result.content == framed("他握着青剑。")
    assert result.applied and result.applied_count == 1 and result.skipped_count == 0


@pytest.mark.parametrize("original,target", [("旧剑与旧剑", "旧剑"), ("aaaa", "aaa")])
def test_ambiguous_exact_match_is_rejected(original, target):
    result = apply_patches(original, [Patch(target, "新剑")])
    assert not result.applied and result.content == original


def test_fuzzy_whitespace_preserves_unrelated_formatting():
    original = framed("他拿起那把\n 古老的剑并走进长廊。")
    result = apply_patches(original, [Patch("他拿起那把古老的剑并走进长廊。", "他拿起青剑，走进长廊。")])
    assert result.content == framed("他拿起青剑，走进长廊。")


def test_short_fuzzy_target_is_not_safe():
    original = framed("旧 剑")
    result = apply_patches(original, [Patch("旧剑", "青剑")])
    assert not result.applied and result.content == original


def test_individual_missing_patch_is_skipped():
    result = apply_patches(framed("旧剑。破门。"), [
        Patch("旧剑", "青剑"), Patch("不存在", "新词"), Patch("破门", "木门")])
    assert result.content == framed("青剑。木门。")
    assert result.applied_count == 2 and result.skipped_count == 1


def test_below_half_reverts_every_change():
    original = framed("旧剑。")
    result = apply_patches(original, [Patch("旧剑", "青剑"), Patch("无一", "一"), Patch("无二", "二")])
    assert not result.applied and result.content == original and result.rejected_reason


@pytest.mark.parametrize("patches", [[], [Patch("", "新")], [Patch("旧剑", "旧剑")]])
def test_empty_or_unchanged_patch_is_not_applied(patches):
    original = framed("旧剑")
    result = apply_patches(original, patches)
    assert not result.applied and result.content == original


def test_patches_cannot_target_earlier_generated_text():
    result = apply_patches(framed("旧剑"), [Patch("旧剑", "青剑"), Patch("青剑", "金剑")])
    assert result.content == framed("青剑")
    assert result.applied_count == 1 and result.skipped_count == 1


def test_overlapping_ranges_do_not_corrupt_text():
    result = apply_patches(framed("他举起旧剑"), [Patch("他举起旧剑", "他举起青剑"), Patch("旧剑", "木剑")])
    assert result.content == framed("他举起青剑")
    assert result.skipped_count == 1


@pytest.mark.parametrize("target,replacement", [("甲" * 601, "乙"), ("甲", "乙" * 601), ("甲" * 150, "乙")])
def test_large_patch_cannot_disguise_full_rewrite(target, replacement):
    original = target + "后续" * 10
    result = apply_patches(original, [Patch(target, replacement)])
    assert not result.applied and result.content == original


def test_parse_only_patch_section_and_allow_deletion():
    raw = """=== FIXED_ISSUES ===
修正剑名
=== PATCHES ===
--- PATCH 1 ---
TARGET_TEXT:
旧剑
REPLACEMENT_TEXT:
青剑
--- END PATCH ---
--- PATCH 2 ---
TARGET_TEXT:
多余句子。
REPLACEMENT_TEXT:

--- END PATCH ---
=== RESPONSES ===
[]"""
    assert parse_patches(raw) == [Patch("旧剑", "青剑"), Patch("多余句子。", "")]


@pytest.mark.parametrize("heading", ["CONTENT", "REVISED_CONTENT"])
def test_full_content_mixed_with_patch_is_rejected(heading):
    raw = f"=== {heading} ===\n全文\n=== PATCHES ===\n--- PATCH 1 ---\nTARGET_TEXT:\n旧\nREPLACEMENT_TEXT:\n新\n--- END PATCH ---"
    assert parse_patches(raw) == []


def finding(scope="local", **kwargs):
    return {"scope": scope, "severity": "major", **kwargs}


@pytest.mark.parametrize("findings,expected", [
    ([finding()], "patch"), ([finding(), finding("structural")], "full"),
    ([finding("unknown")], "full"), ([{"severity": "major"}], "full"), ([], "full"),
    ([finding("structural", severity="hint"), finding()], "patch"),
])
def test_mode_requires_explicit_local_blockers(findings, expected):
    assert resolve_revise_mode({"unresolved": findings}) == expected


def test_audit_cannot_override_structural_rule_scope():
    state = {"report": {"findings": [finding("structural", conflict_key="k")]},
             "unresolved": [finding(conflict_key="k")]}
    assert resolve_revise_mode(state) == "full"


def test_rule_summary_without_corresponding_findings_is_conservative():
    state = {"report": {"summary": {"critical": 2}, "findings": []},
             "unresolved": [finding()]}
    assert resolve_revise_mode(state) == "full"


def test_omitted_scope_does_not_route_structural_issue_to_patch():
    f = Finding(conflict_key="k", conflict_type="character", severity="major")
    assert resolve_revise_mode({"unresolved": [f.model_dump()]}) == "full"
