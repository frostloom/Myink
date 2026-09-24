"""短篇最小闭环：成稿 → 审稿 → 改稿（docs/SHORT-FORM.md §二 第 3–5 步）。

**普通函数，不是图**：短篇没有「章」这个调度单位，整篇是唯一的工作粒度，三步一路走到底，
不需要 LangGraph 的检查点与条件边。

决策文档 §三 的分界在这里是**结构性的**：本模块不 import 也不调用长篇那套一致性机器
（记忆抽取 / 台账召回 / L1-L2 分级校验 / 单章审核 / 全局审计 / 候选池）。短篇整篇在一次
调用里同时产生，一致性由注意力保证；那些机器存在的理由全是「跨章保持一致」，而这里没有
跨章。不能靠「没有数据所以不触发」——否则以后有人加了数据流，短篇会静默地开始跑一套
为长篇设计的检查。

方案与设定由建书流程确认落库，这里只读。返回的 chapters 尚未落库（调用方用
`persist_short_story` 落库——成稿就该看得见、落库是另一件事）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from myink.db import tenant_session
from myink.memory import repository as repo
from myink.models import Chapter, Faction, Location
from myink.providers import ModelResponse, make_chain
from myink.short.form import SHORT_CHARS_MAX, ShortParams
from myink.validation.short import observe_lengths
from myink.workflow import nodes, prompts
from myink.workflow.short_parse import find_empty_chapters, parse_short_draft, render_short_draft


def run_short_story(*, project_id: str, task_id: str, form: ShortParams) -> dict:
    """成稿 → 审稿 → 改稿。审稿说 pass 就到此为止，改稿零调用。

    返回 `{"chapters", "empty_chapters", "length_findings", "review", "warning", "error"}`：
    - `chapters` 逐章 dict（chapter_seq/title/body），空章 body 为空串；
    - `length_findings` 是逐章字数的**观测**（`validation.short.observe_lengths`，
      severity 恒为 hint），随稿回给用户看，不拦稿、不进提示词；
    - `error` 非空 = 整篇没成（成稿就没回来），此时 chapters 为空、不会落库；
    - `warning` 是「降级但仍有稿」的痕迹（输出被长度上限截断、审稿坏了按通过、补写/改稿
      没成保留原样），必须回给用户看——静默降级比降级本身更糟。
    """
    with tenant_session(project_id) as db:
        outline = _outline(db, project_id)
        brief = _load_brief(db, project_id, outline, form)
        budget = _budget(form)

        resp = _call(db, project_id, task_id, node="short_write", role="Writer",
                     messages=prompts.short_write_messages(brief), max_tokens=budget,
                     json_mode=False, disable_thinking=True,
                     detail={"chapter_count": form.chapter_count,
                             "chars_per_chapter": form.chars_per_chapter})
        if resp.error:
            return {"chapters": [], "empty_chapters": [], "length_findings": [],
                    "review": _pass_review(), "warning": None, "error": resp.error}
        bodies = parse_short_draft(resp.content, form.chapter_count)

        warning = _truncation_note(resp, "成稿")
        if find_empty_chapters(bodies):
            filled, continue_warning = _continue(db, project_id, task_id, brief, bodies, form)
            if filled is not None:
                bodies = filled
            warning = warning or continue_warning

        return _finish_short(db, project_id, task_id, brief, bodies, form, budget, warning)


def resume_short_story(*, project_id: str, task_id: str, form: ShortParams) -> dict:
    """续跑（§6.12）：成稿已落库就只接着审稿/改稿，否则整条从头跑。

    「已落库成稿」= 方案里每一章都有非空正文。缺章的半截稿不算成稿——那是落库本身断了，
    拿它当底稿接下去只会把缺章当「已写」，重跑一次成稿比修半截稿更确定。
    """
    bodies = _persisted_bodies(project_id, form.chapter_count)
    if bodies is None:
        return run_short_story(project_id=project_id, task_id=task_id, form=form)
    with tenant_session(project_id) as db:
        brief = _load_brief(db, project_id, _outline(db, project_id), form)
        return _finish_short(db, project_id, task_id, brief, bodies, form, _budget(form), None)


def short_params_for(project_id: str) -> ShortParams:
    """这本书的短篇篇幅参数（路由算闸门、worker 算预算，两边必须同一份）。

    章数以**确认后的方案**为准——用户确认的就是那张逐章表，写手照它写；建书时填的那个数是
    草稿期的意图，方案可能已被归一。每章字数没有别的落点，只能取建书上下文，缺省按每章
    上限换算，正好还原决策文档 §5 的表（1→8000 / 2→8000 / 5→4000 / 10→2000）。

    非短篇书直接失败（防 payload 直投）：短篇任务是「整篇一次写完」，落到长篇书上会把整篇
    塞成一章，破坏长篇的写序。
    """
    with tenant_session(project_id) as db:
        pid = uuid.UUID(project_id)
        project = repo.get_project(db, pid)
        if project is None or (project.form or "long") != "short":
            raise ValueError("该作品不是短篇形态")
        row = repo.get_volume_outline(db, pid, 1)
        context = project.creation_context or {}
        count = (_positive_int(((row.outline if row else None) or {}).get("chapter_count"))
                 or _positive_int(context.get("chapter_count")) or 1)
        chars = _positive_int(context.get("chars_per_chapter")) or SHORT_CHARS_MAX
    return ShortParams.resolve(count, chars)


def _outline(db, project_id: str) -> dict:
    """确认后的逐章方案。短篇恰好一卷，由 Phase 2 的落库校验保证。"""
    row = repo.get_volume_outline(db, uuid.UUID(project_id), 1)
    return (row.outline if row else None) or {}


def _budget(form: ShortParams) -> int:
    """整篇成稿的输出上限：目标字数按 Phase 0 实测的 1.43 字/token 换算，再留 25% 余量。"""
    return int(form.total_chars * nodes._WRITE_TOKENS_PER_CHAR * 1.25)


def _persisted_bodies(project_id: str, chapter_count: int) -> list[str] | None:
    """已落库的整篇正文（按章序）；缺任一章就返回 None——半截稿不算成稿。"""
    pid = uuid.UUID(project_id)
    with tenant_session(project_id) as db:
        rows = db.scalars(select(Chapter).where(Chapter.project_id == pid)
                          .order_by(Chapter.chapter_seq)).all()
    stored = {c.chapter_seq: (c.content or "") for c in rows}
    if any(not stored.get(seq, "").strip() for seq in range(1, chapter_count + 1)):
        return None
    return [stored[seq] for seq in range(1, chapter_count + 1)]


def _positive_int(value) -> int:
    """宽松取正数（老库/脏数据里可能是字符串或空）；取不到返回 0，由调用方兜底。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _notes(*parts: str | None) -> str | None:
    """把几条降级痕迹接成一条（前因后果都留给用户看）。全空则返回 None。"""
    return "；".join(part for part in parts if part) or None


