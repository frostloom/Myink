"""短篇最小闭环：成稿 → 审稿 → 改稿（SHORT-FORM-PLAN Phase 3）。

短篇是一条平行管道，整篇是唯一的工作粒度：一次 `write` 写完，一次 `audit` 以编辑视角
审整篇，只有审稿说 revise 才整篇重写一次。本文件盯四件事：

1. **调用序列**——计划点名的验证口径：审稿 pass 时改稿**零调用**；
2. **成本可查**——三步各记一条 agent_runs（节点 `short_write`/`short_review`/`short_revise`）；
3. **降级**——成稿失败回 error 不抛；审稿坏了当 pass；改稿失败保留首稿 + warning；
4. **决策文档 §三 的分界写死在代码路径里**——本模块源码里不许出现长篇那套一致性机器的
   任何一个符号，不能靠「没有数据所以不触发」。

Phase 6 追加：篇幅参数的唯一读入口（`short_params_for`）、续跑入口（`resume_short_story`）、
审稿结果落到 `short_review` 那条运行记录的 detail 上（前端从既有的任务详情里读，不新增端点）。
"""

from __future__ import annotations

import inspect
import json
import uuid

import pytest
from sqlalchemy import select

from myink.db import new_session, tenant_session
from myink.models import (AgentRun, Chapter, Character, Project, ProjectSettings,
                          VolumeOutline)
from myink.providers.base import ModelProvider, ModelResponse
from myink.short.form import SHORT_CHARS_MAX, ShortParams
from myink.workflow import nodes, short_runner
from myink.workflow.short_parse import CHAPTER_HEADING
from myink.workflow.short_runner import (persist_short_story, resume_short_story,
                                          short_params_for)
from test_short_persist import _result

TASK_ID = "short:test-run"
CHAPTERS = 5


def _plan(chapter_count: int = CHAPTERS) -> dict:
    """确认后落库的逐章方案（与 routes_book 的短篇落库形状一致）。"""
    return {
        "objective": "林砚查清父亲之死，并让青溪渡停航",
        "chapter_count": chapter_count,
        "volumes": [{
            "volume_seq": 1, "title": "全篇 · 最后一班渡船", "goal": "让渡口停航",
            "chapter_start": 1, "chapter_end": chapter_count,
            "chapters": [{"chapter_seq": i, "title": f"渡口之夜 {i}", "goal": f"第 {i} 章的目标"}
                         for i in range(1, chapter_count + 1)],
        }],
    }


def _tagged(chapter_count: int = CHAPTERS, skip: tuple[int, ...] = (), tag: str = "") -> str:
    """写手该产出的形状：每章一行 block 标记 + 正文。"""
    return "\n\n".join(
        f"{CHAPTER_HEADING.format(seq=i)}\n第 {i} 章正文{tag}。老人把最后一盏灯吹了。"
        for i in range(1, chapter_count + 1) if i not in skip)


def _review(verdict: str, *issues: str) -> str:
    return json.dumps({"verdict": verdict, "issues": list(issues),
                       "suggestions": [f"修改建议：{i}" for i in issues]}, ensure_ascii=False)


class _Stub(ModelProvider):
    """按调用次数排队返回原文；异常项直接抛（验证降级路径）。

    队列用尽后重复最后一项——脚本只写一条的场景（如成稿失败）不必凑满三步。
    """

    def __init__(self, script: list):
        self._script = script
        self.calls: list[dict] = []

    def name(self) -> str:
        return "short-runner-stub"

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None,
                 json_mode=False, tools=None, disable_thinking=False):
        self.calls.append({"messages": messages, "max_tokens": max_tokens, "json_mode": json_mode,
                           "disable_thinking": disable_thinking})
        item = self._script[min(len(self.calls) - 1, len(self._script) - 1)]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, ModelResponse):
            return item
        return ModelResponse(content=item, model_id=model_id, input_tokens=100, output_tokens=200)


@pytest.fixture
def stub(monkeypatch):
    import myink.providers as providers_mod

    def _install(script: list) -> _Stub:
        s = _Stub(script)
        monkeypatch.setattr(providers_mod, "default_provider", s)
        return s

    return _install


