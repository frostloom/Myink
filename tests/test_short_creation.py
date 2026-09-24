"""对话式短篇建书：先是纯逻辑（卡合并/就绪判定/premise），端点在后几个任务补。"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete as sa_delete, select

from conftest import identity_headers
from myink.api.main import app
from myink.book_setup import generate_short_creation_turn
from myink.db import ensure_user_environment, new_session, tenant_session
from myink.memory.repository import get_settings, get_volume_outline
from myink.models import AgentRun, Project, ShortCreationMessage, ShortCreationSession, StyleLibraryItem
from myink.providers.base import ModelProvider, ModelResponse
from myink.short import creation
from myink.workflow import nodes, prompts

# 建表是幂等的；不调它，单独跑本模块时 accounts 的 environment 列可能还没补上。
ensure_user_environment()
client = TestClient(app)

_STUB_TURN = ('{"reply": "主角最大的压力是什么？", "card": '
              '{"protagonist_pressure": "守着渡口的生计，也守着不肯走的儿子"}}')

# 模型这轮在暂定名上留空串：这是「没有新信息」，不是「清空」。
_STUB_TURN_BLANK_TITLE = ('{"reply": "环境先放一放，主角的压力是什么？", "card": '
                          '{"working_title": "", "protagonist_pressure": "守着渡口的生计"}}')


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


def test_non_finite_numbers_are_ignored_not_fatal():
    """无穷 / NaN 经 `int()` 会抛 OverflowError 或 ValueError → 端点直接 500。

    数字位与文本位都收得到它们（模型把 `1e400` 写成字符串同样常见），所以两条分支都要挡。
    """
    for bad in (float("inf"), float("-inf"), float("nan"), 1e400, "inf", "-inf", "nan", "1e400"):
        out = creation.merge_model_card({"chapter_count": 5}, {"chapter_count": bad})
        assert out["chapter_count"] == 5, f"{bad!r} 应当被当作「没给」，而不是炸掉或写进去"


def test_numbers_never_land_in_text_fields():
    """文本位收数字 → `Project(title=42)` 在建书那步崩成 500。类型不对就当没给。"""
    out = creation.merge_model_card({}, {"working_title": 42, "genre": {"x": 1}, "chapter_count": 3})
    assert "working_title" not in out
    assert "genre" not in out
    assert out["chapter_count"] == 3                     # 数字位照收，别一刀切


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


def test_short_creation_prompt_is_a_collaborator_not_a_questionnaire():
    """聊天的口径是「合作者」：普通讨论直接答，三样一明确就把卡填满。

    反面同样承重——「只问一个」是问卷机的口径，删掉之后不许再溜回来。
    """
    system = prompts.SYSTEM_SHORT_CREATION
    assert "直接回答" in system
    assert "填满" in system
    assert "只问一个" not in system


def test_short_creation_prompt_imposes_the_product_rules():
    system = prompts.SYSTEM_SHORT_CREATION
    assert "直接回答" in system            # 普通讨论正常答，不拿反问凑回合
    assert "填满" in system                # 关键两样一明确就把卡填满，不再逐项追问
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


def test_get_opens_a_session_with_a_fixed_greeting(temp_user):
    out = client.get("/api/v1/short/creation", headers=identity_headers(temp_user)).json()
    assert out["ready"] is False
    assert out["session"]["status"] == "active"
    assert out["session"]["card"]["chapter_count"] == 5
    assert len(out["messages"]) == 1 and out["messages"][0]["role"] == "assistant"
    # 开场白不调模型：首次进页面不该等一次网络
    assert out["messages"][0]["model_id"] is None


def test_posting_a_message_appends_both_sides_and_updates_the_card(temp_user, chain_stub):
    chain_stub([_STUB_TURN])                       # 不装桩这轮拿不到方案卡增量
    client.get("/api/v1/short/creation", headers=identity_headers(temp_user))
    out = client.post("/api/v1/short/creation/messages",
                      json={"content": "我想写个渡口故事"},
                      headers=identity_headers(temp_user)).json()
    assert [m["role"] for m in out["messages"]] == ["assistant", "user", "assistant"]
    assert out["messages"][-1]["content"] == "主角最大的压力是什么？"
    assert out["session"]["card"]["protagonist_pressure"].startswith("守着渡口")
    assert out["messages"][-1]["cost_est"] >= 0


def test_an_empty_model_field_keeps_what_the_user_already_wrote(temp_user, chain_stub):
    """Review Focus 1：模型在暂定名上回空串，不许冲掉用户已经写好的名字。

    端点级的：handler 是「先合用户卡、再合模型卡」（`routes_short_creation.py:102→107`），
    只测 `merge_model_card` 抓不到「两步顺序被写反」这类改动，所以必须走 POST /messages。
    第二轮**不带** card——带上就等于给实现留了「至少用户卡还兜着」的退路，顺序写反也照样绿。
    """
    chain_stub([_STUB_TURN_BLANK_TITLE])           # 不装桩这轮拿不到「空串」这个输入
    client.post("/api/v1/short/creation/messages",
                json={"content": "渡口，冷白描", "card": {"working_title": "渡口"}},
                headers=identity_headers(temp_user))
    out = client.post("/api/v1/short/creation/messages",
                      json={"content": "接着说说环境"},
                      headers=identity_headers(temp_user)).json()
    assert out["session"]["card"]["working_title"] == "渡口", "空串不该覆盖用户已写的值"
    # 同一轮里模型真正给了值的字段照常落下来（空串不留 ≠ 整张卡不留）
    assert out["session"]["card"]["protagonist_pressure"] == "守着渡口的生计"


def test_ready_flips_only_when_all_seven_fields_are_filled(temp_user, chain_stub):
    chain_stub([_STUB_TURN])
    client.get("/api/v1/short/creation", headers=identity_headers(temp_user))
    body = {"content": "都聊清了", "card": {field: "有" for field in creation.REQUIRED_CARD_FIELDS}}
    out = client.post("/api/v1/short/creation/messages", json=body,
                      headers=identity_headers(temp_user)).json()
    assert out["ready"] is True


def test_a_bad_model_turn_keeps_the_session_alive(temp_user, chain_stub):
    """Review Focus 2：坏 JSON 不能 500，也不能丢会话。"""
    chain_stub(["这是一段没有 JSON 的散文。"])
    client.get("/api/v1/short/creation", headers=identity_headers(temp_user))
    resp = client.post("/api/v1/short/creation/messages", json={"content": "聊两句"},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 200
    out = resp.json()
    assert out["messages"][-1]["error"].startswith("parse_error")
    assert out["messages"][-1]["content"] == "这是一段没有 JSON 的散文。"
    assert out["session"]["card"]["chapter_count"] == 5      # 卡没被毁


def test_reset_clears_the_conversation(temp_user):
    client.get("/api/v1/short/creation", headers=identity_headers(temp_user))
    assert client.delete("/api/v1/short/creation", headers=identity_headers(temp_user)).status_code == 200
    out = client.get("/api/v1/short/creation", headers=identity_headers(temp_user)).json()
    assert len(out["messages"]) == 1                      # 只剩新的开场白
    assert out["session"]["card"]["direction"] == ""


def test_messages_rejects_an_empty_content(temp_user):
    client.get("/api/v1/short/creation", headers=identity_headers(temp_user))
    resp = client.post("/api/v1/short/creation/messages", json={"content": "   "},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 400


_FULL_CARD = {field: "有" for field in creation.REQUIRED_CARD_FIELDS} | {
    "working_title": "最后一班渡船", "genre": "现实主义", "chapter_count": 3,
    "chars_per_chapter": 4000,
}


def _short_outline(chapter_count: int = 3) -> dict:
    """一份能过 `validate_short_outline` 的最小短篇方案。

    章数必须与 `_FULL_CARD` 的 `chapter_count` 对上（这里都是 3），否则落库那步的校验会拒。
    """
    chapters = [{"chapter_seq": i, "title": f"第 {i} 章", "goal": f"第 {i} 章的目标"}
                for i in range(1, chapter_count + 1)]
    return {"objective": "林砚查清父亲之死并让青溪渡停航", "chapter_count": chapter_count,
            "volumes": [{"volume_seq": 1, "title": "全篇 · 最后一班渡船", "goal": "让渡口停航",
                         "chapter_start": 1, "chapter_end": chapter_count, "chapters": chapters}]}


_PLAN_JSON = json.dumps(_short_outline(), ensure_ascii=False)


def _seed_session(user: str, card: dict | None = None):
    """直接把会话摆好：这些用例验的是 commit，不验聊到这一步的过程。"""
    with new_session() as db:
        session = ShortCreationSession(user_id=uuid.UUID(user), status="active",
                                       card=creation.merge_user_card(creation.default_card(), card or _FULL_CARD))
        db.add(session)
        db.commit()


def test_commit_builds_a_ready_short_book_with_a_persisted_plan(temp_user, chain_stub):
    chain_stub([_PLAN_JSON])
    _seed_session(temp_user)
    out = client.post("/api/v1/short/creation/commit", json={},
                      headers=identity_headers(temp_user)).json()
    with new_session() as db:
        project = db.get(Project, uuid.UUID(out["project_id"]))
        assert project.form == "short"
        assert project.creation_status == "ready"
        assert project.creation_context["chapter_count"] == 3
        assert project.creation_context["creation_conversation"]["conflict_core"] == "有"
    with tenant_session(out["project_id"]) as tdb:
        outline = get_volume_outline(tdb, uuid.UUID(out["project_id"]), 1)
    assert outline is not None and len(outline.outline["volumes"][0]["chapters"]) == 3


def test_commit_refuses_an_incomplete_card(temp_user):
    _seed_session(temp_user, {"working_title": "半张卡"})
    resp = client.post("/api/v1/short/creation/commit", json={},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "CARD_INCOMPLETE"


def test_commit_twice_does_not_build_a_second_book(temp_user, chain_stub):
    """Review Focus 4 前半（手滑再点一次）：会话已 committed，第二次是 409，不会建出第二本。"""
    chain_stub([_PLAN_JSON])
    _seed_session(temp_user)
    first = client.post("/api/v1/short/creation/commit", json={},
                        headers=identity_headers(temp_user)).json()
    second = client.post("/api/v1/short/creation/commit", json={},
                         headers=identity_headers(temp_user))
    assert second.status_code == 409                     # 会话已 committed
    assert second.json()["detail"] == "SESSION_COMMITTED"
    with new_session() as db:
        assert db.query(Project).filter(Project.user_id == uuid.UUID(temp_user)).count() == 1
        assert db.scalar(select(ShortCreationSession.book_id)
                         .where(ShortCreationSession.user_id == uuid.UUID(temp_user))) is not None


def test_commit_retry_after_a_plan_failure_reuses_the_same_book(temp_user, chain_stub, monkeypatch):
    """Review Focus 4 后半（中途失败后再点）——这才是「不能建出两本」真正的机制。

    第一条用例走的是干净路径（status 变 committed 后 409），**没有碰到**复用逻辑。
    这里让出方案那步在第一次调用时失败：502 之后会话仍是 active、`book_id` 已记下，
    用户重按一次必须复用同一本书。删掉 `session.book_id = project.id` 那行，这条就红。
    """
    from myink.api import routes_book as _book
    calls, real = [], _book._short_outline_draft

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return ({"outline_error": "boom"}, {"outline": {}, "error": "boom"})
        return real(*args, **kwargs)

    monkeypatch.setattr(_book, "_short_outline_draft", flaky)
    chain_stub([_PLAN_JSON])                 # 只有第二次真的走到模型（第一次被 flaky 提前挡下）
    _seed_session(temp_user)
    first = client.post("/api/v1/short/creation/commit", json={},
                        headers=identity_headers(temp_user))
    assert first.status_code == 502 and first.json()["detail"].startswith("PLAN_FAILED")
    second = client.post("/api/v1/short/creation/commit", json={},
                         headers=identity_headers(temp_user))
    assert second.status_code == 200
    with new_session() as db:
        assert db.query(Project).filter(Project.user_id == uuid.UUID(temp_user)).count() == 1


def test_commit_survives_a_session_deleted_midway(temp_user, chain_stub, monkeypatch):
    """第 1 步锁住会话之后、第 4 步写回之前，会话被 DELETE 掉——不能崩成 500。

    书与逐章方案都已经落了，这条动线的语义就是「成功」：用户回到工作台就能开写。
    收尾那一步写不回去（会话都没了）不该把已经建好的书报成失败。
    """
    from myink.api import routes_short_creation as _mod
    chain_stub([_PLAN_JSON])
    real = _mod._book._short_outline_draft

    def sabotage(*args, **kwargs):
        with new_session() as db:                 # 模拟用户在出方案那几秒里点了「重新开始」
            db.execute(sa_delete(ShortCreationMessage))
            db.execute(sa_delete(ShortCreationSession))
            db.commit()
        return real(*args, **kwargs)

    monkeypatch.setattr(_mod._book, "_short_outline_draft", sabotage)
    _seed_session(temp_user)
    resp = client.post("/api/v1/short/creation/commit", json={},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"]
    with new_session() as db:                     # 书照常落库，只是收尾没写回
        assert db.scalar(select(ShortCreationSession)
                         .where(ShortCreationSession.user_id == uuid.UUID(temp_user))) is None


def test_commit_respects_the_daily_book_cap(temp_user, chain_stub, monkeypatch):
    """Review Focus 3：上限用满时点确认 → 网关同款 429 信封，不是 500。"""
    from dataclasses import replace

    from myink.api import routes_book
    monkeypatch.setattr(routes_book, "settings",
                        replace(routes_book.settings, books_per_day_max=0))
    chain_stub([_PLAN_JSON])              # 上限在出方案之前就拦下，桩是保险不是必需
    _seed_session(temp_user)
    resp = client.post("/api/v1/short/creation/commit", json={},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 429
    assert resp.json() == {"error": "BOOK_CNT_EXCEEDED"}
    with new_session() as db:                             # 会话没被弄脏，用户配好额度后能重来
        assert db.scalar(select(ShortCreationSession)
                         .where(ShortCreationSession.user_id == uuid.UUID(temp_user))).status == "active"


def test_commit_applies_a_library_style_and_rejects_someone_elses(temp_user, chain_stub):
    chain_stub([_PLAN_JSON])              # 两次 commit 都在本用例内，桩装上后一直有效
    with new_session() as db:
        mine = StyleLibraryItem(user_id=uuid.UUID(temp_user), name="渡口冷白描",
                                profile={"pov": "第三人称限知"}, sample_chars=1200)
        # 「别人的」item 只需要一个不属于我的 owner：`StyleLibraryItem.user_id` 是普通索引、
        # **没有外键**（`models/creation.py:29`），所以不必真建一个 User 行。建真 User 反而更糟——
        # 它会出现在管理面板不加筛选的用户列表里，而且没人清理它。
        theirs = StyleLibraryItem(user_id=uuid.uuid4(), name="别人的冷白描",
                                  profile={"pov": "第一人称"}, sample_chars=900)
        db.add_all([mine, theirs])
        db.commit()
        mine_id, other_item_id = str(mine.id), str(theirs.id)
    _seed_session(temp_user)
    out = client.post("/api/v1/short/creation/commit",
                      json={"style_item_id": mine_id},
                      headers=identity_headers(temp_user)).json()
    with tenant_session(out["project_id"]) as db:
        settings_row = get_settings(db, uuid.UUID(out["project_id"]))
        assert settings_row is not None and settings_row.style_profile["pov"] == "第三人称限知"
        session = db.scalar(select(ShortCreationSession)
                            .where(ShortCreationSession.user_id == uuid.UUID(temp_user)))
        assert session.style_name == "渡口冷白描"

    # 借别人的 item id：404，不是 403、更不是静默忽略。
    # 必须用**另一账号名下真实存在**的 item。随手一个随机 uuid 只能证明「未知 id 被拒」——
    # 漏掉 `StyleLibraryItem.user_id == uid` 那个过滤的实现照样返回 404，用例就抓不到越权。
    client.delete("/api/v1/short/creation", headers=identity_headers(temp_user))
    _seed_session(temp_user)
    resp = client.post("/api/v1/short/creation/commit", json={"style_item_id": other_item_id},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 404
    # 「别人的」item 的 owner 是个随机 uuid，`temp_user` 的收尾按 user_id 删不到它——自己收干净。
    with new_session() as db:
        db.query(StyleLibraryItem).filter(StyleLibraryItem.id == uuid.UUID(other_item_id)).delete()
        db.commit()


def test_commit_accepts_a_builtin_preset_by_key(temp_user, chain_stub):
    chain_stub([_PLAN_JSON])
    _seed_session(temp_user)
    out = client.post("/api/v1/short/creation/commit",
                      json={"style_item_id": "builtin:xianxia-jiuzhou"},
                      headers=identity_headers(temp_user)).json()
    with tenant_session(out["project_id"]) as db:
        settings_row = get_settings(db, uuid.UUID(out["project_id"]))
        assert settings_row is not None and settings_row.skill_pack == "xianxia-jiuzhou"


def _malformed_short_outline() -> dict:
    """有 objective、有非空 volumes，但逐章细纲不合规（第 3 章 goal 为空）。

    过得了 commit 那道闸（它只看 outline_error / volumes / objective），
    过不了落库时的 `validate_short_outline`——所以它会一路走到第 3 步才炸。
    """
    plan = _short_outline()
    plan["volumes"][0]["chapters"][2]["goal"] = ""
    return plan


def test_commit_turns_a_malformed_plan_into_a_retryable_502(temp_user, chain_stub):
    """形状不合规给的是可重试的 502，不是 400 OUTLINE_INCOMPLETE。

    第 3 步落库抛的那个 400，文案（apiError.ts）指向长篇设定页的「全书目标/每卷目标」
    表单——对话式建书根本没有那张表单，用户拿到它只会一头雾水。这条路的整个设计是
    「重按复用同一本」，形状不合规与出方案失败是同一件事：可以再来一次。
    """
    chain_stub([json.dumps(_malformed_short_outline(), ensure_ascii=False)])
    _seed_session(temp_user)
    resp = client.post("/api/v1/short/creation/commit", json={},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 502
    assert resp.json()["detail"].startswith("PLAN_FAILED")
    with new_session() as db:
        assert db.query(Project).filter(Project.user_id == uuid.UUID(temp_user)).count() == 1
        # 会话仍 active、book_id 已记下：重按一次就走复用那本的路，不会建出第二本。
        row = db.scalar(select(ShortCreationSession)
                        .where(ShortCreationSession.user_id == uuid.UUID(temp_user)))
        assert row is not None and row.status == "active" and row.book_id is not None
        assert db.get(Project, row.book_id).creation_status != "ready"
