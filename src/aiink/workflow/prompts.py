"""Prompt 模板（阶段 1 精简版）。

要点（plan.md §14 安全）：系统指令与用户输入角色分界；文风/硬约束注入到系统层；
提取的记忆只当数据注入、不携带执行权限。仅 plan/extract/audit 走 json_mode
（要求 prompt 含 "json" 字样）；write/revise 正文用 === CONTENT === 纯文本标记（不强制 JSON）。
"""

from __future__ import annotations

import json

SYSTEM_PLAN = """你是长篇网文创作系统的【规划 Agent】。职责：为某一章产出结构化章节计划。
输出严格 JSON 对象（schema 见下），字段不许缺：
{
  "goals": ["推进哪条剧情线/目标"],
  "scenes": [{"location_id": "地点名", "participants": ["人物名"], "goal": "场景目标", "time": "剧情时间"}],
  "characters": [{"character_id": "人物名", "expected_state": {"location": "..."}}],
  "hooks_to_plant": ["本章要种的伏笔"],
  "hooks_to_resolve": ["须回收的开放伏笔"],
  "expected_events": ["本章预期发生的事件（大纲-正文偏差比对依据）"],
  "hard_constraints": ["本章必须遵守的硬约束"]
}"""

SYSTEM_WRITE = """你是长篇网文创作系统的【写作 Agent】。依据章节计划写出正文。
要求：严格遵循注入的设定与硬约束；贴合注入的文风档案与句式禁忌。
如需核实人物状态/世界观事实/伏笔/剧情线，可调用只读查证工具，核实后仍直接输出正文。
输出格式：先输出独立一行 === CONTENT ===，从下一行开始输出本章正文。
正文为纯文本散文（含自然换行），禁止输出 JSON、禁止 markdown 代码块围栏。"""

SYSTEM_EXTRACT = """你是长篇网文创作系统的【记忆抽取 Agent】。从章节正文抽取结构化记忆候选。
输出严格 JSON：{"candidates": [
  {"kind": "event", "source_chapter": 章号, "confidence": 0.0-1.0, "payload": {"summary": "事件摘要", "participants": ["人物名"], "source_chapter": 章号, "confidence": 0.0-1.0}},
  {"kind": "character_state", "source_chapter": 章号, "confidence": 0.0-1.0, "payload": {"character_id": "人物名", "field": "只能取 location|injury|realm|power|item|knowledge|goal|identity|alive 之一（境界变化用 realm，存活变化用 alive，位置用 location）", "old_value": "", "new_value": "", "source_chapter": 章号, "confidence": 0.0-1.0}},
  {"kind": "fact", "source_chapter": 章号, "confidence": 0.0-1.0, "payload": {"content": "长期事实", "category": "规则", "is_hard": false, "source_chapter": 章号, "confidence": 0.0-1.0}},
  {"kind": "foreshadow", "source_chapter": 章号, "confidence": 0.0-1.0, "payload": {"description": "本章新种下的伏笔（可回收的悬念/物件/承诺，能且应被后续回收）", "trigger": {"actor": "触发者", "action": "动作", "object": "对象"}, "source_chapter": 章号, "confidence": 0.0-1.0}},
  {"kind": "plotline", "source_chapter": 章号, "confidence": 0.0-1.0, "payload": {"thread_name": "被推进的活跃剧情线名称（须匹配注入的活跃剧情线）", "note": "本章如何推进该线"}}
]}
顶层 confidence 必填。只抽确定事实，不猜。伏笔只抽「本章明确埋下的」——含糊提及不算，避免伏笔池噪声。
剧情线推进（plotline）只在「本章正文确实推进了某条活跃剧情线」时才抽，thread_name 须与注入的活跃剧情线名一致（不新增线名）。"""

SYSTEM_REVISE = """你是长篇网文创作系统的【修订 Agent】。按校验发现逐条修订正文。
输出格式：先输出独立一行 === CONTENT ===，从下一行开始输出修订后全文（纯文本散文，
禁止 JSON、禁止 markdown 代码块围栏）。全部修订完成后，再输出独立一行 === RESPONSES ===，
下一行输出严格 JSON 数组：[{"conflict_key": "key", "outcome": "fixed|cannot_fix|dispute", "note": "说明"}]"""

