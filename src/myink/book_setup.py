"""建书设定骨架草稿生成（§7.11 ②：一句话梗概启动 + Planner 提案 + 用户确认落库）。

与 style_extract.extract_style_profile 同款模式：planner 档一次 json_mode 调用 + 鲁棒
JSON 解析 + agent_runs 记录（§6.8 成本透明）+ 从不 raise（§6.12 降级，失败返回 ({}, error)）。

生成的是**可编辑草稿不落库**——用户逐项确认/修改后由 setup 端点落库（数据流边界 §6.2：
agent 只提案、确认 = 编排层写库入口）。草稿可再生（前端「重新生成」反复调用本函数）。
"""

from __future__ import annotations


def generate_book_setup(genre: str, premise: str, *,
                        genre_pack: dict | None = None,
                        project_id: str | None = None, db=None) -> tuple[dict, str | None]:
    """Planner 生成本书设定骨架草稿（境界体系/世界观/硬约束/势力/核心人物/关键地点）。

    返回 (draft, error)：LLM / 解析失败 → ({}, error)（§6.12 降级，端点回空草稿让用户手填）。
    函数内懒导入 providers/workflow（api 层 import 本模块时避免 import 环）。

    db 非 None 时记 agent_runs：generate 后立即 record_run（含降级行 error=resp.error），
    提交由调用方负责；此时 project_id 必填。
    """
    from myink.providers import make_chain
    from myink.workflow import nodes, prompts

    messages = prompts.book_setup_messages(genre, premise, genre_pack=genre_pack)
    resp = make_chain("planner", db=db, project_id=project_id).generate(
        messages, json_mode=True, max_tokens=nodes._MAX_TOKENS["book_setup"])
    if db is not None:
        if project_id is None:
            raise ValueError("db 非 None 时必须提供 project_id（agent_runs 归属）")
        nodes.record_run(db, project_id=project_id, task_id=None, node="book_setup",
                         role="Planner", resp=resp, error=resp.error, messages=messages, detail={"genre": genre})
    if resp.error:
        return {}, resp.error
    try:
        data = nodes._parse_json(resp.content)
    except Exception as exc:  # noqa: BLE001 —— 解析失败同 LLM 失败处理（§6.12）
        return {}, f"parse_error: {exc}"
    if not isinstance(data, dict):
        return {}, "unexpected_json"
    return data, None


def generate_book_outline(genre: str, premise: str, *, chapter_count: int = 200,
                          storyline: str = "", genre_pack: dict | None = None,
                          project_id: str | None = None,
                          db=None) -> tuple[dict, str | None]:
    """Planner 生成整书大纲草稿：Objective + 卷 + 约 30 章一段的阶段。草稿不落库。"""
    from myink.providers import make_chain
    from myink.workflow import nodes, prompts
    from myink.workflow.outline import normalize_outline

    messages = prompts.book_outline_messages(
        genre, premise, chapter_count, storyline, genre_pack=genre_pack)
    resp = make_chain("planner", db=db, project_id=project_id).generate(
        messages, json_mode=True, max_tokens=nodes._MAX_TOKENS["book_outline"])
    if db is not None:
        if project_id is None:
            raise ValueError("db 非 None 时必须提供 project_id（agent_runs 归属）")
        nodes.record_run(db, project_id=project_id, task_id=None, node="book_outline",
                         role="Planner", resp=resp, error=resp.error, messages=messages,
                         detail={"genre": genre, "chapter_count": chapter_count})
    if resp.error:
        return {}, resp.error
    try:
        data = nodes._parse_json(resp.content)
    except Exception as exc:  # noqa: BLE001 —— 解析失败同 LLM 失败处理（§6.12）
        return {}, f"parse_error: {exc}"
    if not isinstance(data, dict):
        return {}, "unexpected_json"
    if not isinstance(data.get("volumes"), list):
        return {}, "unexpected_shape: volumes 缺失或非数组"
    return normalize_outline(data) or data, None


