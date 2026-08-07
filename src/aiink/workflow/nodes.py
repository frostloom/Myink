"""单章子图节点实现（spec/state-flow.md 节点契约）。

确定性节点：load_state / recall / validate / persist —— 无 LLM，纯代码；
LLM 节点：plan_chapter / write / extract / revise —— 走 ModelProvider 降级链。
LLM agent 不持任何工具（§6.2 数据流边界）；写库只在 persist（编排层）发生。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from aiink.config import settings
from aiink.db import tenant_session
from aiink.memory import repository as repo
from aiink.memory.embedder import get_embedder
from aiink.memory.recall import build_context
from aiink.memory.vector_store import PgvectorStore
from aiink.models import AgentRun, CharacterState, Event, Fact, Foreshadow, MemoryCandidate, Relation
from aiink.models.memory import CHARACTER_STATE_FIELDS
from aiink.providers import FallbackChain, ModelResponse, make_chain
from aiink.schemas import AuditVerdict, ChapterPlan, Finding, MutationCandidate, ValidationReport
from aiink.validation.service import ValidationService
from aiink.workflow import prompts
from aiink.workflow.state import ChapterState

logger = logging.getLogger(__name__)


# ---- 运行记录（§6.8：每节点一行 agent_runs 全字段 + 成本估算）----

def record_run(db: Session, *, project_id: str, task_id: str | None, node: str, role: str | None,
               resp: ModelResponse, error: str | None = None) -> None:
    db.add(AgentRun(
        project_id=uuid.UUID(project_id),
        task_id=task_id,  # thread_id（字符串，单章=task_id / 批次= batch:ch{seq}）
        node=node, role=role, model_id=resp.model_id,
        input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
        cache_hit=resp.cache_hit, duration_ms=resp.duration_ms,
        cost_est=resp.cost_est, retry_count=resp.retry_count,
        degraded=resp.degraded, error=error,
    ))


# 各节点 max_tokens 上限（§19.3：JSON mode 须设 max_tokens 防截断）。
# write 按 target_words 换算限长：实测中文约 1 token ≈ 0.7 字（1 字≈1.43 token），
# 3000 字 ≈ 2100 tokens；×1.25 余量防截断，同时从源头限死字数（最多 ~3900 字）。
_WRITE_TOKENS_PER_CHAR = 1.43
_MAX_TOKENS = {"plan_chapter": 4096, "extract": 4096, "revise": 8192, "audit": 4096}


def _llm(db: Session, state: ChapterState, node: str, role: str, chain: FallbackChain,
         messages: list[dict]) -> ModelResponse:
    max_tokens = _MAX_TOKENS.get(node)
    if node == "write":
        # 源头限长：按目标字数换算 token 上限（§6.9 防超写，§19.3 防截断）
        target = state.get("target_words") or 3000
        max_tokens = int(target * _WRITE_TOKENS_PER_CHAR * 1.25)
    resp = chain.generate(messages, json_mode=True, max_tokens=max_tokens)
    record_run(db, project_id=state["project_id"], task_id=state.get("task_id"),
               node=node, role=role, resp=resp, error=resp.error)
    return resp


def _parse_json(content: str) -> Any:
    """鲁棒 JSON 解析：直接 loads 失败则提取首个 {…} 子串（§6.12 输出容错）。

    真实 LLM 偶发在 JSON 前/后附杂质（markdown 围栏、语气词）或被截断，
    直接 json.loads 会误判失败。提取子串可显著提升结构化输出命中率。
    """
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start:end + 1])
        raise


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
        resp = _llm(db, state, "audit", "Audit", make_chain("audit"), messages)
        if resp.error:
            return {"error": resp.error}
    try:
        data = _parse_json(resp.content)
        verdict = AuditVerdict(**{k: v for k, v in data.items() if k in AuditVerdict.model_fields})
    except (json.JSONDecodeError, ValidationError) as exc:
        return {"error": f"audit 输出解析失败: {exc}"}
    # verdict.findings（L2）→ unresolved：rewrite 时 revise 注入逐条修（§6.5）
    unresolved = [f.model_dump(mode="json") for f in verdict.findings
                  if f.severity in ("critical", "major")]
    return {
        "audit_verdict": verdict.model_dump(mode="json"),
        "unresolved": unresolved,
        "replan_batch": verdict.verdict == "replan" and verdict.replan_target == "batch",
    }


# ---- LLM 节点 ----

def node_plan_chapter(state: ChapterState) -> ChapterState:
    pid = state["project_id"]
    with tenant_session(pid) as db:
        messages = prompts.plan_messages(state.get("context") or {}, state.get("batch_goal"))
        resp = _llm(db, state, "plan_chapter", "Planner", make_chain("planner"), messages)
        if resp.error:
            return {"error": resp.error}
    try:
        plan = ChapterPlan(**{k: v for k, v in _parse_json(resp.content).items() if k in ChapterPlan.model_fields})
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
        resp = _llm(db, state, "write", "Writer", make_chain("writer"), messages)
        if resp.error:
            return {"error": resp.error}
    try:
        data = _parse_json(resp.content)
        draft = data["content"]
    except (json.JSONDecodeError, ValidationError, KeyError) as exc:
        return {"error": f"write 输出解析失败: {exc} | content[:120]={resp.content[:120]!r} len={len(resp.content)}"}
    return {"draft": draft}


def node_extract(state: ChapterState) -> ChapterState:
    if state.get("error"):
        return {}  # 上游 LLM 已失败：透传根因（§6.12）
    pid = state["project_id"]
    draft = state.get("draft")
    if not draft:
        return {"error": "write 未产出草稿"}
    with tenant_session(pid) as db:
        messages = prompts.extract_messages(draft, state["chapter_seq"])
        resp = _llm(db, state, "extract", "Memory", make_chain("extract"), messages)
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
        resp = _llm(db, state, "revise", "Writer", make_chain("writer"), messages)
        if resp.error:
            return {"error": resp.error}
    try:
        data = _parse_json(resp.content)
        return {
            "draft": data["content"],
            "revision_count": state.get("revision_count", 0) + 1,
            "revise_responses": data.get("responses", []),
        }
    except (json.JSONDecodeError, KeyError) as exc:
        return {"error": f"revise 输出解析失败: {exc}"}


# ---- persist（编排层，§6.2 数据流边界的落库点）----

def node_persist(state: ChapterState) -> ChapterState:
    """确认分流（§6.11）：无 critical → 低风险自动放行落库；有 critical → 候选池待人工。"""
    pid = state["project_id"]
    chapter_seq = state["chapter_seq"]
    report = state.get("report") or {}
    critical = report.get("summary", {}).get("critical", 0) or 0

    if critical > 0:
        # critical 暂停：候选进待确认池，章节标 awaiting_review（§6.11）
        with tenant_session(pid) as db:
            for cand in state.get("candidates", []):
                db.add(MemoryCandidate(project_id=uuid.UUID(pid), kind=cand["kind"],
                                       source_chapter=chapter_seq, payload=cand["payload"],
                                       confidence=cand.get("confidence", 0.0)))
            ch = repo.get_chapter(db, uuid.UUID(pid), chapter_seq)
            if ch:
                ch.status = "awaiting_review"
        return {"persisted": True, "needs_review": True}

    with tenant_session(pid) as db:
        _persist_candidates(db, pid, chapter_seq, state.get("candidates", []))
        # 落章节正文
        summary = _chapter_summary(state.get("candidates", []))
        repo.save_chapter(db, project_id=uuid.UUID(pid), chapter_seq=chapter_seq,
                          content=state["draft"], summary=summary, generation_source="auto")
        _advance_plot(db, pid, chapter_seq)
    return {"persisted": True, "needs_review": False}


def _persist_candidates(db: Session, pid: str, chapter_seq: int, candidates: list[dict]) -> None:
    project_id = uuid.UUID(pid)
    for cand in candidates:
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
            db.add(Fact(project_id=project_id, content=p.get("content", ""),
                        category=p.get("category"), is_hard=bool(p.get("is_hard")),
                        source_chapter=chapter_seq, confidence=p.get("confidence", 0.8),
                        confirm_status="confirmed"))
        elif cand["kind"] == "relation_change":
            src = p.get("source_id")
            tgt = p.get("target_id")
            if src and tgt:
                db.add(Relation(project_id=project_id, source_id=uuid.UUID(str(src)),
                                relation_type=p["relation_type"], target_id=uuid.UUID(str(tgt)),
                                confidence=p.get("confidence", 0.8), source_chapter=chapter_seq))
        elif cand["kind"] == "foreshadow":
            db.add(Foreshadow(project_id=project_id, description=p.get("description", ""),
                              status="planted", planted_chapter=chapter_seq, trigger=p.get("trigger") or {}))


def _index_event_embedding(db: Session, pid: str, ev: Event) -> None:
    """事件摘要向量化入 embeddings（§15 最小向量召回，level=event）。

    加分项：bge-m3 未装/加载失败都降级（记录日志不阻塞落库，§6.12 数据层），
    伏笔/人设走偏主防线是关系链路（foreshadows 状态机 + 台账），不依赖本函数。
    """
    if not ev.summary:
        return
    try:
        emb = get_embedder().encode([ev.summary])[0]
        PgvectorStore().upsert(db, project_id=ev.project_id, level="event", source_id=ev.id,
                               source_chapter=ev.source_chapter,
                               model_version="bge-m3", embedding=emb)
    except Exception as exc:
        logger.warning("事件向量化失败，跳过索引（不影响落库）: %s", exc)


def _chapter_summary(candidates: list[dict]) -> str:
    return "；".join(p.get("summary", "") for c in candidates if c["kind"] == "event" for p in [c.get("payload") or {}] if p.get("summary"))


def _advance_plot(db: Session, pid: str, chapter_seq: int) -> None:
    """推进剧情线进度（§7.9，状态桥的一部分：上章沉淀 → 下章 recall）。"""
    project_id = uuid.UUID(pid)
    for thread in repo.get_plot_threads(db, project_id):
        thread.last_progress_chapter = chapter_seq
