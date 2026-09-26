"""对话式短篇建书（模仿 inkos）：先聊清楚，再出方案卡，用户确认了才开写。

一期只服务短篇。与 `routes_book.create_project` 的分工：那条是「有表单的一次性建书」，
这条是「聊出来的建书」，两条都往 _create_project_row 落同一张表，上限与幂等口径共用。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete, func, select

from myink.api import routes_book as _book
from myink.api.auth import require_user
from myink.api.routes_style import resolve_style_selection
from myink.api.schemas import (OkOut, ShortCreationCommitBody, ShortCreationCommitOut,
                               ShortCreationMessageBody, ShortCreationMessageOut,
                               ShortCreationOut, ShortCreationSessionOut)
from myink.book_setup import generate_short_creation_turn
from myink.creation import validate_short_outline
from myink.db import new_session, tenant_session
from myink.memory.repository import get_settings
from myink.models import (AgentRun, Chapter, Project, ProjectSettings, ShortCreationMessage,
                          ShortCreationSession, Task, User)
from myink.short import creation
from myink.short.form import resolve_short_lengths
from myink.workflow.outline import build_persisted_short_outline

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


def _orphan_draft_book(db, uid: uuid.UUID, book_id) -> Project | None:
    """上次 commit 中途失败留下的那本当日的草稿书——它已经吃掉了当日建书额度。

    只有「本人 + 当日创建 + 仍是 draft + 一个任务/章节都没有」才认。两条存在性检查必须
    进租户上下文：`chapters` 带 project_id 且有 FORCE RLS，在无租户的普通会话里恒为空，
    那样「没有章节」恒真——守卫会误删一本已经有了正文的书。
    """
    if book_id is None:
        return None
    with tenant_session(str(book_id)) as tdb:
        if tdb.scalar(select(Task.id).where(Task.project_id == book_id).limit(1)) is not None:
            return None
        if tdb.scalar(select(Chapter.id).where(Chapter.project_id == book_id).limit(1)) is not None:
            return None
    return db.scalar(select(Project).where(
        Project.id == book_id, Project.user_id == uid,
        Project.creation_status == "draft",
        Project.created_at >= func.date_trunc("day", func.now()),
    ))


@router.delete("", response_model=OkOut)
def reset_session(user_id: str = Depends(require_user)) -> dict:
    uid = uuid.UUID(user_id)
    with new_session() as db:
        session = _session(db, uid)
        if session is not None:
            book = _orphan_draft_book(db, uid, session.book_id)
            if book is not None:
                # agent_runs 没有 FK：只删 projects 会留下一堆无归属调用，管理面板的全局花费
                # 就对不上各用户之和（口径见 delete_project，这里那本书还没有任务/章节，
                # 所以只剩这一步要补）。
                db.execute(sa_delete(AgentRun).where(AgentRun.project_id == book.id))
                db.delete(book)
            db.execute(sa_delete(ShortCreationMessage)
                       .where(ShortCreationMessage.session_id == session.id))
            db.delete(session)
        db.commit()
    return {"ok": True}


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
        # 空 objective 也在这里挡（而不是留给下面的形状校验）：它给的是「方案为空」这个
        # 更像人话的说法，而形状校验统一回「形状不合规」。
        raise HTTPException(status_code=502,
                            detail=f"PLAN_FAILED: {patch.get('outline_error') or '方案为空'}")
    # 模型按 SYSTEM_SHORT_PLAN 那份 JSON 契约输出，里面**没有** chapter_count；篇幅的真相在
    # 用户卡上，归一后就是这里的 chapters。过一次与向导落库同一个 builder（put_outline 的短篇
    # 分支也用它）：补上 chapter_count、重编卷号。不补的话下面那道形状闸永远拒——它读的正是
    # 这个字段，于是「确认开写」100% 变成 PLAN_FAILED，用户被卡死在方案卡上。
    outline = build_persisted_short_outline(
        objective=outline.get("objective") or "", volumes=outline.get("volumes") or [],
        premise=premise, chapter_count=chapters, storyline="")
    try:
        # 逐章细纲缺章、卷不连续这类形状问题，原本要等到第 3 步落库才炸，那里抛的是
        # 400 OUTLINE_INCOMPLETE——它的文案指向长篇设定页的那张「全书目标/每卷目标」表单，
        # 而这条动线根本没有那张表单。提前按同一件「方案不行」挡成可重试的 502。
        validate_short_outline(outline)
    except HTTPException:
        raise HTTPException(status_code=502, detail="PLAN_FAILED: 方案形状不合规") from None

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
            profile, skill_pack, style_name = resolve_style_selection(tdb, uid, style_item_id)
            settings_row = get_settings(tdb, pid)
            if settings_row is None:
                settings_row = ProjectSettings(project_id=pid, version=1)
                tdb.add(settings_row)
            settings_row.style_profile = profile
            settings_row.skill_pack = skill_pack
            settings_row.version = (settings_row.version or 1) + 1
        tdb.commit()

    # 4) 会话收尾。会话可能在步骤 1 之后被 DELETE /short/creation 删掉
    # （用户在出方案那几秒里点了「重新开始」）——书与方案都已经落了，这一段的语义是
    # 「成功」，不能因为收尾写不回去就把已经建好的书报成 500。
    with new_session() as db:
        session = db.scalar(select(ShortCreationSession)
                            .where(ShortCreationSession.user_id == uid))
        if session is not None:
            session.status = "committed"
            session.book_id = pid
            if style_item_id:
                session.style_item_id = style_item_id
                session.style_name = style_name
        db.commit()
    return {"project_id": pid, "lengths_compressed": compressed,
            "plan_warning": patch.get("outline_warning"), "style_name": style_name}
