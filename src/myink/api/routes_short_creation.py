"""对话式短篇建书（模仿 inkos）：先聊清楚，再出方案卡，用户确认了才开写。

一期只服务短篇。与 `routes_book.create_project` 的分工：那条是「有表单的一次性建书」，
这条是「聊出来的建书」，两条都往 _create_project_row 落同一张表，上限与幂等口径共用。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete, select

from myink.api.auth import require_user
from myink.api.schemas import (OkOut, ShortCreationMessageBody, ShortCreationMessageOut,
                               ShortCreationOut, ShortCreationSessionOut)
from myink.book_setup import generate_short_creation_turn
from myink.db import new_session
from myink.models import ShortCreationMessage, ShortCreationSession
from myink.short import creation

router = APIRouter(prefix="/api/v1/short/creation", tags=["short-creation"])

# 首次进页面不调模型：既慢，又可能因为还没配连接而直接失败。开场白是确定的。
OPENING = ("想写个什么样的短篇？先说一句大方向就行——比如「一个渡口老人等最后一班船」，"
           "我来陪你把它聊成能开写的方案。")

_HISTORY_LIMIT = 20


def _session(db, uid: uuid.UUID) -> ShortCreationSession | None:
    return db.scalar(select(ShortCreationSession).where(ShortCreationSession.user_id == uid))


def _open_session(db, uid: uuid.UUID) -> ShortCreationSession:
    """取（没有则建）本人的会话。已确认开写过的会话照样返回——里面留着这本书的来龙去脉，
    用户想再写一本时点「重新开始」清掉它，而不是让页面自动把对话抹了。
    """
    session = _session(db, uid)
    if session is None:
        session = ShortCreationSession(user_id=uid, status="active", card=creation.default_card())
        db.add(session)
        db.flush()
        db.add(ShortCreationMessage(session_id=session.id, role="assistant", content=OPENING))
    elif not (session.card or {}):
        session.card = creation.default_card()
    return session


def _history(db, session_id: uuid.UUID) -> list[dict]:
    """最近若干条对话。更早的几轮已经体现在卡上，不必每轮重发。"""
    rows = db.scalars(select(ShortCreationMessage)
                      .where(ShortCreationMessage.session_id == session_id)
                      .order_by(ShortCreationMessage.id)).all()
    return [{"role": row.role, "content": row.content} for row in rows[-_HISTORY_LIMIT:]]


def _payload(db, session: ShortCreationSession) -> dict:
    rows = db.scalars(select(ShortCreationMessage)
                      .where(ShortCreationMessage.session_id == session.id)
                      .order_by(ShortCreationMessage.id)).all()
    card = session.card or {}
    return {
        "session": {"id": str(session.id), "status": session.status, "card": card,
                    "style_item_id": session.style_item_id, "style_name": session.style_name,
                    "book_id": str(session.book_id) if session.book_id else None},
        "messages": [{"id": row.id, "role": row.role, "content": row.content, "card": row.card,
                      "model_id": row.model_id, "cost_est": row.cost_est, "error": row.error,
                      "created_at": row.created_at} for row in rows],
        "ready": creation.card_ready(card),
    }


@router.get("", response_model=ShortCreationOut)
def get_session(user_id: str = Depends(require_user)) -> dict:
    uid = uuid.UUID(user_id)
    with new_session() as db:
        session = _open_session(db, uid)
        db.commit()
        return _payload(db, session)


@router.post("/messages", response_model=ShortCreationOut)
def post_message(body: ShortCreationMessageBody, user_id: str = Depends(require_user)) -> dict:
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="说点什么吧")
    uid = uuid.UUID(user_id)
    db = new_session()
    try:
        session = _open_session(db, uid)
        if session.status != "active":
            raise HTTPException(status_code=409, detail="SESSION_COMMITTED")
        # 用户改过的卡先落库：它既是这轮的输入，也是下一轮的现值。
        session.card = creation.merge_user_card(session.card or {}, body.card or {})
        db.add(ShortCreationMessage(session_id=session.id, role="user", content=content))
        db.flush()                                   # _history 要读得到这一条（autoflush=False）
        reply, patch, error, resp = generate_short_creation_turn(
            _history(db, session.id), session.card, user_id=uid, db=db)
        session.card = creation.merge_model_card(session.card, patch)
        db.add(ShortCreationMessage(
            session_id=session.id, role="assistant", content=reply, card=patch or None,
            model_id=resp.model_id, input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens, cost_est=resp.cost_est, error=error))
        db.commit()
        return _payload(db, session)
    finally:
        db.close()


@router.delete("", response_model=OkOut)
def reset_session(user_id: str = Depends(require_user)) -> dict:
    uid = uuid.UUID(user_id)
    with new_session() as db:
        session = _session(db, uid)
        if session is not None:
            db.execute(sa_delete(ShortCreationMessage)
                       .where(ShortCreationMessage.session_id == session.id))
            db.delete(session)
        db.commit()
    return {"ok": True}
