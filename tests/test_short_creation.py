"""对话式短篇建书：先是纯逻辑（卡合并/就绪判定/premise），端点在后几个任务补。"""

from __future__ import annotations

from myink.short import creation


def test_card_patch_drops_blanks_so_the_model_cannot_erase_user_edits():
    """模型这轮没把握的字段会留空串——那是「没有新信息」，不是「清空」。"""
    assert creation.card_patch({"working_title": "  ", "genre": "悬疑", "nonsense": "x"}) == {"genre": "悬疑"}


def test_merge_model_card_keeps_the_users_value_when_the_model_sends_blank():
    current = creation.default_card() | {"working_title": "最后一班渡船"}
    merged = creation.merge_model_card(current, {"working_title": "  ", "genre": "悬疑"})
    assert merged["working_title"] == "最后一班渡船"
    assert merged["genre"] == "悬疑"


def test_merge_user_card_honors_a_deliberate_clear():
    """用户在右栏把字段删空是本人的决定，与模型留空不一样。"""
    current = creation.default_card() | {"direction": "一句话方向"}
    assert creation.merge_user_card(current, {"direction": ""})["direction"] == ""


def test_card_normalize_keeps_numbers_and_drops_unknown_keys():
    assert creation.card_normalize({"chapter_count": 8, "junk": 1}) == {"chapter_count": 8}


def test_a_quoted_number_is_read_as_a_number():
    """模型常把数字写成字符串。卡里的章数必须是数——它一路流到建书与篇幅校验的数值比较里。"""
    assert creation.card_patch({"chapter_count": " 8 ", "chars_per_chapter": "五"}) == {"chapter_count": 8}


def test_card_ready_needs_all_seven_text_fields():
    fields = creation.REQUIRED_CARD_FIELDS
    assert len(fields) == 7
    card = {field: "填好了" for field in fields} | {"chapter_count": 5, "chars_per_chapter": 4000}
    assert creation.card_ready(card) is True
    for field in fields:
        assert creation.card_ready(card | {field: "   "}) is False


def test_default_card_carries_the_short_form_defaults():
    card = creation.default_card()
    assert card["chapter_count"] == creation.DEFAULT_CHAPTER_COUNT == 5
    assert card["chars_per_chapter"] == creation.DEFAULT_CHARS_PER_CHAPTER == 4000
    assert creation.card_ready(card) is False


def test_card_premise_feeds_the_plan_generator_one_string():
    premise = creation.card_premise(creation.default_card() | {
        "direction": "一句话方向", "conflict_core": "核心冲突", "plot_sketch": "大致情节"})
    assert premise == "一句话方向\n\n核心冲突：核心冲突\n\n大致情节：大致情节"