@pytest.fixture
def short_project(temp_project):
    """可成稿的短篇书：form=short、逐章方案已确认、设定已确认、题材包/文风档案就位。"""
    # 租户行（characters 等）必须走 tenant_session：RLS 按 current_setting('app.tenant_id') 过滤。
    with tenant_session(temp_project) as db:
        pid = uuid.UUID(temp_project)
        project = db.get(Project, pid)
        project.form = "short"
        # 建书时填的篇幅（`creation_context` 是每章字数唯一的落点）；章数与方案里故意不同，
        # 用来证明篇幅以**确认后的方案**为准（见 test_the_lengths_come_from_...）。
        project.creation_context = {"form": "short", "chapter_count": 10,
                                    "chars_per_chapter": 2000}
        db.add(VolumeOutline(project_id=pid, volume_seq=1, title="全篇 · 最后一班渡船",
                             outline=_plan()))
        settings = db.scalar(select(ProjectSettings).where(ProjectSettings.project_id == pid))
        if settings is None:
            settings = ProjectSettings(project_id=pid)
            db.add(settings)
        settings.world_rules = {"渡船夜航": "每逢朔月必须点灯"}
        settings.hard_constraints = ["不出现现代器物"]
        settings.style_profile = {"pov": "第三人称限知", "forbidden": ["不是……是……"]}
        settings.genre_pack = {"source_name": "仙侠玄幻", "selling_point": "渡口烟雨"}
        db.add(Character(project_id=pid, name="林砚", personality="沉默寡言", realm_cap="练气"))
        db.commit()
    return temp_project


def _run(short_project, chapter_count: int = CHAPTERS, chars_per_chapter: int = 4000,
         task_id: str = TASK_ID) -> dict:
    return short_runner.run_short_story(
        project_id=short_project, task_id=task_id,
        form=ShortParams.resolve(chapter_count, chars_per_chapter))


def _runs(short_project, task_id: str = TASK_ID) -> list[AgentRun]:
    with new_session() as db:
        return (db.query(AgentRun)
                .filter(AgentRun.project_id == uuid.UUID(short_project), AgentRun.task_id == task_id)
                .order_by(AgentRun.id).all())


# ---------- 调用序列 ----------


def test_a_clean_draft_stops_after_the_review(short_project, stub):
    """审稿 pass → 改稿**零调用**（计划点名的验证口径）。"""
    s = stub([_tagged(), _review("pass")])

    result = _run(short_project)

    assert len(s.calls) == 2, "成稿 + 审稿，没有第三次调用"
    assert result["error"] is None and result["warning"] is None
    assert result["review"]["verdict"] == "pass"
    assert result["empty_chapters"] == []
    assert [c["chapter_seq"] for c in result["chapters"]] == [1, 2, 3, 4, 5]
    assert "第 3 章正文" in result["chapters"][2]["body"]
    assert result["chapters"][2]["title"] == "渡口之夜 3", "章节标题取自确认后的方案"


def test_the_rewrite_runs_only_when_the_review_says_revise(short_project, stub):
    """审稿 revise → 整篇重写一次，落库用的是重写稿；审稿意见要真的进到改稿提示词里。"""
    s = stub([_tagged(tag="-初稿"), _review("revise", "后半段泄气"),
              _tagged(tag="-改稿")])

    result = _run(short_project)

    assert len(s.calls) == 3
    assert result["review"]["verdict"] == "revise"
    assert result["review"]["issues"] == ["后半段泄气"]
    assert all("改稿" in c["body"] for c in result["chapters"]), "改稿成功就用改稿"
    rewrite_user = s.calls[2]["messages"][-1]["content"]
    assert "第 3 章正文-初稿" in rewrite_user, "改稿必须看得见首稿全文"
    assert "后半段泄气" in rewrite_user


def test_the_three_steps_record_agent_runs_with_their_own_nodes_and_roles(short_project, stub):
    """§6.8 成本透明：三步各一条 agent_runs，节点名与角色分得开。"""
    stub([_tagged(), _review("revise", "收尾仓促"), _tagged(tag="-改稿")])

    _run(short_project)

    runs = _runs(short_project)
    assert [(r.node, r.role) for r in runs] == [
        ("short_write", "Writer"), ("short_review", "Audit"), ("short_revise", "Writer")]
    assert all(r.task_id == TASK_ID for r in runs), "task_id 串起同一次运行"


