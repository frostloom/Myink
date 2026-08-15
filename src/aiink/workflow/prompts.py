"""Prompt 模板（阶段 1 精简版）。

要点（plan.md §14 安全）：系统指令与用户输入角色分界；文风/硬约束注入到系统层；
提取的记忆只当数据注入、不携带执行权限。仅 plan/extract/audit/style_extract 走 json_mode
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
  {"kind": "relation_change", "source_chapter": 章号, "confidence": 0.0-1.0, "payload": {"source_id": "人物名", "target_id": "人物名", "relation_type": "只能取 hostile|ally|master_student|located_in|owns|defeated_by|knows|promises|happened_at 之一", "old_value": "", "new_value": "", "source_chapter": 章号, "confidence": 0.0-1.0}},
  {"kind": "fact", "source_chapter": 章号, "confidence": 0.0-1.0, "payload": {"content": "长期事实", "category": "规则", "is_hard": false, "source_chapter": 章号, "confidence": 0.0-1.0}},
  {"kind": "foreshadow", "source_chapter": 章号, "confidence": 0.0-1.0, "payload": {"description": "本章新种下的伏笔（可回收的悬念/物件/承诺，能且应被后续回收）", "trigger": {"actor": "触发者", "action": "动作", "object": "对象"}, "source_chapter": 章号, "confidence": 0.0-1.0}},
  {"kind": "plotline", "source_chapter": 章号, "confidence": 0.0-1.0, "payload": {"thread_name": "被推进的活跃剧情线名称（须匹配注入的活跃剧情线）", "note": "本章如何推进该线"}}
]}
顶层 confidence 必填。只抽确定事实，不猜。伏笔只抽「本章明确埋下的」——含糊提及不算，避免伏笔池噪声。
剧情线推进（plotline）只在「本章正文确实推进了某条活跃剧情线」时才抽，thread_name 须与注入的活跃剧情线名一致（不新增线名）。
关系变更（relation_change）只抽「正文明确发生的关系演变」（和解/决裂/结盟/逐出师门等）；old_value 须与注入的当前台账快照一致；正文仅表现关系现状而无演变 → 不抽。"""

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

SYSTEM_GLOBAL_AUDIT_STYLE = """你是长篇网文创作系统的【全局审计 Agent】。对抽样窗口章节做文风漂移判定（长线一致性治理 §8.6）。
输入：① 【本书既定文风基线】（窗口之前已确认章节的正文摘录，每条带章号，锚定作者自身风格）；② 【文风档案】（project_settings.style_profile）；③ 【审计窗口章节摘录】（每条带章号，待判定）。
任务：比对窗口摘录与「本书既定文风基线 + 文风档案」，判定是否存在系统性、持续性的文风漂移——腔调/句式/用词/视角/对话/氛围/节奏整体偏离既定风格，且非单场景合法变化。
输出严格 JSON：{"findings": [
  {"chapter": 章号, "verdict": "drift"|"ok", "evidence": "原文引用（必须逐字来自该窗口章摘录，供程序核验）",
   "aspect": "句式/用词/视角/对话/氛围/节奏", "reason": "与基线/档案不符的差异点", "confidence": 0.0-1.0}
]}
规则（宁缺毋滥，漏报优于误报）：
- 只判「与既定文风系统性持续偏离」的章；单场景节奏/情感合法变化（战斗短句、抒情长句、情绪波动）→ 不判漂移；
- evidence 必须逐字引用该窗口章正文摘录（不得改写、不得拼接）；每条 finding 的 chapter 必须在审计窗口内；
- 证据不足 / 边界情形 → 直接不输出该条；每章至多 1 条；
- 全窗口无漂移 → 输出空数组 {"findings": []}。"""

