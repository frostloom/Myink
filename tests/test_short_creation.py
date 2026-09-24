"""对话式短篇建书：先是纯逻辑（卡合并/就绪判定/premise），端点在后几个任务补。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from myink.book_setup import generate_short_creation_turn
from myink.db import new_session
from myink.models import AgentRun, ShortCreationMessage, ShortCreationSession
from myink.providers.base import ModelProvider, ModelResponse
from myink.short import creation
from myink.workflow import nodes, prompts

_STUB_TURN = ('{"reply": "主角最大的压力是什么？", "card": '
              '{"protagonist_pressure": "守着渡口的生计，也守着不肯走的儿子"}}')


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


def test_session_is_one_per_user_and_messages_are_ordered(temp_user):
    with new_session() as db:
        session = ShortCreationSession(user_id=uuid.UUID(temp_user), status="active",
                                       card=creation.default_card())
        db.add(session)
        db.commit()
        db.add_all([
            ShortCreationMessage(session_id=session.id, role="assistant", content="开场白"),
            ShortCreationMessage(session_id=session.id, role="user", content="我想写渡口"),
        ])
        db.commit()
        rows = db.scalars(select(ShortCreationMessage)
                          .where(ShortCreationMessage.session_id == session.id)
                          .order_by(ShortCreationMessage.id)).all()
    assert [row.content for row in rows] == ["开场白", "我想写渡口"]
    assert rows[0].id < rows[1].id


def test_session_tables_have_no_project_id_column():
    """同 StyleLibraryItem：带上 project_id 就会被套上租户策略。"""
    assert "project_id" not in ShortCreationSession.__table__.columns
    assert "project_id" not in ShortCreationMessage.__table__.columns


def test_session_user_id_is_unique(temp_user):
    from sqlalchemy.exc import IntegrityError
    with new_session() as db:
        db.add(ShortCreationSession(user_id=uuid.UUID(temp_user), status="active", card={}))
        db.commit()
        db.add(ShortCreationSession(user_id=uuid.UUID(temp_user), status="active", card={}))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_short_creation_messages_carry_history_then_the_current_card():
    messages = prompts.short_creation_messages(
        [{"role": "user", "content": "我想写个渡口的故事"},
         {"role": "assistant", "content": "主角的压力是什么？"}],
        {"working_title": "最后一班渡船", "chapter_count": 5})
    assert messages[0]["content"] == prompts.SYSTEM_SHORT_CREATION
    assert [m["role"] for m in messages[1:3]] == ["user", "assistant"]
    assert '"最后一班渡船"' in messages[-1]["content"]
    assert '"chapter_count": 5' in messages[-1]["content"]


def test_short_creation_prompt_imposes_the_product_rules():
    system = prompts.SYSTEM_SHORT_CREATION
    assert "只问一个" in system            # 一次抛三个问题，用户只会答第一个
    assert "立刻出卡" in system            # 冲突一明确就别再追问细节
    assert "确认，开写" in system          # 不许模型自己宣布已经建书/开写
    assert "留空" in system                # 空串 = 没有新信息，不是清空


def test_short_creation_turn_budget_is_smaller_than_a_plan():
    """一回合只是一段话 + 一张卡，给 1500 token 足够；给大了会鼓励它写小说。"""
    assert nodes._MAX_TOKENS["short_creation"] == 1500
    assert nodes._MAX_TOKENS["short_creation"] < nodes._MAX_TOKENS["short_plan"]


class _ChainStub(ModelProvider):
    """记下每次 generate 的入参，按调用次数排队返回原文（用完重复最后一项）。"""

    def __init__(self, contents: list[str], *, raises: bool = False):
        self._contents = contents
        self._raises = raises
        self.calls: list[dict] = []

    def name(self) -> str:
        return "short-plan-stub"

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None,
                 json_mode=False, tools=None, disable_thinking=False):
        if self._raises:
            raise RuntimeError("provider down")
        self.calls.append({"messages": messages, "max_tokens": max_tokens, "json_mode": json_mode})
        idx = min(len(self.calls) - 1, len(self._contents) - 1)
        return ModelResponse(content=self._contents[idx], model_id=model_id,
                             input_tokens=10, output_tokens=20)


@pytest.fixture
def chain_stub(monkeypatch):
    import myink.providers as providers_mod

    def _install(contents: list[str], *, raises: bool = False) -> _ChainStub:
        stub = _ChainStub(contents, raises=raises)
        monkeypatch.setattr(providers_mod, "default_provider", stub)
        return stub

    return _install


def test_short_creation_turn_returns_reply_and_card(temp_user, chain_stub):
    stub = chain_stub([_STUB_TURN])
    reply, patch, error, resp = generate_short_creation_turn(
        [{"role": "user", "content": "我想写个渡口故事"}], creation.default_card(),
        user_id=temp_user)
    assert error is None
    assert reply == "主角最大的压力是什么？"
    assert patch["protagonist_pressure"] == "守着渡口的生计，也守着不肯走的儿子"
    # 记账：一次 planner 调用、json_mode、额度取自 _MAX_TOKENS、role 标 Planner
    call = stub.calls[-1]
    assert call["json_mode"] is True
    assert call["max_tokens"] == nodes._MAX_TOKENS["short_creation"]


def test_short_creation_turn_survives_bad_json(temp_user, chain_stub):
    """模型吐了一整段散文：把原文当回复交出去，卡不动，error 记下来——用户重说一句就行。"""
    chain_stub(['当然可以！我先说说渡口这个意象……'])
    reply, patch, error, resp = generate_short_creation_turn(
        [{"role": "user", "content": "随便聊聊"}], creation.default_card(), user_id=temp_user)
    assert patch == {}
    assert "渡口" in reply
    assert error is not None and error.startswith("parse_error")


def test_short_creation_turn_records_an_account_level_run(temp_user, chain_stub):
    chain_stub([_STUB_TURN])
    with new_session() as db:
        generate_short_creation_turn([{"role": "user", "content": "hi"}],
                                     creation.default_card(), user_id=temp_user, db=db)
        db.commit()
        row = db.scalar(select(AgentRun).where(AgentRun.user_id == uuid.UUID(temp_user)))
    assert row is not None and row.node == "short_creation" and row.role == "Planner"