# ---------- 三个提示词 ----------


def test_the_writer_sees_the_confirmed_plan_and_the_marker_contract(short_project, stub):
    """成稿输入 = 确认后的逐章方案 + 题材包 + 文风档案 + 已确认设定（计划 §Phase 3 第 1 步）。

    章标记逐章点名：写手 prompt 与解析器共用 `CHAPTER_HEADING`，两边不会漂。
    """
    s = stub([_tagged(), _review("pass")])
    _run(short_project)

    prompt = s.calls[0]["messages"][0]["content"] + s.calls[0]["messages"][-1]["content"]
    assert "林砚查清父亲之死" in prompt          # 方案终局
    assert "第 3 章的目标" in prompt             # 逐章细纲
    for i in range(1, CHAPTERS + 1):
        assert CHAPTER_HEADING.format(seq=i) in prompt, f"第 {i} 章的标记要逐章点名"
    assert "渡口烟雨" in prompt                  # 题材包
    assert "第三人称限知" in prompt              # 文风档案
    assert "每逢朔月必须点灯" in prompt          # 已确认的世界观硬约束
    assert "不出现现代器物" in prompt            # 已确认的硬约束
    assert "林砚" in prompt                      # 已确认的核心人物


def test_the_writer_gets_the_whole_story_budget_in_one_call(short_project, stub):
    """整篇一次写完：只有一次写手调用，max_tokens 按 Phase 0 实测口径换算总量。"""
    s = stub([_tagged(10), _review("pass")])
    _run(short_project, chapter_count=10, chars_per_chapter=2000)

    assert len(s.calls) == 2
    assert s.calls[0]["max_tokens"] == int(20000 * nodes._WRITE_TOKENS_PER_CHAR * 1.25)
    assert s.calls[0]["json_mode"] is False and s.calls[0]["disable_thinking"] is True


def test_the_review_is_one_editor_view_pass_over_the_whole_draft(short_project, stub):
    """审稿整篇一次、编辑视角，检查项照决策文档 §2 第 4 步；明写「不要变成确定性打分」。"""
    s = stub([_tagged(), _review("pass")])
    _run(short_project)

    call = s.calls[1]
    system, user = call["messages"][0]["content"], call["messages"][-1]["content"]
    for item in ("标题", "章节标题", "开篇", "人物动机", "时间线", "人物关系",
                 "证据/权限", "压力递进", "后半段", "回报"):
        assert item in system, f"审稿检查项漏了「{item}」"
    assert "打分" in system
    assert '"verdict"' in system
    assert "第 4 章正文" in user, "审的是整篇"
    assert "林砚查清父亲之死" in user, "有没有回报落地要对着方案判"
    assert call["json_mode"] is True
    assert call["max_tokens"] == nodes._MAX_TOKENS["short_review"]


def test_the_rewrite_prompt_demands_a_complete_rewrite(short_project, stub):
    """改稿是整篇重写而非打补丁（决策文档 §二 第 5 步的原文口径）。"""
    s = stub([_tagged(), _review("revise", "后半段泄气"), _tagged(tag="-改稿")])
    _run(short_project)

    system = s.calls[2]["messages"][0]["content"]
    assert "完整正文" in system
    assert "不要只列" in system
    assert "不要只改几章" in system
    assert CHAPTER_HEADING.format(seq=1) in s.calls[2]["messages"][-1]["content"], \
        "重写仍要按章打标记"


# ---------- 降级 ----------


def test_a_failed_draft_call_returns_an_error_without_asking_for_a_review(short_project, stub):
    """成稿失败 → 回 error 不抛（§6.12），也不再打第二次 LLM。"""
    s = stub([RuntimeError("provider down")])

    result = _run(short_project)

    assert result["chapters"] == [] and result["error"]
    assert len(s.calls) == 1
    assert [r.node for r in _runs(short_project)] == ["short_write"]
    assert _runs(short_project)[0].error, "失败的调用同样留一行，排障查得到"