SYSTEM_LEDGER_L2 = """你是长篇网文创作系统的【正文-台账语义比对 Agent】（点级校验，长线一致性治理 §8.6）。
输入：① 【当前章正文】（待判）；② 【候选变更清单】（每条含 key、类型、实体/关系双方、台账当前值、候选新值）。
任务：对每个候选，判定当前章正文**是否明确建立了该变更**——状态/关系从台账旧值到新值，正文是否有明确交代
（过渡情节 / 来源事件 / 变更记录，如：养伤治疗、闭关突破、受封夺权、逐出师门、把酒言和结盟）。
输出严格 JSON：{"judgments": [
  {"key": "候选键", "verdict": "valid"|"invalid", "evidence": "逐字引用当前章正文中建立或未建立该变更的片段",
   "reason": "判定依据", "confidence": 0.0-1.0}
]}
规则（宁缺毋滥，漏报优于误报）：
- 只判给定的候选，不凭空新增；每候选至多 1 条；
- valid = 正文明确建立了该变更（有过渡/来源/变更记录）；invalid = 正文直接表现新值但无任何建立交代（无过渡推翻 / 无来源却示人 / 无变更却相反）；
- evidence 必须逐字引用当前章正文（不得改写、不得拼接）；key 必须来自给定候选；
- 证据不足 / 边界情形 → valid（不报）；
- 全部变更均已建立 → 输出空数组 {"judgments": []}。"""


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
    relations = item.get("relations", [])
    line = f"- [{item.get('name')}] 境界上限={item.get('realm_cap')} 状态={state}"
    if relations:
        rels = ", ".join(
            f"→{r.get('target')}={r.get('relation_type')}" + (f"(自第{r.get('source_chapter')}章)" if r.get("source_chapter") else "")
            for r in relations
        )
        line += f" 关系: {rels}"
    return line


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


def _profile_list(profile: dict, key: str) -> list[str]:
    """文风档案列表键的安全读取：list→str 清洗；str 非空→单元素；其余→[]。

    防字符串被 join / [*a, *b] 逐字展开（PUT 走 dict 透传，前端可能传 str）。
    """
    val = profile.get(key)
    if isinstance(val, list):
        return [str(v) for v in val if str(v).strip()]
    if isinstance(val, str) and val.strip():
        return [val]
    return []


def _style_section(style_profile: dict | None, target_words: int | None) -> str:
    """文风档案注入段（§7.12 / §8.6 生成约束）：字数目标 + 句式/词汇约束 + 对话要求 + 风格示范。

    §7.12 样本提取新增键全部 get() 容错（lexicon_tendency / reference_excerpts /
    frequent_words / 节奏基线），与既有键渲染一致；fatigue_words/forbidden 键不变 →
    L1/L2 检测零回归（样例 15/38/39 锚点）。列表键经 _profile_list 类型守卫。
    """
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
    if sp.get("lexicon_tendency"):
        parts.append(f"词汇修辞倾向：{sp['lexicon_tendency']}。")
    forbidden = _profile_list(sp, "forbidden")
    if forbidden:
        parts.append("表述禁忌（必须避免）：" + "；".join(forbidden) + "。")
    fw = _profile_list(sp, "fatigue_words")
    freq = _profile_list(sp, "frequent_words")
    # §7.12：样本提取产出的高频词串并入写章节制（与显式 fatigue_words 去重合并），不进 L1 阈值
    high_freq = list(dict.fromkeys([*fw, *freq]))
    if high_freq:
        parts.append("高频词节制（避免机械复用）：" + "、".join(high_freq) + "。")
    if sp.get("dialogue"):
        parts.append(f"对话要求：{sp['dialogue']}。")
    rhythm = _rhythm_reference(sp)
    if rhythm:
        parts.append(rhythm)
    excerpts = _profile_list(sp, "reference_excerpts")
    if excerpts:
        parts.append("风格示范（作者样本摘录，模仿其文风、不逐字复制）：\n"
                     + "\n".join(f"- {e}" for e in excerpts))
    return "\n".join(parts)


def _rhythm_reference(sp: dict) -> str:
    """节奏基线一行（§7.12 样本提取）：样本平均句长 + 对话占比 → 写章节奏参考（容错缺键）。"""
    dist = sp.get("sentence_len_dist")
    if not isinstance(dist, dict) or not dist.get("avg"):
        return ""
    line = f"节奏参考：样本平均句长 {dist['avg']} 字。"
    ratio = sp.get("dialogue_ratio")
    if isinstance(ratio, (int, float)) and 0 <= ratio <= 1:
        line += (f" 对话占比约 {ratio * 100:.0f}%，对话偏{'多' if ratio >= 0.4 else '少'}"
                 f"，写章对话密度请贴近样本。")
    return line


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


