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
- GET /projects/{pid}/characters：人物卡片浏览（静态基底 + 当前状态台账 §7.7）。

与 §7.11 权威模型一致：agent 只提案、用户确认是唯一 canon；确认 = 编排层写库入口
（同 persist 层级，数据流边界 §6.2）。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aiink.api.auth import current_user, require_owner
from aiink.api.schemas import CharacterCardOut, ProjectOut, SetupConfirmOut, SetupDraftOut, WorldViewOut
from aiink.book_setup import generate_book_setup
from aiink.config import settings
from aiink.db import new_session, tenant_session
from aiink.memory.repository import get_all_characters, get_character, get_character_state, get_settings
from aiink.models import Character, Faction, Location, Project, ProjectSettings
from sqlalchemy import func

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


class SetupDraftBody(BaseModel):
    premise: str


class SetupBody(BaseModel):
    """确认落库的设定（前端可编辑草稿后回传；自由形状字段松类型，落库前清洗）。"""

    world_rules: dict = Field(default_factory=dict)
    hard_constraints: list[str] = Field(default_factory=list)
    characters: list[dict] = Field(default_factory=list)
    forces: list[dict] = Field(default_factory=list)
    locations: list[dict] = Field(default_factory=list)


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
        project = Project(user_id=uid, title=title, genre=body.genre.strip() or "仙侠玄幻")
        db.add(project)
        db.flush()
        pid = str(project.id)
        db.commit()  # 根表先落库，后续租户事务才能引用外键（seed._ensure_sample_book 同款）
    with tenant_session(pid) as tdb:
        if tdb.query(ProjectSettings).filter_by(project_id=pid).first() is None:
            tdb.add(ProjectSettings(project_id=pid))
    return {"id": pid, "title": project.title, "genre": project.genre,
            "current_chapter": project.current_chapter}


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
