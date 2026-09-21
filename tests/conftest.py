"""共享测试设施：复用 test_flow 的活库 + 假 provider 模式（阶段 2 worker/API 测试）。

test_flow.py 自带同名 fixtures（模块级优先于 conftest），此处 re-export 仅服务新测试文件；
不修改既有测试文件（外科手术式改动）。
"""

from __future__ import annotations

import os

# 扫榜默认关（§10）：图节点集成测试不触外网。DaoSearch 不可达会让 mcp initialize 挂起/
# 被内部 cancel scope 取消（CancelledError 不降级直接炸节点）；且 test_multiprocess 的子
# 进程是全新 import（monkeypatch 传播不到）。必须在 myink.config 首次导入前设（settings
# 是 frozen dataclass 模块级单例）。rankings 特性测试自带 FakeSettings/monkeypatch，不受影响。
os.environ["RANKINGS_ENABLED"] = "0"
# RabbitMQ 测试隔离（阶段 6）：QUEUE_PREFIX=-mp- 让本套件发布/消费全走 queue:tasks-mp-，
# 不碰开发栈无前缀真实队列（避免测试消息污染生产队列/被真实 worker 抢走）。
# 必须在 myink.config 首次导入前设（settings 是 frozen 单例）——单在 test_multiprocess.py
# 模块级设已太晚：conftest 的 myink.db 导入会先触发 settings 冻结。
os.environ["QUEUE_PREFIX"] = "-mp-"
# 本地 compose 对外暴露的 RabbitMQ 用户。显式传入的 CI/开发环境配置仍优先。
os.environ.setdefault("AMQP_URL", "amqp://myink:myink@localhost:5672/")

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import delete as sa_delete, select as sa_select

from myink.api.auth import create_access_token
from myink.config import settings
from myink.db import new_session
from myink.models import AgentRun, Project, ProjectSettings

from test_flow import (  # noqa: F401  (re-export fixtures/StubProvider)
    FakeEmbedder,
    StubProvider,
    fake_embedder,
    project_id,
    stub_provider,
)

TEST_JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long"

# 形态是 Bearer 但内容不是合法 JWT：用于「坏凭证 → 401」的用例。
# 旧套件用 _h("not-a-uuid") 表达同一件事（当时身份是明文头，可以随便塞垃圾）；
# 现在身份是签名令牌，垃圾要塞在 Authorization 里才等效。
INVALID_BEARER = {"Authorization": "Bearer not-a-jwt"}


@pytest.fixture(autouse=True)
def _strong_auth_secret(monkeypatch):
    """业务路由现在自己验 JWT，而 ``require_auth_configuration`` 对所有环境拒绝短于
    32 字节的密钥（``_DEV_JWT_SECRET`` 只有 23 字节）——不换密钥则全站 503。

    补丁打在 ``myink.api.auth`` 里那个 ``settings`` 名字上（不是环境变量），所以不会
    泄漏到别的进程，也不依赖 conftest 的 import 顺序。test_auth / test_admin 自带的
    同款夹具值相同，两者共存不冲突。
    """
    import myink.api.auth as auth

    monkeypatch.setattr(auth, "settings", replace(settings, jwt_secret=TEST_JWT_SECRET))


def identity_headers(
    user, *, tier: str | None = None, auth_version: int | None = None
) -> dict[str, str]:
    """给 ``user`` 签一个真 HS256 bearer；``user`` 为 None 时返回 ``{}``。

    ``user`` 可以是 ``User`` 行，也可以只是 id。tier / auth_version 省略时取行上的值
    （``models/project.py`` 给这两列都设了 default，裸 ``User(username=...)`` flush 后
    就带得上），所以绝大多数用例直接 ``identity_headers(user)`` 即可。

    取代旧的 ``{"X-Myink-User": str(uid)}``：那个头已经不再被信任，测试必须出示一个
    真能验过的令牌。
    """
    uid = getattr(user, "id", user)
    if uid is None:
        return {}
    claims_tier = tier or getattr(user, "tier", None) or "normal"
    claimed_version = auth_version if auth_version is not None else getattr(user, "auth_version", None)
    token = create_access_token(uuid.UUID(str(uid)), claims_tier, claimed_version or 1)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _no_rate_limits(monkeypatch):
    """把两个限流器在测试期抬到几乎无穷大。

    它们一个按「全进程一个桶」、一个按「一个 IP 一个键」计数，而整套 pytest 共用同一个
    TestClient 地址、在几十秒内打完几百次请求——按真实阈值会大面积 429，那测的是限流器
    而不是被测代码。限流器本身由 tests/test_ratelimit.py 把阈值调回真实值专测。
    """
    import myink.api.ratelimit as rl

    monkeypatch.setattr(rl, "settings", replace(rl.settings, rate_per_sec=10**9, rate_burst=10**9))
    monkeypatch.setattr(rl, "AUTH_RATE_MAX", 10**9)


@pytest.fixture
def temp_project():
    """每测试独立临时书（复制 demo 的 Project+ProjectSettings，§13 多书）。

    写保护（§11 顺序约束）要求章节只能写「已写最大章+1」；demo 已写到 ch-55，
    共享 demo 会让测试的固定 seq 被拦截且顺序耦合。临时书 max_seq=0 → next=1，
    测试用 seq=1 即可无耦合跑 worker 机制验证。用毕删书（FK 级联子表 + agent_runs 手动）。
    """
    with new_session() as db:
        row = db.execute(sa_select(Project).where(Project.title == "九州问天")).scalars().first()
        assert row is not None, "请先运行 `myink init --seed`"
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
                skill_pack=ds.skill_pack, genre_pack=getattr(ds, "genre_pack", None) or {},
                model_routes=ds.model_routes,
                hard_constraints=ds.hard_constraints, version=1))
        db.commit()
        pid = str(b.id)
    yield pid
    with new_session() as db:
        db.execute(sa_delete(AgentRun).where(AgentRun.project_id == pid))
        db.execute(sa_delete(ProjectSettings).where(ProjectSettings.project_id == pid))
        db.execute(sa_delete(Project).where(Project.id == pid))
        db.commit()