def extract_messages(draft: str, chapter_seq: int, context: dict | None = None) -> list[dict]:
    """extract 输入：正文 + （可选）当前台账快照。

    context（recall 的 RetrievedContext）非空时注入实体状态/关系快照——extract 据此校准
    character_state.old_value 与产出 relation_change 候选（正文-台账语义比对 L2 的证据链入口）。
    """
    ledger_block = ""
    if context:
        entities = _join(context.get("entity_snapshots", []), _render_entity)
        if entities:
            ledger_block = f"\n\n【当前台账快照】（供校准 old_value / 产出 relation_change 候选）\n{entities}"
    return [
        {"role": "system", "content": SYSTEM_EXTRACT},
        {"role": "user", "content": f"【章节正文】（第 {chapter_seq} 章）\n{draft}{ledger_block}\n\n请抽取记忆候选（严格 JSON）。"},
    ]


def ledger_l2_messages(judgments: list[dict], draft: str, chapter_seq: int) -> list[dict]:
    """正文-台账语义比对 L2 输入：当前章正文 + 待判候选清单（台账当前值 vs 候选新值）。"""
    rows = []
    for j in judgments:
        if j["kind"] == "relation_change":
            rows.append(f"- [{j['key']}] 关系变更 {j['src_name']}→{j['tgt_name']}: 台账={j['ledger']} → 候选新值={j['new_value']}")
        else:
            rows.append(f"- [{j['key']}] 状态变更 {j['entity_name']}.{j['field']}: 台账={j['ledger']} → 候选新值={j['new_value']}")
    body = "\n".join(rows) or "（无）"
    return [
        {"role": "system", "content": SYSTEM_LEDGER_L2},
        {"role": "user", "content": f"【当前章正文】（第 {chapter_seq} 章）\n{draft}\n\n【候选变更清单】\n{body}\n\n请逐项判定（严格 JSON）。"},
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


def style_audit_messages(baseline: list[dict], sampled: list[dict], style_profile: dict | None,
                         window: tuple[int, int]) -> list[dict]:
    """全局审计文风漂移输入（§8.6 切片 3）：基线摘录 + 窗口摘录 + 文风档案（逐字供核验）。

    档案块复用 _style_section（pov/句式/禁忌/fatigue_words/对话，容错缺键）。
    """
    def render(items: list[dict], label: str) -> str:
        lines = "\n".join(f"- 第 {c['chapter']} 章：{c['text']}" for c in items)
        return f"【{label}】\n{lines}" if lines else f"【{label}】（空）"

    profile = _style_section(style_profile, None)
    user = (
        f"审计窗口：第 {window[0]}–{window[1]} 章。比对窗口摘录与本书既定文风基线，判定文风漂移：\n\n"
        + render(baseline, "本书既定文风基线（窗口之前已确认章节摘录，锚定作者自身风格）")
        + f"\n\n【文风档案（project_settings.style_profile）】\n" + (profile or "（未配置）")
        + "\n\n" + render(sampled, "审计窗口章节摘录（待判定）")
        + "\n\n请输出严格 JSON（无漂移输出空数组）。"
    )
    return [{"role": "system", "content": SYSTEM_GLOBAL_AUDIT_STYLE},
            {"role": "user", "content": user}]


SYSTEM_STYLE_EXTRACT = """你是长篇网文创作系统的【文风提炼 Agent】。把作者提交的样本正文提炼成该书可复用的文风档案草稿（§7.12 样本提取）。
输入：① 作者样本（1–2 篇）；② 对样本的确定性统计（句长分布 / 对话密度 / 段落结构 / 高频词串——数字只作参考，语义提炼以样本正文为准）。
输出严格 JSON 对象：
{
  "pov": "叙事人称与视角（如：第三人称限知、以主角为主；样本无稳定倾向写「未从样本提炼」）",
  "sentence_style": "句式与节奏习惯（长短句偏好 / 段落疏密 / 避免机械交替；样本无稳定倾向写「未从样本提炼」）",
  "lexicon_tendency": "词汇与修辞倾向（用词色彩 / 意象 / 比喻习惯）",
  "dialogue": "对话腔调要求（角色区分度 / 口语化程度）",
  "forbidden": ["样本中反复暴露的滥俗 / AI 味表达（2–4 条，具体可执行）"],
  "reference_excerpts": ["1–2 段最能代表该文风的样本原文（逐字摘自样本，供写章作风格示范）"]
}
规则：
- 只提炼样本中真实、反复出现的特征，不臆造；样本信息不足的字段填「未从样本提炼」或省略该键；
- forbidden 只列样本里确实反复出现 / 暴露问题的表达，宁缺毋滥；
- reference_excerpts 必须逐字摘自样本原文（不得改写、不得拼接），1–2 段即可。"""


def style_extract_messages(samples: list[str], stats: dict) -> list[dict]:
    """文风样本提炼输入（§7.12 样本提取）：作者样本正文 + 确定性统计（数字只作提炼参考）。"""
    sample_block = "\n\n".join(f"【样本 {i + 1}】\n{s}" for i, s in enumerate(samples))
    dist = stats.get("sentence_len_dist") or {}
    para = stats.get("para_stats") or {}
    freq = "、".join(stats.get("frequent_words") or []) or "（无）"
    stats_block = (
        f"- 句长分布（字）：短<15 {dist.get('short')} / 中15-40 {dist.get('mid')} / "
        f"长>40 {dist.get('long')}，平均 {dist.get('avg')} 字\n"
        f"- 对话占比：{stats.get('dialogue_ratio')}\n"
        f"- 段落结构：{para.get('count')} 段，平均 {para.get('avg_len')} 字/段\n"
        f"- 高频词串（2 字）：{freq}"
    )
    return [
        {"role": "system", "content": SYSTEM_STYLE_EXTRACT},
        {"role": "user", "content": f"【作者样本】\n{sample_block}\n\n"
                                    f"【确定性统计（仅参考，语义以样本为准）】\n{stats_block}\n\n"
                                    f"请提炼文风档案草稿（严格 JSON）。"},
    ]


SYSTEM_BOOK_SETUP = """你是长篇网文创作系统的【规划 Agent】。职责：根据作者的一句话梗概与题材偏好，产出本书的**设定骨架草稿**（§7.11 建书流程：提案→确认→落库，agent 只提案不篡改）。
输出严格 JSON 对象（schema 见下），字段不许缺：
{
  "realm_order": ["境界/实力阶段按升序排列，非仙侠题材则给出实力/职业进阶序列"],
  "world_rules": {"规则键": "规则值，如 时间/地域/禁制 等世界观硬性规定"},
  "hard_constraints": ["写作必须遵守的硬约束，如 不可越级晋升、不得引入仙佛鬼神"],
  "forces": [{"name": "势力名", "stance": "立场/主张", "resources": ["资源"]}],
  "characters": [{"name": "人物名", "role": "主角/重要配角/反派", "race": "", "origin": "出身", "realm_cap": "实力上限（战力硬约束，非仙侠题材给定位）", "personality": "性格基调一句话"}],
  "locations": [{"name": "关键地点名"}]
}
要求：骨架是**可编辑草稿**不是定稿——数量克制（核心 3-6 个角色、2-4 个势力、3-5 个地点即可），留白让作者后续补全；hard_constraints 必须是明确的、可执行的写作纪律，不是风格形容词。"""


def book_setup_messages(genre: str, premise: str) -> list[dict]:
    """建书设定草稿输入（§7.11 ② 一句话梗概启动 + Planner 提案）：题材 + 作者一句话梗概。

    json_mode 调用（prompt 含 "json" 字样）；Planner 复用（不新增 agent），生成的是
    可编辑骨架，不落库——用户逐项确认/修改后走 setup 端点落库。
    """
    return [
        {"role": "system", "content": SYSTEM_BOOK_SETUP},
        {"role": "user", "content": f"【题材偏好】\n{genre}\n\n"
                                    f"【作者一句话梗概】\n{premise}\n\n"
                                    f"请产出本书设定骨架草稿（严格 JSON）。"},
    ]