def generate_short_plan(genre: str, premise: str, *, chapter_count: int,
                        chars_per_chapter: int, storyline: str = "",
                        revision_reason: str = "", genre_pack: dict | None = None,
                        project_id: str | None = None,
                        db=None) -> tuple[dict, str | None]:
    """Planner 生成短篇逐章方案草稿：恰好一卷 + 逐章细纲（docs/SHORT-FORM §5）。草稿不落库。

    与 `generate_book_outline` 同款：一次 json_mode 调用 + 鲁棒解析 + agent_runs + 从不 raise。
    但两份方案是两回事，所以**不共用节点名**——成本面板上要能一眼分清长篇大纲与短篇方案。

    逐章 chapters 原样带出：短篇写手要靠它一次成稿，这里不能走长篇那条「折成 stages」的归一。
    """
    from myink.providers import make_chain
    from myink.workflow import nodes, prompts

    messages = prompts.short_plan_messages(
        genre, premise, chapter_count, chars_per_chapter, genre_pack=genre_pack,
        storyline=storyline, revision_reason=revision_reason)
    resp = make_chain("planner", db=db, project_id=project_id).generate(
        messages, json_mode=True, max_tokens=nodes._MAX_TOKENS["short_plan"])
    if db is not None:
        if project_id is None:
            raise ValueError("db 非 None 时必须提供 project_id（agent_runs 归属）")
        nodes.record_run(db, project_id=project_id, task_id=None, node="short_plan",
                         role="Planner", resp=resp, error=resp.error, messages=messages,
                         detail={"genre": genre, "chapter_count": chapter_count,
                                 "chars_per_chapter": chars_per_chapter,
                                 "revision_reason": revision_reason})
    if resp.error:
        return {}, resp.error
    try:
        data = nodes._parse_json(resp.content)
    except Exception as exc:  # noqa: BLE001 —— 解析失败同 LLM 失败处理（§6.12）
        return {}, f"parse_error: {exc}"
    if not isinstance(data, dict):
        return {}, "unexpected_json"
    volumes = data.get("volumes")
    if not isinstance(volumes, list) or not volumes:
        return {}, "unexpected_shape: volumes 缺失或非数组"
    for volume in volumes:
        if isinstance(volume, dict) and not isinstance(volume.get("chapters"), list):
            return {}, "unexpected_shape: 卷内缺少逐章 chapters"
    return data, None


def review_short_plan(plan: dict, *, chapter_count: int, project_id: str | None = None,
                      db=None) -> tuple[str, str]:
    """短篇审纲：只判这份方案能不能支撑一次写完整篇（决策文档 §2 第 2 步）。

    返回 `(verdict, reason)`，verdict 只可能是 "pass" / "revise"。

    **审纲失败一律当作 "pass"**：它是建议不是闸门。一次 parse 失败就把用户卡在出方案页上，
    比放过一份平庸方案糟糕得多——方案本来就是可反复重出的草稿。
    """
    from myink.providers import make_chain
    from myink.workflow import nodes, prompts

    messages = prompts.short_plan_review_messages(plan, chapter_count)
    resp = make_chain("planner", db=db, project_id=project_id).generate(
        messages, json_mode=True, max_tokens=nodes._MAX_TOKENS["short_plan_review"])
    if db is not None:
        if project_id is None:
            raise ValueError("db 非 None 时必须提供 project_id（agent_runs 归属）")
        nodes.record_run(db, project_id=project_id, task_id=None, node="short_plan_review",
                         role="Planner", resp=resp, error=resp.error, messages=messages,
                         detail={"chapter_count": chapter_count})
    if resp.error:
        return "pass", ""
    try:
        data = nodes._parse_json(resp.content)
    except Exception:  # noqa: BLE001 —— 审纲坏了不拦方案
        return "pass", ""
    if not isinstance(data, dict) or data.get("verdict") != "revise":
        return "pass", ""
    return "revise", str(data.get("reason") or "").strip()


def generate_short_creation_turn(history: list[dict], card: dict, *,
                                 user_id, db=None) -> tuple[str, dict, str | None, ModelResponse]:
    """建书对话一回合：一次 planner json_mode 调用，回 (reply, 卡增量, error, resp)。

    模型/解析失败不清卡；准入失败抛 GateError / EnqueueUnavailable，由 API 返回 429/503。
    解析失败时把模型原文当 reply 交出去、增量回空 dict（调用方保留现值）、
    error 记进消息。用户重说一句就能接着聊，而不是丢掉整场对话。

    resp 一并交出去，是为了让调用方把 model_id / token / 花费逐条落进会话消息里。
    """
    from myink.model_admission import generate_account_model
    from myink.providers import make_user_chain
    from myink.providers.base import ModelResponse
    from myink.short import creation
    from myink.workflow import nodes, prompts

    messages = prompts.short_creation_messages(history, card)
    resp = generate_account_model(
        make_user_chain("planner", user_id), user_id=user_id, messages=messages,
        json_mode=True, max_tokens=nodes._MAX_TOKENS["short_creation"])
    if db is not None:
        nodes.record_run(db, user_id=user_id, task_id=None, node="short_creation",
                         role="Planner", resp=resp, error=resp.error, messages=messages,
                         detail={"turn": len(history)})
    if resp.error:
        return "（这一轮没连上模型，请再说一次）", {}, resp.error, resp
    try:
        data = nodes._parse_json(resp.content)
    except Exception as exc:                       # 坏 JSON：原文当回复
        return resp.content.strip(), {}, f"parse_error: {exc}", resp
    if not isinstance(data, dict):
        return resp.content.strip(), {}, "unexpected_json", resp
    reply = str(data.get("reply") or "").strip() or "（模型这轮没有回复内容）"
    return reply, creation.card_patch(data.get("card")), None, resp