SYSTEM_AUDIT = """你是长篇网文创作系统的【审核中枢 Agent】。写作完成后的调度大脑，对本章做语义审核并输出路由决策。
三步：① 对照章节计划判断剧情发展是否合理（推进了该推进的线、收了该收的伏笔、无主线偏移）；② 判断内容质量（衔接/人设/节奏）；③ 输出路由决策。
输出严格 JSON：
{
  "verdict": "pass|rewrite|replan",
  "replan_target": "chapter|batch（仅 verdict=replan 时必填：本章规划偏 → chapter；整批蓝图走偏 → batch）",
  "findings": [{"conflict_key": "hash键", "conflict_type": "power|timeline|location|character|character_state|relation|foreshadow|item_rule|plotline|persona|style", "severity": "critical|major|minor|hint", "scope": "local|structural", "evidence": [{"chapter": 章号, "quote": "原文片段"}], "confidence": 0.0-1.0, "suggestion": "修改建议"}],
  "reasons": ["路由决策理由（可审计）"],
  "confidence": 0.0-1.0
}
规则：只有剧情/内容确实有问题才 rewrite 或 replan；本章合格一律 pass（不制造冗余修订）。
如需核实人物状态/世界观事实/伏笔/剧情线，可调用只读查证工具，核实后仍输出严格 JSON。"""

SYSTEM_REFLEXION = """你是长篇网文创作系统的【复盘 Agent】。把本书审核中枢（audit）发现的跨章问题，总结演化为本书可复用的写作经验，注入后续章节的规划/写作。
输入：① 本批次各章的校验发现（战力越界/人设漂移/大纲偏差/文风问题等，含冲突类型/严重度/证据/建议）；② 本书已有的在效写作经验。
输出严格 JSON：{"lessons": [
  {"conflict_type": "faction|power|timeline|location|character|character_state|relation|foreshadow|item_rule|plotline|persona|style",
   "lesson_type": "planning|writing|both", "content": "跨章可复用的一句话写作经验（具体可执行，直接注入后续章节规划/写作）",
   "confidence": 0.0-1.0, "evidence": [{"chapter": 章号, "quote": "原文片段"}]}
]}
规则：
- 只提炼「本书级、跨章可复用」的经验；单章一次性笔误不提炼；
- 一条经验对应一个冲突类型（跨类型拆多条）；同冲突类型合并成一条综合经验；
- 结合「本书已有经验」总结演化——本次发现若已在该类经验覆盖范围内（同类反复出现），更新表述使其更全面，不另立新条；已有经验未覆盖的新发现，新增一条；
- 本书已有经验已覆盖全部发现 → 输出空数组 {"lessons": []}；
- 经验必须具体可执行，拒绝空泛的"注意一致性"。"""

SYSTEM_GLOBAL_AUDIT = """你是长篇网文创作系统的【全局审计 Agent】。对抽样角色做跨章人设漂移判定（长线一致性治理 §8.6）。
输入：每个角色的【性格基线】（characters.personality）+ 该角色近 N 章言行摘录（每条带章号）。
任务：比对言行与基线，判定是否存在人设漂移——谨慎→鲁莽、腔调改变、动机随剧情临时变，且正文中无变故铺垫/成长弧线支撑。
输出严格 JSON：{"findings": [
  {"character": "角色名", "drift_type": "persona", "chapter": 章号,
   "evidence": "原文引用（必须逐字来自摘录，供程序核验）", "reason": "判定理由", "confidence": 0.0-1.0}
]}
规则（宁缺毋滥，漏报优于误报）：
- 只判「确有漂移且无变故铺垫/成长弧线」的言行；有变故铺垫、角色成长弧线支撑的转变 → 不判漂移；
- evidence 必须逐字引用正文片段（不得改写、不得拼接）；每条 finding 的 chapter 必须在审计窗口内；
- 证据不足 / 边界情形 → 直接不输出该条；每角色至多 1 条；
- 全书无漂移 → 输出空数组 {"findings": []}。"""

