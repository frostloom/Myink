"""短篇整篇草稿的宽容解析（SHORT-FORM-PLAN Phase 4）。

写手是「一次调用写完 5–10 章」，所以拆章只能靠模型自己打的标记。模型不保证听话，
于是四级兜底：block 标记 → markdown 标题 → 数字前缀 → 均分。

**解析器绝不抛异常、绝不拦稿**：拆不出来就回空串，让 `find_empty_chapters` 去数，
后面还有一次续写（Phase 4 `continue_draft`）。抛异常的解析器会把一次 160 秒的生成
变成一次 500。
"""

from __future__ import annotations

import pytest

from myink.workflow.short_parse import (CHAPTER_HEADING, find_empty_chapters, parse_short_draft,
                                        render_short_draft)

SCENES = ["渡船靠岸时林砚还在数手里的铜钱。", "老人把最后一盏灯吹了。",
          "江面上浮起来一盏没人点的灯。", "林砚在船板上刻下父亲的名字。",
          "天亮时渡口一个人也没有。"]


def _tagged(n: int = 5) -> str:
    return "\n\n".join(CHAPTER_HEADING.format(seq=i + 1) + "\n" + SCENES[i] for i in range(n))


def _markdown(n: int = 5) -> str:
    return "\n\n".join(f"## 第 {i + 1} 章 标题\n{SCENES[i]}" for i in range(n))


def _prefixed(n: int = 5) -> str:
    return "\n\n".join(f"第 {i + 1} 章 标题\n{SCENES[i]}" for i in range(n))


def test_the_tagged_heading_is_what_the_writer_is_asked_for():
    """标记格式只在一处定义：Phase 3 的写手 prompt 与这里的解析器共用同一个常量，
    免得「prompt 要 `=== CHAPTER N CONTENT ===`、解析器认 `## 第 N 章`」这种接口错位。

    取材参照实现（决策文档 §四 点名的 `=== CHAPTER N CONTENT ===`）。
    """
    text = CHAPTER_HEADING.format(seq=3)
    assert text.startswith("===") and text.endswith("===")
    assert "CHAPTER 3" in text and "CONTENT" in text


def test_a_drifting_title_marker_line_is_tolerated():
    """模型爱多打一行 `=== CHAPTER N TITLE ===`（参照实现的产物形状就是 TITLE + CONTENT 两行）。

    容忍它的方式是**把 TITLE 行删掉**，而不是让它也当边界——否则每章会被切成两格，
    正文整体错位一格，比空章难查得多。
    """
    text = "\n\n".join(f"=== CHAPTER {i + 1} TITLE ===\n{CHAPTER_HEADING.format(seq=i + 1)}\n{SCENES[i]}"
                       for i in range(3))
    chapters = parse_short_draft(text, 3)
    assert [c.strip() for c in chapters] == SCENES[:3]


def test_the_preamble_before_the_first_marker_is_dropped():
    """整篇标题那行（`=== SHORT_FICTION_TITLE ===` 之类）不是章，别混进第 1 章。"""
    text = "=== SHORT_FICTION_TITLE ===\n最后一班渡船\n\n" + _tagged(2)
    chapters = parse_short_draft(text, 2)
    assert "最后一班渡船" not in chapters[0]
    assert chapters[0].strip() == SCENES[0]


@pytest.mark.parametrize("build", [_tagged, _markdown, _prefixed],
                         ids=["block-marker", "markdown-heading", "number-prefix"])
def test_three_levels_of_markers_all_split_into_the_same_chapters(build):
    chapters = parse_short_draft(build(5), 5)
    assert len(chapters) == 5
    for i, scene in enumerate(SCENES):
        assert scene in chapters[i], f"第 {i + 1} 章的内容应落在第 {i + 1} 个位置"


def test_the_marker_line_itself_is_dropped_from_the_body():
    """标记行只是路牌，不是正文——章节标题另有出处（方案里的 title，Phase 5）。"""
    chapters = parse_short_draft(_tagged(3), 3)
    assert all("===" not in chapter for chapter in chapters)
    assert chapters[0].strip() == SCENES[0]


def test_a_chapter_the_model_forgot_becomes_an_empty_slot_not_a_shift():
    """模型只写了前 3 章 → 后两章留空、**不能把第 3 章挤到第 4 格**。

    位置错位比空章危险得多：续写会以为「第 3 章有了」，而第 4 章的内容被当成第 3 章落库。
    """
    text = "\n\n".join(CHAPTER_HEADING.format(seq=i + 1) + "\n" + SCENES[i]
                       for i in range(3))
    chapters = parse_short_draft(text, 5)
    assert chapters[2].strip() == SCENES[2]
    assert chapters[3] == "" and chapters[4] == ""


def test_a_gap_in_the_numbering_still_places_chapters_by_their_number():
    """中间的章漏打标记（1、2、4、5）：章号仍然可信，**别把第 4 章塞进第 3 格**。

    当初的判据是「章号必须构成 1..块数 的排列」，把「缺号」和「章号不可信」混成了一件事。
    缺号恰恰是补写要靠的确定状态：位置对了才知道缺的是第 3 章。
    """
    text = "\n\n".join(CHAPTER_HEADING.format(seq=i) + "\n" + SCENES[i - 1]
                       for i in (1, 2, 4, 5))
    chapters = parse_short_draft(text, 5)
    assert chapters[2] == "", "猜不出第 3 章写了什么，就别往那一格放东西"
    assert chapters[3].strip() == SCENES[3] and chapters[4].strip() == SCENES[4]