def test_a_failed_rewrite_keeps_the_first_draft_and_warns(short_project, stub):
    """改稿失败保留首稿 + warning（决策文档 §二 第 5 步：不抛、不用残缺输出覆盖）。"""
    stub([_tagged(tag="-初稿"), _review("revise", "后半段泄气"),
          RuntimeError("provider down")])

    result = _run(short_project)

    assert result["error"] is None
    assert result["warning"] and "首稿" in result["warning"]
    assert all("初稿" in c["body"] for c in result["chapters"])
    assert result["review"]["verdict"] == "revise", "意见照实回给用户"


def test_a_rewrite_that_lost_a_chapter_is_treated_as_a_failure(short_project, stub):
    """改稿比首稿还缺章 = 改稿没写成：整篇重写是 2 万字的生成，截断是真实风险。

    一次重写把第 2 章重写成空章、而首稿是齐的——这不是「改好了」。
    """
    stub([_tagged(tag="-初稿"), _review("revise", "后半段泄气"), _tagged(skip=(2,), tag="-改稿")])

    result = _run(short_project)

    assert all("初稿" in c["body"] for c in result["chapters"])
    assert result["warning"] and "首稿" in result["warning"]


@pytest.mark.parametrize("review", ["{not-json", '{"verdict": "REVISE"}', "{}"],
                         ids=["broken-json", "wrong-case", "missing-verdict"])
def test_an_unusable_review_falls_back_to_pass_and_skips_the_rewrite(short_project, stub, review):
    """审稿坏了当 pass（同 Phase 2 审纲的口径）：解析不了就别拿一次 160 秒的重写去赌。"""
    s = stub([_tagged(), review])

    result = _run(short_project)

    assert len(s.calls) == 2
    assert result["review"]["verdict"] == "pass"
    assert result["warning"], "降级要留下痕迹，不能静默"
    assert result["error"] is None


def test_a_forgotten_chapter_is_reported_as_empty(short_project, stub):
    """模型漏写第 3 章 → 留空章并报出来（补写由 Phase 4 接手，这里只做可观测）。"""
    stub([_tagged(skip=(3,)), _review("pass")])

    result = _run(short_project)

    assert result["empty_chapters"] == [3]
    assert result["chapters"][2]["body"] == ""
    assert "第 4 章正文" in result["chapters"][3]["body"], "别把第 4 章挤到第 3 格"


def test_the_review_judges_the_reassembled_draft_not_the_raw_output(short_project, stub):
    """模型整篇不打卡时，审稿看的是解析后重新装回的带标记草稿——读者读的也是这个。"""
    s = stub(["\n\n".join(f"第 {i} 段散文，没有章标记。" for i in range(1, CHAPTERS + 1)),
              _review("pass")])

    result = _run(short_project)

    assert result["empty_chapters"] == [], "均分兜底后没有空章"
    assert CHAPTER_HEADING.format(seq=2) in s.calls[1]["messages"][-1]["content"]


def test_a_gap_triggers_one_continuation_that_fills_the_missing_chapter(short_project, stub):
    """空章 → 一次补写：已写正文与缺失章号一起回喂（决策文档 §二 第 3 步）。

    补写在审稿之前：让审稿审一篇齐的稿，而不是先审一篇带洞的再去补。
    """
    s = stub([_tagged(skip=(3,)), _tagged(), _review("pass")])

    result = _run(short_project)

    assert len(s.calls) == 3, "成稿 + 补写 + 审稿"
    assert [r.node for r in _runs(short_project)] == ["short_write", "short_continue", "short_review"]
    user = s.calls[1]["messages"][-1]["content"]
    assert "第 3 章" in user and "第 1 章正文" in user, "缺失章号 + 已写正文一起回喂"
    assert result["empty_chapters"] == []
    assert "第 3 章正文" in result["chapters"][2]["body"]
    assert "第 3 章正文" in s.calls[2]["messages"][-1]["content"], "审稿审的是补齐后的稿"
    # 补写只补缺的章，预算按缺章数给，不必再买一次整篇
    assert s.calls[1]["max_tokens"] < s.calls[0]["max_tokens"]