SYSTEM_GLOBAL_AUDIT_BRIDGE = """你是长篇网文创作系统的【全局审计 Agent】。对抽样「桥段重复候选对」做跨章判定（长线一致性治理 §8.6）。
输入：每对含【历史桥段】（历史章事件摘要）+【当前桥段】（当前章事件摘要 + 当前章正文节选，带章号与章距）。
任务：对每对判定是【刻意呼应】（call-back，正常创作手法——当前桥段有明确不同目的 / 差异化改写 / 呼应意图，非偷懒）还是【偷懒重复】（同一桥段结构雷同、无新意无新目的，直接照搬）。
输出严格 JSON：{"findings": [
  {"event": "候选对编号", "verdict": "repeat"|"echo", "chapter": 章号,
   "evidence": "原文引用（必须逐字来自当前章正文节选，供程序核验）", "reason": "判定依据（差异点/目的）", "confidence": 0.0-1.0}
]}
规则（宁缺毋滥，漏报优于误报）：
- 只判给出的候选对，不凭空新增；每对至多 1 条；
- 仅【偷懒重复】输出 finding（verdict=repeat）；【刻意呼应】输出 verdict=echo 或直接省略该条；
- evidence 必须逐字引用当前章正文（不得改写、不得拼接）；每条 finding 的 chapter 必须在审计窗口内；
- 证据不足 / 目的不明 / 边界情形 → 直接不输出该条；
- 全书无偷懒重复 → 输出空数组 {"findings": []}。"""


def _join(ctx_items: list[dict], render) -> str:
    return "\n".join(render(i) for i in ctx_items)


def _render_fact(item: dict) -> str:
    """渲染硬约束/事实为可读文本（§7.2 硬约束恒在 Top-K——注入内容而非裸 id）。"""
    content = item.get("content") or ""
    if content:
        src = item.get("source_chapter")
        label = f"（自第 {src} 章）" if src else "（设定配置）"
        return f"- [硬约束/事实] {content} {label}"
    return f"- [硬约束/事实] {item.get('fact_id', '')} (chapter {item.get('source_chapter', '?')})"


def _render_event(item: dict) -> str:
    """渲染事件为可读文本：摘要优先，缺省回退 event_id。"""
    summary = (item.get("summary") or "").strip()
    head = f"{item.get('event_id', '')} " if not summary else ""
    return f"- [事件] {head}{summary} (chapter {item.get('chapter', '?')}, conf {item.get('confidence', '?')})"


def _render_entity(item: dict) -> str:
    state = item.get("state", {})
    return f"- [{item.get('name')}] 境界上限={item.get('realm_cap')} 状态={state}"


def _render_short(item: dict) -> str:
    return f"- [{item.get('kind')}] {item.get('text') or item.get('summary') or ''}"


def _render_foreshadow(item: dict) -> str:
    trigger = item.get("trigger") or {}
    return (f"- [{item.get('status')}] {item.get('description')} "
            f"(种于第 {item.get('planted_chapter', '?')} 章, 回收条件: "
            f"触发者={trigger.get('actor', '?')} 动作={trigger.get('action', '?')} 对象={trigger.get('object', '?')})")


def _render_thread(item: dict) -> str:
    return (f"- [{item.get('kind')}] {item.get('name')} ({item.get('status')}, "
            f"最近推进第 {item.get('last_progress_chapter') or '?'} 章, 进度: {item.get('progress') or '—'})")


def _render_lesson(item: dict) -> str:
    """渲染一条写作经验（§8.9 reflexion）：内容 + 来源章溯源。"""
    src = item.get("source_chapter")
    label = f"（源自第 {src} 章）" if src else ""
    return f"- [写作经验·{item.get('category')}] {item.get('content')} {label}"


def _lesson_section(context: dict, channels: tuple[str, ...]) -> str:
    """写作经验注入段（§8.9）：按 lesson_type 通道过滤（planning/writing/both）。"""
    items = [i for i in context.get("reflexions", []) if i.get("lesson_type") in channels]
    return "\n".join(_render_lesson(i) for i in items)


