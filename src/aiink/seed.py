"""Demo 种子数据：《九州问天》世界观基线（conflict-samples.md 附录 A）。

init 命令：建库建表 + RLS 启用 + 写入 demo user/project/人物/硬约束/剧情线。
幂等：重复执行不重复写。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from aiink.db import get_engine, tenant_session
from aiink.models import Character, Fact, PlotThread, Project, ProjectSettings, User

DEMO_USERNAME = "demo"
DEMO_PROJECT_TITLE = "九州问天"
DEMO_TARGET_WORDS = 3000  # §6.9 单遍生成整章目标字数

REALM_ORDER = ["炼气", "筑基", "金丹", "元婴", "化神", "大乘", "渡劫"]

# 文风档案（§7.12 / §8.6）：进写作 Prompt 的生成约束，禁止 AI 味句式
DEMO_STYLE_PROFILE = {
    "pov": "第三人称限知视角，以林砚为主，外部环境描写克制",
    "sentence_style": "长短句结合但自然，禁止机械交替排比；对话口语化、有真实语感；段落不宜整段叙述堆叠",
    "forbidden": [
        "禁止'不是…而是…'式转折句堆砌",
        "禁止段落结尾总结式收束（每段末句点题升华）",
        "禁止连续排比/对仗句式机械重复",
        "禁止高频空泛连接词滥用（'仿佛'、'顿时'、'竟然'、'只见'）",
        "禁止'只见一道流光'、'他的眼神闪过一丝'类模板化动作描写",
        "禁止解释性旁白替读者下结论（不说'他知道事情不简单了'）",
    ],
    "dialogue": "不同角色腔调需区分：林砚克制隐忍、秦虎直率莽撞、黑脸修士阴冷，同一角色对话风格稳定",
}

# 硬约束（is_hard，恒在 Top-K，§7.2）
_HARD_FACTS = [
    ("境界体系：炼气→筑基→金丹→元婴→化神→大乘→渡劫，不可越级晋升，需逐境淬炼", "规则"),
    ("地域禁制：全九州设禁制结界，不可瞬移，跨域需传送阵", "规则"),
    ("天衡宗与叛出弟子为敌对关系", "归属"),
]


def _ensure_demo_project() -> str:
    """建 demo 用户 + 作品，返回 project_id（先 commit 根表，避免嵌套事务外键不可见）。"""
    with Session(get_engine()) as db:
        user = db.query(User).filter(User.username == DEMO_USERNAME).first()
        if user is None:
            user = User(username=DEMO_USERNAME, email="demo@aiink.local")
            db.add(user)
            db.flush()
        project = db.query(Project).filter(Project.title == DEMO_PROJECT_TITLE, Project.user_id == user.id).first()
        if project is None:
            project = Project(user_id=user.id, title=DEMO_PROJECT_TITLE, genre="仙侠玄幻",
                              target_words=DEMO_TARGET_WORDS)
            db.add(project)
            db.flush()
        pid = str(project.id)
        db.commit()  # 根表先落库，后续租户事务才能引用外键
        return pid


def create_demo_project() -> str:
    """幂等建 demo 数据，返回 project_id。"""
    pid = _ensure_demo_project()
    with tenant_session(pid) as tdb:
        if tdb.query(ProjectSettings).filter_by(project_id=pid).first() is None:
            tdb.add(ProjectSettings(
                project_id=pid,
                world_rules={"realm_order": REALM_ORDER},
                hard_constraints=[f[0] for f in _HARD_FACTS],
                style_profile=DEMO_STYLE_PROFILE,
            ))
            for content, category in _HARD_FACTS:
                tdb.add(Fact(project_id=pid, content=content, category=category, is_hard=True,
                             source_chapter=1, confidence=1.0, confirm_status="confirmed"))
        _ensure_character(tdb, pid, "林砚", realm_cap="金丹",
                          personality="谨慎隐忍、谋定后动", origin="叛出天衡宗")
        _ensure_character(tdb, pid, "黑脸修士", realm_cap="元婴", origin="天衡宗执法堂")
        _ensure_character(tdb, pid, "秦虎", realm_cap="筑基", origin="北境城守将")
        if tdb.query(PlotThread).filter_by(project_id=pid).first() is None:
            tdb.add(PlotThread(project_id=pid, name="叛出天衡宗，追寻真相", kind="main",
                               status="active", priority=1))
            tdb.add(PlotThread(project_id=pid, name="玉佩真相", kind="side",
                               status="active", priority=2))
    return pid


def _ensure_character(db: Session, project_id: str, name: str, **kw) -> None:
    if db.query(Character).filter_by(project_id=project_id, name=name).first() is None:
        db.add(Character(project_id=project_id, name=name, **kw))
