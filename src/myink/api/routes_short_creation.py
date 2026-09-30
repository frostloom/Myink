"""对话式短篇建书：先聊清楚，再出方案卡，用户确认了才开写。

一期只服务短篇。与 `routes_book.create_project` 的分工：那条是「有表单的一次性建书」，
这条是「聊出来的建书」，两条都往 _create_project_row 落同一张表，上限与幂等口径共用。

**会话是多条的**：一个短篇聊一条，聊废了就另起一条，旧的原样留着能翻回去看。所以读写一律
带 session_id，不再有「本人唯一的那条会话」。`status` 仍只有 active / committed 两种——
已开写的那条不必删，它自己会成为列表里的一条历史。

**落点是自动的**：进建书页落在那条还没开写的会话上，一条都没有就新开一条；已开写的自动
让位（`_latest_active`）。这是会话本意的直接推论——一条会话只服务一本书，开写它就等于用完了，
留着它抢落点只会让人一进页面就撞上 409。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete, func, select, text
from sqlalchemy.exc import TimeoutError as PoolTimeout

from myink.api import routes_book as _book
from myink.api.auth import require_user
from myink.api.routes_style import resolve_style_selection
from myink.api.schemas import (OkOut, ShortCreationCommitBody, ShortCreationCommitOut,
                               ShortCreationMessageBody, ShortCreationOut)
from myink.book_setup import generate_short_creation_turn
from myink.creation import validate_short_outline
from myink.db import new_creation_lock_session, new_session, tenant_session
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
# 会话列表的上限：它只是给人翻的，翻不到更早的也不影响任何东西。
_LIST_LIMIT = 50


def _advisory_lock(user_id: str, key: str) -> Iterator[str]:
    """独立事务持有 advisory lock：业务事务的 commit 不提前放锁；请求失败或进程断开时
    数据库自动释放，不留下永久的 preparing 状态。拿不到就直接 409，排队的请求没有意义。
    """
    with new_creation_lock_session() as lock_db:
        try:
            acquired = lock_db.scalar(text(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"
            ), {"key": key})
        except PoolTimeout:
            raise HTTPException(status_code=503, detail="CREATION_CAPACITY_EXCEEDED") from None
        if not acquired:
            raise HTTPException(status_code=409, detail="SESSION_BUSY")
        yield user_id


def _session_user(session_id: uuid.UUID,
                  user_id: str = Depends(require_user)) -> Iterator[str]:
    """同一条会话的改动互斥，锁覆盖模型调用及所有提交阶段。

    锁按**会话**分，不按账号分：多会话之后，串行化的正确性单位就是「一条会话」——两个
    标签页各聊各的本来就该并行。当日建书上限那条读-改-写另有把关（commit 里锁用户行）。
    """
    yield from _advisory_lock(user_id, f"short-creation:{user_id}:{session_id}")


def _latest_active(db, uid: uuid.UUID) -> ShortCreationSession | None:
    """最近动过的、还没开写的那条会话；都开写过了就返回 None，由调用方另起一条。

    排序口径与 `_summaries` 一致，差的只是那个 status 条件。
    """
    return db.scalar(select(ShortCreationSession)
                     .where(ShortCreationSession.user_id == uid,
                            ShortCreationSession.status == "active")
                     .order_by(ShortCreationSession.updated_at.desc(),
                               ShortCreationSession.id.desc())
                     .limit(1))


def _new_session(db, uid: uuid.UUID) -> ShortCreationSession:
    """开一条新会话并落开场白。"""
    session = ShortCreationSession(user_id=uid, status="active",
                                   title=creation.NEW_SESSION_TITLE,
                                   card=creation.default_card())
    db.add(session)
    db.flush()
    db.add(ShortCreationMessage(session_id=session.id, role="assistant", content=OPENING))
    return session


def _matching(db, uid: uuid.UUID, session_id: uuid.UUID) -> ShortCreationSession:
    """本人的那条会话，否则 404。

    别人的会话与不存在的会话回同一个 404：403 与 404 的差别本身就在确认「这条存在」。
    """
    session = db.scalar(select(ShortCreationSession)
                        .where(ShortCreationSession.id == session_id,
                               ShortCreationSession.user_id == uid))
    if session is None:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    return session


def _first_user_message(db, session_id: uuid.UUID) -> str:
    return db.scalar(select(ShortCreationMessage.content)
                     .where(ShortCreationMessage.session_id == session_id,
                            ShortCreationMessage.role == "user")
                     .order_by(ShortCreationMessage.id).limit(1)) or ""


def _retitle(db, session: ShortCreationSession) -> None:
    """标题跟着卡上的暂定名走；名字还没聊出来时退回用户的第一句话。"""
    session.title = creation.session_title(session.card, _first_user_message(db, session.id))


def _history(db, session_id: uuid.UUID) -> list[dict]:
    """最近若干条对话。更早的几轮已经体现在卡上，不必每轮重发。"""
    rows = db.scalars(select(ShortCreationMessage)
                      .where(ShortCreationMessage.session_id == session_id)
                      .order_by(ShortCreationMessage.id)).all()
    return [{"role": row.role, "content": row.content} for row in rows[-_HISTORY_LIMIT:]]


def _summaries(db, uid: uuid.UUID) -> list[dict]:
    rows = db.scalars(select(ShortCreationSession)
                      .where(ShortCreationSession.user_id == uid)
                      .order_by(ShortCreationSession.updated_at.desc(),
                                ShortCreationSession.id.desc())
                      .limit(_LIST_LIMIT)).all()
    # title 可能是空的（存量行只按卡上的暂定名回填过，没名字的就空着），展示时补占位名。
    return [{"id": row.id, "title": row.title or creation.NEW_SESSION_TITLE,
             "status": row.status, "book_id": row.book_id, "updated_at": row.updated_at}
            for row in rows]


def _payload(db, session: ShortCreationSession, uid: uuid.UUID) -> dict:
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
        # 列表随载荷一起回：切会话、新建之后前端都要立刻重画那排会话，没必要再多一次往返。
        "sessions": _summaries(db, uid),
        "ready": creation.card_ready(card),
    }


@router.get("", response_model=ShortCreationOut)
def get_session(user_id: str = Depends(require_user)) -> dict:
    """回到建书页：自动落到最近那条**还没开写**的会话；没有就开一条。

    已开写的会话不再抢落点。它已经不是「一段正在聊的建书对话」而是一本书了，继续往里
    聊也没用（POST 消息会 409 SESSION_COMMITTED）。它仍在 sessions 列表里，要回看就手动点。
    规则与建书会话的本意一致：一条会话只服务一本书，开写它就等于用完了——见模块 docstring。

    刻意不加锁：这是页面加载路径，两个标签页同时进页面各建一条空会话只是碍眼，而在这里
    加锁会让「另一个标签页正在生成」把当前页面的首次加载打成 409——代价比收益大得多。
    """
    uid = uuid.UUID(user_id)
    with new_session() as db:
        session = _latest_active(db, uid) or _new_session(db, uid)
        db.commit()
        return _payload(db, session, uid)


@router.post("/sessions", response_model=ShortCreationOut)
def create_session(user_id: str = Depends(require_user)) -> dict:
    """另起一条新会话。旧的原样留着——用户随时能翻回去看之前聊了什么。"""
    uid = uuid.UUID(user_id)
    with new_session() as db:
        session = _new_session(db, uid)
        db.commit()
        return _payload(db, session, uid)


@router.get("/sessions/{session_id}", response_model=ShortCreationOut)
def open_session(session_id: uuid.UUID, user_id: str = Depends(require_user)) -> dict:
    uid = uuid.UUID(user_id)
    with new_session() as db:
        return _payload(db, _matching(db, uid, session_id), uid)


@router.post("/sessions/{session_id}/messages", response_model=ShortCreationOut)
def post_message(body: ShortCreationMessageBody, session_id: uuid.UUID,
                 user_id: str = Depends(_session_user)) -> dict:
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="说点什么吧")
    uid = uuid.UUID(user_id)
    db = new_session()
    try:
        session = _matching(db, uid, session_id)
        if session.status != "active":
            raise HTTPException(status_code=409, detail="SESSION_COMMITTED")
        # 用户改过的卡先落库：它既是这轮的输入，也是下一轮的现值。
        session.card = creation.merge_user_card(session.card or {}, body.card or {})
        db.add(ShortCreationMessage(session_id=session.id, role="user", content=content))
        db.flush()                                   # _history 要读得到这一条（autoflush=False）
        reply, patch, error, resp = generate_short_creation_turn(
            _history(db, session.id), session.card, user_id=uid, db=db)
        session.card = creation.merge_model_card(session.card, patch)
        # 标题重算放在模型卡合并之后：这轮模型可能刚把暂定名聊出来；还没聊出来则退回用户
        # 刚才那句话——那一条已经 flush 过了，读得到。
        _retitle(db, session)
        db.add(ShortCreationMessage(
            session_id=session.id, role="assistant", content=reply, card=patch or None,
            model_id=resp.model_id, input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens, cost_est=resp.cost_est, error=error))
        db.commit()
        return _payload(db, session, uid)
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


@router.delete("/sessions/{session_id}", response_model=OkOut)
def delete_session(session_id: uuid.UUID,
                   user_id: str = Depends(_session_user)) -> dict:
    """删掉一条会话（连同它的消息）。**不碰已经开写成的书**——那本书是用户的成品，
    这里删的只是这段对话；只有「当日建的、还是 draft、没任务没章节」的孤儿草稿才一并带走
    （它吃掉了当日额度却什么都没产出，留着才是坑）。"""
    uid = uuid.UUID(user_id)
    with new_session() as db:
        session = _matching(db, uid, session_id)
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


@router.post("/sessions/{session_id}/commit", response_model=ShortCreationCommitOut)
def commit(body: ShortCreationCommitBody, session_id: uuid.UUID,
           user_id: str = Depends(_session_user)) -> dict:
    """确认开写：落书 + 出方案 + 落方案置 ready + 落文风。**不入队。**

    入队交给既有 POST /projects/{id}/short/generate——配额与成本估算只有那一条实现，
    在这里再写一份就会出现第二个口径；而且分离之后，入队失败用户能在工作台点「开始写全篇」重来。
    """
    uid = uuid.UUID(user_id)
    # 1) 会话 + 卡 + 归一后的篇幅
    with new_session() as db:
        session = db.scalar(select(ShortCreationSession)
                            .where(ShortCreationSession.id == session_id,
                                   ShortCreationSession.user_id == uid).with_for_update())
        if session is None:
            raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
        if session.status != "active":
            raise HTTPException(status_code=409, detail="SESSION_COMMITTED")
        card = creation.merge_user_card(session.card or {}, body.card or {})
        if not creation.card_ready(card):
            raise HTTPException(status_code=400, detail="CARD_INCOMPLETE")
        session.card = card
        # 卡上最后改的名字可能从没发过言（就是在方案卡里改的），标题以卡为准。
        _retitle(db, session)
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
                               "creation_conversation": {
                                   field: card[field] for field in creation.REQUIRED_CARD_FIELDS}}
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

    # 4) 只收尾发起的那条会话；期间用户在别的会话里做的事、乃至把这条删了，都不影响这次建书。
    with new_session() as db:
        session = db.scalar(select(ShortCreationSession)
                            .where(ShortCreationSession.user_id == uid,
                                   ShortCreationSession.id == session_id))
        if session is not None:
            session.status = "committed"
            session.book_id = pid
            if style_item_id:
                session.style_item_id = style_item_id
                session.style_name = style_name
        db.commit()
    return {"project_id": pid, "lengths_compressed": compressed,
            "plan_warning": patch.get("outline_warning"), "style_name": style_name}
