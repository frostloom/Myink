"""验证去 AI 味规则到达实际模型消息边界；不把提示词接入当作文笔效果评测。"""
import pytest

from myink.workflow import prompts


@pytest.mark.parametrize("messages", [
    lambda: prompts._write_messages({}, {}),
    lambda: prompts.revise_messages("他推开门。", [], 1),
    lambda: prompts.patch_messages({"draft": "他推开门。", "chapter_seq": 1}),
    lambda: prompts.short_write_messages({"chapter_count": 2}),
    lambda: prompts.short_continue_messages({"chapter_count": 2}, "正文", [2]),
    lambda: prompts.short_revise_messages({"chapter_count": 2}, "正文", {}),
], ids=["long-write", "long-revise", "long-patch", "short-write", "short-continue", "short-revise"])
def test_prose_policy_reaches_generation_and_revision(messages):
    from myink.workflow.prose_rules import PROSE_RULES

    system = messages()[0]
    assert system["role"] == "system"
    assert system["content"].count(PROSE_RULES) == 1


@pytest.mark.parametrize("messages", [
    lambda: prompts._audit_messages("他推开门。", {}, {}, 1),
    lambda: prompts.short_review_messages({"chapter_count": 2}, "他推开门。"),
], ids=["long-audit", "short-review"])
def test_editorial_review_receives_evidence_and_severity_policy(messages):
    from myink.workflow.prose_rules import PROSE_REVIEW_RULES

    assert PROSE_REVIEW_RULES in messages()[0]["content"]
