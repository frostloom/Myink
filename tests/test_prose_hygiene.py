"""正文卫生四则（对齐 inkos post-write-validator 的同类硬规则）。

阈值一律取 inkos 代码的实际值：连续「了」字 >= 6 句、段落 > 300 字且 >= 2 段
（inkos 自己的注释写成 3 句 / 50-250 字，与代码不符，这里以代码为准）。
"""

from myink.validation.l1 import (
    L1Validator,
    _chapter_refs,
    _long_paragraphs,
    _max_consecutive_le,
    _sermon_words,
)

REALM_ORDER = ["炼气", "筑基", "金丹", "元婴", "化神", "大乘", "渡劫"]


def _findings(draft: str, seq: int = 1) -> dict[str, dict]:
    fs = L1Validator(REALM_ORDER).prose_hygiene_check(
        None, project_id=None, chapter_seq=seq, draft=draft)
    return {f.conflict_key: f.model_dump(mode="json") for f in fs}


# ---- 章节号指称 ----

def test_chapter_refs_matches_arabic_chapter_number_forms():
    assert _chapter_refs("见第33章。") == ["第33章"]
    assert _chapter_refs("第 3 章里提过") == ["第 3 章"]
    assert _chapter_refs("chapter 33 said so") == ["chapter 33"]
    assert _chapter_refs("Chapter 7") == ["Chapter 7"]


def test_chapter_refs_ignores_chinese_numerals_and_dedupes():
    # 「第一章」不含阿拉伯数字，是正常行文，不算指称
    assert _chapter_refs("第一章就埋了这个伏笔") == []
    assert _chapter_refs("第3章和第3章都提过") == ["第3章"]


def test_chapter_ref_is_critical_so_it_blocks():
    found = _findings("他翻到第12章，忽然明白。")
    assert len(found) == 1
    only = next(iter(found.values()))
    assert only["severity"] == "critical"
    assert only["conflict_type"] == "style"
    assert "第12章" in only["evidence"][0]["quote"]


# ---- 作者说教词 ----

def test_sermon_words_reports_each_hit():
    hits = _sermon_words("显然他没懂，众所周知这事不重要。")
    assert hits == ["显然", "众所周知"]


def test_sermon_is_hint_only():
    found = _findings("显然，他不会回来了。")
    assert len(found) == 1
    only = next(iter(found.values()))
    assert only["severity"] == "hint"
    assert "显然" in only["evidence"][0]["quote"]


# ---- 连续「了」字 ----

def test_consecutive_le_at_threshold_is_flagged():
    draft = "他来了。她走了。天黑了。雨停了。灯灭了。门开了。"
    assert _max_consecutive_le(draft) == 6
    found = _findings(draft)
    assert len(found) == 1
    assert next(iter(found.values()))["severity"] == "hint"


def test_consecutive_le_below_threshold_is_silent():
    draft = "他来了。她走了。天黑了。雨停了。灯灭了。窗外很静。"
    assert _max_consecutive_le(draft) == 5
    assert _findings(draft) == {}


def test_consecutive_le_resets_on_sentence_without_le():
    # 中间夹一句没有「了」的，链就断了，最长连续仍是 3
    draft = "他来了。她走了。天黑了。四下无声。他又站住了。雨停了。灯灭了。"
    assert _max_consecutive_le(draft) == 3


# ---- 段落过长 ----

def test_long_paragraphs_boundary_is_strictly_over_300():
    assert _long_paragraphs("甲" * 300) == []
    assert _long_paragraphs("甲" * 301) == [301]


def test_single_long_paragraph_is_not_enough():
    assert _findings("甲" * 400) == {}


def test_two_long_paragraphs_are_flagged_as_hint():
    draft = "甲" * 301 + "\n\n" + "乙" * 305
    found = _findings(draft)
    assert len(found) == 1
    only = next(iter(found.values()))
    assert only["severity"] == "hint"
    assert "305" in only["evidence"][0]["quote"]


# ---- 组合与空输入 ----

def test_clean_draft_produces_nothing():
    assert _findings("他推门进来，屋里没人。桌上那盏灯还亮着。") == {}


def test_empty_draft_produces_nothing():
    assert L1Validator(REALM_ORDER).prose_hygiene_check(
        None, project_id=None, chapter_seq=1, draft=None) == []


def test_all_four_rules_can_fire_together():
    draft = (
        "第9章提过这事。显然他忘了。\n\n"
        + "他来了。她走了。天黑了。雨停了。灯灭了。门开了。\n\n"
        + "甲" * 301 + "\n\n" + "乙" * 301
    )
    assert len(_findings(draft)) == 4