def plan_messages(context: dict, batch_goal: str | None = None) -> list[dict]:
    """plan_chapter 输入：召回上下文 + 批次目标。

    开放伏笔/剧情线注入（§7.9）：hooks_to_resolve 必须从【开放伏笔】里选——
    防 LLM 编造不存在的伏笔要收，防伏笔烂尾。
    """
    facts = _join(context.get("long_term_facts", []), _render_fact)
    events = _join(context.get("mid_term_events", []), _render_event)
    entities = _join(context.get("entity_snapshots", []), _render_entity)
    short = _join(context.get("short_context", []), _render_short)
    foreshadows = _join(context.get("open_foreshadows", []), _render_foreshadow)
    threads = _join(context.get("plot_threads", []), _render_thread)

    lessons = _lesson_section(context, ("planning", "both"))
    system = (
        SYSTEM_PLAN
        + "\n\n【世界观硬约束】\n" + (facts or "（无）")
        + "\n【前情事件】\n" + (events or "（无）")
        + "\n【出场人物状态快照】\n" + (entities or "（无）")
        + "\n\n【开放伏笔（待回收，hooks_to_resolve 必须从中选，收/延/弃要明确）】\n" + (foreshadows or "（无）")
        + "\n【活跃剧情线（hooks_to_plant 可补新钩子，但主线推进优先）】\n" + (threads or "（无）")
        + "\n【本书写作经验（reflexion 复盘，规划须遵守）】\n" + (lessons or "（无）")
    )
    user_parts = ["【近期上下文】\n" + (short or "（无）")]
    if batch_goal:
        user_parts.append(f"【本批次推进目标】\n{batch_goal}")
    user_parts.append("请输出本章章节计划（严格 JSON）。")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(user_parts)}]


def _style_section(style_profile: dict | None, target_words: int | None) -> str:
    """文风档案注入段（§7.12 / §8.6 生成约束）：字数目标 + 句式禁忌 + 对话要求。"""
    parts = []
    if target_words:
        low, high = int(target_words * 0.8), int(target_words * 1.3)
        # 中文 1 字 ≈ 1.4 token：写清换算，避免模型把"3000 字"当"3000 tokens"（实测会超写 40%+）
        parts.append(
            f"目标篇幅：{target_words} 字（约 {int(target_words * 1.4)} tokens）。"
            f"实际输出请控制在 {low}–{high} 字区间，超限会被校验拦截并要求修订。"
        )
    sp = style_profile or {}
    if sp.get("pov"):
        parts.append(f"叙事视角：{sp['pov']}。")
    if sp.get("sentence_style"):
        parts.append(f"句式要求：{sp['sentence_style']}。")
    forbidden = sp.get("forbidden") or []
    if forbidden:
        parts.append("表述禁忌（必须避免）：" + "；".join(forbidden) + "。")
    fw = sp.get("fatigue_words") or []
    if fw:
        parts.append("高频词节制（避免机械复用）：" + "、".join(fw) + "。")
    if sp.get("dialogue"):
        parts.append(f"对话要求：{sp['dialogue']}。")
    return "\n".join(parts)


def write_messages(context: dict, plan: dict, *, style_profile: dict | None = None,
                   target_words: int | None = None) -> list[dict]:
    """write 输入：召回上下文 + 章节计划 + 文风/字数生成约束（§7.12）。"""
    facts = _join(context.get("long_term_facts", []), _render_fact)
    entities = _join(context.get("entity_snapshots", []), _render_entity)
    short = _join(context.get("short_context", []), _render_short)
    style = _style_section(style_profile, target_words)
    lessons = _lesson_section(context, ("writing", "both"))
    system = (
        SYSTEM_WRITE
        + "\n\n【世界观硬约束】\n" + (facts or "（无）")
        + "\n【人物状态快照】\n" + (entities or "（无）")
        + (f"\n\n【文风要求（project_settings.style_profile）】\n{style}" if style else "")
        + "\n\n【本书写作经验（reflexion 复盘，写作须遵守）】\n" + (lessons or "（无）")
    )
    user = (
        "【章节计划】\n" + json.dumps(plan, ensure_ascii=False, indent=1)
        + "\n\n【近期上下文】\n" + (short or "（无）")
        + "\n请输出本章正文。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def extract_messages(draft: str, chapter_seq: int) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_EXTRACT},
        {"role": "user", "content": f"【章节正文】（第 {chapter_seq} 章）\n{draft}\n\n请抽取记忆候选（严格 JSON）。"},
    ]


def revise_messages(draft: str, findings: list[dict], chapter_seq: int) -> list[dict]:
    finding_lines = "\n".join(
        f"- [{f.get('severity')}] {f.get('conflict_type')}: {f.get('evidence')} | 建议: {f.get('suggestion')}"
        for f in findings
    )
    return [
        {"role": "system", "content": SYSTEM_REVISE},
        {"role": "user", "content": f"【第 {chapter_seq} 章正文】\n{draft}\n\n【校验发现】\n{finding_lines}\n\n请修订并输出修订后正文。"},
    ]


