"""共享测试设施：复用 test_flow 的活库 + 假 provider 模式（阶段 2 worker/API 测试）。

test_flow.py 自带同名 fixtures（模块级优先于 conftest），此处 re-export 仅服务新测试文件；
不修改既有测试文件（外科手术式改动）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete as sa_delete, select as sa_select

from aiink.db import new_session
from aiink.models import AgentRun, Project, ProjectSettings

from test_flow import (  # noqa: F401  (re-export fixtures/StubProvider)
    FakeEmbedder,
    StubProvider,
    fake_embedder,
    project_id,
    stub_provider,
)


@pytest.fixture
def temp_project():
    """每测试独立临时书（复制 demo 的 Project+ProjectSettings，§13 多书）。

    写保护（§11 顺序约束）要求章节只能写「已写最大章+1」；demo 已写到 ch-55，
    共享 demo 会让测试的固定 seq 被拦截且顺序耦合。临时书 max_seq=0 → next=1，
    测试用 seq=1 即可无耦合跑 worker 机制验证。用毕删书（FK 级联子表 + agent_runs 手动）。
    """
    with new_session() as db:
        row = db.execute(sa_select(Project).where(Project.title == "九州问天")).scalars().first()
        assert row is not None, "请先运行 `aiink init`"
        demo = row
        b = Project(user_id=demo.user_id, title=f"test书-{uuid.uuid4().hex[:6]}",
                    genre=demo.genre, target_words=demo.target_words)
        db.add(b)
        db.flush()
        ds = db.execute(sa_select(ProjectSettings).where(
            ProjectSettings.project_id == demo.id)).scalar_one_or_none()
        if ds is not None:
            db.add(ProjectSettings(
                project_id=b.id, world_rules=ds.world_rules, style_profile=ds.style_profile,
                skill_pack=ds.skill_pack, model_routes=ds.model_routes,
                hard_constraints=ds.hard_constraints, version=1))
        db.commit()
        pid = str(b.id)
    yield pid
    with new_session() as db:
        db.execute(sa_delete(AgentRun).where(AgentRun.project_id == pid))
        db.execute(sa_delete(ProjectSettings).where(ProjectSettings.project_id == pid))
        db.execute(sa_delete(Project).where(Project.id == pid))
        db.commit()