def test_the_continuation_is_attempted_at_most_once(short_project, stub):
    """补写有次数上限（一次）：还是缺，就照实报出来，不无限重试。"""
    s = stub([_tagged(skip=(3,)), _tagged(skip=(3,)), _review("pass")])

    result = _run(short_project)

    assert len(s.calls) == 3, "只补一次"
    assert result["empty_chapters"] == [3]
    assert result["warning"], "补不上也要留痕"
    assert result["error"] is None


def test_a_truncated_draft_is_completed_by_one_continuation(short_project, stub):
    """被截断的输出（只写到第 3 章就断了）→ 补写补上第 4、5 章，而不是静默落库半成品。

    这是计划点名的验证口径：解析不抛异常、空章被数出来、补写接手，最终拿出来的是齐的稿。
    """
    continuation = (CHAPTER_HEADING.format(seq=4) + "\n第 4 章正文\n\n"
                    + CHAPTER_HEADING.format(seq=5) + "\n第 5 章正文")
    s = stub([_tagged(skip=(4, 5)), continuation, _review("pass")])

    result = _run(short_project)

    assert result["empty_chapters"] == []
    assert "第 4 章正文" in result["chapters"][3]["body"]
    assert "第 5 章正文" in result["chapters"][4]["body"]
    markers = CHAPTER_HEADING.format(seq=4), CHAPTER_HEADING.format(seq=5)
    assert all(m in s.calls[1]["messages"][-1]["content"] for m in markers), "缺的章要逐章点名"


def _truncated(text: str) -> ModelResponse:
    """被 max_tokens 砍断的一次调用：content 非空、error 为空，只有 finish_reason 说明它断了。"""
    return ModelResponse(content=text, model_id="short-runner-stub", input_tokens=100,
                         output_tokens=999, finish_reason="length")


def test_a_draft_cut_off_at_the_token_ceiling_is_flagged_even_with_no_empty_chapter(short_project, stub):
    """截断落在末章中间时章标记是齐的、空章判据看不出来——半句话的稿会被当完整稿落库、报 done。

    `finish_reason` 是「整篇一次成稿没被砍」唯一的观测点（字段注释点名的 SHORT-FORM §7 门禁）：
    截断时 content 非空、error 也为空，别处都无法分辨。
    """
    stub([_truncated(_tagged()), _review("pass")])

    result = _run(short_project)

    assert result["error"] is None
    assert result["empty_chapters"] == [], "章标记都齐，空章判据看不出截断"
    assert result["warning"] and "截断" in result["warning"]
    detail = next(r.detail for r in _runs(short_project) if r.node == "short_review")
    assert detail["short_review"]["warning"] == result["warning"], "降级痕迹要回给用户看"


def test_a_successful_continuation_does_not_erase_the_truncation_trace(short_project, stub):
    """补写补齐了缺章，不等于「这篇没被砍过」：痕迹不能被后一步的成功抹掉。"""
    stub([_truncated(_tagged(skip=(4, 5))), _tagged(), _review("pass")])

    result = _run(short_project)

    assert result["empty_chapters"] == [], "补写补齐了"
    assert result["warning"] and "截断" in result["warning"]


def test_a_truncated_rewrite_is_flagged_too(short_project, stub):
    """改稿是同样的 2 万字体量、同样的截断风险（`_rewrite` 的注释点名的就是它）：
    章标记齐但末章停在半句上时，空章数不比首稿差，于是它会被接受——必须留痕。"""
    stub([_tagged(tag="-初稿"), _review("revise", "后半段泄气"),
          _truncated(_tagged(tag="-改稿"))])

    result = _run(short_project)

    assert all("改稿" in c["body"] for c in result["chapters"]), "截断的改稿仍被接受"
    assert result["warning"] and "截断" in result["warning"]


def test_a_plan_chapter_without_a_sequence_number_does_not_crash_the_run(short_project, stub):
    """方案里某章缺 `chapter_seq` 时不能抛 KeyError——标题只用于展示。

    `put_outline` 在书 `ready` 之后不再校验形状（用户可以回传任意 volumes），老数据也可能缺号。
    这条路径在**一次 160 秒的整篇成稿之后**才走到，抛出去等于稿子白买。
    """
    with tenant_session(short_project) as db:
        pid = uuid.UUID(short_project)
        row = db.scalar(select(VolumeOutline).where(VolumeOutline.project_id == pid))
        outline = _plan()
        del outline["volumes"][0]["chapters"][2]["chapter_seq"]
        row.outline = outline
        db.commit()
    stub([_tagged(), _review("pass")])

    result = _run(short_project)

    assert result["chapters"][2]["title"] == "第 3 章", "缺号就退回默认标题"
    assert result["chapters"][0]["title"] == "渡口之夜 1", "别的章照常取方案里的标题"
    assert "第 3 章正文" in result["chapters"][2]["body"], "正文照落"