def _truncation_note(resp: ModelResponse, stage: str) -> str | None:
    """被 `max_tokens` 砍断的痕迹（`ModelResponse.finish_reason`，短篇唯一的截断观测点）。

    截断不拦稿（大半篇仍是可用的），但必须回给用户看：章标记都打齐时「空章」判据看不出它，
    末章停在半句上却照样被当完整稿落库、任务报 done。
    """
    if resp.finish_reason != "length":
        return None
    return f"{stage}输出达到长度上限被截断，末章可能停在半句上"


def _finish_short(db, project_id: str, task_id: str, brief: dict, bodies: list[str],
                  form: ShortParams, budget: int, warning: str | None) -> dict:
    """审稿 →（仅当 revise）改稿 → 组装返回值。成稿与续跑共用的尾巴。

    审稿结果是短篇唯一的出口（没有全局审计），所以连同降级痕迹一并落在 `short_review`
    那条运行记录的 detail 上：前端从既有的任务详情（`GET /tasks/{id}` → runs）就读得到，
    不新增端点、不改响应契约。空章、逐章字数观测、改没改也挂在这条 detail 上——它们同样
    只有走完三步才知道，而任务结果字典（`_dispatch` 的返回值）不落库，这里是唯一的出口。
    """
    review, review_warning = _review(db, project_id, task_id, brief, bodies)
    warning = warning or review_warning
    revised = False
    if review["verdict"] == "revise":
        rewritten, rewrite_warning = _rewrite(db, project_id, task_id, brief, bodies,
                                              review, budget)
        if rewritten is not None:
            bodies = rewritten
            revised = True
        warning = warning or rewrite_warning

    empty_chapters = find_empty_chapters(bodies)
    length_findings = [f.model_dump(mode="json") for f in
                       observe_lengths(bodies, form.chars_per_chapter)]
    nodes.record_run_detail(db, task_id=task_id, node="short_review",
                            detail={"short_review": {**review, "warning": warning},
                                    "empty_chapters": empty_chapters,
                                    "length_findings": length_findings,
                                    "revised": revised})
    titles = _chapter_titles(brief.get("outline") or {}, form.chapter_count)
    return {"chapters": [{"chapter_seq": i + 1, "title": titles[i], "body": bodies[i]}
                         for i in range(form.chapter_count)],
            "empty_chapters": empty_chapters,
            "length_findings": length_findings,
            "review": review, "warning": warning, "error": None}


