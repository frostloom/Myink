"""短篇的方案与审纲（SHORT-FORM-PLAN Phase 2）。

- 2.1 prompt 口径（三条硬要求 / 只判能不能一次成稿）；
- 2.3 大纲校验；
- 2.2 两次 LLM 调用本身（角色/节点/降级/改稿 reason 是否真的进了提示词）。
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException

from myink.book_setup import generate_short_plan, review_short_plan
from myink.creation import validate_short_outline
from myink.db import new_session
from myink.models import AgentRun
from myink.providers.base import ModelProvider, ModelResponse
from myink.workflow import nodes, prompts


def _short_outline(chapter_count: int = 5, **overrides) -> dict:
    chapters = [{"chapter_seq": i, "title": f"第 {i} 章",
                 "goal": f"第 {i} 章的目标"} for i in range(1, chapter_count + 1)]
    payload = {
        "objective": "林砚查清父亲之死并让青溪渡停航",
        "chapter_count": chapter_count,
        "volumes": [{"volume_seq": 1, "title": "全篇 · 最后一班渡船", "goal": "让渡口停航",
                     "chapter_start": 1, "chapter_end": chapter_count, "chapters": chapters}],
    }
    payload.update(overrides)
    return payload


def test_short_plan_messages_carry_the_three_hard_requirements():
    """计划点名「必须写进 prompt 的三条硬要求」。

    缺哪一条，方案就会退回长篇启动包或空壳结构——而这正是短篇最典型的失败模式。
    """
    msgs = prompts.short_plan_messages(
        genre="仙侠玄幻", premise="渡口老人与最后一班船",
        chapter_count=10, chars_per_chapter=2000)

    assert msgs[0]["content"] == prompts.SYSTEM_SHORT_PLAN
    system = msgs[0]["content"]
    assert "空壳" in system            # 禁止「本卷共 N 章」这类空壳
    assert "不是长篇前" in system       # 故事必须完整，不是长篇的启动包
    for field in ("标题方向", "关键场面", "角色动作", "压力升级或回报", "章尾钩子"):
        assert field in system        # 逐章要素：信息密度够一次成稿
    # 反梗概口径（Phase 0 实测：不写这句，模型会把正文写成梗概）
    assert "梗概" in system


def test_short_plan_messages_state_the_resolved_lengths():
    msgs = prompts.short_plan_messages(
        genre="仙侠玄幻", premise="渡口老人与最后一班船",
        chapter_count=10, chars_per_chapter=2000, storyline="起承转合")

    user = msgs[1]["content"]
    assert "10 章" in user
    assert "2000" in user
    assert "渡口老人与最后一班船" in user
    assert "起承转合" in user


def test_short_plan_messages_omit_storyline_when_blank():
    user = prompts.short_plan_messages(
        genre="仙侠玄幻", premise="x", chapter_count=5, chars_per_chapter=4000)[1]["content"]
    assert "起承转合" not in user


def test_short_plan_review_messages_ask_only_for_a_verdict():
    """审纲只判一件事：能不能支撑一次写完整篇（决策文档 §2 第 2 步）。"""
    plan = {"objective": "林砚查清旧案并让渡口停航",
            "volumes": [{"volume_seq": 1, "chapters": [{"chapter_seq": 1, "goal": "g"}]}]}
    msgs = prompts.short_plan_review_messages(plan, chapter_count=10)

    assert msgs[0]["content"] == prompts.SYSTEM_SHORT_PLAN_REVIEW
    system = msgs[0]["content"]
    assert '"verdict"' in system
    assert "pass" in system
    assert "revise" in system
    assert "打分" in system           # 明写「不要把审纲变成确定性打分」
    assert "林砚查清旧案并让渡口停航" in msgs[1]["content"]


# ---------- Phase 2.3：短篇大纲校验 ----------


def test_validate_short_outline_accepts_one_volume_with_per_chapter_detail():
    validate_short_outline(_short_outline(5))


@pytest.mark.parametrize("chapter_count", [0, 11])
def test_validate_short_outline_rejects_chapter_count_outside_one_to_ten(chapter_count):
    with pytest.raises(HTTPException):
        validate_short_outline(_short_outline(chapter_count=chapter_count))


def test_validate_short_outline_rejects_more_than_one_volume():
    """短篇恰好一卷——多卷就意味着「章数少则每章长」的前提没了。"""
    payload = _short_outline(5)
    payload["volumes"].append(dict(payload["volumes"][0], volume_seq=2))
    with pytest.raises(HTTPException):
        validate_short_outline(payload)


def test_validate_short_outline_rejects_volume_not_covering_the_whole_book():
    payload = _short_outline(5)
    payload["volumes"][0]["chapter_end"] = 4
    with pytest.raises(HTTPException):
        validate_short_outline(payload)


def test_validate_short_outline_rejects_blank_objective():
    with pytest.raises(HTTPException):
        validate_short_outline(_short_outline(5, objective="   "))


def test_validate_short_outline_rejects_volume_without_goal():
    payload = _short_outline(5)
    payload["volumes"][0]["goal"] = ""
    with pytest.raises(HTTPException):
        validate_short_outline(payload)


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda p: p["volumes"][0].pop("chapters"), id="no-chapters"),
    pytest.param(lambda p: p["volumes"][0].update(chapters=[]), id="empty-chapters"),
    pytest.param(lambda p: p["volumes"][0]["chapters"].pop(2), id="missing-chapter"),
    pytest.param(lambda p: p["volumes"][0]["chapters"][2].update(chapter_seq=99),
                 id="non-contiguous-seq"),
    pytest.param(lambda p: p["volumes"][0]["chapters"][1].update(goal=""), id="blank-goal"),
])
def test_validate_short_outline_requires_contiguous_non_empty_chapters(mutate):
    """逐章细纲是短篇特有的硬要求：长篇明令禁止逐章，短篇必须逐章。

    写手要靠这份逐章方案一次成稿，缺章或空 goal 等于让写手自己编。
    """
    payload = _short_outline(5)
    mutate(payload)
    with pytest.raises(HTTPException):
        validate_short_outline(payload)


# ---------- Phase 2.2：出方案 / 审纲两次调用 ----------


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


def _plan_run_rows(pid: str, node: str) -> list[AgentRun]:
    with new_session() as db:
        return db.query(AgentRun).filter(AgentRun.project_id == uuid.UUID(pid),
                                        AgentRun.node == node).all()


def _generate(pid: str, **kwargs) -> tuple[dict, str | None]:
    with new_session() as db:
        result = generate_short_plan("仙侠玄幻", "渡口老人与最后一班船",
                                     project_id=pid, db=db, **kwargs)
        db.commit()
    return result


def test_generate_short_plan_records_one_planner_run(temp_project, chain_stub):
    """§6.8 成本透明：出方案走 planner 角色、记一条 agent_runs（节点名 short_plan）。"""
    stub = chain_stub([json.dumps(_short_outline(10), ensure_ascii=False)])
    plan, error = _generate(temp_project, chapter_count=10, chars_per_chapter=2000)

    assert error is None and plan["chapter_count"] == 10
    assert stub.calls[0]["json_mode"] is True
    assert stub.calls[0]["max_tokens"] == nodes._MAX_TOKENS["short_plan"]
    runs = _plan_run_rows(temp_project, "short_plan")
    assert len(runs) == 1 and runs[0].role == "Planner"


def test_review_short_plan_records_a_planner_run(temp_project, chain_stub):
    """审纲也是 planner 档的独立一次调用——两次调用各记一条，成本才看得清。"""
    stub = chain_stub([json.dumps({"verdict": "revise", "reason": "第三章没有章尾钩子"},
                                  ensure_ascii=False)])
    with new_session() as db:
        verdict, reason = review_short_plan(_short_outline(5), chapter_count=5,
                                            project_id=temp_project, db=db)
        db.commit()

    assert (verdict, reason) == ("revise", "第三章没有章尾钩子")
    assert stub.calls[0]["json_mode"] is True
    runs = _plan_run_rows(temp_project, "short_plan_review")
    assert len(runs) == 1 and runs[0].role == "Planner"


def test_generate_short_plan_passes_the_revision_reason_into_the_prompt(temp_project, chain_stub):
    """改稿 reason 必须真的进提示词——不带 reason 的重出就是同一份方案再掷一次骰子。"""
    stub = chain_stub([json.dumps(_short_outline(5), ensure_ascii=False)])
    _generate(temp_project, chapter_count=5, chars_per_chapter=4000,
              revision_reason="第三章没有章尾钩子")

    assert "第三章没有章尾钩子" in stub.calls[0]["messages"][-1]["content"]


def test_review_short_plan_degrades_to_pass_without_raising(temp_project, chain_stub):
    """审纲失败不能反过来拦住方案：解析不了就当作「没意见」，方案照发。

    审纲是建议不是闸门（决策文档 §2 第 2 步）；一次 parse 失败就把用户卡在出方案页
    上，比放过一份平庸方案糟糕得多。
    """
    chain_stub(["{not-json"])
    with new_session() as db:
        verdict, reason = review_short_plan(_short_outline(5), chapter_count=5,
                                            project_id=temp_project, db=db)
    assert verdict == "pass" and reason == ""


def test_generate_short_plan_degrades_on_bad_json(temp_project, chain_stub):
    """§6.12 降级：不 raise，回 ({}, error) 让端点 200 带错。"""
    chain_stub(["{not-json"])
    plan, error = _generate(temp_project, chapter_count=5, chars_per_chapter=4000)
    assert plan == {} and error and "parse_error" in error
    assert len(_plan_run_rows(temp_project, "short_plan")) == 1, "降级调用也要留 agent_runs 行"


def test_generate_short_plan_requires_project_id_for_run_recording(chain_stub):
    chain_stub([json.dumps(_short_outline(5), ensure_ascii=False)])
    with new_session() as db, pytest.raises(ValueError, match="project_id"):
        generate_short_plan("仙侠玄幻", "x", chapter_count=5, chars_per_chapter=4000, db=db)