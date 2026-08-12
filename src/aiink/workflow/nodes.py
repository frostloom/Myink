"""单章子图节点实现（spec/state-flow.md 节点契约）。

确定性节点：load_state / recall / validate / persist —— 无 LLM，纯代码；
LLM 节点：plan_chapter / write / extract / revise / audit —— 走 ModelProvider 降级链。
LLM agent 不持**写**工具（§6.2 数据流边界）：Audit/Writer 持只读查证工具（§10，
function calling），写库只在 persist（编排层）发生。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from aiink.config import settings
from aiink.db import tenant_session
from aiink.memory import repository as repo
from aiink.memory.embedder import get_embedder
from aiink.memory.recall import build_context
from aiink.memory.vector_store import PgvectorStore
from aiink.models import AgentRun, Chapter, CharacterState, Event, Fact, Foreshadow, MemoryCandidate, Relation, WritingLesson
from aiink.models.memory import CHARACTER_STATE_FIELDS
from aiink.providers import FallbackChain, ModelResponse, make_chain
from aiink.schemas import AuditVerdict, ChapterPlan, Finding, MutationCandidate, ValidationReport
from aiink.validation.service import ValidationService
from aiink.workflow import prompts
from aiink.workflow.state import ChapterState
from aiink.workflow.tools import READ_TOOLS, execute_tool

logger = logging.getLogger(__name__)


# ---- 运行记录（§6.8：每节点一行 agent_runs 全字段 + 成本估算）----

def record_run(db: Session, *, project_id: str, task_id: str | None, node: str, role: str | None,
               resp: ModelResponse, error: str | None = None, detail: dict | None = None) -> None:
    db.add(AgentRun(
        project_id=uuid.UUID(project_id),
        task_id=task_id,  # thread_id（字符串，单章=task_id / 批次= batch:ch{seq}）
        node=node, role=role, model_id=resp.model_id,
        input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
        cache_hit=resp.cache_hit, duration_ms=resp.duration_ms,
        cost_est=resp.cost_est, retry_count=resp.retry_count,
        degraded=resp.degraded, error=error, detail=detail,
    ))


def record_plain(db: Session, *, project_id: str, task_id: str | None, node: str,
                 detail: dict | None = None, duration_ms: int = 0) -> None:
    """确定性节点运行记录（无 LLM 调用：load_state/recall/validate/persist，§6.8 debug 全链路）。

    cost/token 为 0（不是 LLM 调用），detail 带执行统计（角色数/召回数/校验命中/落库数），
    让前端流转图能画出完整真实链路，而非只画 LLM 环节。
    """
    db.add(AgentRun(
        project_id=uuid.UUID(project_id),
        task_id=task_id, node=node,
        input_tokens=0, output_tokens=0, duration_ms=duration_ms,
        cost_est=0.0, detail=detail,
    ))


def record_run_detail(db: Session, *, task_id: str | None, node: str, detail: dict) -> None:
    """补记节点关键产物到最后一次该节点 agent_runs（如 audit verdict——解析后才产生）。

    合并而非覆盖：工具轮已写入 tool_trace，这里再叠加 verdict，保持 debug 信息完整。
    """
    if not task_id:
        return
    db.flush()  # 保证上一次 record_run 的 insert 对后续 query 可见（session autoflush=False）
    row = (db.query(AgentRun)
           .filter(AgentRun.task_id == task_id, AgentRun.node == node)
           .order_by(AgentRun.id.desc()).first())
    if row:
        row.detail = {**(row.detail or {}), **detail}


# 各节点 max_tokens 上限（§19.3：JSON mode 须设 max_tokens 防截断）。
# write 按 target_words 换算限长：实测中文约 1 token ≈ 0.7 字（1 字≈1.43 token），
# 3000 字 ≈ 2100 tokens；×1.25 余量防截断，同时从源头限死字数（最多 ~3900 字）。
_WRITE_TOKENS_PER_CHAR = 1.43
_MAX_TOKENS = {"plan_chapter": 4096, "extract": 4096, "revise": 8192, "audit": 4096, "reflexion": 4096}


def _assistant_tool_calls_message(resp: ModelResponse) -> dict:
    """重建 assistant tool_calls 消息（§10 工具循环回传格式）。

    DeepSeek/OpenAI 要求下轮请求原样回传 assistant 的 tool_calls：arguments 须为
    JSON 字符串（Provider 已解析成 dict，这里重新 dumps）；thinking 已在 Provider
    关掉，无 reasoning_content 需回传（§19.3）。
    """
    return {
        "role": "assistant",
        "content": resp.content or "",
        "tool_calls": [
            {"id": tc["id"], "type": "function",
             "function": {"name": tc["name"],
                          "arguments": json.dumps(tc.get("arguments") or {}, ensure_ascii=False)}}
            for tc in (resp.tool_calls or [])
        ],
    }


def _run_tool_loop(db: Session, state: ChapterState, node: str, role: str, chain: FallbackChain,
                   messages: list[dict], *, max_tokens: int, tools: list[dict],
                   max_tool_calls: int, detail: dict | None = None,
                   final_json: bool = True) -> tuple[ModelResponse, list[dict]]:
    """只读查证工具循环（§10）。

    单循环 + 条件最终轮：工具轮无 tool_calls 就直接用其 content（单轮，与无工具
    完全一致）；只有实际调了工具才追加「无 tools」最终轮输出最终结果。预算以工具执行
    总数计，超预算先把已发起的工具执行完再进最终轮（保证消息历史合法：不存在无 tool
    结果的 assistant tool_calls）。最终轮按节点区分输出格式：final_json=True（audit）
    强制严格 JSON；final_json=False（write）要求纯文本正文（=== CONTENT === 标记）。
    """
    messages = list(messages)
    used_tool = False
    tool_count = 0
    tool_trace: list[dict] = []
    while True:
        resp = chain.generate(messages, json_mode=False, max_tokens=max_tokens, tools=tools)
        # detail 带「到本轮为止已执行的工具」：每轮可审计调了哪些工具（§6.8 debug）
        record_run(db, project_id=state["project_id"], task_id=state.get("task_id"),
                   node=node, role=role, resp=resp, error=resp.error,
                   detail={**(detail or {}), "tool_trace": list(tool_trace)})
        if resp.error or not resp.tool_calls:
            return resp, tool_trace
        used_tool = True
        messages.append(_assistant_tool_calls_message(resp))
        for tc in resp.tool_calls:
            result = execute_tool(db, uuid.UUID(state["project_id"]), tc["name"], tc.get("arguments") or {})
            tool_trace.append({"tool": tc["name"], "arguments": tc.get("arguments") or {},
                               "result": result[:200]})
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            tool_count += 1
        if tool_count >= max_tool_calls:
            break
    # 条件最终轮：去掉 tools（§10：最终轮带 tools 会诱导再次调工具）。按节点分输出格式：
    # audit 强制严格 JSON；write 纯文本正文（json_mode=False + 关思考，防思考抢占预算）。
    if final_json:
        messages.append({"role": "system",
                         "content": "请基于工具核实结果直接输出最终严格 JSON，不要再调用工具。"})
        resp = chain.generate(messages, json_mode=True, max_tokens=max_tokens)
    else:
        messages.append({"role": "system",
                         "content": "请基于工具核实结果直接输出本章正文（纯文本散文，先输出独立一行 === CONTENT ===，禁止 JSON），不要再调用工具。"})
        resp = chain.generate(messages, json_mode=False, max_tokens=max_tokens,
                              disable_thinking=True)
    record_run(db, project_id=state["project_id"], task_id=state.get("task_id"),
               node=node, role=role, resp=resp, error=resp.error,
               detail={**(detail or {}), "tool_trace": list(tool_trace)})
    return resp, tool_trace


def _llm(db: Session, state: ChapterState, node: str, role: str, chain: FallbackChain,
         messages: list[dict], *, tools: list[dict] | None = None,
         detail: dict | None = None,
         json_mode: bool = True, disable_thinking: bool = False) -> tuple[ModelResponse, list[dict]]:
    """统一 LLM 调用入口：带 tools 走只读查证工具循环，否则单次调用（§10）。

    json_mode 默认 True（plan/extract/audit 结构化输出）；write/revise 传 False
    走纯文本正文（=== CONTENT === 标记）。disable_thinking 仅纯文本路径需要：
    DeepSeek v4 思考模式默认开启，不关会抢占正文 token 预算（§19.3）。
    """
    max_tokens = _MAX_TOKENS.get(node)
    if node == "write":
        # 源头限长：按目标字数换算 token 上限（§6.9 防超写，§19.3 防截断）
        target = state.get("target_words") or 3000
        max_tokens = int(target * _WRITE_TOKENS_PER_CHAR * 1.25)
    if tools:
        return _run_tool_loop(db, state, node, role, chain, messages,
                              max_tokens=max_tokens, tools=tools,
                              max_tool_calls=settings.max_tool_calls, detail=detail,
                              final_json=json_mode)
    resp = chain.generate(messages, json_mode=json_mode, max_tokens=max_tokens,
                          disable_thinking=disable_thinking)
    record_run(db, project_id=state["project_id"], task_id=state.get("task_id"),
               node=node, role=role, resp=resp, error=resp.error, detail=detail)
    return resp, []


def _split_marked(content: str) -> dict[str, str]:
    """按 === 标记切块（write/revise 纯文本正文，§6.12 标记锚点）。

    独立行 ``=== 标记名 ===`` 起一个新块，块内文本归该标记；标记行前的杂质文本
    归 "default"。无任何标记 → 整段归 "default"（模型漏写标记时兜底不丢章）。
    块文本保留原始换行，仅去掉首尾空行。
    """
    parts: dict[str, str] = {}
    cur_key: str | None = None
    cur_buf: list[str] = []
    for line in content.split("\n"):
        # 标记名大小写不敏感（模型偶发输出小写/中文标记行，兜底归 default 会污染正文）
        m = re.match(r"^=== ([a-zA-Z_一-鿿]+) ===\s*$", line.strip())
        if m:
            if cur_key is not None:
                parts[cur_key] = "\n".join(cur_buf).strip("\n")
            cur_key = m.group(1).upper()
            cur_buf = []
        else:
            if cur_key is None:
                cur_key = "default"
            cur_buf.append(line)
    if cur_key is not None:
        parts[cur_key] = "\n".join(cur_buf).strip("\n")
    return parts


def _content_block(parts: dict[str, str], raw: str) -> str:
    """取正文块（write/revise）：优先 CONTENT 标记，其次 default（模型漏写标记兜底），
    再次第一个非空命名块（模型写错标记名如 === 正文 === 时仍取到正文、标记行不落库），
    最后回退整段原文。"""
    for key in ("CONTENT", "default"):
        if key in parts and parts[key]:
            return parts[key]
    for v in parts.values():
        if v:
            return v
    return raw


# 模型把工具调用写成文本（未走 function calling 协议）的强特征（§10 单轮/最终轮跑偏）。
# 网文正文几乎不可能含这些 XML/函数调用痕迹，命中即判 write/revise 跑偏、显式失败，
# 防止把噪声当正文落库。
_TOOL_NOISE_MARKERS = ("<ai_output>", "<function_results>", "<invoke name=", "<tool_use",
                       "<tool_calls>", "<DSML", "|assistant|")


def _looks_like_tool_noise(text: str) -> bool:
    """DeepSeek 偶发在 tools 上下文里输出文本式工具调用（而非返回 tool_calls）。

    场景：`_run_tool_loop` 单轮直出（模型没调工具但写了"调用了 inspect_facts…"）或
    最终轮跑偏，把 `<ai_output>...<invoke name=...>` 混进正文 → 无标记归 default →
    垃圾当正文。命中强特征即显式失败（诚实报错可重发），不落库污染。
    """
    return any(m in text for m in _TOOL_NOISE_MARKERS)


def _parse_json(content: str) -> Any:
    """鲁棒 JSON 解析（§6.12 输出容错）。

    真实 LLM 偶发在 JSON 前/后附杂质（markdown 围栏、语气词）、尾部含 ``}`` 的废话、
    或字符串里放原始控制字符（DeepSeek 偶发未转义换行 → 非法 JSON）、
    正文里放裸 ASCII 双引号（字符串被提前闭合 → Expecting ',' delimiter）。
    raw_decode 只解析首个完整 JSON 值，天然截断尾部杂质；控制字符转义、裸引号转义依次兜底。
    """
    decoder = json.JSONDecoder()
    try:
        return decoder.raw_decode(content)[0]
    except json.JSONDecodeError:
        start = content.find("{")
        if start == -1:
            raise
        body = _escape_control_chars(content[start:])
        try:
            return decoder.raw_decode(body)[0]
        except json.JSONDecodeError:
            # 裸引号兜底：仅当常规容错仍失败（不影响合法 JSON 的解析路径）
            return decoder.raw_decode(_repair_stray_quotes(body))[0]


def _escape_control_chars(s: str) -> str:
    """JSON 字符串值内原始控制字符转义（§6.12 输出容错，§19.3 思考兜底必踩）。

    状态机：只在 JSON 字符串值内转义 0x00-0x1F / 0x7F 单字节控制字符；
    结构空白 ``\\t``/``\\n``/``\\r`` 原样保留（JSON 结构空白只允许这三个原始字符）。
    已转义的 ``\\n`` 是反斜杠+n 两字符，状态机按转义对跳过，不误伤。

    旧实现用 ``[\\x00-\\x1f\\x7f]`` 无差别正则替换，把结构位置的合法换行也转成
    ``\\u000a`` 字面量 —— 字面量在结构位置非法（结构空白不接受转义序列），
    导致「前导杂质 + 多行 JSON」在容错路径必挂：audit 的 reasoning_content 兜底
    是带前导思考文本的多行 JSON，2026-08-10 演示逼出（Expecting property name
    line 1 column 2）。仅当字符串值内原始换行/制表符 → \\uXXXX 还原为字符串内容。
    """
    out: list[str] = []
    in_str = False
    escaped = False
    for ch in s:
        if escaped:  # 字符串值内转义对的后半（\" \\\\ \\uXXXX 的后续），原样跳过
            out.append(ch)
            escaped = False
            continue
        if in_str and ch == "\\":
            escaped = True
            out.append(ch)
            continue
        if ch == '"':
            in_str = not in_str
            out.append(ch)
            continue
        if not in_str and ch in ("\t", "\n", "\r"):
            out.append(ch)  # JSON 结构空白：合法，保留
            continue
        if in_str and ("\x00" <= ch <= "\x1f" or ch == "\x7f"):
            out.append("\\u%04x" % ord(ch))
            continue
        out.append(ch)
    return "".join(out)


def _repair_stray_quotes(s: str) -> str:
    """JSON 字符串值内裸引号转义兜底（§6.12 输出容错）。

    DeepSeek 偶发在正文里用 ASCII 双引号（应转义而未转义）→ 字符串被提前闭合，
    json 报 ``Expecting ',' delimiter``。状态机：在字符串值内，裸 ``"`` 后跟 ``, : } ]``
    之一视为结构闭合符（保留），否则视为正文引号（补反斜杠转义）。已转义的 ``\\"``/``\\\\``/``\\uXXXX``
    原样跳过不误伤。仅在常规容错后兜底，合法 JSON 走不到这里。
    """
    out: list[str] = []
    in_str = False
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if in_str:
            if ch == "\\" and i + 1 < n:  # 转义对（\" \\\\ \\uXXXX）整对跳过
                out.append(ch)
                out.append(s[i + 1])
                i += 2
                continue
            if ch == '"':
                nxt = s[i + 1] if i + 1 < n else ""
                if nxt in ',:}]':
                    in_str = False  # 后随结构分隔符 → 真正的字符串闭合引号
                    out.append(ch)
                else:
                    out.append("\\")  # 正文里的裸引号 → 转义保留
                    out.append(ch)
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_str = True
        out.append(ch)
        i += 1
    return "".join(out)


def _coerce_str_lists(data: dict, model: type[BaseModel]) -> dict:
    """§6.12 输出容错：把 schema 的 list[str] 字段归一化（LLM 偶发写成对象数组）。

    真实 DeepSeek 会把 ``hooks_to_plant`` 返回成 ``[{"hook": "..."}]`` 而非 ``["..."]``，
    直接过 pydantic 校验失败。这里只对 list[str] 字段取主要文本文值，其余字段不动。
    """
    str_list_fields = {n for n, f in model.model_fields.items() if f.annotation == list[str]}
    for field in str_list_fields:
        items = data.get(field)
        if not isinstance(items, list):
            continue
        coerced: list[str] = []
        for it in items:
            if isinstance(it, str):
                coerced.append(it)
            elif isinstance(it, dict):
                # 优先取常见文本键；没有则取「唯一字符串值」兜底（键名不可控，值内容才可信）
                text = next((it[k] for k in ("hook", "goal", "event", "constraint", "text", "content",
                                             "title", "description", "summary")
                             if isinstance(it.get(k), str)), None)
                if text is None:
                    str_values = [v for v in it.values() if isinstance(v, str)]
                    if len(str_values) == 1:
                        text = str_values[0]
                if text:
                    coerced.append(text)
            # 其他类型（数字/嵌套对象）丢弃，保持下游 contract 稳定
        data[field] = coerced
    return data


def _resolve_character_id(db: Session, project_id: str, name: str) -> uuid.UUID | None:
    """人名 → canonical id（§7.5 归一化；找不到则不落该候选，不猜）。"""
    ch = repo.get_character(db, uuid.UUID(project_id), name)
    return ch.id if ch else None


# ---- 确定性节点 ----

def node_load_state(state: ChapterState) -> ChapterState:
    pid = state["project_id"]
    with tenant_session(pid) as db:
        characters = [
            {"id": str(c.id), "name": c.name, "realm_cap": c.realm_cap, "personality": c.personality}
            for c in repo.get_all_characters(db, uuid.UUID(pid))
        ]
        settings_row = repo.get_settings(db, uuid.UUID(pid))
        world_rules = (settings_row.world_rules if settings_row else {}) or {}
        style_profile = (settings_row.style_profile if settings_row else {}) or {}
        project = repo.get_project(db, uuid.UUID(pid))
        target_words = project.target_words if project and project.target_words else None
        plan_input = {"characters": characters, "world_rules": world_rules}
        record_plain(db, project_id=pid, task_id=state.get("task_id"), node="load_state",
                     detail={"characters": len(characters)})
        return {"characters": characters, "chapter_plan_input": plan_input, "settings": world_rules,
                "style_profile": style_profile, "target_words": target_words,
                # 重置上次尝试的瞬态失败标记（§6.12 续跑）：同 thread 再 invoke 时
                # LangGraph 合并 checkpoint 状态，残留 error 会让 write/extract 短路重蹈失败 → 这里清零
                "error": None, "needs_review": False, "persisted": False, "unresolved": []}


def node_recall(state: ChapterState) -> ChapterState:
    pid = state["project_id"]
    participants = [c.get("name") for c in state.get("characters", [])[:12]]
    shared = state.get("shared_context") or {}
    with tenant_session(pid) as db:
        ctx = build_context(
            db, project_id=uuid.UUID(pid), chapter_seq=state["chapter_seq"],
            participants=participants, user_instruction=state.get("user_instruction"),
            shared_context=shared,
        )
        out = {"context": ctx.model_dump(mode="json")}
        # 批次级共享池：首章组装后回写，供批次层桥给后续章复用（§6.11，稳定部分一次组装）
        if shared:
            out["shared_context"] = shared
        record_plain(db, project_id=pid, task_id=state.get("task_id"), node="recall",
                     detail={"facts": len(ctx.long_term_facts), "events": len(ctx.mid_term_events),
                             "snapshots": len(ctx.entity_snapshots),
                             "foreshadows": len(ctx.open_foreshadows),
                             "threads": len(ctx.plot_threads)})
        return out


def node_validate(state: ChapterState) -> ChapterState:
    pid = state["project_id"]
    realm_order = (state.get("settings") or {}).get("realm_order", [])
    if not realm_order:
        return {"report": ValidationReport(
            project_id=uuid.UUID(pid), chapter_seq=state["chapter_seq"],
        ).model_dump(), "unresolved": []}

    with tenant_session(pid) as db:
        candidates = [MutationCandidate(**c) for c in state.get("candidates", [])]
        plan = ChapterPlan(**state["plan"]) if state.get("plan") else None
        if state.get("error"):
            return {"report": ValidationReport(
                project_id=uuid.UUID(pid), chapter_seq=state["chapter_seq"],
            ).model_dump(), "unresolved": []}
        service = ValidationService(realm_order=realm_order)
        report = service.validate(db, project_id=uuid.UUID(pid), chapter_seq=state["chapter_seq"],
                                  candidates=candidates, plan=plan,
                                  draft=state.get("draft"), target_words=state.get("target_words"))
        # unresolved = critical/major（触发 revise；hint 不阻塞）
        unresolved = [f.model_dump(mode="json") for f in report.findings if f.severity in ("critical", "major")]
        # 校验报告落库（findings 证据链可追溯，§8.7）
        record_plain(db, project_id=pid, task_id=state.get("task_id"), node="validate",
                     detail={"findings_total": report.summary.get("total", 0),
                             "critical": report.summary.get("critical", 0),
                             "unresolved": len(unresolved)})
        return {"report": report.model_dump(mode="json"), "unresolved": unresolved}


def node_audit(state: ChapterState) -> ChapterState:
    """审核中枢（§6.5/§6.11 混合路由的 LLM 语义层）：L2 语义校验 + 剧情/质量判断 + 路由决策。

    输出 AuditVerdict（pass/rewrite/replan）做语义路由；L1 critical 与轮次预算由
    route_after_audit 规则层强制（Audit 不能绕过硬约束）。决策 reasons/confidence 落库可审计。
    """
    if state.get("error"):
        return {}  # 上游 LLM 已失败：透传根因（§6.12）
    pid = state["project_id"]
    draft = state.get("draft")
    if not draft:
        return {"error": "write 未产出草稿"}
    with tenant_session(pid) as db:
        messages = prompts.audit_messages(
            draft, state.get("plan") or {}, state.get("context") or {}, state["chapter_seq"]
        )
        resp, tool_trace = _llm(db, state, "audit", "Audit", make_chain("audit"), messages,
                                tools=READ_TOOLS)
        if resp.error:
            return {"error": resp.error}
        try:
            data = _parse_json(resp.content)
            verdict = AuditVerdict(**{k: v for k, v in data.items() if k in AuditVerdict.model_fields})
            # 审核决策补记到本条 agent_runs（§6.8 debug：verdict/reasons/confidence 落库可审计）
            record_run_detail(db, task_id=state.get("task_id"), node="audit",
                              detail={"audit_verdict": verdict.model_dump(mode="json")})
        except (json.JSONDecodeError, ValidationError) as exc:
            return {"error": f"audit 输出解析失败: {exc} | content[:120]={resp.content[:120]!r} len={len(resp.content)}"}
    # verdict.findings（L2）→ unresolved：rewrite 时 revise 注入逐条修（§6.5）
    unresolved = [f.model_dump(mode="json") for f in verdict.findings
                  if f.severity in ("critical", "major")]
    out: dict = {
        "audit_verdict": verdict.model_dump(mode="json"),
        "unresolved": unresolved,
        "replan_batch": verdict.verdict == "replan" and verdict.replan_target == "batch",
    }
    # 只读查证工具调用痕迹（§10）：可审计 + 佐证 Agent 确实核实过（ §5 工具参与率）
    if tool_trace:
        out["tool_trace"] = tool_trace
    return out


# ---- LLM 节点 ----

def node_plan_chapter(state: ChapterState) -> ChapterState:
    pid = state["project_id"]
    with tenant_session(pid) as db:
        messages = prompts.plan_messages(state.get("context") or {}, state.get("batch_goal"))
        resp, _ = _llm(db, state, "plan_chapter", "Planner", make_chain("planner"), messages)
        if resp.error:
            return {"error": resp.error}
    try:
        data = _coerce_str_lists(
            _parse_json(resp.content), ChapterPlan)
        plan = ChapterPlan(**{k: v for k, v in data.items() if k in ChapterPlan.model_fields})
        plan.project_id = uuid.UUID(pid)
        plan.chapter_seq = state["chapter_seq"]
    except (json.JSONDecodeError, ValidationError) as exc:
        return {"error": f"plan_chapter 输出解析失败: {exc}"}
    return {"plan": plan.model_dump(mode="json")}


def node_write(state: ChapterState) -> ChapterState:
    if state.get("error"):
        return {}  # 上游 LLM 已失败：透传根因，不再覆盖（§6.12 错误可追溯）
    pid = state["project_id"]
    with tenant_session(pid) as db:
        messages = prompts.write_messages(
            state.get("context") or {}, state.get("plan") or {},
            style_profile=state.get("style_profile"), target_words=state.get("target_words"),
        )
        resp, tool_trace = _llm(db, state, "write", "Writer", make_chain("writer"), messages,
                                tools=READ_TOOLS, json_mode=False, disable_thinking=True)
        if resp.error:
            return {"error": resp.error}
    parts = _split_marked(resp.content)
    draft = _content_block(parts, resp.content)
    if not draft:
        return {"error": f"write 输出为空: content[:120]={resp.content[:120]!r} len={len(resp.content)}"}
    if _looks_like_tool_noise(draft):
        return {"error": f"write 输出跑偏（工具调用文本而非正文）: content[:120]={resp.content[:120]!r} len={len(resp.content)}"}
    out: dict = {"draft": draft}
    if tool_trace:
        out["tool_trace"] = tool_trace
    return out


def node_extract(state: ChapterState) -> ChapterState:
    if state.get("error"):
        return {}  # 上游 LLM 已失败：透传根因（§6.12）
    pid = state["project_id"]
    draft = state.get("draft")
    if not draft:
        return {"error": "write 未产出草稿"}
    with tenant_session(pid) as db:
        messages = prompts.extract_messages(draft, state["chapter_seq"])
        resp, _ = _llm(db, state, "extract", "Memory", make_chain("extract"), messages)
        if resp.error:
            return {"error": resp.error}
        try:
            data = _parse_json(resp.content)
            raw_candidates = data.get("candidates", []) or []
        except json.JSONDecodeError as exc:
            return {"error": f"extract 输出解析失败: {exc}"}

        candidates: list[dict] = []
        for raw in raw_candidates:
            try:
                cand = MutationCandidate(**raw)
            except ValidationError:
                continue  # 坏候选拒绝但不崩（§6.12 数据层）
            if cand.kind == "character_state":
                cid = _resolve_character_id(db, pid, str(cand.payload.get("character_id", "")))
                if not cid:
                    continue  # 无法归一化的角色不落库
                # field 白名单校验（§6.12 坏候选拒绝但不崩）：LLM 自由输出可能造出
                # DB CHECK 枚举外的新值（如 "realm_status"），落库必炸批次 → 这里丢弃
                if cand.payload.get("field") not in CHARACTER_STATE_FIELDS:
                    logger.warning("丢弃非法 character_state 候选 field=%r（ch%d）",
                                   cand.payload.get("field"), state["chapter_seq"])
                    continue
                cand.payload["character_id"] = str(cid)
            candidates.append(cand.model_dump(mode="json"))
    return {"candidates": candidates}


def node_revise(state: ChapterState) -> ChapterState:
    pid = state["project_id"]
    with tenant_session(pid) as db:
        messages = prompts.revise_messages(state["draft"], state.get("unresolved", []), state["chapter_seq"])
        resp, _ = _llm(db, state, "revise", "Writer", make_chain("writer"), messages,
                       json_mode=False, disable_thinking=True)
        if resp.error:
            return {"error": resp.error}
    parts = _split_marked(resp.content)
    draft = _content_block(parts, resp.content)
    if not draft:
        return {"error": f"revise 输出为空: content[:120]={resp.content[:120]!r} len={len(resp.content)}"}
    if _looks_like_tool_noise(draft):
        return {"error": f"revise 输出跑偏（工具调用文本而非正文）: content[:120]={resp.content[:120]!r} len={len(resp.content)}"}
    responses = []
    raw_responses = parts.get("RESPONSES")
    if raw_responses:
        try:
            parsed = _parse_json(raw_responses)
            if isinstance(parsed, list):
                responses = parsed
        except json.JSONDecodeError:
            logger.warning("revise RESPONSES 块解析失败，忽略: %r", raw_responses[:120])
    return {
        "draft": draft,
        "revision_count": state.get("revision_count", 0) + 1,
        "revise_responses": responses,
    }


# ---- persist（编排层，§6.2 数据流边界的落库点）----

def node_persist(state: ChapterState) -> ChapterState:
    """确认分流（§6.11）：无 critical → 低风险自动放行落库；有 critical → 候选池待人工。"""
    pid = state["project_id"]
    chapter_seq = state["chapter_seq"]
    report = state.get("report") or {}
    critical = report.get("summary", {}).get("critical", 0) or 0

    if critical > 0:
        # critical 暂停：候选进待确认池，章节标 awaiting_review（§6.11）。
        # plotline 推进候选不落池——正文已写即推进已发生（低风险自动生效，§7.11），
        # 且 memory_candidates 的 DB CHECK 不含 plotline kind。
        with tenant_session(pid) as db:
            for cand in state.get("candidates", []):
                if cand["kind"] == "plotline":
                    continue
                # 幂等守卫：resume 续跑会重跑 extract → 防同 payload 候选在池里堆重复
                # （确认流：人工处理候选后 resume 重跑，重复项不应再进池）。
                if _pool_has_duplicate(db, pid, chapter_seq, cand):
                    continue
                db.add(MemoryCandidate(project_id=uuid.UUID(pid), kind=cand["kind"],
                                       source_chapter=chapter_seq, payload=cand["payload"],
                                       confidence=cand.get("confidence", 0.0)))
            ch = repo.get_chapter(db, uuid.UUID(pid), chapter_seq)
            if ch:
                ch.status = "awaiting_review"
            else:
                # 无行（该章从未 auto 落库）→ 补建待确认行：critical 转人工也应有章节
                # 记录可展示（原缺陷：critical 路径只更新不创建，依赖前序 auto 残留的行）
                db.add(Chapter(project_id=uuid.UUID(pid), chapter_seq=chapter_seq,
                               status="awaiting_review"))
        record_plain(db, project_id=pid, task_id=state.get("task_id"), node="persist",
                     detail={"candidates": len(state.get("candidates", [])),
                             "status": "awaiting_review", "reason": "critical"})
        return {"persisted": True, "needs_review": True}

    with tenant_session(pid) as db:
        # auto 放行路径：跳过已进确认池的候选（评审 A2——critical→confirm→resume 后
        # 重跑无 critical 时，confirmed/rejected 候选不再重复落库）
        _persist_candidates(db, pid, chapter_seq, state.get("candidates", []),
                            skip_pool_handled=True)
        # 落章节正文
        summary = _chapter_summary(state.get("candidates", []))
        repo.save_chapter(db, project_id=uuid.UUID(pid), chapter_seq=chapter_seq,
                          content=state["draft"], summary=summary, generation_source="auto")
        _advance_current_chapter(db, pid, chapter_seq)
        record_plain(db, project_id=pid, task_id=state.get("task_id"), node="persist",
                     detail={"candidates": len(state.get("candidates", [])),
                             "status": "auto_confirm"})
    return {"persisted": True, "needs_review": False}


def _persist_candidates(db: Session, pid: str, chapter_seq: int, candidates: list[dict],
                        *, skip_pool_handled: bool = False) -> None:
    """候选落库（auto 放行 / confirm 共用，§6.11）。

    skip_pool_handled=True（auto 路径，评审 A2）：候选已进过确认池（confirm 已落库 /
    reject 已拒绝）则跳过，防止「critical→confirm→resume→无 critical」时重复写入记忆。
    confirm_candidate 调用传 False（正在确认的那条必须落库）。"""
    project_id = uuid.UUID(pid)
    for cand in candidates:
        # plotline 不落确认池（正文已写即推进），无需查池
        if skip_pool_handled and cand["kind"] != "plotline" \
                and _pool_has_duplicate(db, pid, chapter_seq, cand):
            continue
        p = cand.get("payload") or {}
        if cand["kind"] == "event":
            # participants 是人物名（extract LLM 输出）→ 归一化为 canonical id（§7.5）
            participants: list[uuid.UUID] = []
            for name in p.get("participants", []):
                cid = _resolve_character_id(db, pid, str(name))
                if cid:
                    participants.append(cid)
            ev = Event(project_id=project_id, summary=p.get("summary", ""),
                       participants=[str(c) for c in participants],
                       source_chapter=chapter_seq, confidence=p.get("confidence", 0.8))
            db.add(ev)
            db.flush()  # 拿 ev.id 供向量索引关联
            _index_event_embedding(db, project_id, ev)
        elif cand["kind"] == "character_state":
            db.add(CharacterState(project_id=project_id,
                                  character_id=uuid.UUID(str(p["character_id"])),
                                  chapter_seq=chapter_seq, field=p["field"],
                                  old_value=p.get("old_value"), new_value=p.get("new_value"),
                                  source_chapter=chapter_seq, confidence=p.get("confidence", 0.8)))
        elif cand["kind"] == "fact":
            fact = Fact(project_id=project_id, content=p.get("content", ""),
                        category=p.get("category"), is_hard=bool(p.get("is_hard")),
                        source_chapter=chapter_seq, confidence=p.get("confidence", 0.8),
                        confirm_status="confirmed")
            db.add(fact)
            db.flush()  # 拿 fact.id 供向量索引关联
            _index_fact_embedding(db, project_id, fact)
        elif cand["kind"] == "relation_change":
            # 关系写入语义（§3 决策）：落库前先关闭同 (source_id, target_id) 有序对全部活跃
            # 旧行（schema.md §6「当前关系 = 最新 valid_to IS NULL」），透传候选 valid_to（临时盟约）。
            # 双端缺一或类型缺失无法定位关系对 → 跳过且不关任何行（§6.12 坏数据拒绝但不崩）。
            src = p.get("source_id")
            tgt = p.get("target_id")
            rtype = p.get("relation_type")
            if src and tgt and rtype:
                src_uuid, tgt_uuid = uuid.UUID(str(src)), uuid.UUID(str(tgt))
                _close_active_relations(db, project_id, src_uuid, tgt_uuid, chapter_seq)
                db.add(Relation(project_id=project_id, source_id=src_uuid,
                                relation_type=rtype, target_id=tgt_uuid,
                                confidence=p.get("confidence", 0.8), source_chapter=chapter_seq,
                                valid_from=p.get("valid_from", 1),
                                valid_to=p.get("valid_to")))
        elif cand["kind"] == "foreshadow":
            db.add(Foreshadow(project_id=project_id, description=p.get("description", ""),
                              status="planted", planted_chapter=chapter_seq, trigger=p.get("trigger") or {}))
        elif cand["kind"] == "plotline":
            # 剧情线推进台账（§7.9）：正文已写 = 推进已发生，低风险自动生效（同 §7.11
            # 地点自动建档），不落候选池。按名称匹配线程更新最近推进章；匹配不到不推进。
            name = str(p.get("thread_name", "") or "").strip()
            if name:
                for t in repo.get_plot_threads(db, project_id):
                    if name == (t.name or "") or name in (t.name or "") or (t.name or "") in name:
                        t.last_progress_chapter = chapter_seq
                        break


def _close_active_relations(db: Session, project_id: uuid.UUID, source_id: uuid.UUID,
                            target_id: uuid.UUID, chapter_seq: int) -> int:
    """收口同一 (source_id, target_id) 有序对的全部活跃旧关系（valid_to = 本章序，§7.8）。

    维护 schema.md §6「当前关系 = 最新一条 valid_to IS NULL」：新关系变更落库前必须把
    该对旧活跃行全部关闭，保证「每对至多一条活跃」不变量。跨类型全关（按对，非按类型）；
    只关同向对，不代写反向 (target, source)（§9.3 成对落库语义由写入侧负责）。返回关闭行数。
    """
    rows = db.query(Relation).filter(
        Relation.project_id == project_id,
        Relation.source_id == source_id,
        Relation.target_id == target_id,
        Relation.valid_to.is_(None),
    ).all()
    for r in rows:
        r.valid_to = chapter_seq
    return len(rows)


def _pool_has_duplicate(db: Session, pid: str, chapter_seq: int, cand: dict) -> bool:
    """候选池去重：同 kind+payload+章 的候选已存在（任意状态）则跳过。

    评审 A2 修复：原只查 pending——人工 confirm/reject 后状态变 confirmed/rejected，
    resume 重跑 extract 时对旧实现不可见 → 同 payload 候选再次进池 / 再次落库。
    现在任意状态（pending/confirmed/rejected）都挡重写，池内 (kind, payload, 章)
    至多一条。payload 列是 `JSON`（PG json 无 `=` 运算符），故拉同 kind+章的候选、
    Python 侧比对字典（池单章量级小，一次查询可接受）。"""
    from sqlalchemy import select

    project_id = uuid.UUID(pid)
    rows = db.execute(
        select(MemoryCandidate).where(
            MemoryCandidate.project_id == project_id,
            MemoryCandidate.kind == cand["kind"],
            MemoryCandidate.source_chapter == chapter_seq,
        )
    ).scalars().all()
    return any(r.payload == cand["payload"] for r in rows)


def confirm_candidate(db: Session, project_id: str, candidate_id: uuid.UUID) -> MemoryCandidate | None:
    """人工确认待确认池候选落库（§6.11 确认分流 / §7.3 事实生命周期）。

    编排层写库入口：候选的 kind+payload 走与 persist 自动放行完全相同的落库路径
    （_persist_candidates，含人物名归一化 / 向量索引降级），候选标 confirmed。
    归属断言：tenant_session 已按 project_id RLS 隔离，此处再显式校验 project_id
    防歧义（双保险，§14.1）。非 pending 候选（已确认/已拒绝）返回 None 不可重复处理。
    """
    cand = db.get(MemoryCandidate, candidate_id)
    if cand is None or str(cand.project_id) != project_id or cand.status != "pending":
        return None
    _persist_candidates(db, project_id, cand.source_chapter,
                        [{"kind": cand.kind, "payload": cand.payload, "confidence": cand.confidence}])
    cand.status = "confirmed"
    return cand


def _index_embedding(db: Session, *, project_id: uuid.UUID, level: str,
                     source_id: uuid.UUID, source_chapter: int | None,
                     text: str, model_version: str = "bge-m3") -> None:
    """通用向量化入 embeddings（分层 event/world/chapter，§7.2/§15）。

    加分项：bge-m3 未装/加载失败都降级（记录日志不阻塞落库，§6.12 数据层），
    伏笔/人设走偏主防线是关系链路（foreshadows 状态机 + 台账），不依赖本函数。
    """
    if not text:
        return
    try:
        emb = get_embedder().encode([text])[0]
        PgvectorStore().upsert(db, project_id=project_id, level=level, source_id=source_id,
                               source_chapter=source_chapter,
                               model_version=model_version, embedding=emb)
    except Exception as exc:
        logger.warning("向量化失败（level=%s），跳过索引（不影响落库）: %s", level, exc)


def _index_event_embedding(db: Session, pid: str, ev: Event) -> None:
    """事件摘要向量化入 embeddings（level=event，§15 最小向量召回）。"""
    _index_embedding(db, project_id=ev.project_id, level="event", source_id=ev.id,
                     source_chapter=ev.source_chapter, text=ev.summary)


def _index_fact_embedding(db: Session, pid: str, fact: Fact) -> None:
    """世界观/长期事实向量化入 embeddings（level=world，§7.2 分层 collection）。

    硬约束恒在 Top-K、不参与相似度截断（§7.2），向量化是浪费 → 跳过。
    """
    if fact.is_hard:
        return
    _index_embedding(db, project_id=fact.project_id, level="world", source_id=fact.id,
                     source_chapter=fact.source_chapter, text=fact.content)


def _chapter_summary(candidates: list[dict]) -> str:
    return "；".join(p.get("summary", "") for c in candidates if c["kind"] == "event" for p in [c.get("payload") or {}] if p.get("summary"))


def _advance_current_chapter(db: Session, pid: str, chapter_seq: int) -> None:
    """推进书当前进度 `Project.current_chapter`（§11.1，展示「下一章」与写保护基准）。

    之前恒为 0（没人更新），导致前端默认序号永远是 1、重复重写第 1 章。
    落库时置为 max(current, seq)——单调递增，不因重写已写章倒退。
    """
    from aiink.models import Project

    project_id = uuid.UUID(pid)
    proj = db.get(Project, project_id)
    if proj is not None and chapter_seq > (proj.current_chapter or 0):
        proj.current_chapter = chapter_seq


# ---- reflexion 复盘沉淀（§8.9）：audit findings → 跨章写作经验 ----

_SEVERITY_RANK = {"critical": 4, "major": 3, "minor": 2, "hint": 1}


def _collect_batch_audit_findings(db: Session, batch_task_id: str) -> list[dict]:
    """整批各章 audit findings（唯一持久化点 = agent_runs.detail，§6.8）。

    每章取最后一条 audit 行（settled 终态——不把 rewrite 循环里已修的发现重复灌入，
    后行覆盖即得本章最终 verdict）。每条补 `_chapter`（从 task_id `{batch}:ch{seq}` 解析）。
    """
    runs = db.query(AgentRun).filter(
        AgentRun.task_id.like(f"{batch_task_id}:ch%"), AgentRun.node == "audit",
    ).order_by(AgentRun.id.asc()).all()
    final: dict[str, AgentRun] = {}
    for r in runs:
        final[r.task_id] = r
    out: list[dict] = []
    for tid, r in final.items():
        verdict = (r.detail or {}).get("audit_verdict") or {}
        ch = int(tid.rsplit("ch", 1)[1])
        for f in verdict.get("findings") or []:
            f = dict(f)
            f["_chapter"] = ch
            out.append(f)
    return out


def _update_recurrences(db: Session, project_id: str, findings: list[dict],
                        start_chapter: int) -> int:
    """复发记账（确定性，不耗 LLM）：新 finding.conflict_type == active lesson.category
    且 lesson.source_chapter < 本批首章 → 复发。按 (lesson, chapter) 去重（rewrite 循环内
    同一 finding 只记一次）。返回本次复发数。"""
    pid = uuid.UUID(project_id)
    active = db.query(WritingLesson).filter(
        WritingLesson.project_id == pid, WritingLesson.status == "active"
    ).all()
    by_cat = {l.category: l for l in active}
    seen: set[tuple[str, int]] = set()
    for f in findings:
        lesson = by_cat.get(f.get("conflict_type"))
        if not lesson or (lesson.source_chapter or 0) >= start_chapter:
            continue
        seen.add((str(lesson.id), f.get("_chapter") or 0))
    for lid, ch in seen:
        lesson = next(l for l in active if str(l.id) == lid)
        lesson.recurrence_count = (lesson.recurrence_count or 0) + 1
        lesson.last_recurrence_at = max(lesson.last_recurrence_at or 0, ch)
    db.flush()
    return len(seen)


def _batch_already_reflexed(db: Session, project_id: str, batch_task_id: str) -> bool:
    """同批次已提炼过 → 跳过（幂等 guard，重跑不堆重复）。"""
    return db.query(WritingLesson).filter(
        WritingLesson.project_id == uuid.UUID(project_id),
        WritingLesson.source_batch_task_id == batch_task_id,
    ).first() is not None


def _covered_by_active(db: Session, project_id: str, findings: list[dict],
                       start_chapter: int) -> list[dict]:
    """已被在效经验覆盖的发现（同类经验 source_chapter < 本批首章）：不发 LLM、不新增经验。

    复发率已在 _update_recurrences 记账；只把「未被覆盖」的新发现喂 LLM 提炼/演化。
    """
    pid = uuid.UUID(project_id)
    active = db.query(WritingLesson).filter(
        WritingLesson.project_id == pid, WritingLesson.status == "active"
    ).all()
    covered_cats = {l.category for l in active if (l.source_chapter or 0) < start_chapter}
    return [f for f in findings if f.get("conflict_type") not in covered_cats]


def _persist_lessons(db: Session, project_id: str, batch_task_id: str, start: int,
                     lessons: list[dict], findings: list[dict]) -> tuple[int, int]:
    """提炼产物落库（编排层，§6.2 数据流边界）：Agent 不直写。

    - 可溯源守卫：lesson.conflict_type 必须在 findings 里有同型发现，否则丢弃（LLM 幻觉）；
    - 路由：同 category 已有行 → update 演化（保留 id、继承复发指标）；无 → create；
    - 分级（仅 create）：同型 findings 最高 severity critical/major → proposed，否则 active；
    - 去重：content_hash 字面（同 project+content_hash 任意状态已存在 → 跳过）。
    返回 (inserted, skipped_duplicates)。
    """
    pid = uuid.UUID(project_id)
    by_type: dict[str, list[dict]] = {}
    for f in findings:
        by_type.setdefault(f.get("conflict_type"), []).append(f)
    existing = {l.category: l for l in db.query(WritingLesson).filter(
        WritingLesson.project_id == pid).all()}
    inserted = skipped = 0
    for lesson in lessons:
        src = by_type.get(lesson.get("conflict_type")) or []
        if not src:
            continue  # 不可溯源 → 丢弃
        max_sev = max((f.get("severity") for f in src), key=lambda s: _SEVERITY_RANK.get(s, 0))
        h = hashlib.sha256(lesson["content"].encode("utf-8")).hexdigest()
        dup = db.query(WritingLesson).filter(
            WritingLesson.project_id == pid, WritingLesson.content_hash == h).first()
        if dup:
            skipped += 1
            continue
        evidence = [{k: f.get(k) for k in ("chapter", "conflict_type", "severity", "quote", "suggestion")}
                    for f in src if isinstance(f, dict)]
        src_ch = min((f.get("_chapter") or start for f in src), default=start)
        prev = existing.get(lesson.get("conflict_type"))
        if prev is not None:
            # 总结演化：同 category 更新同一行——content 换演化版、evidence 追加、保留 id 与复发指标
            prev.content = lesson["content"]
            prev.content_hash = h
            prev.confidence = lesson.get("confidence") or prev.confidence
            merged = prev.evidence or []
            existing_keys = {(e.get("chapter"), e.get("quote")) for e in merged if isinstance(e, dict)}
            for e in evidence:
                if (e.get("chapter"), e.get("quote")) not in existing_keys:
                    merged.append(e)
            prev.evidence = merged
            prev.source_chapter = min(prev.source_chapter or start, src_ch)
            prev.lesson_type = lesson.get("lesson_type", prev.lesson_type or "both")
            prev.source_batch_task_id = batch_task_id
            inserted += 1
            continue
        status = "proposed" if max_sev in ("critical", "major") else "active"
        db.add(WritingLesson(
            project_id=pid, category=lesson["conflict_type"],
            lesson_type=lesson.get("lesson_type", "both"),
            content=lesson["content"], content_hash=h,
            evidence=evidence, confidence=lesson.get("confidence") or 1.0,
            source_chapter=src_ch, source_batch_task_id=batch_task_id, status=status,
        ))
        inserted += 1
    db.flush()
    return inserted, skipped


def confirm_lesson(db: Session, project_id: str, lesson_id: uuid.UUID) -> WritingLesson | None:
    """人工确认经验生效（proposed→active，§8.9）。幂等：非 proposed 返回 None。

    归属断言同 confirm_candidate：tenant_session RLS + 显式 project_id 比对（双保险，§14.1）。
    """
    lesson = db.get(WritingLesson, lesson_id)
    if lesson is None or str(lesson.project_id) != project_id or lesson.status != "proposed":
        return None
    lesson.status = "active"
    return lesson


def reject_lesson(db: Session, project_id: str, lesson_id: uuid.UUID) -> WritingLesson | None:
    """拒绝经验（proposed→rejected，§8.9）。幂等：非 proposed 返回 None。"""
    lesson = db.get(WritingLesson, lesson_id)
    if lesson is None or str(lesson.project_id) != project_id or lesson.status != "proposed":
        return None
    lesson.status = "rejected"
    return lesson