def persist_short_story(*, project_id: str, result: dict) -> int:
    """把成稿落库：逐章 `save_chapter` + 推进 `Project.current_chapter`。返回落库章数。

    版本语义照仓库既有那套（§四：短篇的版本就是整篇版本）：`chapters` 装当前版、版本表装
    被覆盖掉的旧版。首稿 = N 行 v1，改稿 = 同一批行整批升到 v2（`save_chapter` 覆盖写前
    自动快照）+ 版本表 N 行 v1。于是「整篇 v2」= 逐章读 `chapters`、「整篇 v1」= 逐章读
    版本表，回退端点照常可用，短篇不需要新表。

    空章不落库：它的正文哪都没有（模型没写、补写也没成），落一行空的只会在章节列表里显示成
    一个坏掉的白章。进度跟着最后落库的那一章走——与删章端点同口径（保留的最大章序）。
    """
    rows = [c for c in (result.get("chapters") or []) if (c.get("body") or "").strip()]
    if not rows:
        return 0
    with tenant_session(project_id) as db:
        pid = uuid.UUID(project_id)
        for row in rows:
            repo.save_chapter(db, project_id=pid, chapter_seq=row["chapter_seq"],
                              content=row["body"], title=row.get("title"),
                              generation_source="auto")
        project = repo.get_project(db, pid)
        if project is not None:
            project.current_chapter = max(row["chapter_seq"] for row in rows)
    return len(rows)


def _load_brief(db, project_id: str, outline: dict, form: ShortParams) -> dict:
    """成稿输入：确认后的方案 + 已确认设定 + 题材包 + 文风档案 + 篇幅。

    设定直读不召回：短篇成稿前不需要检索，这一本书的设定本来就装得下。用户在建书页
    逐项确认过的内容（硬约束/人物/势力/地点）都得进提示词——确认了却不给写手看，
    等于把那一页白填了。
    """
    pid = uuid.UUID(project_id)
    project = repo.get_project(db, pid)
    settings = repo.get_settings(db, pid)
    return {
        "genre": project.genre if project else "",
        "outline": outline,
        "chapter_count": form.chapter_count,
        "chars_per_chapter": form.chars_per_chapter,
        "world_rules": (settings.world_rules if settings else None) or {},
        "hard_constraints": (settings.hard_constraints if settings else None) or [],
        "style_profile": (settings.style_profile if settings else None) or {},
        "genre_pack": (settings.genre_pack if settings else None) or {},
        "characters": [{"name": c.name, "personality": c.personality, "realm_cap": c.realm_cap}
                       for c in repo.get_all_characters(db, pid)],
        "factions": [{"name": f.name, "stance": f.stance}
                     for f in db.scalars(select(Faction).where(Faction.project_id == pid))],
        "locations": [{"name": location.name}
                      for location in db.scalars(select(Location).where(Location.project_id == pid))],
    }


def _chapter_titles(outline: dict, chapter_count: int) -> list[str]:
    """逐章标题取自确认后的方案；缺了就用「第 N 章」（标题只用于展示，不拦稿）。

    方案是可回传的形状（书 ready 之后 `put_outline` 不再校验），所以章号可能缺、
    可能是字符串——取不到就跳过，别在一次整篇成稿之后抛出去。
    """
    titles: dict[int, str] = {}
    for volume in (outline or {}).get("volumes") or []:
        if not isinstance(volume, dict):
            continue
        for chapter in volume.get("chapters") or []:
            if not isinstance(chapter, dict) or not str(chapter.get("title") or "").strip():
                continue
            seq = _positive_int(chapter.get("chapter_seq"))
            if seq:
                titles[seq] = str(chapter["title"]).strip()
    return [titles.get(i) or f"第 {i} 章" for i in range(1, chapter_count + 1)]


def _call(db, project_id: str, task_id: str, *, node: str, role: str, messages: list[dict],
          max_tokens: int, json_mode: bool, disable_thinking: bool = False,
          detail: dict | None = None) -> ModelResponse:
    """一次 LLM 调用 + 一条 agent_runs（§6.8 成本透明）。

    角色分两套写法：配置角色名小写（`CONFIGURABLE_ROLES`），运行记录用大写标签
    （与 nodes/book_setup 一致，成本面板按标签聚合）。
    """
    resp = nodes._bounded_generate(
        make_chain(role.lower(), db=db, project_id=project_id), messages, json_mode=json_mode,
        max_tokens=max_tokens, disable_thinking=disable_thinking)
    nodes.record_run(db, project_id=project_id, task_id=task_id, node=node, role=role,
                     resp=resp, error=resp.error, messages=messages,
                     detail={"form": "short", **(detail or {})})
    return resp


