"""章节修改后记忆失效与重建索引（§7.3/§11.2，阶段 3 落地）。

确定性失效服务，编排层调用（数据流边界 §6.2：Agent 不直写）。必须在 tenant_session
内调用（RLS 按 project_id 隔离，§14.1）。语义：

- facts / character_states / relations：时间窗关闭（valid_to = chapter_seq）——长期记忆
  用时间窗表达「新事实覆盖旧事实」（§7.3），保留行供证据链追溯；
- facts 同时置 confirm_status="expired"——get_hard_facts 按 confirm_status=="confirmed"
  过滤，单独 valid_to 对硬约束事实无效（§7.2 硬约束恒在 Top-K），expired 双保险剔除；
- events / foreshadows（planted/developing）：硬删除——一次性记忆随重写作废（重写后旧
  事件 = 从未发生）；Event 无 valid_to 列，不引入 schema 变更（无迁移设施）；
- embeddings：按 source_chapter 删除（PgvectorStore.delete），新记忆 persist 时重写。

幂等：无旧记忆时各表 0 行受影响，返回全 0，不抛错。整函数确定性，不耗 LLM。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete as sa_delete, update as sa_update
from sqlalchemy.orm import Session

from aiink.memory.vector_store import PgvectorStore
from aiink.models import CharacterState, Event, Fact, Foreshadow, Relation

logger = logging.getLogger(__name__)


def invalidate_chapter_memory(db: Session, *, project_id: uuid.UUID, chapter_seq: int) -> dict:
    """失效某章全部旧记忆（重写前调用），返回各表关闭/删除统计。

    与后续 _persist_candidates 在同一事务内：新写失败回滚则旧记忆不失效（原子）。
    """
    # 1. 长期事实：时间窗关闭 + expired（硬约束靠 expired 被 get_hard_facts 剔除）
    facts_closed = db.execute(
        sa_update(Fact)
        .where(Fact.project_id == project_id, Fact.source_chapter == chapter_seq,
               Fact.valid_to.is_(None))
        .values(valid_to=chapter_seq, confirm_status="expired")
    ).rowcount or 0

    # 2. 人物状态台账：时间窗关闭
    states_closed = db.execute(
        sa_update(CharacterState)
        .where(CharacterState.project_id == project_id,
               CharacterState.source_chapter == chapter_seq,
               CharacterState.valid_to.is_(None))
        .values(valid_to=chapter_seq)
    ).rowcount or 0

    # 3. 实体关系：时间窗关闭（§7.8 当前关系 = 最新一条 valid_to IS NULL）
    relations_closed = db.execute(
        sa_update(Relation)
        .where(Relation.project_id == project_id, Relation.source_chapter == chapter_seq,
               Relation.valid_to.is_(None))
        .values(valid_to=chapter_seq)
    ).rowcount or 0

    # 4. 一次性事件：硬删（重写后旧事件 = 从未发生）
    events_deleted = db.execute(
        sa_delete(Event).where(Event.project_id == project_id,
                               Event.source_chapter == chapter_seq)
    ).rowcount or 0

    # 5. 开放伏笔：硬删（resolved/dropped 为历史保留，不删）
    foreshadows_closed = db.execute(
        sa_delete(Foreshadow)
        .where(Foreshadow.project_id == project_id,
               Foreshadow.planted_chapter == chapter_seq,
               Foreshadow.status.in_(["planted", "developing"]))
    ).rowcount or 0

    # 6. 向量：按来源章删除（新记忆 persist 时重写）
    embeddings_deleted = PgvectorStore().delete(db, project_id=project_id,
                                                source_chapter=chapter_seq)

    if any((facts_closed, states_closed, relations_closed, events_deleted,
            foreshadows_closed, embeddings_deleted)):
        logger.info("失效章节记忆 ch%s（project=%s）：facts=%s states=%s relations=%s "
                    "events=%s foreshadows=%s embeddings=%s",
                    chapter_seq, project_id, facts_closed, states_closed, relations_closed,
                    events_deleted, foreshadows_closed, embeddings_deleted)
    return {
        "facts_closed": facts_closed,
        "states_closed": states_closed,
        "relations_closed": relations_closed,
        "events_deleted": events_deleted,
        "foreshadows_closed": foreshadows_closed,
        "embeddings_deleted": embeddings_deleted,
    }
