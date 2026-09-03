"""建书 + 设定浏览端点（§7.11 建书流程：一句话梗概启动 + Planner 提案 + 用户确认落库）。

- POST /projects：创建作品（Project + 空 ProjectSettings，不调 LLM，快）。每日建书数
  闸门（plan.md §13 bookcnt：每用户每天最多 N 本不同书，超限 429 BOOK_CNT_EXCEEDED——
  生成入队时的网关 rate:bookcnt 管不住"只建书不生成"，建书端点需独立计数）；
- POST /projects/{pid}/setup-draft：一句话梗概 → Planner（复用，不新增 agent）生成设定
  骨架草稿（境界体系/世界观/硬约束/势力/核心人物/关键地点），**可编辑草稿不落库**，
  可反复调用（前端「重新生成」）；LLM 失败 → {} + error 200 降级（§6.12 不 500）；
- PUT /projects/{pid}/setup：用户确认/修改后落库——world_rules/hard_constraints 在
  ProjectSettings 整体替换 + version++；characters/factions/locations **按 name
  create-if-missing**（append-only，§7.11 ③：新增零成本、已落行不覆盖——修改走未来
  影响面流程，避免无影响面分析直接改基底）；
- GET /projects/{pid}/world：世界观浏览（world_rules + hard_constraints + 势力/地点）；
- GET /projects/{pid}/characters：人物卡片浏览（静态基底 + 当前状态台账 §7.7）；
- GET /projects/{pid}/graph：世界拓扑全量（4 类节点 + 人物关系/地点层级边，§9 图谱前端）。

与 §7.11 权威模型一致：agent 只提案、用户确认是唯一 canon；确认 = 编排层写库入口
（同 persist 层级，数据流边界 §6.2）。
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete, func

from aiink.api.auth import current_user, require_owner
from aiink.api.schemas import (BookOutlineOut, CharacterCardOut, DeleteProjectOut,
                               EntityCardOut, ForeshadowOut, OutlineDraftOut, ProjectOut,
                               SetupConfirmOut, SetupDraftOut, WorldGraphOut, WorldViewOut)
from aiink.book_setup import generate_book_outline, generate_book_setup
from aiink.config import settings
from aiink.db import new_session, tenant_session
from aiink.memory.repository import (get_all_characters, get_character, get_character_state,
                                     get_settings, get_volume_outline)
from aiink.models import (AgentRun, Character, Entity, Faction, Foreshadow, Location,
                          Project, ProjectSettings, Relation, Task, VolumeOutline)
from aiink.worker.redis_client import book_key, get_redis, inflight_key, lock_key, sse_key
from aiink.workflow.checkpointer import delete_threads
from aiink.workflow.outline import normalize_outline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/v1", tags=["book"])


def _pid(project_id: str) -> uuid.UUID:
    """path 里的 project_id 转 uuid（require_owner 已校验格式合法，此处仅类型转换）。"""
    return uuid.UUID(project_id)


def _str_or_none(value) -> str | None:
    """草稿字段清洗：None/空 → None（可空列）；否则去首尾空白。"""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


class CreateProjectBody(BaseModel):
    title: str
    genre: str = "仙侠玄幻"
    target_words: int | None = None


class ProjectUpdateBody(BaseModel):
    """作品基本信息更新（§6.9 字数可配）：非 None 字段才更新；target_words 显式传 null 置空。"""

    title: str | None = None
    genre: str | None = None
    target_words: int | None = None


def _check_target_words(v: int | None, *, field: str) -> int | None:
    """字数白名单：500–20000，越界 400（对齐 L1 章节字数门禁的可写区间）。"""
    if v is not None and not (500 <= v <= 20000):
        raise HTTPException(status_code=400, detail=f"{field} 需在 500–20000 之间（当前 {v}）")
    return v


class SetupDraftBody(BaseModel):
    premise: str


class SetupBody(BaseModel):
    """确认落库的设定（前端可编辑草稿后回传；自由形状字段松类型，落库前清洗）。"""

    world_rules: dict = Field(default_factory=dict)
    hard_constraints: list[str] = Field(default_factory=list)
    characters: list[dict] = Field(default_factory=list)
    forces: list[dict] = Field(default_factory=list)
    locations: list[dict] = Field(default_factory=list)


class OutlineDraftBody(BaseModel):
    """整书大纲草稿输入（§11 建书 ③）：一句话梗概 + 大致章节数 + 大致故事线。"""

    premise: str
    chapter_count: int = 20
    storyline: str = ""


class OutlineConfirmBody(BaseModel):
    """整书大纲确认落库（§11 ③）：Objective + volumes（每卷含逐章 {title, goal, beats}）；
    premise/章节数/故事线一并存下供后续重新生成。"""

    objective: str = ""
    volumes: list[dict] = Field(default_factory=list)
    premise: str = ""
    chapter_count: int = 0
    storyline: str = ""


@router.post("/projects", response_model=ProjectOut)
def create_project(body: CreateProjectBody,
                   user_id: str | None = Depends(current_user)) -> dict:
    """创建作品：根表 Project + 空 ProjectSettings（不调 LLM，快；设定草稿走 setup-draft）。

    身份缺失/非法 → 403（fail closed，§14.1 ③）；当日建书数超限 → 429 BOOK_CNT_EXCEEDED
    （对齐网关 gates.lua rate:bookcnt 默认值，双端同 BOOKS_PER_DAY env；错误体用网关同款
    {"error": code} 信封，前端 GATE_CODES 才能命中中文文案）。
    """
    if not user_id:
        raise HTTPException(status_code=403, detail="缺失身份（未携带已认证用户）")
    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=403, detail="身份非法")
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="作品标题不能为空")

    with new_session() as db:
        today = func.date_trunc("day", func.now())
        created = db.query(Project).filter(
            Project.user_id == uid, Project.created_at >= today).count()
        if created >= settings.books_per_day_max:
            return JSONResponse(status_code=429, content={"error": "BOOK_CNT_EXCEEDED"})
        target_words = _check_target_words(body.target_words, field="每章目标字数")
        project = Project(user_id=uid, title=title, genre=body.genre.strip() or "仙侠玄幻",
                          target_words=target_words)
        db.add(project)
        db.flush()
        pid = str(project.id)
        db.commit()  # 根表先落库，后续租户事务才能引用外键（seed._ensure_sample_book 同款）
    with tenant_session(pid) as tdb:
        if tdb.query(ProjectSettings).filter_by(project_id=pid).first() is None:
            tdb.add(ProjectSettings(project_id=pid))
    return {"id": pid, "title": project.title, "genre": project.genre,
            "current_chapter": project.current_chapter, "target_words": project.target_words}


@router.put("/projects/{project_id}", dependencies=[Depends(require_owner)],
            response_model=ProjectOut)
def update_project(project_id: str, body: ProjectUpdateBody) -> dict:
    """更新作品基本信息（§6.9 每章目标字数可配）。非 None 字段才更新（None = 不改）；
    target_words 显式传 null 才置空（清空回落生成侧默认 3000）。归属断言 fail closed。"""
    pid = _pid(project_id)
    with new_session() as db:
        project = db.get(Project, pid)
        if project is None:
            raise HTTPException(status_code=404, detail="作品不存在")
        if body.title is not None and body.title.strip():
            project.title = body.title.strip()
        if body.genre is not None and body.genre.strip():
            project.genre = body.genre.strip()
        if body.target_words is not None:
            project.target_words = _check_target_words(body.target_words, field="每章目标字数")
        elif "target_words" in body.model_fields_set and body.target_words is None:
            project.target_words = None  # 显式传 null → 置空
        db.commit()
    return {"id": str(project.id), "title": project.title, "genre": project.genre,
            "current_chapter": project.current_chapter, "target_words": project.target_words}


@router.delete("/projects/{project_id}", dependencies=[Depends(require_owner)],
               response_model=DeleteProjectOut)
def delete_project(project_id: str) -> dict:
    """整本书删除（硬删）：守卫进行中任务 → 清 checkpoint/Redis 残留 → FK 级联删业务表。

    守卫：DB 非终态任务 ∪ Redis inflight 键——网关入队先 SADD inflight + XADD，worker 消费
    才物化 DB 行，单查 DB 会漏「已入队未物化」窗口；resume 直发绕过网关（无 SADD）但
    DB status 非终态，由 DB 腿兜住（双腿互补）。有进行中任务 → 409（对齐 pause/cancel）。

    级联（FK ondelete=CASCADE，RLS 对参照动作豁免）覆盖：chapters/versions/outlines/
    settings/characters/factions/locations/记忆层/memory_candidates/writing_lessons/
    validation 报表/**embeddings 向量**/tasks；agent_runs（无 FK）、LangGraph checkpoint
    三表（无 project_id）与 Redis 队列/锁残留需显式清理（本函数完成）。
    """
    pid = _pid(project_id)
    with new_session() as db:
        proj = db.get(Project, pid)
        if proj is None:
            raise HTTPException(status_code=404, detail="作品不存在")
        active = db.query(Task.id).filter(
            Task.project_id == pid,
            Task.status.in_(("queued", "running", "paused", "awaiting_review")),
        ).count()
        inflight = get_redis().exists(inflight_key(str(proj.user_id), str(pid)))
        if active or inflight:
            raise HTTPException(status_code=409, detail="本书有进行中任务，请先暂停/取消后再删除")
        task_ids = [str(tid) for (tid,) in
                    db.query(Task.id).filter(Task.project_id == pid).all()]
    # best-effort 清理（checkpoint/Redis 是可重建、幂等数据；失败仅告警不阻塞删除）
    try:
        delete_threads(task_ids)
    except Exception:
        logger.warning("删除书籍：checkpoint 清理失败 project_id=%s", project_id)
    r = get_redis()
    for tid in task_ids:
        r.delete(sse_key(tid), lock_key(tid))
    r.delete(book_key(project_id), inflight_key(str(proj.user_id), str(pid)))
    # 最终不可逆点：agent_runs（无 FK）+ projects（FK 级联清其余全部业务表）。
    # with new_session() 退出只 close（回滚未提交事务），必须显式 commit（代码库约定）。
    with new_session() as db:
        db.execute(sa_delete(AgentRun).where(AgentRun.project_id == pid))
        db.execute(sa_delete(Project).where(Project.id == pid))
        db.commit()
    return {"project_id": project_id, "deleted": True}


@router.get("/projects/{project_id}/entities",
            dependencies=[Depends(require_owner)], response_model=list[EntityCardOut])
def entity_cards(project_id: str) -> list[dict]:
    """设定实体浏览（§7.11 ④ 自动建档：武器/功法/技能/地点低风险自动登记）。

    实体是"存在即登记"的低冲突注册表（对齐地点自动建档口径）；状态变化仍走状态台账
    （character_state item/power/location），此处只读静态卡。"""
    pid = _pid(project_id)
    with tenant_session(project_id) as db:
        rows = db.query(Entity).filter(Entity.project_id == pid) \
            .order_by(Entity.entity_type, Entity.canonical_name).all()
        return [
            {
                "id": str(e.id),
                "entity_type": e.entity_type,
                "name": e.canonical_name,
                "description": (e.properties or {}).get("description"),
                "first_seen_chapter": (e.properties or {}).get("first_seen_chapter"),
            }
            for e in rows
        ]


@router.post("/projects/{project_id}/setup-draft",
             dependencies=[Depends(require_owner)], response_model=SetupDraftOut)
def setup_draft(project_id: str, body: SetupDraftBody) -> dict:
    """一句话梗概 → Planner 生成设定骨架草稿（不落库，可反复重新生成）。

    LLM 失败 / 解析失败 → {draft: {}, error} 200（§6.12 降级，前端回手填空表单）。
    agent_runs 记录（§6.8 成本透明）；agent_runs 无 RLS（观测表），普通连接可写。
    """
    premise = body.premise.strip()
    if not premise:
        raise HTTPException(status_code=400, detail="一句话梗概不能为空")
    db = new_session()
    try:
        project = db.get(Project, _pid(project_id))
        genre = project.genre if project is not None else ""
        draft, error = generate_book_setup(genre, premise, project_id=project_id, db=db)
        db.commit()
    finally:
        db.close()
    return {"draft": draft, "error": error}


@router.put("/projects/{project_id}/setup",
            dependencies=[Depends(require_owner)], response_model=SetupConfirmOut)
def put_setup(project_id: str, body: SetupBody) -> dict:
    """确认落库：编排层写 project_settings + characters/factions/locations（create-if-missing）。

    world_rules / hard_constraints 整体替换 + version 递增（§7.6 乐观版本号）；角色/势力/
    地点按 name 查重，不存在才建（§7.11 ③ append-only：已落行不覆盖，防无影响面分析改基底）。
    """
    pid = _pid(project_id)
    with tenant_session(project_id) as db:
        st = get_settings(db, pid)
        if st is None:
            st = ProjectSettings(project_id=pid)
            db.add(st)
        st.world_rules = dict(body.world_rules or {})
        st.hard_constraints = [str(x).strip() for x in (body.hard_constraints or []) if str(x).strip()]
        st.version = (st.version or 1) + 1

        for c in body.characters or []:
            name = str(c.get("name") or "").strip()
            if not name:
                continue
            if get_character(db, pid, name) is None:
                db.add(Character(
                    project_id=pid, name=name,
                    race=_str_or_none(c.get("race")),
                    origin=_str_or_none(c.get("origin")),
                    realm_cap=str(c.get("realm_cap") or "无").strip() or "无",
                    personality=_str_or_none(c.get("personality")),
                    base_attrs=c.get("base_attrs") if isinstance(c.get("base_attrs"), dict) else {},
                ))
        for f in body.forces or []:
            name = str(f.get("name") or "").strip()
            if not name:
                continue
            exists = db.query(Faction).filter(Faction.project_id == pid, Faction.name == name).first()
            if exists is None:
                db.add(Faction(
                    project_id=pid, name=name,
                    stance=_str_or_none(f.get("stance")),
                    resources=[str(x) for x in (f.get("resources") or [])],
                    members=[str(x) for x in (f.get("members") or [])],
                ))
        for loc in body.locations or []:
            name = str(loc.get("name") or "").strip()
            if not name:
                continue
            exists = db.query(Location).filter(Location.project_id == pid, Location.name == name).first()
            if exists is None:
                db.add(Location(project_id=pid, name=name))
    return {"ok": True}


@router.post("/projects/{project_id}/outline-draft",
             dependencies=[Depends(require_owner)], response_model=OutlineDraftOut)
def outline_draft(project_id: str, body: OutlineDraftBody) -> dict:
    """整书大纲草稿（§11 建书 ③）：题材/梗概/大致章节数/大致故事线 → Planner 提案。

    不落库可反复重新生成；LLM 失败 → {outline: {}, error} 200 降级（§6.12）。
    agent_runs 记 node=book_outline（§6.8 成本透明）。
    """
    premise = body.premise.strip()
    if not premise:
        raise HTTPException(status_code=400, detail="一句话梗概不能为空")
    cc = body.chapter_count
    if not (1 <= cc <= 200):
        raise HTTPException(status_code=400, detail="大致章节数需在 1–200 之间")
    db = new_session()
    try:
        project = db.get(Project, _pid(project_id))
        genre = project.genre if project is not None else ""
        outline, error = generate_book_outline(
            genre, premise, chapter_count=cc, storyline=body.storyline,
            project_id=project_id, db=db)
        db.commit()
    finally:
        db.close()
    return {"outline": outline, "error": error}


@router.put("/projects/{project_id}/outline",
            dependencies=[Depends(require_owner)], response_model=BookOutlineOut)
def put_outline(project_id: str, body: OutlineConfirmBody) -> dict:
    """整书大纲确认落库（§11 ③）：volume_outlines 单行（volume_seq=1）整体替换。

    归一化：逐章补全局 seq（跨卷连续编号），plan/write 按 seq 取本章大纲位；空章/空卷丢弃；
    volume_seq 重新编号（=卷下标+1）。objective 单行存全书终局。
    """
    pid = _pid(project_id)
    volumes: list[dict] = []
    seq_counter = 0
    for v in body.volumes or []:
        if not isinstance(v, dict):
            continue
        chapters: list[dict] = []
        for c in v.get("chapters") or []:
            if not isinstance(c, dict):
                continue
            title = str(c.get("title") or "").strip()
            goal = str(c.get("goal") or "").strip()
            if not title and not goal:
                continue
            seq_counter += 1
            chapters.append({
                "seq": seq_counter,
                "title": title,
                "goal": goal,
                "beats": [str(b).strip() for b in (c.get("beats") or []) if str(b).strip()],
            })
        if not chapters:
            continue  # 空卷丢弃（防全空 outline 落库）
        volumes.append({
            "volume_seq": len(volumes) + 1,
            "title": str(v.get("title") or "").strip() or f"第 {len(volumes) + 1} 卷",
            "theme": str(v.get("theme") or "").strip(),
            "goal": str(v.get("goal") or "").strip(),
            "key_results": [str(k).strip() for k in (v.get("key_results") or []) if str(k).strip()],
            "end_event": str(v.get("end_event") or "").strip(),
            "chapters": chapters,
        })
    payload = {
        "premise": body.premise.strip(),
        "chapter_count": body.chapter_count or seq_counter,
        "storyline": body.storyline.strip(),
        "objective": str(body.objective or "").strip(),
        "volumes": volumes,
    }
    with tenant_session(project_id) as db:
        row = get_volume_outline(db, pid, 1)
        if row is None:
            db.add(VolumeOutline(project_id=pid, volume_seq=1, title="整书大纲",
                                 outline=payload))
        else:
            row.outline = payload
        db.commit()
    return {"outline": payload}


@router.get("/projects/{project_id}/outline",
            dependencies=[Depends(require_owner)], response_model=BookOutlineOut)
def get_outline(project_id: str) -> dict:
    """整书大纲读取（§11 前端展示 / 重新生成输入）。无大纲 → {outline: null} 不 500。

    存量旧版扁平大纲（{arc, chapters}）经 normalize_outline 归一为新三层（并入「全书主线」单卷），
    前端展示与写作注入对新旧数据一致。
    """
    pid = _pid(project_id)
    with tenant_session(project_id) as db:
        row = get_volume_outline(db, pid, 1)
    return {"outline": normalize_outline(row.outline) if row else None}


@router.get("/projects/{project_id}/world",
            dependencies=[Depends(require_owner)], response_model=WorldViewOut)
def world_view(project_id: str) -> dict:
    """世界观浏览：settings 的 world_rules/hard_constraints + 势力 + 地点。

    无 settings 行 → 空默认不 500（仿 routes_settings 空默认口径）。
    """
    pid = _pid(project_id)
    with tenant_session(project_id) as db:
        st = get_settings(db, pid)
        factions = db.query(Faction).order_by(Faction.name).all()
        locations = db.query(Location).order_by(Location.name).all()
    return {
        "world_rules": st.world_rules if st and st.world_rules else {},
        "hard_constraints": st.hard_constraints if st and st.hard_constraints else [],
        "factions": [
            {"name": f.name, "stance": f.stance, "resources": f.resources or []}
            for f in factions
        ],
        "locations": [{"name": loc.name} for loc in locations],
    }


@router.get("/projects/{project_id}/characters",
            dependencies=[Depends(require_owner)], response_model=list[CharacterCardOut])
def character_cards(project_id: str) -> list[dict]:
    """人物卡片：静态基底 + 当前状态台账（§7.7 按当前章物化 {field: new_value}）。"""
    pid = _pid(project_id)
    seq = 0
    with new_session() as db:
        project = db.get(Project, pid)
        if project is not None:
            seq = project.current_chapter or 0
    with tenant_session(project_id) as db:
        cards = []
        for ch in get_all_characters(db, pid):
            state = get_character_state(db, pid, ch.id, chapter_seq=seq)
            cards.append({
                "id": str(ch.id), "name": ch.name, "race": ch.race, "origin": ch.origin,
                "realm_cap": ch.realm_cap, "personality": ch.personality,
                "aliases": ch.aliases or [], "base_attrs": ch.base_attrs or {},
                "state": state,
            })
    return cards


@router.get("/projects/{project_id}/graph",
            dependencies=[Depends(require_owner)], response_model=WorldGraphOut)
def world_graph(project_id: str) -> dict:
    """世界拓扑全量（§9 图谱前端：4 类节点 + 人物关系/地点层级边）。

    节点全量含孤立项（建书设定即入图，不因无关联被裁掉）；人物关系**含失效行**
    （valid_to 非空 → expired=True，前端活跃实线/失效虚线区分），地点层级按 parent_id。
    tenant_session RLS 已按项目隔离，此处再显式 project_id 过滤为双保险（同 entity_cards）。
    """
    pid = _pid(project_id)
    with tenant_session(project_id) as db:
        nodes: list[dict] = []
        edges: list[dict] = []
        for ch in db.query(Character).filter(Character.project_id == pid).order_by(Character.name).all():
            nodes.append({"id": str(ch.id), "name": ch.name, "type": "character",
                          "realm_cap": ch.realm_cap})
        for f in db.query(Faction).filter(Faction.project_id == pid).order_by(Faction.name).all():
            nodes.append({"id": str(f.id), "name": f.name, "type": "faction", "stance": f.stance})
        # 地点节点 = Location 注册表 ∪ 自动建档的地点实体（按名去重）：new_entity 从
        # §7.11 ④ 起镜像进 Location（带 parent_id），旧数据只有 Entity 行也要留在图上。
        loc_names: set[str] = set()
        for loc in db.query(Location).filter(Location.project_id == pid).order_by(Location.name).all():
            loc_names.add(loc.name)
            nodes.append({"id": str(loc.id), "name": loc.name, "type": "location",
                          "parent_id": str(loc.parent_id) if loc.parent_id else None})
            if loc.parent_id:
                edges.append({"source_id": str(loc.id), "target_id": str(loc.parent_id),
                              "edge_type": "hierarchy"})
        for e in db.query(Entity).filter(Entity.project_id == pid) \
                .order_by(Entity.entity_type, Entity.canonical_name).all():
            if e.entity_type == "location":
                if e.canonical_name in loc_names:
                    continue  # 已由 Location 节点覆盖，避免同地双节点
                # 仅 Entity 行（旧数据）→ 仍以地点节点入图（无层级 parent）
                nodes.append({"id": str(e.id), "name": e.canonical_name,
                              "type": "location", "parent_id": None})
            else:
                nodes.append({"id": str(e.id), "name": e.canonical_name, "type": "entity",
                              "entity_type": e.entity_type})
        for r in db.query(Relation).filter(Relation.project_id == pid).all():
            edges.append({
                "source_id": str(r.source_id),
                "target_id": str(r.target_id),
                "edge_type": r.relation_type,
                "confidence": r.confidence,
                "expired": r.valid_to is not None,
                "source_chapter": r.source_chapter,
            })
    return {"nodes": nodes, "edges": edges}


@router.get("/projects/{project_id}/foreshadows",
            dependencies=[Depends(require_owner)], response_model=list[ForeshadowOut])
def foreshadow_ledger(project_id: str) -> list[dict]:
    """伏笔池台账（§7.9 状态机全量，供前端「伏笔池」区块）。

    全状态返回（planted/developing/resolved/dropped 都展示）——已回收/已废弃保留历史
    供复盘「哪些伏笔埋了没收、哪些收早了」，open 的才是 plan_chapter 会消费的。
    tenant_session RLS 隔离 + 显式 project_id 过滤双保险（同 world_graph）。
    """
    pid = _pid(project_id)
    with tenant_session(project_id) as db:
        rows = db.query(Foreshadow).filter(Foreshadow.project_id == pid) \
            .order_by(Foreshadow.status, Foreshadow.planted_chapter, Foreshadow.description).all()
        return [
            {
                "id": str(f.id),
                "description": f.description,
                "status": f.status,
                "planted_chapter": f.planted_chapter,
                "resolved_chapter": f.resolved_chapter,
                "trigger": f.trigger or {},
                "related_entities": f.related_entities or [],
            }
            for f in rows
        ]
