"""分层召回（recall 节点，§7 三层记忆 + §7.4 召回预算）。

阶段 1 主链路（关系查询，防走偏的第一道防线）：
- 硬约束（恒在 Top-K）+ 最近事件 + 出场人物状态台账快照 + 上一章摘要/开头；
- 开放伏笔 + 活跃剧情线注入（§7.9：plan_chapter 据此决定收/延/弃，防伏笔烂尾）。

向量召回（§15 阶段 1「最小向量召回」）：bge-m3 对上一章摘要做语义近邻，
补充关键词召回漏掉的历史相似事件（呼应/重复判据输入）。加分项——失败降级
为纯关系召回，不阻塞生成（§6.12 数据层）。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiink.config import settings
from aiink.memory import repository as repo
from aiink.memory.embedder import get_embedder
from aiink.memory.vector_store import PgvectorStore
from aiink.models import Event
from aiink.schemas import RetrievedContext

logger = logging.getLogger(__name__)

# 出场人物上限（recall 预算控制，防上下文膨胀）
_MAX_ENTITIES = 12
# 事件语义召回补充上限（去重后）
_VECTOR_RECALL_TOP_K = 5
# 硬约束/事件内容注入上限（§7.4 召回预算：防超长文本撑爆 12k tokens）
_CONTENT_CAP = 300


def _merge_settings_constraints(session: Session, project_id: uuid.UUID,
                                facts_out: list[dict]) -> None:
    """project_settings.hard_constraints 并入硬约束列表（§7.11：设定是活数据）。

    facts 表是硬约束权威；project_settings.hard_constraints 是建书时的配置层约束
    （seed 双源）。合并按 content 去重：九州问天 同源只出现一次，示例书的
    题材硬约束（如「不得引入仙佛鬼神」）自此真正注入生成上下文。
    """
    settings_row = repo.get_settings(session, project_id)
    if not settings_row or not settings_row.hard_constraints:
        return
    seen = {f.get("content") for f in facts_out}
    for text in settings_row.hard_constraints:
        text = str(text or "").strip()[: _CONTENT_CAP]
        if text and text not in seen:
            facts_out.append({"content": text, "source_chapter": None,
                              "category": "规则", "is_hard": True, "source": "project_settings"})
            seen.add(text)


def build_context(session: Session, *, project_id: uuid.UUID, chapter_seq: int,
                  participants: list[str] | None = None,
                  user_instruction: str | None = None,
                  shared_context: dict | None = None) -> RetrievedContext:
    """组装 recall 输出：设定 + 前情 + 状态快照 + 伏笔/剧情线 + 事件语义召回。

    批次级共享池（§6.11）：shared_context 携带批次内已组装一次的**稳定部分**
    （长期事实 hard_facts），传入则复用、不再查库；首章未缓存则查库并把结果回填
    到同一 dict，供批次层桥给后续章。变化部分（近期事件/伏笔/剧情线/快照）每章照查。
    """
    # 批次级共享池（§6.11）：注意仅当 None 才新建——调用方可能传入空 dict 期望原地回填
    # hard_facts（falsy 用 `or {}` 会重绑定新对象，回填丢失 → 后续章无法复用缓存）。
    if shared_context is None:
        shared_context = {}
    if "hard_facts" in shared_context:
        facts_out = shared_context["hard_facts"]  # 复用批次内已组装结果（§6.11）
    else:
        hard_facts = repo.get_hard_facts(session, project_id, chapter_seq)
        # content 必须带上：硬约束恒在 Top-K（§7.2），注入的是可读文本而非裸 id
        #（裸 id 模型不可反查 → 硬约束对生成实际不可见）。截断防超长规则撑爆预算。
        facts_out = [
            {"fact_id": str(f.id), "source_chapter": f.source_chapter,
             "content": (f.content or "")[:300], "category": f.category, "is_hard": bool(f.is_hard)}
            for f in hard_facts
        ]
        # §7.11 设定是活数据：project_settings.hard_constraints 一并并入硬约束（按内容去重，
        # 避免与 facts 表同源重复）。示例书（长安夜行/星舰远征）的题材硬约束此前从未生效。
        _merge_settings_constraints(session, project_id, facts_out)
        shared_context["hard_facts"] = facts_out
    recent_events = repo.get_recent_events(session, project_id, limit=10)

    # 上一章摘要 / 开头（短期上下文）
    short: list[dict] = []
    prev = repo.get_latest_chapter(session, project_id)
    if prev and prev.chapter_seq < chapter_seq:
        short.append({"kind": "prev_chapter_summary", "chapter": prev.chapter_seq, "summary": prev.summary or ""})

    # 出场人物状态快照
    snapshots: list[dict] = []
    if participants:
        for name in participants[: _MAX_ENTITIES]:
            ch = repo.get_character(session, project_id, name)
            if not ch:
                continue
            state = repo.get_character_state(session, project_id, ch.id, chapter_seq)
            snapshots.append({
                "character_id": str(ch.id), "name": ch.name, "realm_cap": ch.realm_cap,
                "state": state, "personality": ch.personality,
            })

    # 开放伏笔 + 活跃剧情线（§7.9 防伏笔烂尾：plan_chapter 输入，决定收/延/弃）
    foreshadows_out = [
        {"foreshadow_id": str(f.id), "description": f.description, "trigger": f.trigger,
         "planted_chapter": f.planted_chapter, "status": f.status}
        for f in repo.get_open_foreshadows(session, project_id)
    ]
    threads_out = [
        {"name": t.name, "kind": t.kind, "status": t.status, "progress": t.progress,
         "last_progress_chapter": t.last_progress_chapter}
        for t in repo.get_plot_threads(session, project_id)
    ]

    events_out = [
        {"event_id": str(e.id), "chapter": e.source_chapter, "confidence": e.confidence,
         "summary": (e.summary or "")[: _CONTENT_CAP]} for e in recent_events
    ]

    # 事件语义近邻召回（§15 最小向量召回）：以上一章摘要为 query，召回历史相似事件
    # ——补充关键词命中漏掉的呼应/重复素材；失败降级（模型未装/加载失败都不阻断）。
    if prev and prev.summary:
        events_out = _semantic_recall(session, project_id, prev.summary, events_out)

    ctx = RetrievedContext(
        long_term_facts=facts_out,
        mid_term_events=events_out,
        short_context=short,
        entity_snapshots=snapshots,
        open_foreshadows=foreshadows_out,
        plot_threads=threads_out,
    )
    if user_instruction:
        ctx.short_context.append({"kind": "user_instruction", "text": user_instruction})
    # 召回预算（§7.4）：正文 tokens 估算只读层，节点组装时按 budget 截断
    ctx.token_usage = settings.recall_token_budget
    return ctx


def _semantic_recall(session: Session, project_id: uuid.UUID, query_text: str,
                     events_out: list[dict]) -> list[dict]:
    """bge-m3 近邻召回补充事件（level=event，显式 project_id 过滤走 HNSW 过滤索引，§14.1 坑 1）。"""
    try:
        emb = get_embedder().encode([query_text])[0]
        hits = PgvectorStore().search(session, project_id=project_id, level="event",
                                      embedding=emb, top_k=_VECTOR_RECALL_TOP_K)
        if not hits:
            return events_out
        known = {str(e["event_id"]) for e in events_out}
        extra_ids = [sid for sid, _ in hits if str(sid) not in known]
        if not extra_ids:
            return events_out
        rows = session.execute(
            select(Event).where(Event.id.in_(extra_ids))
        ).scalars().all()
        for e in rows:
            events_out.append({"event_id": str(e.id), "chapter": e.source_chapter,
                               "confidence": e.confidence, "recalled_by": "vector",
                               "summary": (e.summary or "")[: _CONTENT_CAP]})
        logger.info("事件语义召回补充 %d 条（query=上一章摘要）", len(rows))
        return events_out
    except Exception as exc:
        logger.warning("向量语义召回失败，降级为纯关系召回: %s", exc)
        return events_out