def test_each_chapter_is_measured_against_its_length_target(short_project, stub):
    """字数观测随稿回出来（决策文档：确定性检查只剩字数，且**不阻塞**）。"""
    stub([_tagged(), _review("pass")])

    result = _run(short_project)

    seqs = {f["conflict_key"] for f in result["length_findings"]}
    assert seqs == {f"short-len:{i}" for i in range(1, CHAPTERS + 1)}
    assert all(f["severity"] == "hint" for f in result["length_findings"]), "观测不阻塞"


# ---------- Phase 6：篇幅参数、续跑、审稿结果外露 ----------


def test_the_lengths_come_from_the_confirmed_plan_and_the_creation_context(short_project):
    """章数以**确认后的方案**为准（用户确认的就是那张逐章表），每章字数取建书时填的值。"""
    form = short_params_for(short_project)

    assert (form.chapter_count, form.chars_per_chapter) == (CHAPTERS, 2000), \
        "章数取方案里的 5，不是建书上下文里的 10"


def test_the_lengths_fall_back_to_the_creation_context_when_the_plan_has_no_count(temp_project):
    """方案里没有章数（老数据）→ 退到建书上下文；每章字数缺省按上限换算（§5 的表）。"""
    with tenant_session(temp_project) as db:
        pid = uuid.UUID(temp_project)
        db.get(Project, pid).form = "short"
        db.get(Project, pid).creation_context = {"chapter_count": 10}
        db.add(VolumeOutline(project_id=pid, volume_seq=1, title="全篇",
                             outline={"objective": "x"}))
        db.commit()

    assert short_params_for(temp_project) == ShortParams(10, 2000, True)


def test_a_long_book_has_no_short_params(short_project):
    """防 payload 直投：短篇任务落到长篇书上要当场失败，不能把整篇当一章塞进章表。"""
    with tenant_session(short_project) as db:
        db.get(Project, uuid.UUID(short_project)).form = "long"
        db.commit()

    with pytest.raises(ValueError):
        short_params_for(short_project)


def test_the_review_result_is_recorded_on_the_review_run(short_project, stub):
    """审稿结果是短篇唯一的出口（§8 风险第二条），落在 `short_review` 那条运行记录的
    detail 上——前端从既有的 `GET /tasks/{id}` 里读得到，不新增端点/字段。"""
    stub([_tagged(), _review("revise", "后半段泄气"), RuntimeError("provider down")])

    result = _run(short_project)

    detail = next(r.detail for r in _runs(short_project) if r.node == "short_review")
    assert detail["short_review"]["verdict"] == "revise"
    assert detail["short_review"]["issues"] == ["后半段泄气"]
    assert detail["short_review"]["suggestions"] == ["修改建议：后半段泄气"]
    assert detail["short_review"]["warning"] == result["warning"], "降级痕迹同处可见"


def test_a_clean_pass_is_recorded_without_a_warning(short_project, stub):
    stub([_tagged(), _review("pass")])

    _run(short_project)

    detail = next(r.detail for r in _runs(short_project) if r.node == "short_review")
    assert detail["short_review"] == {"verdict": "pass", "issues": [], "suggestions": [],
                                      "warning": None}


def test_the_review_run_carries_the_empty_chapters_and_the_length_observations(short_project, stub):
    """空章与逐章字数观测只有走完三步才知道，而任务结果字典不落库——只能挂在这条 detail 上。

    用户面的 `GET /tasks/{id}` 只回 runs（没有任务结果表），短篇又没有全局审计报告，
    所以审稿那条运行记录是全篇唯一的出口。
    """
    stub([_tagged(), _review("pass")])

    result = _run(short_project)

    detail = next(r.detail for r in _runs(short_project) if r.node == "short_review")
    assert detail["empty_chapters"] == []
    assert [f["conflict_key"] for f in detail["length_findings"]] == [
        f"short-len:{seq}" for seq in range(1, CHAPTERS + 1)]
    assert detail["length_findings"] == result["length_findings"], "面板看的与返回值是同一份"