def test_document_order_wins_when_the_numbering_is_unusable():
    """章号重复或越界时（模型爱把「第 5 章」写成「第 五 章」再退化成 5 次「第 1 章」），
    按出现顺序装配仍能给出可用的拆分。"""
    text = "\n\n".join(CHAPTER_HEADING.format(seq=1) + "\n" + scene
                       for scene in SCENES[:3])
    chapters = parse_short_draft(text, 3)
    assert [c.strip() for c in chapters] == SCENES[:3]


def test_no_marker_at_all_falls_back_to_an_even_split():
    """模型整篇不打卡 → 按段落均分（最后一道兜底，宁可切歪也不能让整篇丢在地上）。"""
    body = "\n\n".join(SCENES * 4)
    chapters = parse_short_draft(body, 5)
    assert len(chapters) == 5
    assert all(chapter.strip() for chapter in chapters)
    assert "".join(chapters).count("渡船靠岸时") == 4, "内容不丢"


def test_a_numbered_line_inside_plain_prose_is_not_mistaken_for_a_chapter_marker():
    """散文里以「3：」开头的行也会命中数字前缀那一级。误判的代价不是切歪，是**正文消失**：
    `_split` 丢掉标记之前的全部内容，于是「3：」之前的正文没了，剩下的那一块还会被
    当成完整的一章落库，任务照样报 done、warning 为 null。

    这一级只认「从 1 起、严格递增」的编号——那才是一份章节清单的样子。
    """
    prose = ("林砚把铜钱收进袖口时，渡船已经离岸了。风从江面过来，把灯笼吹得贴住桅杆。\n\n"
             "父亲说过的话他记了很多年。\n\n"
             "3：渡口的人从来不看船票，只看鞋底有没有泥。\n\n"
             "他低头看了看自己的鞋，鞋帮上全是干了的泥。")
    chapters = parse_short_draft(prose, 3)
    joined = "".join(chapters)
    assert "林砚把铜钱收进袖口" in joined, "标记之前的正文不能被当前言丢掉"
    assert "父亲说过的话他记了很多年" in joined
    assert "鞋帮上全是干了的泥" in joined


def test_a_numbered_list_that_starts_at_one_is_still_trusted():
    """「从 1 起、严格递增」的编号仍要按章号归位——放宽这一级不能顺手废掉它的用处：
    模型用 `1.` `2.` `3.` 分段时，缺号那一格仍要留空给补写（与 block 标记同级的行为）。"""
    text = "1. 渡船靠岸时林砚还在数手里的铜钱。\n\n3. 江面上浮起来一盏没人点的灯。"
    chapters = parse_short_draft(text, 3)
    assert chapters[0].strip() == "渡船靠岸时林砚还在数手里的铜钱。"
    assert chapters[1] == "", "缺号是可信的：位置对了才知道缺的是第 2 章"
    assert chapters[2].strip() == "江面上浮起来一盏没人点的灯。"


def test_even_split_never_drops_the_tail():
    """最后一段必须收尾——丢了尾巴就是「结尾没了」，短篇最不能接受的一种坏。"""
    chapters = parse_short_draft("\n\n".join(SCENES * 3), 4)
    assert SCENES[-1] in chapters[-1]


@pytest.mark.parametrize("text", ["", "   \n\n  ", "没有换行的连续文字" * 200])
def test_degenerate_text_returns_empty_slots_instead_of_raising(text):
    chapters = parse_short_draft(text, 5)
    assert len(chapters) == 5
    assert all(isinstance(chapter, str) for chapter in chapters)


def test_fewer_markers_than_chapters_still_returns_the_asked_length():
    chapters = parse_short_draft(_tagged(2), 10)
    assert len(chapters) == 10
    assert chapters[0].strip() and chapters[1].strip()
    assert not any(chapters[2:])


# ---------- render_short_draft ----------


def test_render_short_draft_puts_the_marker_lines_back():
    """审稿与改稿看的是「拆好再装回去」的草稿：读者读的就是这个形状。

    直接回喂原始输出的话，模型漏打标记时审稿看到的是一堵墙，而不是 5 章。
    """
    text = render_short_draft(SCENES)
    assert CHAPTER_HEADING.format(seq=1) in text and CHAPTER_HEADING.format(seq=5) in text
    assert parse_short_draft(text, 5) == SCENES


def test_render_short_draft_skips_the_empty_slots():
    """空章不装进草稿——审稿不该看见一排空标记。"""
    text = render_short_draft(["a", "", "c"])
    assert CHAPTER_HEADING.format(seq=2) not in text
    assert parse_short_draft(text, 2) == ["a", "c"]


# ---------- find_empty_chapters ----------


def test_find_empty_chapters_reports_one_based_numbers():
    assert find_empty_chapters(["a", "", "c"]) == [2]


def test_find_empty_chapters_treats_whitespace_as_empty():
    """模型「写了」一整章的换行，等于没写。"""
    assert find_empty_chapters(["a", "  \n\t ", "c"]) == [2]


def test_find_empty_chapters_is_empty_when_every_chapter_has_a_body():
    assert find_empty_chapters(["a", "b"]) == []