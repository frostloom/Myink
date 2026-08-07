"""Prompt 模板（阶段 1 精简版）。

要点（plan.md §14 安全）：系统指令与用户输入角色分界；文风/硬约束注入到系统层；
提取的记忆只当数据注入、不携带执行权限。JSON mode 要求 prompt 含 "json" 字样。
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
输出严格 JSON：{"content": "正文全文"}"""

SYSTEM_EXTRACT = """你是长篇网文创作系统的【记忆抽取 Agent】。从章节正文抽取结构化记忆候选。
输出严格 JSON：{"candidates": [
  {"kind": "event", "source_chapter": 章号, "confidence": 0.0-1.0, "payload": {"summary": "事件摘要", "participants": ["人物名"], "source_chapter": 章号, "confidence": 0.0-1.0}},
  {"kind": "character_state", "source_chapter": 章号, "confidence": 0.0-1.0, "payload": {"character_id": "人物名", "field": "只能取 location|injury|realm|power|item|knowledge|goal|identity|alive 之一（境界变化用 realm，存活变化用 alive，位置用 location）", "old_value": "", "new_value": "", "source_chapter": 章号, "confidence": 0.0-1.0}},
  {"kind": "fact", "source_chapter": 章号, "confidence": 0.0-1.0, "payload": {"content": "长期事实", "category": "规则", "is_hard": false, "source_chapter": 章号, "confidence": 0.0-1.0}},
  {"kind": "foreshadow", "source_chapter": 章号, "confidence": 0.0-1.0, "payload": {"description": "本章新种下的伏笔（可回收的悬念/物件/承诺，能且应被后续回收）", "trigger": {"actor": "触发者", "action": "动作", "object": "对象"}, "source_chapter": 章号, "confidence": 0.0-1.0}}
]}
顶层 confidence 必填。只抽确定事实，不猜。伏笔只抽「本章明确埋下的」——含糊提及不算，避免伏笔池噪声。"""

SYSTEM_REVISE = """你是长篇网文创作系统的【修订 Agent】。按校验发现逐条修订正文。
输出严格 JSON：{"content": "修订后全文", "responses": [{"conflict_key": "key", "outcome": "fixed|cannot_fix|dispute", "note": "说明"}]}"""

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
规则：只有剧情/内容确实有问题才 rewrite 或 replan；本章合格一律 pass（不制造冗余修订）。"""


def _join(ctx_items: list[dict], render) -> str:
    return "\n".join(render(i) for i in ctx_items)


def _render_fact(item: dict) -> str:
    return f"- [硬约束/事实] {item.get('fact_id', '')} (chapter {item.get('source_chapter', '?')})"


def _render_event(item: dict) -> str:
    return f"- [事件] {item.get('event_id', '')} (chapter {item.get('chapter', '?')}, conf {item.get('confidence', '?')})"


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

    system = (
        SYSTEM_PLAN
        + "\n\n【世界观硬约束】\n" + (facts or "（无）")
        + "\n【前情事件】\n" + (events or "（无）")
        + "\n【出场人物状态快照】\n" + (entities or "（无）")
        + "\n\n【开放伏笔（待回收，hooks_to_resolve 必须从中选，收/延/弃要明确）】\n" + (foreshadows or "（无）")
        + "\n【活跃剧情线（hooks_to_plant 可补新钩子，但主线推进优先）】\n" + (threads or "（无）")
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
    system = (
        SYSTEM_WRITE
        + "\n\n【世界观硬约束】\n" + (facts or "（无）")
        + "\n【人物状态快照】\n" + (entities or "（无）")
        + (f"\n\n【文风要求（project_settings.style_profile）】\n{style}" if style else "")
    )
    user = (
        "【章节计划】\n" + json.dumps(plan, ensure_ascii=False, indent=1)
        + "\n\n【近期上下文】\n" + (short or "（无）")
        + "\n请输出本章正文（严格 JSON）。"
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
        {"role": "user", "content": f"【第 {chapter_seq} 章正文】\n{draft}\n\n【校验发现】\n{finding_lines}\n\n请修订（严格 JSON）。"},
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