def test_the_review_run_says_whether_the_rewrite_landed(short_project, stub):
    """改稿成功之后没有别的信号——用户唯一能问的是「这一篇到底改没改」。"""
    stub([_tagged(tag="-初稿"), _review("revise", "后半段泄气"), _tagged(tag="-改稿")])

    _run(short_project)

    detail = next(r.detail for r in _runs(short_project) if r.node == "short_review")
    assert detail["revised"] is True


def test_a_resume_with_a_persisted_draft_goes_straight_to_the_review(short_project, stub):
    """续跑：成稿已落库就不重买（§6.12 resume 语义）——审一篇落库的稿。"""
    persist_short_story(project_id=short_project, result=_result())
    s = stub([_review("pass")])

    result = resume_short_story(project_id=short_project, task_id="short:resume",
                                form=short_params_for(short_project))

    assert len(s.calls) == 1, "只有审稿，没有第二次成稿"
    assert s.calls[0]["max_tokens"] == nodes._MAX_TOKENS["short_review"]
    assert "第 3 章正文" in s.calls[0]["messages"][-1]["content"], "审的是落库的那份稿"
    assert result["error"] is None and result["review"]["verdict"] == "pass"
    assert [c["chapter_seq"] for c in result["chapters"]] == [1, 2, 3, 4, 5]


def test_a_resume_without_a_persisted_draft_runs_the_whole_thing(short_project, stub):
    """成稿没落库（成稿就失败过）→ 从头跑，没有半截稿可接。"""
    s = stub([_tagged(), _review("pass")])

    result = resume_short_story(project_id=short_project, task_id="short:resume",
                                form=short_params_for(short_project))

    assert len(s.calls) == 2
    assert result["error"] is None


def test_a_resume_treats_a_partial_draft_as_no_draft(short_project, stub):
    """落库的稿缺章（落库本身断了）→ 不算「已成稿」，重跑整条。"""
    persist_short_story(project_id=short_project, result=_result(skip=(3,)))
    s = stub([_tagged(), _review("pass")])

    resume_short_story(project_id=short_project, task_id="short:resume",
                       form=short_params_for(short_project))

    assert len(s.calls) == 2, "缺章的半截稿不是成稿"


def test_a_resume_rewrites_and_lands_through_the_same_tail(short_project, stub):
    """续跑走的是同一条尾巴：审稿判 revise → 改稿 → 返回值照常（调用方接着落库）。"""
    persist_short_story(project_id=short_project, result=_result(tag="-初稿"))
    s = stub([_review("revise", "收尾仓促"), _tagged(tag="-改稿")])

    result = resume_short_story(project_id=short_project, task_id="short:resume",
                                form=short_params_for(short_project))
    persist_short_story(project_id=short_project, result=result)

    assert len(s.calls) == 2
    assert all("改稿" in c["body"] for c in result["chapters"])
    with tenant_session(short_project) as db:
        rows = db.scalars(select(Chapter).where(Chapter.project_id == uuid.UUID(short_project))
                          .order_by(Chapter.chapter_seq)).all()
        assert all(c.version == 2 for c in rows), "续跑的改稿落成整篇 v2"


# ---------- 决策文档 §3 的分界 ----------


def test_the_short_path_carries_none_of_the_long_form_machinery():
    """短篇整篇一次成稿，一致性由注意力保证，不需要外部台账——所以那条流水线整个不存在。

    必须是结构性的（源码里就没有），不能靠「没有数据所以不触发」：否则以后有人加了
    数据流，短篇会静默地开始跑一套为长篇设计的检查。
    """
    source = inspect.getsource(short_runner)
    for token in ("build_context", "recall", "extract", "ledger_l2", "run_global_audit",
                  "node_audit", "ValidationService", "MemoryCandidate", "待确认"):
        assert token not in source, f"短篇管道里不该出现「{token}」"