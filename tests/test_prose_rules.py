"""验证去 AI 味规则到达实际模型消息边界；不把提示词接入当作文笔效果评测。"""
import pytest

from myink.workflow import prompts


@pytest.mark.parametrize("messages", [
    lambda: prompts.write_messages({}, {}),
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
    lambda: prompts.audit_messages("他推开门。", {}, {}, 1),
    lambda: prompts.short_review_messages({"chapter_count": 2}, "他推开门。"),
], ids=["long-audit", "short-review"])
def test_editorial_review_receives_evidence_and_severity_policy(messages):
    from myink.workflow.prose_rules import PROSE_REVIEW_RULES

    assert PROSE_REVIEW_RULES in messages()[0]["content"]


@pytest.mark.parametrize("builder,role", [
    (lambda: prompts.write_messages({}, {}), "writer"),
    (lambda: prompts.revise_messages("原稿", [], 1), "writer"),
    (lambda: prompts.patch_messages({"draft": "原稿", "chapter_seq": 1}), "writer"),
    (lambda: prompts.short_write_messages({"chapter_count": 1}), "writer"),
    (lambda: prompts.short_continue_messages({"chapter_count": 1}, "原稿", [1]), "writer"),
    (lambda: prompts.short_revise_messages({"chapter_count": 1}, "原稿", {}), "writer"),
    (lambda: prompts.audit_messages("原稿", {}, {}, 1), "audit"),
    (lambda: prompts.short_review_messages({"chapter_count": 1}, "原稿"), "audit"),
])
def test_explicit_prose_selection_controls_real_messages(builder, role):
    from myink.workflow.prose_rules import PROSE_RULES, PROSE_REVIEW_RULES
    from myink.writing_resource_runtime import bind_resources

    header = "【中文小说表达规则】" if role == "writer" else "【中文小说表达审核】"
    with bind_resources({"configured": False}):
        legacy = builder()
    assert sum(m["content"].count(header) for m in legacy) == 1

    with bind_resources({"configured": True, "selections": []}):
        unselected = builder()
    assert not any(header in m["content"] for m in unselected)

    text = PROSE_RULES[:PROSE_RULES.index("- 输出前")].rstrip() if role == "writer" else PROSE_REVIEW_RULES
    for publication in (text, "仅采用发布的新表达要求", text):
        with bind_resources({"configured": True, "selections": [{
            "kind": "expression_rule", "name": "中文小说表达", "body": {"roles": {role: publication}},
        }]}):
            selected = builder()
        assert sum(m["content"].count(publication) for m in selected) == 1
        if publication != text:
            assert not any(header in m["content"] for m in selected)