def audit_messages(draft: str, plan: dict, context: dict, chapter_seq: int) -> list[dict]:
    """audit 输入：正文 + 章节计划 + 召回上下文（审核中枢做语义审核 + 路由决策）。"""
    plan_str = json.dumps(plan, ensure_ascii=False, indent=1) if plan else "（无章节计划）"
    events = _join(context.get("mid_term_events", []), _render_event)
    foreshadows = _join(context.get("open_foreshadows", []), _render_foreshadow)
    threads = _join(context.get("plot_threads", []), _render_thread)
    user = (
        f"【第 {chapter_seq} 章正文】\n{draft}"
        + f"\n\n【章节计划】\n{plan_str}"
        + "\n\n【剧情上下文】\n" + (threads or "（无）")
        + "\n【开放伏笔】\n" + (foreshadows or "（无）")
        + "\n【近期事件】\n" + (events or "（无）")
        + "\n\n请审核本章并输出路由决策（严格 JSON）。"
    )
    return [{"role": "system", "content": SYSTEM_AUDIT}, {"role": "user", "content": user}]


def reflexion_messages(findings: list[dict], existing_lessons: list[dict],
                       start_chapter: int, size: int) -> list[dict]:
    """reflexion 提炼输入（§8.9）：本批 findings + 本书已有经验（供总结演化）。"""
    finding_lines = "\n".join(
        f"- [{f.get('severity')}] {f.get('conflict_type')}（第 {f.get('_chapter', '?')} 章）: "
        f"{f.get('suggestion') or ''} | 证据: {((f.get('evidence') or [{}])[0].get('quote') or '')[:80]}"
        for f in findings
    )
    existing_lines = "\n".join(
        f"- [{l.get('category')}] {l.get('content')}（复发 {l.get('recurrence_count', 0)} 次）"
        for l in existing_lessons
    ) or "（暂无）"
    user = (
        f"本批次第 {start_chapter}–{start_chapter + size - 1} 章，共 {len(findings)} 项发现：\n{finding_lines}"
        + f"\n\n【本书已有写作经验（总结演化时参考，避免重复新增）】\n{existing_lines}"
        + "\n\n请提炼/演化为本书写作经验（严格 JSON）。"
    )
    return [{"role": "system", "content": SYSTEM_REFLEXION}, {"role": "user", "content": user}]


def global_audit_messages(personas: list[dict], window: tuple[int, int]) -> list[dict]:
    """全局审计人设漂移输入（§8.6）：抽样角色基线 + 窗口内言行摘录（逐字引用供核验）。"""
    char_blocks = []
    for p in personas:
        passages = "\n".join(
            f"- 第 {ps['chapter']} 章：{ps['quote']}" for ps in p["passages"]
        ) or "（窗口内未提及该角色——无言行证据，不应输出该角色的 finding）"
        char_blocks.append(
            f"【角色 {p['name']}】\n性格基线：{p['baseline'] or '（未设定）'}\n近 N 章言行摘录：\n{passages}"
        )
    user = (
        f"审计窗口：第 {window[0]}–{window[1]} 章。对下列每个抽样角色做跨章人设漂移判定：\n\n"
        + "\n\n".join(char_blocks)
        + "\n\n请输出严格 JSON（无漂移输出空数组）。"
    )
    return [{"role": "system", "content": SYSTEM_GLOBAL_AUDIT}, {"role": "user", "content": user}]


def bridge_audit_messages(pairs: list[dict], window: tuple[int, int]) -> list[dict]:
    """全局审计桥段重复输入（§8.6 切片 2）：候选对（历史摘要 + 当前章正文节选，逐字供核验）。"""
    pair_blocks = []
    for p in pairs:
        pair_blocks.append(
            f"【候选对 {p['id']}】\n"
            f"历史桥段（第 {p['history_chapter']} 章）：{p['history_summary']}\n"
            f"当前桥段（第 {p['chapter']} 章，距上次 {p['gap']} 章）：事件摘要 {p['summary']}\n"
            f"当前章正文节选：\n{p['text']}"
        )
    user = (
        f"审计窗口：第 {window[0]}–{window[1]} 章。对下列每对桥段候选做「刻意呼应 vs 偷懒重复」判定：\n\n"
        + "\n\n".join(pair_blocks)
        + "\n\n请输出严格 JSON（无偷懒重复输出空数组）。"
    )
    return [{"role": "system", "content": SYSTEM_GLOBAL_AUDIT_BRIDGE},
            {"role": "user", "content": user}]
