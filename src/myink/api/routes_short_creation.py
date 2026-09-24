"""对话式短篇建书（模仿 inkos）：先聊清楚，再出方案卡，用户确认了才开写。

一期只服务短篇。与 `routes_book.create_project` 的分工：那条是「有表单的一次性建书」，
这条是「聊出来的建书」，两条都往 _create_project_row 落同一张表，上限与幂等口径共用。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete, select

from myink.api import routes_book as _book
from myink.api.auth import require_user
from myink.api.schemas import (OkOut, ShortCreationCommitBody, ShortCreationCommitOut,
                               ShortCreationMessageBody, ShortCreationMessageOut,
                               ShortCreationOut, ShortCreationSessionOut)
from myink.book_setup import generate_short_creation_turn
from myink.db import new_session, tenant_session
from myink.memory.repository import get_settings
from myink.models import (Project, ProjectSettings, ShortCreationMessage,
                          ShortCreationSession, StyleLibraryItem, User)
from myink.short import creation
from myink.short.form import resolve_short_lengths

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


def _style_for(db, uid: uuid.UUID, item_id: str) -> tuple[dict, str | None, str]:
    """选择器的值 → (style_profile, skill_pack, 展示名)。

    `builtin:<preset id>` 是内置预设（id 同时当 skill_pack 标记，与长篇那条路同口径）；
    其他按文风库 item id 处理，且**只查自己名下的**——查不到给 404，不区分「不存在」与
    「是别人的」，免得拿 404/403 的差别当探测别人的库。
    """
    from myink.seed import STYLE_PRESETS

    if item_id.startswith("builtin:"):
        key = item_id[len("builtin:"):]
        preset = next((p for p in STYLE_PRESETS if p["id"] == key), None)
        if preset is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        return dict(preset["style_profile"]), key, str(preset["name"])
    try:
        target = uuid.UUID(item_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    item = db.scalar(select(StyleLibraryItem).where(
        StyleLibraryItem.id == target, StyleLibraryItem.user_id == uid))
    if item is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return dict(item.profile), None, item.name


@router.post("/commit", response_model=ShortCreationCommitOut)
def commit(body: ShortCreationCommitBody, user_id: str = Depends(require_user)) -> dict:
    """确认开写：落书 + 出方案 + 落方案置 ready + 落文风。**不入队。**

    入队交给既有 POST /projects/{id}/short/generate——配额与成本估算只有那一条实现，
    在这里再写一份就会出现第二个口径；而且分离之后，入队失败用户能在工作台点「开始写全篇」重来。
    """
    uid = uuid.UUID(user_id)
    # 1) 会话 + 卡 + 归一后的篇幅
    with new_session() as db:
        session = db.scalar(select(ShortCreationSession)
                            .where(ShortCreationSession.user_id == uid).with_for_update())
        if session is None:
            raise HTTPException(status_code=409, detail="SESSION_EMPTY")
        if session.status != "active":
            raise HTTPException(status_code=409, detail="SESSION_COMMITTED")
        card = creation.merge_user_card(session.card or {}, body.card or {})
        if not creation.card_ready(card):
            raise HTTPException(status_code=400, detail="CARD_INCOMPLETE")
        session.card = card
        chapters, chars, compressed = resolve_short_lengths(
            int(card["chapter_count"]), int(card["chars_per_chapter"]))
        premise = creation.card_premise(card)
        # 与表单建书同一把锁：当日上限的读-算-写不能被并发挤穿
        if db.scalar(select(User.id).where(User.id == uid).with_for_update()) is None:
            raise HTTPException(status_code=403, detail="身份非法")
        project = db.get(Project, session.book_id) if session.book_id else None
        if project is None:
            try:
                project = _book._create_project_row(
                    db, uid, title=card["working_title"], genre=card["genre"],
                    premise=premise, chapter_count=chapters, chars_per_chapter=chars,
                    form="short")
            except _book.BookCountExceeded:
                return _book._book_cnt_response()
            session.book_id = project.id          # 先记下：后面任一步失败，重试复用它
        pid = project.id
        db.commit()

    # 2) 出方案 + 审纲（复用旧向导的短篇分支，含「被打回就重出一次」）
    db2 = new_session()
    try:
        patch, _ = _book._short_outline_draft(
            str(pid),
            _book.OutlineDraftBody(premise=premise, chapter_count=chapters,
                                   chars_per_chapter=chars, storyline=""),
            card["genre"], {}, chapters, db2)
    finally:
        db2.close()
    outline = patch.get("outline_draft") or {}
    if (patch.get("outline_error") or not outline.get("volumes")
            or not str(outline.get("objective") or "").strip()):
        # 书已经在库里（session.book_id 记着），这一步失败用户重按一次即可——
        # 不会建出第二本，也不会卡在「方案空了但状态是 ready」上。
        # 空 objective 也要在这里挡：它能过 generate_short_plan 的宽松形状检查，却过不了
        # 第 3 步的 validate_short_outline——那时书已落库，用户拿到的是一个莫名其妙的
        # 400 OUTLINE_INCOMPLETE，而这条路的整个设计就是「重按复用同一本」。
        raise HTTPException(status_code=502,
                            detail=f"PLAN_FAILED: {patch.get('outline_error') or '方案为空'}")

    # 3) 落方案置 ready + 落文风
    style_item_id = (body.style_item_id or "").strip()
    style_name: str | None = None
    with tenant_session(str(pid)) as tdb:
        _book._persist_short_outline(tdb, pid, outline)
        row = tdb.scalar(select(Project).where(Project.id == pid))
        row.creation_context = {**(row.creation_context or {}),
                               "creation_conversation": {"direction": card["direction"],
                                                         "conflict_core": card["conflict_core"],
                                                         "plot_sketch": card["plot_sketch"]}}
        if style_item_id:
            profile, skill_pack, style_name = _style_for(tdb, uid, style_item_id)
            settings_row = get_settings(tdb, pid)
            if settings_row is None:
                settings_row = ProjectSettings(project_id=pid, version=1)
                tdb.add(settings_row)
            settings_row.style_profile = profile
            settings_row.skill_pack = skill_pack
            settings_row.version = (settings_row.version or 1) + 1
        tdb.commit()

    # 4) 会话收尾
    with new_session() as db:
        session = db.scalar(select(ShortCreationSession)
                            .where(ShortCreationSession.user_id == uid))
        session.status = "committed"
        session.book_id = pid
        if style_item_id:
            session.style_item_id = style_item_id
            session.style_name = style_name
        db.commit()
    return {"project_id": pid, "lengths_compressed": compressed,
            "plan_warning": patch.get("outline_warning"), "style_name": style_name}