def _continue(db, project_id: str, task_id: str, brief: dict, bodies: list[str],
              form: ShortParams) -> tuple[list[str] | None, str | None]:
    """补写空章：**一次为限**（§二 第 3 步：格式坏 → 内容为空 → 补写，有次数上限）。

    只把补出来的那几格并回原稿——模型顺手重写别的章是它的自由，但这里不动已有的章：
    缺的那格填上了才算成功；没填上就照实报空章，不假装补齐了。

    预算按缺章数给，不必为补一章再买一次整篇的额度。
    """
    missing = find_empty_chapters(bodies)
    resp = _call(db, project_id, task_id, node="short_continue", role="Writer",
                 messages=prompts.short_continue_messages(
                     brief, render_short_draft(bodies), missing),
                 max_tokens=int(len(missing) * form.chars_per_chapter
                                * nodes._WRITE_TOKENS_PER_CHAR * 1.25),
                 json_mode=False, disable_thinking=True, detail={"missing": missing})
    if resp.error:
        return None, f"补写未完成（{resp.error}），第 {'、'.join(map(str, missing))} 章仍是空的"
    filled = parse_short_draft(resp.content, brief.get("chapter_count") or form.chapter_count)
    merged = [old if (old or "").strip() else new for old, new in zip(bodies, filled)]
    still_empty = find_empty_chapters(merged)
    if still_empty:
        return None, _notes(f"补写没能补齐第 {'、'.join(map(str, still_empty))} 章，这几章仍是空的",
                            _truncation_note(resp, "补写"))
    return merged, _truncation_note(resp, "补写")


def _review(db, project_id: str, task_id: str, brief: dict,
            bodies: list[str]) -> tuple[dict, str | None]:
    """审稿：整篇一次，编辑视角。返回 `(review, warning)`。

    审的是「拆好再装回去」的草稿，不是模型的原始输出：读者读到的就是这个形状，
    模型整篇漏打标记时审稿看到的也仍是 5 章而不是一堵墙。

    **审稿坏了一律当作通过**（与审纲同一条口径）：解析失败就再打一次 160 秒的整篇重写，
    是拿最贵的调用去赌一个连意见都没读到的信号。
    """
    resp = _call(db, project_id, task_id, node="short_review", role="Audit",
                 messages=prompts.short_review_messages(brief, render_short_draft(bodies)),
                 max_tokens=nodes._MAX_TOKENS["short_review"], json_mode=True,
                 detail={"chapters": len(bodies)})
    if resp.error:
        return _pass_review(), f"审稿未完成（{resp.error}），这一篇按通过处理"
    try:
        data = nodes._parse_json(resp.content)
    except Exception:  # noqa: BLE001 —— 审稿坏了不拦稿
        return _pass_review(), "审稿结果无法解析，这一篇按通过处理"
    if not isinstance(data, dict):
        return _pass_review(), "审稿结果形状不对，这一篇按通过处理"
    if data.get("verdict") == "revise":
        return {"verdict": "revise", "issues": _strings(data.get("issues")),
                "suggestions": _strings(data.get("suggestions"))}, None
    return _pass_review(), (None if data.get("verdict") == "pass"
                            else "审稿没有给出可用判定，这一篇按通过处理")


def _rewrite(db, project_id: str, task_id: str, brief: dict, bodies: list[str],
             review: dict, budget: int) -> tuple[list[str] | None, str | None]:
    """改稿：整篇重写一次。返回 `(新正文, warning)`，None 表示保留首稿。

    重写没写成（报错 / 空输出 / 比首稿还缺章）都算失败——整篇重写是一次 2 万字的生成，
    截断是真实风险，拿一次缺章的稿子覆盖一份齐的首稿是净损失。
    """
    resp = _call(db, project_id, task_id, node="short_revise", role="Writer",
                 messages=prompts.short_revise_messages(brief, render_short_draft(bodies), review),
                 max_tokens=budget, json_mode=False, disable_thinking=True,
                 detail={"issues": len(review.get("issues") or [])})
    if resp.error:
        return None, f"改稿未完成（{resp.error}），已保留首稿"
    rewritten = parse_short_draft(resp.content, brief["chapter_count"])
    if len(find_empty_chapters(rewritten)) > len(find_empty_chapters(bodies)):
        return None, _notes("改稿没写全（空章比首稿更多），已保留首稿",
                            _truncation_note(resp, "改稿"))
    return rewritten, _truncation_note(resp, "改稿")


def _pass_review() -> dict:
    return {"verdict": "pass", "issues": [], "suggestions": []}


def _strings(value) -> list[str]:
    """意见列表清洗：字符串直接用，对象取其中唯一的文本值（§6.12 输出容错）。"""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            out.append(item.strip())
        elif isinstance(item, dict):
            texts = [str(v).strip() for v in item.values()
                     if isinstance(v, str) and str(v).strip()]
            if len(texts) == 1:
                out.append(texts[0])
    return [text for text in out if text]