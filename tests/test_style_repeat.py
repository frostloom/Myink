"""句式禁令：任何题材，同一句内「不是…是…」（含「不是…而是…」「不是…，是…」）或连续排比出现
一次即 critical。

不读文风档案，不按词频计数。普通用词和未达结构的句子不报。
"""

from __future__ import annotations

import uuid

import pytest

from myink.db import tenant_session
from myink.validation.l1 import L1Validator, _prose_ban_quotes
from myink.validation.service import ValidationService

REALM_ORDER = ["炼气", "筑基", "金丹", "元婴", "化神", "大乘", "渡劫"]


@pytest.mark.parametrize("ending", ["。", "！", "？", "!", "?", "\n", "\r\n"])
def test_prose_evidence_includes_right_clause_without_next_sentence(ending):
    draft = "他不是害怕，是不愿意走" + ending + "门外有人。"
    assert _prose_ban_quotes(draft) == ["不是害怕，是不愿意走"]


def test_not_but_evidence_includes_right_clause_at_end_of_text():
    assert _prose_ban_quotes("他不是胆怯，而是在等援兵") == ["不是胆怯，而是在等援兵"]


def test_prose_evidence_keeps_original_whitespace():
    assert _prose_ban_quotes("他不是害怕, 是  不愿意走。") == ["不是害怕, 是  不愿意走"]


def test_long_prose_evidence_is_bounded_and_remains_an_exact_excerpt():
    draft = "他不是害怕，是不愿意走" + "远" * 500
    quotes = _prose_ban_quotes(draft)
    assert len(quotes) == 1
    assert "是不愿意走" in quotes[0]
    assert quotes[0] in draft
    assert len(quotes[0]) <= 160


def test_prose_evidence_bounds_whitespace_inside_the_detected_match():
    draft = "不是害怕，" + " " * 500 + "是不愿意走。"
    quotes = _prose_ban_quotes(draft)
    assert len(quotes) == 1
    assert quotes[0] in draft
    assert len(quotes[0]) <= 160


def test_prose_evidence_does_not_cross_a_newline_inside_the_match():
    # 既有检测式的逗号后允许空白；本次不改判定，只限制展示证据的范围。
    assert _prose_ban_quotes("不是害怕，\n是不愿意走。") == ["不是害怕，"]


def _check(pid: str, draft, seq: int = 15) -> list[dict]:
    with tenant_session(pid) as db:
        findings = L1Validator(REALM_ORDER).prose_ban_check(
            db, project_id=uuid.UUID(pid), chapter_seq=seq, draft=draft)
        return [f.model_dump(mode="json") for f in findings]


def test_not_but_is_critical(temp_project):
    """一处「不是…而是…」即 style/critical，不看文风档案。"""
    fs = _check(temp_project, "他不是不知道前路凶险，而是早已没有退路。")
    assert len(fs) == 1, fs
    assert fs[0]["conflict_type"] == "style"
    assert fs[0]["severity"] == "critical"
    assert fs[0]["source"] == "L1"
    assert "而是" in fs[0]["evidence"][0]["quote"]


def test_not_comma_is_critical(temp_project):
    """「不是…，是…」同样拦截。"""
    fs = _check(temp_project, "他不是害怕，是不愿意走。")
    assert len(fs) == 1, fs
    assert "是不愿意" in fs[0]["evidence"][0]["quote"]


def test_not_is_without_a_comma_is_critical(temp_project):
    """没有逗号、也没有「而是」的对举同样算：否定与改口在同一句里就够了。"""
    assert _prose_ban_quotes("他不是坏人是个好人。") == ["不是坏人是个好人"]
    fs = _check(temp_project, "他不是坏人是个好人。")
    assert len(fs) == 1, fs
    assert fs[0]["severity"] == "critical"


@pytest.mark.parametrize("draft", [
    "他不是不想去，只是没时间。",          # 只是：后一个「是」是词的一部分
    "他不是不知道轻重，就是不肯低头。",     # 就是
    "他不是不怕，但是不能退。",            # 但是
    "这到底是不是真的？",                 # 是不是：前一个「是」把「不是」挡住了
    "他不是不想去，也不是不愿意。",         # 不是A不是B：只有一个「不是」在对举
])
def test_words_containing_shi_pass(temp_project, draft):
    """连词/副词里的「是」不是禁句；否则每一章都会命中。"""
    assert _prose_ban_quotes(draft) == []
    assert _check(temp_project, draft) == []


def test_parallel_clauses_critical(temp_project):
    """同一句里连续三个结构相同的分句算排比。"""
    fs = _check(temp_project, "他的剑很快，他的刀很沉，他的心很冷。门外有人。")
    assert len(fs) == 1, fs
    assert "他的剑很快" in fs[0]["evidence"][0]["quote"]


def test_plain_words_and_negation_pass(temp_project):
    """仿佛、冷笑、单独的「不是」都不算禁句。"""
    draft = "仿佛夜色沉沉。他冷笑一声。他不是坏人。他走进大殿，看见秦虎，手里还握着剑。"
    assert _check(temp_project, draft) == []


def test_no_draft_skips(temp_project):
    assert _check(temp_project, None) == []
    assert _check(temp_project, "") == []


def test_service_wiring_blocks(temp_project):
    """经 ValidationService.validate 编排后，禁句以 critical 进入报告。"""
    draft = "他不是畏惧强敌，而是害怕辜负。"
    with tenant_session(temp_project) as db:
        report = ValidationService(REALM_ORDER).validate(
            db, project_id=uuid.UUID(temp_project), chapter_seq=15,
            candidates=[], draft=draft)
    assert report.summary["critical"] == 1
    assert any(f.severity == "critical" and "而是" in (f.evidence[0].quote if f.evidence else "")
               for f in report.findings)
