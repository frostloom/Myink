# 对话式短篇建书（模仿 inkos）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把短篇建书从「长篇同款向导」换成 inkos 式的对话助手动线——与初始大模型聊清意图、由它出方案卡、用户可编辑、确认即开写；顺带落一个账号级文风库，并把账号级 LLM 花费记进管理面板。

**Architecture:** 三条互不重叠的工作流。① 账号级文风库：新表 `style_library_items` + `make_user_chain`（账号级模型链）+ `/api/v1/style-library` 四端点；② 对话式建书：新表 `short_creation_sessions`/`short_creation_messages` + 每回合一次 `planner` json_mode 调用 + `/api/v1/short/creation` 四端点，commit 复用现有 `_short_outline_draft` 出方案、直接落库并置 `ready`；③ 收口：短篇工作台去掉 Plan 阶段与账本 rail，`agent_runs` 放宽为「可无 project_id、可有 user_id」，管理面板加用户 tab 与用户详情页。前端 `/short/new` 换成两栏对话页。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0（Mapped）+ PostgreSQL(RLS) / Pydantic v2；React 19 + react-router 7 + vitest 4 + oxlint。

**Spec:** `docs/superpowers/specs/2026-09-24-short-creation-assistant-design.md`

**参照实现（不在本仓库，只作语义参照）:** `Narcooo/inkos` —— `packages/cli/src/commands/short-fiction.ts`（短篇是独立顶层命令）、其建书对话与「方案卡 → 确认后开写」的两段式。

## Global Constraints

- **长篇完全不动。** 一期只改短篇。`form == "long"` 的任何分支、`_ROLE_INHERIT`（项目级角色继承）、`validate_creation_outline` 一律不改。子代理若发现自己要动长篇路径，停下来报告。
- **`form` 建书后不可改。** 文风同理：建书时定，之后没有换文风的入口。
- **短篇生成只读 `volume_outlines` 第 1 卷 + 只认 `creation_status ∈ {ready, legacy_ready}`。** 所以 commit 必须**同步**产出逐章方案并落库、并把状态推到 `ready`。
- **新表不带 `project_id` 列。** `db.enable_row_level_security()` 会给任何带 `project_id` 的表套 `tenant_isolation` 策略，账号级表一旦带上，账号级查询会被静默清空。归属自己用 `user_id` 把住。
- **记账不能没有归属。** 每条 `agent_runs` 至少有 `project_id` 或 `user_id` 之一。
- **模型调用失败不 500。** 建书对话一回合失败要把原文当回复返回、卡保持原值、错误记进消息（对齐 `book_setup.py` 既有的降级约定）。
- **上游响应只认 `{draft}`。** 文风样例端点返回 `{"draft": {...}}`（`merge_style_draft` 已把 stats 与 `extract_error` 并进一份 draft），**不是** `{draft, stats, error}`。
- **`plan.md` 是本项目的规格文档；本次不写新 agent，不新增角色。** 建书对话固定用 `planner`。
- **验证环境（务必用这个组合）：** Bash + `source .local/env-test.sh` + conda `aiink` 的 python。后端 `python -m pytest <file> -q`；前端必须进 `web/` 目录跑 `npm run lint` / `npm test` / `npm run build`（**真类型闸是 `npm run build`**）。新增表/列之后必须重跑 `python -m myink.cli init`，否则活的测试库看不到它们。
- **提交需授权。** 本计划每个任务末尾的 commit 步是 TDD 节奏的一部分，但 AGENTS.md 规定「默认不自动提交、推送、合并或发布」——执行到第一次 commit 前先向用户要授权，之后按授权范围执行。

## Review Focus

以下几类输入 spec 没写、测试最容易漏，但真会咬到人。每条都在后面点名了拥有它的任务，测试一并写进那个任务：

1. **模型这轮把某个字段给成空串或干脆没给** —— 用户手改过的内容必须留着（用户在右栏改了「暂定名」，模型下一轮思考时不回这个字段，卡不能被抹空）。→ Task 7、Task 11。
2. **模型这轮返回坏 JSON / 空 content / 一整段散文** —— 会话不能丢、不能 500，用户重说一句就能接着聊。→ Task 10、Task 11。
3. **当日建书数刚好用满时点「确认，开写」** —— 必须是网关同款 `{"error": "BOOK_CNT_EXCEEDED"}` + 429，不能 500，也不能悄悄建成功。→ Task 12、Task 13。
4. **commit 中途失败后用户再点一次确认**（方案为空、审纲后的校验不过、模型连不上）—— 不能建出第二本书。→ Task 13。
5. **账号级运行（`project_id` 为 NULL 的花费）出现在管理面板** —— 用户总花费要含它们、点进去能看到每次调用，且 `/runs?user_id=` 与列表显示的归属一致。→ Task 15。

---

## File Structure

**后端新增**

| 文件 | 职责 |
| --- | --- |
| `src/myink/models/creation.py` | 三张账号级表：文风库条目 + 建书会话 + 会话消息（无 `project_id` 列） |
| `src/myink/short/creation.py` | 方案卡的纯逻辑：字段表、卡 patch/normalize/merge、ready 判定、premise 拼装（无 I/O） |
| `src/myink/api/routes_style_library.py` | `/api/v1/style-library` 四端点（列/提取/保存/删） |
| `src/myink/api/routes_short_creation.py` | `/api/v1/short/creation` 四端点（取会话/发消息/确认开写/重来） |

**后端修改**

| 文件 | 改动 |
| --- | --- |
| `src/myink/providers/__init__.py` | 抽 `_chain_from_override`；加 `_USER_ROLE_FALLBACK` / `_lookup_user_override` / `make_user_chain` |
| `src/myink/models/runs.py` | `AgentRun.project_id` 可空 + 新增 `user_id` |
| `src/myink/db.py` | `ensure_agent_run_user()`（纯 DDL，不回填） |
| `src/myink/cli.py` | `init` 里接上两个新 ensure |
| `src/myink/workflow/nodes.py` | `_owner_ids()`；`record_run`/`record_plain` 接 `user_id`；`_MAX_TOKENS["short_creation"]` |
| `src/myink/style_extract.py` | 提取可账号级记账（`user_id`） |
| `src/myink/book_setup.py` | 新增 `generate_short_creation_turn()`（建书对话一回合） |
| `src/myink/workflow/prompts.py` | `SYSTEM_SHORT_CREATION` + `short_creation_messages()` |
| `src/myink/api/routes_book.py` | 抽 `_create_project_row` / `_persist_short_outline`（行为不变），短篇分支改走 helper |
| `src/myink/api/routes_admin.py` | 成本归属口径（`/users` 聚合、`_run_statement` 外连接、`/runs` 筛选） |
| `src/myink/api/admin_schemas.py` | `AdminRun.project_id/username/project_title` 放宽为可空 |
| `src/myink/api/schemas.py` | 两个新路由的响应体 |
| `src/myink/api/main.py` | 注册两个新 router |
| `spec/api-openapi.json` | 末尾任务重新导出 |

**前端新增**

| 文件 | 职责 |
| --- | --- |
| `web/src/lib/styleLibraryApi.ts` | 文风库四端点调用 |
| `web/src/lib/shortCreationApi.ts` | 建书对话四端点调用 |
| `web/src/pages/ShortCreationPage.tsx` + `.module.css` | `/short/new` 两栏对话页 |
| `web/src/pages/admin/UserDetail.tsx` | 用户详情：总花费 + 每次调用明细 |

**前端修改**

`web/src/router.tsx`（`/short/new` 换页 + `users/:userId` 子路由）、`web/src/lib/projectCreation.ts`（短篇草稿一律进工作台）、`web/src/lib/adminApi.ts`（`AdminRun` 放宽）、`web/src/pages/AdminPage.tsx`（用户 tab）、`web/src/pages/WorkspacePage.tsx`（短篇不渲染 Plan 视图）、`web/src/components/ProjectRail.tsx`（短篇隐藏三处账本入口）。

---

## Task 0: 修 spec 勘误（3 处）

spec 是本次的权威文档，先把它与代码对齐，后面每个任务才有一个能信的口径。

**Files:**
- Modify: `docs/superpowers/specs/2026-09-24-short-creation-assistant-design.md`

**Interfaces:**
- Consumes: 无
- Produces: 无（纯文档）

- [ ] **Step 1: 改文风样例端点的响应形状**

把工作流 1 里描述 `POST /api/v1/style-library/samples` 返回 `{draft, stats, error}` 的那句改成：

> 返回 `{"draft": {...}}`：`merge_style_draft(stats, llm_profile, extract_error=...)` 已经把统计与提取失败并进同一份 draft（含 `source` 与 `extract_error`），所以不另外暴露 `stats`/`error` 两个顶层键。

- [ ] **Step 2: 去掉「待新增 `adminApi.listUsers`」的说法**

`web/src/lib/adminApi.ts` 的 `listUsers` 与 `getProject` 都已存在（`adminApi.ts:367`、`:377`），工作流 3 的前端改动只需新增 `UserDetail.tsx` 与用户 tab。

- [ ] **Step 3: 记上短篇草稿跳转口径的变化**

在「要动的文件清单」的 `web/src/lib/projectCreation.ts` 一行补上：短篇（**含草稿**）一律跳 `/projects/<id>`；长篇草稿仍跳 `/long/new?draft=<id>`。

- [ ] **Step 4: 提交（与 Task 1 合并提交）**

```bash
git add docs/superpowers/specs/2026-09-24-short-creation-assistant-design.md
git commit -m "docs: 短篇建书 spec 勘误——文风样例响应形状与既有前端接口"
```

---

# 一期 A：账号级文风库

## Task 1: `StyleLibraryItem` 模型

**Files:**
- Create: `src/myink/models/creation.py`
- Modify: `src/myink/models/__init__.py`
- Test: `tests/test_style_library.py`

**Interfaces:**
- Consumes: `myink.models.base.{Base, UUIDPkMixin, TimestampMixin}`
- Produces: `StyleLibraryItem`（表 `style_library_items`，字段 `id: UUID`、`user_id: UUID`、`name: str`、`profile: dict`、`sample_chars: int`、`created_at`、`updated_at`）—— 后续 Task 5/13 都用它

- [ ] **Step 1: 写失败测试**

新建 `tests/test_style_library.py`：

```python
"""账号级文风库：表形状 + 端点（端点部分在后一个任务补齐）。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete as sa_delete, select

from myink.db import new_session
from myink.models import StyleLibraryItem, User


def test_style_library_item_roundtrip():
    with new_session() as db:
        user = User(username=f"style-{uuid.uuid4().hex[:8]}")
        db.add(user)
        db.commit()
        uid = user.id
    try:
        with new_session() as db:
            item = StyleLibraryItem(user_id=uid, name="渡口冷白描",
                                    profile={"pov": "第三人称限知"}, sample_chars=3200)
            db.add(item)
            db.commit()
            item_id = item.id
        with new_session() as db:
            row = db.scalar(select(StyleLibraryItem).where(StyleLibraryItem.id == item_id))
            assert row is not None
            assert row.name == "渡口冷白描"
            assert row.profile["pov"] == "第三人称限知"
            assert row.sample_chars == 3200
    finally:
        with new_session() as db:
            db.execute(sa_delete(StyleLibraryItem).where(StyleLibraryItem.user_id == uid))
            db.execute(sa_delete(User).where(User.id == uid))
            db.commit()


def test_style_library_has_no_project_id_column():
    """账号级表不能有 project_id 列。

    db.enable_row_level_security() 会给任何带 project_id 的表套 FORCE RLS +
    tenant_isolation 策略；账号级查询没设 app.tenant_id，会被策略静默过滤成空。
    """
    assert "project_id" not in StyleLibraryItem.__table__.columns
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_style_library.py -q`
Expected: FAIL —— `ImportError: cannot import name 'StyleLibraryItem' from 'myink.models'`（或 `ModuleNotFoundError: myink.models.creation`）

- [ ] **Step 3: 最小实现**

新建 `src/myink/models/creation.py`：

```python
"""账号级建书产物：用户自命名的文风档案 + 短篇建书会话。

这些表都**不带 `project_id` 列**：`db.enable_row_level_security()` 只给带该列的表加
FORCE RLS + tenant_isolation 策略，而这些数据在建书之前就存在（还没有书），账号级
查询也不设 `app.tenant_id`——一旦带上列，读出来会被策略静默清空。归属一律用 `user_id`
在查询条件里自己把住。
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from myink.models.base import Base, TimestampMixin, UUIDPkMixin


class StyleLibraryItem(Base, UUIDPkMixin, TimestampMixin):
    """用户导入文章提取出来的文风，命名后可复用（长短篇都能在建书时选一次）。

    建书后 `ProjectSettings.style_profile` 是那一刻的副本——改这里不会回头改已建的书，
    这是有意的：文风建书后不可换。
    """

    __tablename__ = "style_library_items"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sample_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

`src/myink/models/__init__.py` 加导入与 `__all__`：

```python
from myink.models.creation import StyleLibraryItem
```

```python
    # creation（账号级）
    "StyleLibraryItem",
```

- [ ] **Step 4: 建表并跑测试**

Run: `python -m myink.cli init && python -m pytest tests/test_style_library.py -q`
Expected: PASS 2 passed（`init` 的 `Base.metadata.create_all` 会建出新表）

- [ ] **Step 5: 提交**

```bash
git add src/myink/models/creation.py src/myink/models/__init__.py tests/test_style_library.py
git commit -m "feat: 文风库表——用户自命名的文风档案"
```

---

## Task 2: `make_user_chain` 账号级模型链

建书对话与文风提取发生在「还没有书」的时刻，`make_chain` 需要 `project_id` 才能查项目设置。加一条账号级入口，复用同一套 provider 构造。

**Files:**
- Modify: `src/myink/providers/__init__.py`
- Modify: `tests/conftest.py`（把 `temp_user` 提上来）
- Modify: `tests/test_environment_routes.py`（删掉本地 `temp_user`）
- Test: `tests/test_user_chain.py`

**Interfaces:**
- Consumes: `make_chain` 的既有内部件 `_from_packed(role, packed) -> dict | None`、`_no_model_chain(thinking)`、`default_provider`、`FallbackChain`、`price_table(override)`
- Produces: `make_user_chain(role: str, user_id: str | uuid.UUID) -> FallbackChain`（**不需要 db**）—— Task 4 的 `extract_style_profile` 与 Task 10 的建书回合都调它

- [ ] **Step 1: 写失败测试**

先看 `tests/test_environment_routes.py:80-101`（`test_environment_connection_prices_roundtrip_and_chain`）——它用 `put_environment(EnvironmentBody(model_connections=[...], model_routes={...}), user_id=temp_user)` 装一条真连接。新测试照抄这个装法，但断言 `make_user_chain`（不经过任何 project）。

新建 `tests/test_user_chain.py`：

```python
"""账号级模型链：建书对话与文风提取走这条（此刻还没有书，拿不到 project_settings）。

不装 chain_stub —— make_chain/make_user_chain 在 default_provider 是测试桩时会短路，
那样就绕过了这里要验的路由逻辑。
"""

from __future__ import annotations

import uuid

from myink.api.routes_environment import EnvironmentBody, ModelConnectionBody, put_environment
from myink.providers import make_user_chain


def _install(temp_user, routes: dict) -> str:
    cid = str(uuid.uuid4())
    put_environment(EnvironmentBody(
        model_connections=[ModelConnectionBody(
            id=cid, name="私有", protocol="openai",
            base_url="https://models.example.com/v1", model="novel-pro",
            api_key="k", input_price=3.5, output_price=8,
        )],
        model_routes={role: f"custom:{cid}" for role in routes},
    ), user_id=temp_user)
    return cid


def test_user_chain_uses_the_account_route_and_its_prices(temp_user):
    _install(temp_user, {"planner": None})
    chain = make_user_chain("planner", temp_user)
    assert chain.chain == ["novel-pro"]
    assert chain.prices == {"input": 3.5, "input_cache_hit": 3.5, "output": 8.0}


def test_user_chain_falls_back_from_planner_to_writer(temp_user):
    """用户只配了 writer：建书对话不该因为没配 planner 就变哑巴。"""
    _install(temp_user, {"writer": None})
    assert make_user_chain("planner", temp_user).chain == ["novel-pro"]


def test_user_chain_falls_back_from_extract_to_planner_then_writer(temp_user):
    _install(temp_user, {"writer": None})
    assert make_user_chain("extract", temp_user).chain == ["novel-pro"]


def test_user_chain_without_any_route_is_unconfigured(temp_user):
    assert make_user_chain("planner", temp_user).chain == ["unconfigured"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_user_chain.py -q`
Expected: FAIL —— `ImportError: cannot import name 'make_user_chain' from 'myink.providers'`

- [ ] **Step 3: 把 `temp_user` 提到 conftest**

`tests/conftest.py` 末尾加（照抄 `test_environment_routes.py` 那份，并补账号级行的清理）：

```python
@pytest.fixture
def temp_user():
    """一次性用户：不碰 seed 的 demo 账号，测完连它留下的账号级行一起删干净。

    必须删账号级行（agent_runs / 会话 / 文风库）：它们没有 project_id，`temp_project`
    的清理逻辑盖不到；留着会污染别的模块里「全局计数」类断言。
    """
    with new_session() as db:
        user = User(username=f"tmp-{uuid.uuid4().hex[:8]}")
        db.add(user)
        db.commit()
        uid = user.id
    yield str(uid)
    with new_session() as db:
        for model in (AgentRun, ShortCreationMessage, ShortCreationSession, StyleLibraryItem):
            db.execute(sa_delete(model).where(model.user_id == uid)) if hasattr(model, "user_id") else None
        db.execute(sa_delete(AgentRun).where(AgentRun.user_id == uid))
        db.execute(sa_delete(User).where(User.id == uid))
        db.commit()
```

`ShortCreationMessage` 没有 `user_id`（靠 `session_id`），上面的写法既绕又脆。**照下面这份写**，别用 for 循环：

```python
@pytest.fixture
def temp_user():
    """一次性用户：不碰 seed 的 demo 账号，测完连它留下的账号级行一起删干净。

    必须删账号级行（agent_runs / 会话 / 文风库）：它们没有 project_id，`temp_project`
    的清理逻辑盖不到；留着会污染别的模块里「全局计数」类断言。
    """
    with new_session() as db:
        user = User(username=f"tmp-{uuid.uuid4().hex[:8]}")
        db.add(user)
        db.commit()
        uid = user.id
    yield str(uid)
    with new_session() as db:
        sessions = select(ShortCreationSession.id).where(ShortCreationSession.user_id == uid)
        db.execute(sa_delete(ShortCreationMessage).where(ShortCreationMessage.session_id.in_(sessions)))
        db.execute(sa_delete(ShortCreationSession).where(ShortCreationSession.user_id == uid))
        db.execute(sa_delete(StyleLibraryItem).where(StyleLibraryItem.user_id == uid))
        db.execute(sa_delete(AgentRun).where(AgentRun.user_id == uid))
        db.execute(sa_delete(User).where(User.id == uid))
        db.commit()
```

（`ShortCreationSession`/`ShortCreationMessage` 在 Task 8 才有——**这一步先只写 `AgentRun`/`StyleLibraryItem`/`User` 三行**，Task 8 再把会话两行补进来。）

`tests/conftest.py` 顶部补导入：

```python
from myink.db import new_session
from myink.models import AgentRun, StyleLibraryItem, User
```

然后删掉 `tests/test_environment_routes.py` 里本地的 `temp_user` fixture 定义（保留它的其他 fixture），确认它自己的用例仍然取得到同名 fixture。

- [ ] **Step 4: 抽 `_chain_from_override` 并实现 `make_user_chain`**

`src/myink/providers/__init__.py`：把 `make_chain` 里「拿到 override 之后构造 provider」那一段原样抽成函数（**纯搬运，不改逻辑**），并加账号级入口与角色回退表：

```python
# 账号级角色继承：建书对话与文风提取发生在还没有书的时刻，用户往往只配过少数几个角色。
# 与项目级 _ROLE_INHERIT 分开维护——那张表服务于生成管道，这张服务于建书前。
_USER_ROLE_FALLBACK = {
    "planner": ("writer", "extract"),
    "extract": ("planner", "writer"),
}


def _chain_from_override(role: str, override: dict, thinking: bool) -> FallbackChain:
    """override（一条路由配置）→ 可用的模型链。make_chain 与 make_user_chain 共用。

    原样搬自 make_chain 内联的那段：api_key 解密 → 协议/model 取用 → prices 表。
    """
    api_key = decrypt_api_key(override["api_key"]) if override.get("api_key") else None
    provider = _build_provider(
        override["protocol"], override["base_url"], api_key,
        thinking=thinking, role=role, model=override["model"],
    )
    return FallbackChain(provider, [override["model"]], providers=[provider],
                         thinking_enabled=thinking, prices=price_table(override))


def _lookup_user_override(role: str, packed: dict) -> dict | None:
    hit = _from_packed(role, packed)
    if hit is not None:
        return hit
    for inherited in _USER_ROLE_FALLBACK.get(role, ()):
        hit = _from_packed(inherited, packed)
        if hit is not None:
            return hit
    return None


def make_user_chain(role: str, user_id: str | uuid.UUID) -> FallbackChain:
    """账号级模型链：建书对话 / 文风提取这类「还没有书」的调用走它。

    与 make_chain 的差别只有起点：路由从 users.environment 里找（项目级覆盖此刻不存在），
    找不到就按 _USER_ROLE_FALLBACK 退一步，再没有就是 unconfigured。
    """
    from myink.environment import packed_models, thinking_enabled_for_user

    thinking = thinking_enabled_for_user(user_id)
    if default_provider is not _BUILTIN_PROVIDER:      # 测试桩：与 make_chain 同一条短路
        return FallbackChain(default_provider, ["stub"], thinking_enabled=thinking)
    override = _lookup_user_override(role, packed_models(user_id) or {})
    if override is None:
        return _no_model_chain(thinking)
    return _chain_from_override(role, override, thinking)
```

`make_chain` 里对应的内联段改成 `return _chain_from_override(role, override, thinking)`（其余分支不变）。`_build_provider` 若当前不存在，就是那段里实际用的构造调用——按现有代码原样命名，不要新造抽象。

`__all__` 加 `"make_user_chain"`。

- [ ] **Step 5: 跑测试**

Run: `python -m pytest tests/test_user_chain.py tests/test_environment_routes.py tests/test_short_plan.py -q`
Expected: PASS —— `test_user_chain.py` 4 passed；另两个文件全绿（证明 `_chain_from_override` 是纯搬运）

- [ ] **Step 6: 提交**

```bash
git add src/myink/providers/__init__.py tests/conftest.py tests/test_environment_routes.py tests/test_user_chain.py
git commit -m "feat: 账号级模型链 make_user_chain——建书前的调用有路由可走"
```

---

## Task 3: `agent_runs` 归属放宽（可无书、可有账号）

账号级调用要记账，但 `agent_runs.project_id` 是 NOT NULL。放宽它、加 `user_id`，把「至少有一个归属」的规则钉在 `record_run` 里。

**Files:**
- Modify: `src/myink/models/runs.py`
- Modify: `src/myink/db.py`
- Modify: `src/myink/cli.py`
- Modify: `src/myink/workflow/nodes.py`
- Test: `tests/test_run_ownership.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `AgentRun.project_id: uuid.UUID | None`、`AgentRun.user_id: uuid.UUID | None`
  - `ensure_agent_run_user()`（`db.py`）
  - `nodes.record_run(db, *, project_id=None, user_id=None, task_id=None, node, role, resp, error=None, detail=None, messages=None)`
  - `nodes.record_plain(db, *, project_id=None, user_id=None, task_id=None, node, detail=None, duration_ms=0)`
  - `nodes._owner_ids(*, project_id, user_id) -> tuple[uuid.UUID | None, uuid.UUID | None]`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_run_ownership.py`：

```python
"""记账归属：每条 agent_runs 至少属于一本书或一个账号。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete as sa_delete, select

from myink.db import new_session
from myink.models import AgentRun, User
from myink.providers.base import ModelResponse
from myink.workflow import nodes


def _resp() -> ModelResponse:
    return ModelResponse(content="{}", model_id="m", input_tokens=1, output_tokens=2,
                         cost_est=0.01, duration_ms=5)


def test_record_run_accepts_account_only_ownership():
    with new_session() as db:
        user = User(username=f"own-{uuid.uuid4().hex[:8]}")
        db.add(user)
        db.commit()
        uid = user.id
    try:
        with new_session() as db:
            nodes.record_run(db, user_id=uid, node="short_creation", role="Planner", resp=_resp())
            db.commit()
        with new_session() as db:
            row = db.scalar(select(AgentRun).where(AgentRun.user_id == uid))
            assert row is not None
            assert row.project_id is None
            assert row.node == "short_creation"
    finally:
        with new_session() as db:
            db.execute(sa_delete(AgentRun).where(AgentRun.user_id == uid))
            db.execute(sa_delete(User).where(User.id == uid))
            db.commit()


def test_record_run_refuses_a_row_with_no_owner():
    with new_session() as db:
        with pytest.raises(ValueError, match="记账不能没有归属"):
            nodes.record_run(db, node="short_creation", role="Planner", resp=_resp())


def test_owner_ids_normalizes_both_forms():
    pid, uid = nodes._owner_ids(project_id=None, user_id=uuid.uuid4())
    assert pid is None and isinstance(uid, uuid.UUID)
```

**先确认 `ModelResponse` 的真实字段名**：`grep -n "class ModelResponse" -A 20 src/myink/providers/base.py`，按实际字段改 `_resp()`（`duration_ms` 若不在构造参数里就去掉）。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_run_ownership.py -q`
Expected: FAIL —— `TypeError: record_run() got an unexpected keyword argument 'user_id'`

- [ ] **Step 3: 模型与迁移**

`src/myink/models/runs.py` 的 `AgentRun`：

```python
    # 可空：账号级调用（建书对话、文风提取）此刻还没有书；账号归属落在 user_id 上。
    # 两者至少有一个——由 workflow.nodes.record_run 统一把守（建表约束替不了跨行语义）。
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
```

`src/myink/db.py` 新增（放在 `ensure_user_environment` 附近，写法照抄它们）：

```python
def ensure_agent_run_user() -> None:
    """agent_runs 归属放宽：project_id 可空 + 新增 user_id（账号级调用记账用）。

    纯 DDL、不回填：老行本来就有 project_id，回填 user_id 要按 project→owner 猜，
    猜错就是把别人的花费记到别人头上。查询口径用 OR 同时认两条路。
    """
    with get_admin_engine().begin() as conn:
        conn.execute(text("ALTER TABLE agent_runs ALTER COLUMN project_id DROP NOT NULL"))
        conn.execute(text("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS user_id UUID"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_user_id ON agent_runs (user_id)"))
```

`src/myink/cli.py` 的 `init`：在 `ensure_user_environment()` 之后加 `ensure_agent_run_user()`。

- [ ] **Step 4: `nodes` 接 `user_id`**

`src/myink/workflow/nodes.py`：

```python
def _owner_ids(*, project_id: str | None, user_id) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """记账的归属：至少要有一个。

    放在这里而不是 DB 约束里，是因为「账号级调用是合法的」这件事是业务规则，
    表约束只能写 NOT NULL project_id（那会直接封死账号级记账）。
    """
    pid = uuid.UUID(str(project_id)) if project_id else None
    uid = None if user_id is None else (
        user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id)))
    if pid is None and uid is None:
        raise ValueError("record_run 需要 project_id 或 user_id（记账不能没有归属）")
    return pid, uid
```

`record_run` 签名改成 `def record_run(db, *, project_id: str | None = None, user_id=None, task_id, node, role, resp, error=None, detail=None, messages=None)`，函数体里 `AgentRun(project_id=uuid.UUID(project_id), ...)` 换成：

```python
    pid, uid = _owner_ids(project_id=project_id, user_id=user_id)
    db.add(AgentRun(project_id=pid, user_id=uid, task_id=task_id, node=node, role=role, ...))
```

`record_plain` 同样加 `user_id=None` 与 `_owner_ids`。

- [ ] **Step 5: 跑测试**

Run: `python -m myink.cli init && python -m pytest tests/test_run_ownership.py -q`
Expected: PASS 3 passed

- [ ] **Step 6: 跑全套后端测试，确认没有既有调用点被打破**

Run: `python -m pytest tests/ -q`
Expected: 全绿（`project_id` 由位置参数变关键字默认值，既有调用点都写的是 `project_id=`，不受影响）。若有失败逐个查明原因，不要靠改测试绕过。

- [ ] **Step 7: 提交**

```bash
git add src/myink/models/runs.py src/myink/db.py src/myink/cli.py src/myink/workflow/nodes.py tests/test_run_ownership.py
git commit -m "feat: 运行记录可归属到账号——没有书的调用也能记账"
```

---

## Task 4: 文风提取走账号级记账

`extract_style_profile` 现在强制要 `project_id`，因为它被项目上的风格端点调用。文风库要能脱离任何作品提取。

**Files:**
- Modify: `src/myink/style_extract.py:93-120`
- Test: `tests/test_style_profile.py`（追加一条）

**Interfaces:**
- Consumes: `nodes.record_run(user_id=...)`（Task 3）、`make_user_chain`（Task 2）
- Produces: `extract_style_profile(samples, stats, *, project_id=None, user_id=None, db=None) -> tuple[dict, str | None]`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_style_profile.py`：

```python
def test_extract_style_profile_records_an_account_level_run(temp_user, chain_stub):
    """没有 project_id、只有 user_id 时也要能提取并记账（建书时的文风导入走这条路）。"""
    with new_session() as db:
        profile, err = extract_style_profile(
            [_SAMPLE_1], analyze_sample_stats([_SAMPLE_1]), user_id=temp_user, db=db)
        db.commit()
        assert err is None and isinstance(profile, dict)
        row = db.scalar(select(AgentRun).where(AgentRun.user_id == uuid.UUID(temp_user)))
    assert row is not None and row.project_id is None and row.node == "style_extract"


def test_extract_style_profile_without_any_owner_still_extracts():
    """不记账的纯提取（既有用法）不能被归属检查误伤。"""
    profile, err = extract_style_profile([_SAMPLE_1], analyze_sample_stats([_SAMPLE_1]))
    assert isinstance(profile, dict)
```

按该文件现有导入补齐 `new_session`/`AgentRun`/`uuid`/`select`。`chain_stub` 若该文件没有，就照 `tests/test_short_plan.py` 的同名 fixture 形态在本文件里加一个（它 monkeypatch `providers_mod.default_provider`，让 `make_user_chain` 短路到桩）。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_style_profile.py -q -k account_level`
Expected: FAIL —— `TypeError: extract_style_profile() got an unexpected keyword argument 'user_id'`

- [ ] **Step 3: 实现**

`src/myink/style_extract.py`：

```python
def extract_style_profile(samples: list[str], stats: dict, *,
                          project_id: str | None = None, user_id=None,
                          db=None) -> tuple[dict, str | None]:
```

函数体里：`make_chain("extract", db=db, project_id=project_id)` → `make_user_chain("extract", user_id)`（**有 project_id 时走 make_chain，只给了 user_id 时走 make_user_chain**，两者选一的判别写在一处），并删掉现有的

```python
            raise ValueError("db 非 None 时必须提供 project_id（agent_runs 归属）")
```

那三行守卫，改成

```python
            nodes.record_run(db, project_id=project_id, user_id=user_id, task_id=None,
                             node="style_extract", role="StyleExtract", resp=resp,
                             error=resp.error, messages=messages,
                             detail={"n_samples": len(samples)})
```

`_owner_ids` 会把「两个都没有」的情况顶回去——守卫只剩一处，不会两处说法不一致。

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_style_profile.py -q`
Expected: PASS（新两条 + 既有全绿）

- [ ] **Step 5: 提交**

```bash
git add src/myink/style_extract.py tests/test_style_profile.py
git commit -m "feat: 文风提取可脱离作品——建书时导入文章也能提取"
```

---

## Task 5: 文风库四端点

**Files:**
- Create: `src/myink/api/routes_style_library.py`
- Modify: `src/myink/api/schemas.py`
- Modify: `src/myink/api/main.py`
- Test: `tests/test_style_library.py`（追加）

**Interfaces:**
- Consumes: `StyleLibraryItem`（Task 1）、`extract_style_profile(..., user_id=..., db=...)`（Task 4）、`analyze_sample_stats`、`merge_style_draft`、`validate_profile`、`require_user`
- Produces: 四条路由
  - `GET /api/v1/style-library` → `{"items": [{id, name, profile, sample_chars, created_at}]}`
  - `POST /api/v1/style-library/samples` body `{"samples": [str]}` → `{"draft": {...}}`
  - `POST /api/v1/style-library` body `{"name": str, "profile": dict, "sample_chars": int}` → 上面 item 的形状
  - `DELETE /api/v1/style-library/{item_id}` → `{"ok": true}`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_style_library.py`（用 Task 2 提到 conftest 的 `temp_user`）：

```python
def _headers(user: str) -> dict[str, str]:
    return identity_headers(user)


def test_style_library_crud_is_scoped_to_the_owner(temp_user):
    other = ...  # 再造一个 temp_user 风格的账号，或用 uuid 随机的第二个 User，见下
```

写成下面这份具体版本（两个账号，验隔离）：

```python
def test_style_library_crud_is_scoped_to_the_owner(temp_user):
    with new_session() as db:
        other = User(username=f"style-{uuid.uuid4().hex[:8]}")
        db.add(other)
        db.commit()
        other_id = other.id
    try:
        created = client.post("/api/v1/style-library",
                              json={"name": "渡口冷白描", "profile": {"pov": "限知"}, "sample_chars": 1200},
                              headers=_headers(temp_user))
        assert created.status_code == 200, created.text
        item_id = created.json()["id"]

        assert client.get("/api/v1/style-library", headers=_headers(other_id)).json()["items"] == []
        assert client.get("/api/v1/style-library", headers=_headers(temp_user)).json()["items"][0]["name"] == "渡口冷白描"

        # 删别人的：不能删掉，也不能借 404 反推 id 存在
        assert client.delete(f"/api/v1/style-library/{item_id}", headers=_headers(other_id)).status_code == 404
        assert client.delete(f"/api/v1/style-library/{item_id}", headers=_headers(temp_user)).status_code == 200
        assert client.get("/api/v1/style-library", headers=_headers(temp_user)).json()["items"] == []
    finally:
        with new_session() as db:
            db.execute(sa_delete(StyleLibraryItem).where(StyleLibraryItem.user_id == other_id))
            db.execute(sa_delete(User).where(User.id == other_id))
            db.commit()


def test_style_library_extract_needs_at_least_one_sample(temp_user):
    resp = client.post("/api/v1/style-library/samples", json={"samples": []},
                       headers=_headers(temp_user))
    assert resp.status_code == 400


def test_style_library_save_rejects_a_blank_name(temp_user):
    resp = client.post("/api/v1/style-library", json={"name": "   ", "profile": {}, "sample_chars": 0},
                       headers=_headers(temp_user))
    assert resp.status_code == 400
```

`client` 用该仓库现有的测试客户端 fixture（`grep -n "^def client\|TestClient" tests/conftest.py tests/test_admin.py` 找现成的那个，照用，不要新造）。`identity_headers(user)` 来自 conftest。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_style_library.py -q`
Expected: FAIL —— 404（路由还不存在）

- [ ] **Step 3: 实现**

`src/myink/api/schemas.py` 追加：

```python
class StyleLibraryItemOut(BaseModel):
    id: UUID
    name: str
    profile: dict
    sample_chars: int
    created_at: datetime


class StyleLibraryOut(BaseModel):
    items: list[StyleLibraryItemOut]


class StyleLibrarySaveBody(BaseModel):
    name: str = Field(max_length=64)
    profile: dict
    sample_chars: int = Field(default=0, ge=0)


class StyleSampleBody(BaseModel):
    samples: list[str] = Field(default_factory=list)
```

（`StyleDraftOut` 已存在，样例端点复用它。）

新建 `src/myink/api/routes_style_library.py`：

```python
"""账号级文风库：导入文章 → 提取文风 → 命名保存 → 建书时选一次。

与项目上的 `/projects/{pid}/style-samples` 的分工：那条是「给这本书导一份参考文风」，
这条是「把文风留成我自己的资产」，后者不依赖任何作品，所以走 make_user_chain 记账。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from myink.api.auth import require_user
from myink.api.schemas import (OkOut, StyleDraftOut, StyleLibraryItemOut, StyleLibraryOut,
                               StyleLibrarySaveBody, StyleSampleBody)
from myink.db import new_session
from myink.models import StyleLibraryItem
from myink.style_extract import (analyze_sample_stats, extract_style_profile,
                                 merge_style_draft, validate_profile)

router = APIRouter(prefix="/api/v1/style-library", tags=["style-library"])

_MAX_SAMPLES = 3
_MAX_TOTAL_CHARS = 20_000


def _items(db, uid: uuid.UUID) -> list[StyleLibraryItem]:
    return list(db.scalars(
        select(StyleLibraryItem).where(StyleLibraryItem.user_id == uid)
        .order_by(StyleLibraryItem.created_at.desc(), StyleLibraryItem.id)))


def _item_out(item: StyleLibraryItem) -> dict:
    return {"id": str(item.id), "name": item.name, "profile": item.profile,
            "sample_chars": item.sample_chars, "created_at": item.created_at}


@router.get("", response_model=StyleLibraryOut)
def list_items(user_id: str = Depends(require_user)) -> dict:
    with new_session() as db:
        return {"items": [_item_out(item) for item in _items(db, uuid.UUID(user_id))]}


@router.post("/samples", response_model=StyleDraftOut)
def extract_samples(body: StyleSampleBody, user_id: str = Depends(require_user)) -> dict:
    """导入的文章 → 一份可编辑的文风草稿（不落库，用户看过、改了名再保存）。

    返回 `{"draft": ...}`：merge_style_draft 已把统计与提取失败并进同一份 draft。
    """
    samples = [s.strip() for s in body.samples if s and s.strip()]
    if not samples:
        raise HTTPException(status_code=400, detail="至少要有一段文章")
    if len(samples) > _MAX_SAMPLES:
        raise HTTPException(status_code=400, detail=f"最多 {_MAX_SAMPLES} 段")
    if sum(len(s) for s in samples) > _MAX_TOTAL_CHARS:
        raise HTTPException(status_code=400, detail=f"合计不能超过 {_MAX_TOTAL_CHARS} 字")
    uid = uuid.UUID(user_id)
    stats = analyze_sample_stats(samples)
    db = new_session()
    try:
        profile, extract_error = extract_style_profile(samples, stats, user_id=uid, db=db)
        db.commit()
    finally:
        db.close()
    return {"draft": merge_style_draft(stats, profile, extract_error=extract_error)}


@router.post("", response_model=StyleLibraryItemOut)
def save_item(body: StyleLibrarySaveBody, user_id: str = Depends(require_user)) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="文风名不能为空")
    uid = uuid.UUID(user_id)
    with new_session() as db:
        item = StyleLibraryItem(user_id=uid, name=name,
                                profile=validate_profile(body.profile or {}),
                                sample_chars=body.sample_chars)
        db.add(item)
        db.commit()
        return _item_out(item)


@router.delete("/{item_id}", response_model=OkOut)
def delete_item(item_id: str, user_id: str = Depends(require_user)) -> dict:
    uid = uuid.UUID(user_id)
    try:
        target = uuid.UUID(item_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    with new_session() as db:
        item = db.scalar(select(StyleLibraryItem).where(
            StyleLibraryItem.id == target, StyleLibraryItem.user_id == uid))
        if item is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        db.delete(item)
        db.commit()
    return {"ok": True}
```

`src/myink/api/main.py`：`from myink.api.routes_style_library import router as style_library_router`，在 `include_router(style_router)` 之后加 `app.include_router(style_library_router)`。

**注意 `validate_profile` 的行为**：`grep -n "def validate_profile" -A 20 src/myink/style_extract.py` 确认它是归一化（补齐缺失字段）而不是校验抛错。若它会为缺失字段抛错，则保存一份用户手改过的 draft 会 422——那就在保存时先与 `merge_style_draft` 的默认形状合并再 validate。**这条是执行前必须先看清的**，不要凭猜。

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_style_library.py -q`
Expected: PASS（含 Task 1 的两条）

- [ ] **Step 5: 提交**

```bash
git add src/myink/api/routes_style_library.py src/myink/api/schemas.py src/myink/api/main.py tests/test_style_library.py
git commit -m "feat: 文风库端点——列/提取/保存/删，都在自己名下"
```

---

## Task 6: 前端文风库调用层

**Files:**
- Create: `web/src/lib/styleLibraryApi.ts`
- Test: `web/src/lib/styleLibraryApi.test.ts`

**Interfaces:**
- Consumes: `authenticatedGet(path, token, signal?)`、`authenticatedSend(method, path, token, body?, signal?)`（`./api`
- Produces: `styleLibraryApi`（Task 14 的建书页用它装文风选择器）

- [ ] **Step 1: 写失败测试**

新建 `web/src/lib/styleLibraryApi.test.ts`（照 `web/src/lib/adminApi.test.ts` 的 mock 形态：mock `./api` 的 `authenticatedGet`/`authenticatedSend`，断言路径与方法）：

```ts
import { beforeEach, expect, it, vi } from 'vitest'
import { authenticatedGet, authenticatedSend } from './api'
import { styleLibraryApi } from './styleLibraryApi'

vi.mock('./api', () => ({
  authenticatedGet: vi.fn(),
  authenticatedSend: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(authenticatedGet).mockReset()
  vi.mocked(authenticatedSend).mockReset()
})

it('lists the library from the owner-scoped endpoint', async () => {
  vi.mocked(authenticatedGet).mockResolvedValue({ items: [] })
  await expect(styleLibraryApi.list('t')).resolves.toEqual({ items: [] })
  expect(authenticatedGet).toHaveBeenCalledWith('/api/v1/style-library', 't', undefined)
})

it('extracts samples without saving anything', async () => {
  vi.mocked(authenticatedSend).mockResolvedValue({ draft: {} })
  await styleLibraryApi.extract('t', ['正文一段'])
  expect(authenticatedSend).toHaveBeenCalledWith(
    'POST', '/api/v1/style-library/samples', 't', { samples: ['正文一段'] }, undefined)
})

it('saves a named item and deletes by id', async () => {
  vi.mocked(authenticatedSend).mockResolvedValue({ ok: true })
  await styleLibraryApi.save('t', { name: '渡口', profile: {}, sample_chars: 10 })
  expect(authenticatedSend).toHaveBeenCalledWith(
    'POST', '/api/v1/style-library', 't', { name: '渡口', profile: {}, sample_chars: 10 }, undefined)
  await styleLibraryApi.remove('t', 'item-1')
  expect(authenticatedSend).toHaveBeenCalledWith(
    'DELETE', '/api/v1/style-library/item-1', 't', undefined, undefined)
})
```

- [ ] **Step 2: 跑测试确认失败**

Run（在 `web/` 下）: `npm test -- src/lib/styleLibraryApi.test.ts`
Expected: FAIL —— 模块不存在

- [ ] **Step 3: 实现**

新建 `web/src/lib/styleLibraryApi.ts`：

```ts
/** 账号级文风库：导入文章提取文风 → 命名保存 → 建书时选一次。
 *
 * 认证与账号切换中止复用 lib/api 的同一套语义（与 adminApi 同款）。
 */
import { authenticatedGet, authenticatedSend } from './api'

export interface StyleLibraryItem {
  id: string
  name: string
  profile: Record<string, unknown>
  sample_chars: number
  created_at: string
}

export interface StyleDraft {
  draft: Record<string, unknown>
}

export const styleLibraryApi = {
  list: (token: string, signal?: AbortSignal): Promise<{ items: StyleLibraryItem[] }> =>
    authenticatedGet('/api/v1/style-library', token, signal),

  extract: (token: string, samples: string[], signal?: AbortSignal): Promise<StyleDraft> =>
    authenticatedSend('POST', '/api/v1/style-library/samples', token, { samples }, signal),

  save: (token: string, body: { name: string; profile: Record<string, unknown>; sample_chars: number },
         signal?: AbortSignal): Promise<StyleLibraryItem> =>
    authenticatedSend('POST', '/api/v1/style-library', token, body, signal),

  remove: (token: string, itemId: string, signal?: AbortSignal): Promise<{ ok: boolean }> =>
    authenticatedSend('DELETE', `/api/v1/style-library/${itemId}`, token, undefined, signal),
}
```

- [ ] **Step 4: 跑测试与类型闸**

Run: `npm test -- src/lib/styleLibraryApi.test.ts && npm run build`
Expected: PASS；`build` 通过

- [ ] **Step 5: 提交**

```bash
git add web/src/lib/styleLibraryApi.ts web/src/lib/styleLibraryApi.test.ts
git commit -m "feat: 前端文风库调用层"
```

---

# 一期 B：对话式短篇建书

## Task 7: 方案卡的纯逻辑

**Files:**
- Create: `src/myink/short/creation.py`
- Test: `tests/test_short_creation.py`

**Interfaces:**
- Consumes: 无
- Produces（后续 Task 10/11/13 全用这些名字）：
  - `REQUIRED_CARD_FIELDS: tuple[str, ...]`（7 个文本字段）
  - `DEFAULT_CHAPTER_COUNT = 5`、`DEFAULT_CHARS_PER_CHAPTER = 4000`
  - `ShortCreationCard`（pydantic，9 个字段）
  - `default_card() -> dict`
  - `card_patch(raw) -> dict`（模型给的：只收已知字段、只留非空）
  - `card_normalize(raw) -> dict`（用户改的：只收已知字段、**保留空串**）
  - `merge_model_card(current, raw) -> dict`、`merge_user_card(current, edited) -> dict`
  - `card_ready(card) -> bool`、`card_premise(card) -> str`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_short_creation.py`：

```python
"""对话式短篇建书：先是纯逻辑（卡合并/就绪判定/premise），端点在后几个任务补。"""

from __future__ import annotations

from myink.short import creation


def test_card_patch_drops_blanks_so_the_model_cannot_erase_user_edits():
    """模型这轮没把握的字段会留空串——那是「没有新信息」，不是「清空」。"""
    assert creation.card_patch({"working_title": "  ", "genre": "悬疑", "nonsense": "x"}) == {"genre": "悬疑"}


def test_merge_model_card_keeps_the_users_value_when_the_model_sends_blank():
    current = creation.default_card() | {"working_title": "最后一班渡船"}
    merged = creation.merge_model_card(current, {"working_title": "  ", "genre": "悬疑"})
    assert merged["working_title"] == "最后一班渡船"
    assert merged["genre"] == "悬疑"


def test_merge_user_card_honors_a_deliberate_clear():
    """用户在右栏把字段删空是本人的决定，与模型留空不一样。"""
    current = creation.default_card() | {"direction": "一句话方向"}
    assert creation.merge_user_card(current, {"direction": ""})["direction"] == ""


def test_card_normalize_keeps_numbers_and_drops_unknown_keys():
    assert creation.card_normalize({"chapter_count": 8, "junk": 1}) == {"chapter_count": 8}


def test_card_ready_needs_all_seven_text_fields():
    fields = creation.REQUIRED_CARD_FIELDS
    assert len(fields) == 7
    card = {field: "填好了" for field in fields} | {"chapter_count": 5, "chars_per_chapter": 4000}
    assert creation.card_ready(card) is True
    for field in fields:
        assert creation.card_ready(card | {field: "   "}) is False


def test_default_card_carries_the_short_form_defaults():
    card = creation.default_card()
    assert card["chapter_count"] == creation.DEFAULT_CHAPTER_COUNT == 5
    assert card["chars_per_chapter"] == creation.DEFAULT_CHARS_PER_CHAPTER == 4000
    assert creation.card_ready(card) is False


def test_card_premise_feeds_the_plan_generator_one_string():
    premise = creation.card_premise(creation.default_card() | {
        "direction": "一句话方向", "conflict_core": "核心冲突", "plot_sketch": "大致情节"})
    assert premise == "一句话方向\n\n核心冲突：核心冲突\n\n大致情节：大致情节"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_short_creation.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'myink.short.creation'`

- [ ] **Step 3: 实现**

新建 `src/myink/short/creation.py`：

```python
"""对话式短篇建书的纯逻辑：方案卡、合并规则、就绪判定、premise 拼装。

与 `short/form.py` 的分工：那边管篇幅护栏（章数/每章字数，后端最终按它归一），
这边管「聊出来的那张卡」。这里没有 I/O，LLM 那一回合在 `book_setup` 里。
"""

from __future__ import annotations

from pydantic import BaseModel

# 凑齐这 7 个才允许「确认，开写」。后端自算，不信模型自报 ready——
# 模型很容易在只聊了两句时说「这就够了」，而短篇方案缺了冲突或回报就是一堆空话。
REQUIRED_CARD_FIELDS = (
    "working_title", "genre", "direction", "protagonist_pressure",
    "conflict_core", "emotional_payoff", "plot_sketch",
)

DEFAULT_CHAPTER_COUNT = 5
# 5 × 4000 = 20000，正好是 SHORT_TOTAL_MAX（short/form.py）——默认值不触发压缩。
DEFAULT_CHARS_PER_CHAPTER = 4000

_NUMBER_FIELDS = ("chapter_count", "chars_per_chapter")


class ShortCreationCard(BaseModel):
    """方案卡：模型提案与用户可编辑的**同一份数据**（右栏就是它的可编辑视图）。"""

    working_title: str = ""
    genre: str = ""
    direction: str = ""
    protagonist_pressure: str = ""
    conflict_core: str = ""
    emotional_payoff: str = ""
    plot_sketch: str = ""
    chapter_count: int = DEFAULT_CHAPTER_COUNT
    chars_per_chapter: int = DEFAULT_CHARS_PER_CHAPTER


def default_card() -> dict:
    return ShortCreationCard().model_dump()


def _known(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for key, value in raw.items():
        if key not in ShortCreationCard.model_fields:
            continue
        if isinstance(value, bool):          # bool 是 int 的子类，先挡掉
            continue
        if isinstance(value, str):
            out[key] = value.strip()
        elif isinstance(value, (int, float)):
            out[key] = int(value)
    return out


def card_patch(raw) -> dict:
    """模型这轮给的卡：只收已知字段，且**空串不留**。

    留空是不留痕的意思——「这轮我没新想法」。若把空串也当值写进去，模型一轮走神就能把
    用户手写好的一段抹掉。
    """
    return {key: value for key, value in _known(raw).items()
            if not (isinstance(value, str) and value == "")}


def card_normalize(raw) -> dict:
    """用户改过的卡：只收已知字段，**空串照收**——用户有权把一个字段清空。

    与 `card_patch` 的唯一差别就是这一条。
    """
    return _known(raw)


def merge_model_card(current: dict, raw) -> dict:
    return {**(current or {}), **card_patch(raw)}


def merge_user_card(current: dict, edited) -> dict:
    return {**(current or {}), **card_normalize(edited)}


def card_ready(card: dict) -> bool:
    return all(str((card or {}).get(field) or "").strip() for field in REQUIRED_CARD_FIELDS)


def card_premise(card: dict) -> str:
    """拼成 `premise` 一段——方案生成器只吃一个字符串（`generate_short_plan` 的入参）。"""
    card = card or {}
    parts = [str(card.get("direction") or "").strip()]
    for label, key in (("核心冲突", "conflict_core"), ("大致情节", "plot_sketch")):
        value = str(card.get(key) or "").strip()
        if value:
            parts.append(f"{label}：{value}")
    return "\n\n".join(part for part in parts if part)
```

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_short_creation.py -q`
Expected: PASS 7 passed

- [ ] **Step 5: 提交**

```bash
git add src/myink/short/creation.py tests/test_short_creation.py
git commit -m "feat: 方案卡纯逻辑——只覆盖非空的合并规则与就绪判定"
```

---

## Task 8: 建书会话两表

**Files:**
- Modify: `src/myink/models/creation.py`
- Modify: `src/myink/models/__init__.py`、`src/myink/cli.py`
- Modify: `tests/conftest.py`（`temp_user` 的清理补上会话两行）
- Test: `tests/test_short_creation.py`（追加）

**Interfaces:**
- Consumes: `StyleLibraryItem` 所在的 `models/creation.py`（Task 1）
- Produces:
  - `ShortCreationSession`（表 `short_creation_sessions`；`user_id` 唯一、`status`、`card`、`book_id`、`style_item_id`、`style_name`）
  - `ShortCreationMessage`（表 `short_creation_messages`；自增 int `id`、`session_id`、`role`、`content`、`card`、`model_id`、`input_tokens`、`output_tokens`、`cost_est`、`error`）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_short_creation.py`：

```python
def test_session_is_one_per_user_and_messages_are_ordered(temp_user):
    with new_session() as db:
        session = ShortCreationSession(user_id=uuid.UUID(temp_user), status="active",
                                       card=creation.default_card())
        db.add(session)
        db.commit()
        db.add_all([
            ShortCreationMessage(session_id=session.id, role="assistant", content="开场白"),
            ShortCreationMessage(session_id=session.id, role="user", content="我想写渡口"),
        ])
        db.commit()
        rows = db.scalars(select(ShortCreationMessage)
                          .where(ShortCreationMessage.session_id == session.id)
                          .order_by(ShortCreationMessage.id)).all()
    assert [row.content for row in rows] == ["开场白", "我想写渡口"]
    assert rows[0].id < rows[1].id


def test_session_tables_have_no_project_id_column():
    """同 StyleLibraryItem：带上 project_id 就会被套上租户策略。"""
    assert "project_id" not in ShortCreationSession.__table__.columns
    assert "project_id" not in ShortCreationMessage.__table__.columns


def test_session_user_id_is_unique():
    from sqlalchemy.exc import IntegrityError
    with new_session() as db:
        db.add(ShortCreationSession(user_id=uuid.UUID(temp_user), status="active", card={}))
        db.commit()
        db.add(ShortCreationSession(user_id=uuid.UUID(temp_user), status="active", card={}))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
```

（本文件的导入改为 `from myink.db import new_session`、`from myink.models import ShortCreationMessage, ShortCreationSession`、`import pytest`、`from sqlalchemy import select`、`import uuid`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m myink.cli init && python -m pytest tests/test_short_creation.py -q`
Expected: FAIL —— `ImportError: cannot import name 'ShortCreationSession'`

- [ ] **Step 3: 实现**

`src/myink/models/creation.py` 追加（顶部导入补 `Index`、`Text`；`TimestampMixin` 已导入）：

```python
class ShortCreationSession(Base, UUIDPkMixin, TimestampMixin):
    """每用户一条建书会话（一期不做多会话）。确认开写后 status='committed'。

    `book_id` 记下已建成的书：commit 重试时复用它，不会建出第二本（也没有 request_id 可依，
    这条会话本身就是幂等键）。不建外键——会话要能在书被删掉之后留档。
    """

    __tablename__ = "short_creation_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    card: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    book_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    style_item_id: Mapped[str | None] = mapped_column(
        String(48), comment="builtin:<preset id> 或 style_library_items.id")
    style_name: Mapped[str | None] = mapped_column(String(64))


class ShortCreationMessage(Base, TimestampMixin):
    """会话消息流。自增 id：对话很短，顺序读即可，不需要 UUID。

    token 与花费逐条记下来，是为了让「这次建书花了多少」在会话里就看得见——
    agent_runs 里也有，但那是给管理面板的；这里的数字是给用户看的。
    """

    __tablename__ = "short_creation_messages"
    __table_args__ = (Index("ix_short_creation_messages_session", "session_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    card: Mapped[dict | None] = mapped_column(JSON)
    model_id: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_est: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error: Mapped[str | None] = mapped_column(String(512))
```

（`Float` 也要加进导入。）

`models/__init__.py`：导入与 `__all__` 补 `ShortCreationMessage, ShortCreationSession`。

`cli.py` 的 `init`：两个新表由 `Base.metadata.create_all` 建出，**不需要新的 `ensure_*`**（ensure 只用于给老库补列）。这里不用改 cli——除非 `init` 里有一处显式的表清单，那就把它补上（`grep -n "create_all" -A 6 src/myink/cli.py` 确认）。

`tests/conftest.py` 的 `temp_user` 清理补上会话两行（见 Task 2 的完整版本），并补 `ShortCreationMessage, ShortCreationSession` 到 imports。

- [ ] **Step 4: 跑测试**

Run: `python -m myink.cli init && python -m pytest tests/test_short_creation.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/myink/models/creation.py src/myink/models/__init__.py tests/conftest.py tests/test_short_creation.py
git commit -m "feat: 建书会话表——一个用户一条会话，消息逐条留痕"
```

---

## Task 9: 建书对话提示词

**Files:**
- Modify: `src/myink/workflow/prompts.py`
- Modify: `src/myink/workflow/nodes.py`（`_MAX_TOKENS`）
- Test: `tests/test_short_creation.py`（追加）

**Interfaces:**
- Consumes: 无
- Produces: `prompts.SYSTEM_SHORT_CREATION: str`、`prompts.short_creation_messages(history, card) -> list[dict]`、`nodes._MAX_TOKENS["short_creation"] == 1500`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_short_creation.py`：

```python
def test_short_creation_messages_carry_history_then_the_current_card():
    messages = prompts.short_creation_messages(
        [{"role": "user", "content": "我想写个渡口的故事"},
         {"role": "assistant", "content": "主角的压力是什么？"}],
        {"working_title": "最后一班渡船", "chapter_count": 5})
    assert messages[0]["content"] == prompts.SYSTEM_SHORT_CREATION
    assert [m["role"] for m in messages[1:3]] == ["user", "assistant"]
    assert '"最后一班渡船"' in messages[-1]["content"]
    assert '"chapter_count": 5' in messages[-1]["content"]


def test_short_creation_prompt_imposes_the_product_rules():
    system = prompts.SYSTEM_SHORT_CREATION
    assert "只问一个" in system            # 一次抛三个问题，用户只会答第一个
    assert "立刻出卡" in system            # 冲突一明确就别再追问细节
    assert "确认，开写" in system          # 不许模型自己宣布已经建书/开写
    assert "留空" in system                # 空串 = 没有新信息，不是清空


def test_short_creation_turn_budget_is_smaller_than_a_plan():
    """一回合只是一段话 + 一张卡，给 1500 token 足够；给大了会鼓励它写小说。"""
    assert nodes._MAX_TOKENS["short_creation"] == 1500
    assert nodes._MAX_TOKENS["short_creation"] < nodes._MAX_TOKENS["short_plan"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_short_creation.py -q -k prompt or turn_budget`
Expected: FAIL —— `AttributeError: module 'myink.workflow.prompts' has no attribute 'SYSTEM_SHORT_CREATION'`

- [ ] **Step 3: 实现**

`src/myink/workflow/prompts.py` 追加（放在 `short_plan_messages` 附近；顶部已有 `json` 导入则复用，没有就加）：

```python
SYSTEM_SHORT_CREATION = """你是中文短篇创作系统的【建书助手】。用户想写一篇短篇小说，你的任务是通过对话把这件事聊清楚，然后给出一张方案卡。

要弄清楚的七件事：题材 / 方向 / 主角压力 / 核心冲突 / 情绪回报 / 大致情节 / 暂定名。

规则：
1. 一回合**只问一个**最关键的问题。一次抛三个问题，用户只会回答第一个。
2. 核心冲突与主角压力一明确就**立刻出卡**，不要继续追问细节——用户随时可以在卡上改，也可以直接点「确认，开写」。
3. 暂定名缺失就自己拟一个（2–8 字），并在 reply 里说明可以改。
4. 不要承诺「已经建好书」或「已经开始写了」：建书由用户点「确认，开写」触发，不由你宣布。
5. 用户没提章数与每章字数就放默认值（5 章 / 每章 4000 字）。
6. 用中文，别用 markdown 表格——前端是聊天气泡，不是文档。

输出严格 JSON：
{"reply": "对用户说的一句话（提问，或说明你为什么这么定）",
 "card": {"working_title": "", "genre": "", "direction": "一句话方向/卖点",
          "protagonist_pressure": "", "conflict_core": "", "emotional_payoff": "",
          "plot_sketch": "大致情节", "chapter_count": 5, "chars_per_chapter": 4000}}

card 里你**没有把握的字段留空**：留空表示「这轮没有新信息」，系统会保留用户已经写好的值；填了就会覆盖掉它。"""


def short_creation_messages(history: list[dict], card: dict) -> list[dict]:
    """建书对话输入：完整历史 + 当前卡。

    卡必须每轮都带上——用户可能刚在右栏改过，模型看不见就会以为自己上一轮说的还算数。
    """
    conversation = [{"role": m["role"], "content": m["content"]}
                    for m in history if (m.get("content") or "").strip()]
    return [
        {"role": "system", "content": SYSTEM_SHORT_CREATION},
        *conversation,
        {"role": "user", "content":
            "【当前方案卡（用户可能已编辑过）】\n"
            + json.dumps(card, ensure_ascii=False, indent=2)
            + "\n\n请继续：能出卡就出卡，还差关键信息就只问那一个问题。只输出 JSON。"},
    ]
```

`src/myink/workflow/nodes.py` 的 `_MAX_TOKENS` 字典加一行：

```python
    "short_creation": 1500,
```

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_short_creation.py -q`
Expected: PASS（含前面两个任务的用例）

- [ ] **Step 5: 提交**

```bash
git add src/myink/workflow/prompts.py src/myink/workflow/nodes.py tests/test_short_creation.py
git commit -m "feat: 建书对话提示词——一回合一个问题的客服式助手"
```

---

## Task 10: 建书对话一回合

**Files:**
- Modify: `src/myink/book_setup.py`
- Test: `tests/test_short_creation.py`（追加）

**Interfaces:**
- Consumes: `make_user_chain(role, user_id)`（Task 2）、`nodes.record_run(user_id=...)`（Task 3）、`nodes._parse_json`、`prompts.short_creation_messages`、`creation.card_patch`（Task 7）
- Produces: `book_setup.generate_short_creation_turn(history, card, *, user_id, db=None) -> tuple[str, dict, str | None]` 返回 `(reply, card_patch, error)`——**永不抛异常**

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_short_creation.py`（这个文件要拿到 `chain_stub`：照 `tests/test_short_plan.py` 的同名 fixture 抄一份到本文件）：

```python
def test_short_creation_turn_returns_reply_and_card(temp_user, chain_stub):
    reply, patch, error = generate_short_creation_turn(
        [{"role": "user", "content": "我想写个渡口故事"}], creation.default_card(),
        user_id=temp_user)
    assert error is None
    assert reply == "主角最大的压力是什么？"
    assert patch["protagonist_pressure"] == "守着渡口的生计，也守着不肯走的儿子"
    # 记账：一次 planner 调用、json_mode、额度取自 _MAX_TOKENS、role 标 Planner
    call = chain_stub.calls[-1]
    assert call["json_mode"] is True
    assert call["max_tokens"] == nodes._MAX_TOKENS["short_creation"]


def test_short_creation_turn_survives_bad_json(temp_user, chain_stub_named):
    """模型吐了一整段散文：把原文当回复交出去，卡不动，error 记下来——用户重说一句就行。"""
    chain_stub_named('当然可以！我先说说渡口这个意象……')
    reply, patch, error = generate_short_creation_turn(
        [{"role": "user", "content": "随便聊聊"}], creation.default_card(), user_id=temp_user)
    assert patch == {}
    assert "渡口" in reply
    assert error is not None and error.startswith("parse_error")


def test_short_creation_turn_records_an_account_level_run(temp_user, chain_stub):
    with new_session() as db:
        generate_short_creation_turn([{"role": "user", "content": "hi"}],
                                     creation.default_card(), user_id=temp_user, db=db)
        db.commit()
        row = db.scalar(select(AgentRun).where(AgentRun.user_id == uuid.UUID(temp_user)))
    assert row is not None and row.node == "short_creation" and row.role == "Planner"
```

`chain_stub`（照 `tests/test_short_plan.py` 抄）返回的固定 JSON 用这份，两处断言才对得上：

```python
_STUB_TURN = ('{"reply": "主角最大的压力是什么？", "card": '
              '{"protagonist_pressure": "守着渡口的生计，也守着不肯走的儿子"}}')


@pytest.fixture
def chain_stub(monkeypatch):
    stub = _ChainStub(ModelProvider, _STUB_TURN)
    monkeypatch.setattr(providers_mod, "default_provider", stub)
    return stub


@pytest.fixture
def chain_stub_named(monkeypatch):
    """按用例换内容：坏 JSON 那类用例要自己指定模型吐什么。"""
    def install(content: str):
        stub = _ChainStub(ModelProvider, content)
        monkeypatch.setattr(providers_mod, "default_provider", stub)
        return stub
    return install
```

（`_ChainStub` 与 `ModelProvider` 一并从 `tests/test_short_plan.py` 的写法抄过来——它包一个 `ModelProvider`，在 `generate()` 里记下 `{"messages","max_tokens","json_mode"}` 并返回固定 content。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_short_creation.py -q -k turn`
Expected: FAIL —— `ImportError: cannot import name 'generate_short_creation_turn'`

- [ ] **Step 3: 实现**

`src/myink/book_setup.py` 追加（与同文件另外四个生成函数同款：一次调用、记一条 run、绝不抛）：

```python
def generate_short_creation_turn(history: list[dict], card: dict, *,
                                 user_id, db=None) -> tuple[str, dict, str | None]:
    """建书对话一回合：一次 planner json_mode 调用，回 (reply, 卡增量, error)。

    **不抛、不清卡**：解析失败时把模型原文当 reply 交出去、增量回空 dict（调用方保留现值）、
    error 记进消息。用户重说一句就能接着聊，而不是丢掉整场对话。
    """
    from myink.providers import make_user_chain
    from myink.short import creation
    from myink.workflow import nodes, prompts

    messages = prompts.short_creation_messages(history, card)
    resp = make_user_chain("planner", user_id).generate(
        messages, json_mode=True, max_tokens=nodes._MAX_TOKENS["short_creation"])
    if db is not None:
        nodes.record_run(db, user_id=user_id, task_id=None, node="short_creation",
                         role="Planner", resp=resp, error=resp.error, messages=messages,
                         detail={"turn": len(history)})
    if resp.error:
        return "（这一轮没连上模型，请再说一次）", {}, resp.error
    try:
        data = nodes._parse_json(resp.content)
    except Exception as exc:                       # 坏 JSON：原文当回复
        return resp.content.strip(), {}, f"parse_error: {exc}"
    if not isinstance(data, dict):
        return resp.content.strip(), {}, "unexpected_json"
    reply = str(data.get("reply") or "").strip() or "（模型这轮没有回复内容）"
    return reply, creation.card_patch(data.get("card")), None
```

**注意 `disable_thinking`**：同文件其他函数若传了 `disable_thinking=True` 就照传，没传就别加——按现有代码原样。

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_short_creation.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/myink/book_setup.py tests/test_short_creation.py
git commit -m "feat: 建书对话一回合——坏 JSON 也把话接住"
```

---

## Task 11: 会话端点（取/发/重来）

**Files:**
- Create: `src/myink/api/routes_short_creation.py`
- Modify: `src/myink/api/schemas.py`、`src/myink/api/main.py`
- Test: `tests/test_short_creation.py`（追加）

**Interfaces:**
- Consumes: `generate_short_creation_turn`（Task 10）、`creation.*`（Task 7）、`ShortCreation{Session,Message}`（Task 8）、`require_user`
- Produces:
  - `GET /api/v1/short/creation` → `ShortCreationOut`
  - `POST /api/v1/short/creation/messages` body `{content, card?}` → `ShortCreationOut`
  - `DELETE /api/v1/short/creation` → `{ok: true}`
  - `ShortCreationOut = {session: {id, status, card, style_item_id, style_name, book_id}, messages: [...], ready: bool}` —— Task 13 的 commit 与 Task 14 的前端都按这个形状读

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_short_creation.py`：

```python
def test_get_opens_a_session_with_a_fixed_greeting(temp_user):
    out = client.get("/api/v1/short/creation", headers=identity_headers(temp_user)).json()
    assert out["ready"] is False
    assert out["session"]["status"] == "active"
    assert out["session"]["card"]["chapter_count"] == 5
    assert len(out["messages"]) == 1 and out["messages"][0]["role"] == "assistant"
    # 开场白不调模型：首次进页面不该等一次网络
    assert out["messages"][0]["model_id"] is None


def test_posting_a_message_appends_both_sides_and_updates_the_card(temp_user, chain_stub):
    client.get("/api/v1/short/creation", headers=identity_headers(temp_user))
    out = client.post("/api/v1/short/creation/messages",
                      json={"content": "我想写个渡口故事"},
                      headers=identity_headers(temp_user)).json()
    assert [m["role"] for m in out["messages"]] == ["assistant", "user", "assistant"]
    assert out["messages"][-1]["content"] == "主角最大的压力是什么？"
    assert out["session"]["card"]["protagonist_pressure"].startswith("守着渡口")
    assert out["messages"][-1]["cost_est"] >= 0


def test_the_users_card_edits_win_over_the_models_next_blank(temp_user, chain_stub):
    """Review Focus 1：用户手改的字段不能被模型下一轮的空字段抹掉。"""
    client.get("/api/v1/short/creation", headers=identity_headers(temp_user))
    client.post("/api/v1/short/creation/messages",
                json={"content": "第一轮", "card": {"working_title": "最后一班渡船"}},
                headers=identity_headers(temp_user))
    out = client.post("/api/v1/short/creation/messages",
                      json={"content": "第二轮"}, headers=identity_headers(temp_user)).json()
    assert out["session"]["card"]["working_title"] == "最后一班渡船"


def test_ready_flips_only_when_all_seven_fields_are_filled(temp_user, chain_stub):
    client.get("/api/v1/short/creation", headers=identity_headers(temp_user))
    body = {"content": "都聊清了", "card": {field: "有" for field in creation.REQUIRED_CARD_FIELDS}}
    out = client.post("/api/v1/short/creation/messages", json=body,
                      headers=identity_headers(temp_user)).json()
    assert out["ready"] is True


def test_a_bad_model_turn_keeps_the_session_alive(temp_user, chain_stub_named):
    """Review Focus 2：坏 JSON 不能 500，也不能丢会话。"""
    chain_stub_named("这是一段没有 JSON 的散文。")
    client.get("/api/v1/short/creation", headers=identity_headers(temp_user))
    resp = client.post("/api/v1/short/creation/messages", json={"content": "聊两句"},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 200
    out = resp.json()
    assert out["messages"][-1]["error"].startswith("parse_error")
    assert out["messages"][-1]["content"] == "这是一段没有 JSON 的散文。"
    assert out["session"]["card"]["chapter_count"] == 5      # 卡没被毁


def test_reset_clears_the_conversation(temp_user):
    client.get("/api/v1/short/creation", headers=identity_headers(temp_user))
    assert client.delete("/api/v1/short/creation", headers=identity_headers(temp_user)).status_code == 200
    out = client.get("/api/v1/short/creation", headers=identity_headers(temp_user)).json()
    assert len(out["messages"]) == 1                      # 只剩新的开场白
    assert out["session"]["card"]["direction"] == ""


def test_messages_rejects_an_empty_content(temp_user):
    client.get("/api/v1/short/creation", headers=identity_headers(temp_user))
    resp = client.post("/api/v1/short/creation/messages", json={"content": "   "},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_short_creation.py -q -k "greeting or reset or rejects_an_empty"`
Expected: FAIL —— 404

- [ ] **Step 3: 实现**

`src/myink/api/schemas.py` 追加：

```python
class ShortCreationMessageOut(BaseModel):
    id: int
    role: str
    content: str
    card: dict | None
    model_id: str | None
    cost_est: float
    error: str | None
    created_at: datetime


class ShortCreationSessionOut(BaseModel):
    id: UUID
    status: str
    card: dict
    style_item_id: str | None
    style_name: str | None
    book_id: UUID | None


class ShortCreationOut(BaseModel):
    session: ShortCreationSessionOut
    messages: list[ShortCreationMessageOut]
    ready: bool


class ShortCreationMessageBody(BaseModel):
    content: str = Field(max_length=4000)
    card: dict | None = None
```

新建 `src/myink/api/routes_short_creation.py`：

```python
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
        reply, patch, error = generate_short_creation_turn(
            _history(db, session.id), session.card, user_id=uid, db=db)
        session.card = creation.merge_model_card(session.card, patch)
        db.add(ShortCreationMessage(
            session_id=session.id, role="assistant", content=reply, card=patch or None,
            model_id=session.updated_model, input_tokens=0, output_tokens=0,
            cost_est=0.0, error=error))
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
```

**上面 `post_message` 里 `model_id`/token/花费那三个字段是我留的坑**：`generate_short_creation_turn` 返回三元组，拿不到 `resp`。改它返回四元组 `(reply, patch, error, resp)`（`resp` 始终非 None：模型链失败时也是一条带 `error` 的响应），于是这里写：

```python
        reply, patch, error, resp = generate_short_creation_turn(
            _history(db, session.id), session.card, user_id=uid, db=db)
        session.card = creation.merge_model_card(session.card, patch)
        db.add(ShortCreationMessage(
            session_id=session.id, role="assistant", content=reply, card=patch or None,
            model_id=resp.model_id, input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens, cost_est=resp.cost_est, error=error))
```

**相应地回到 Task 10** 把 `generate_short_creation_turn` 的返回类型与三个 return 都补上第四个元素 `resp`，并让 Task 10 的三条测试解包四个值。**（顺序上先按四元组写 Task 10 更省事；这里写出来是因为端点需要它。）**

`src/myink/api/main.py`：导入并 `app.include_router(short_creation_router)`。

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_short_creation.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/myink/api/routes_short_creation.py src/myink/api/schemas.py src/myink/api/main.py src/myink/book_setup.py tests/test_short_creation.py
git commit -m "feat: 建书对话端点——开场白不调模型，坏回合不丢会话"
```

---

## Task 12: 抽出建书与落方案的两段共用逻辑（行为不变）

commit 要复用建书的「上限 + 幂等」与落方案的「置 ready」。先纯搬运地抽出来，**这一步不改任何可观测行为**，既有测试必须保持全绿。

**Files:**
- Modify: `src/myink/api/routes_book.py`
- Test: 既有 `tests/test_book*.py`、`tests/test_short*.py`

**Interfaces:**
- Consumes: `settings.books_per_day_max`、`save_proposal`、`get_volume_outline`、`validate_short_outline`、`VolumeOutline`
- Produces:
  - `BookCountExceeded(Exception)`、`_book_cnt_response() -> JSONResponse`
  - `_create_project_row(db, uid, *, title, genre, premise="", chapter_count, chars_per_chapter, storyline="", target_words=None, form="long", genre_pack=None, request_id=None) -> Project`
  - `_persist_short_outline(db, pid, payload) -> None`

- [ ] **Step 1: 先跑一遍基线，记录现状**

Run: `python -m pytest tests/test_book.py tests/test_short_plan.py tests/test_api_contract.py -q`
Expected: 全绿。**把结果记在便签上**——这一步的意义就是后面每一步都拿它对比。

- [ ] **Step 2: 加异常与 helper**

`src/myink/api/routes_book.py` 模块级加：

```python
class BookCountExceeded(Exception):
    """当日建书数超限。

    两个建书入口（表单建书、对话建书）共用同一段计数逻辑，所以也要共用同一个信号。
    不用 HTTPException：错误体必须是网关同款 {"error": "BOOK_CNT_EXCEEDED"} 信封
    （前端 GATE_CODES 才能命中中文文案），而 HTTPException 会被包成 {"detail": ...}。
    """


def _book_cnt_response() -> JSONResponse:
    return JSONResponse(status_code=429, content={"error": "BOOK_CNT_EXCEEDED"})


def _create_project_row(db, uid: uuid.UUID, *, title: str, genre: str, premise: str = "",
                        chapter_count: int, chars_per_chapter: int, storyline: str = "",
                        target_words: int | None = None, form: str = "long",
                        genre_pack: dict | None = None,
                        request_id: uuid.UUID | None = None) -> Project:
    """建 Project 行 + 空 ProjectSettings。**每日上限与 request_id 幂等都在这里。**

    两条建书动线共用这一段——各写一份就会出现两种上限口径（对话建书能绕开表单建书的
    闸门，那是最糟的一类漏洞）。调用方负责先做完形态/章数/字数的白名单校验。

    request_id 命中已有作品时直接返回它（不计数、不新建），与调用方的响应形状无关。
    """
    if request_id is not None:
        existing = db.scalar(select(Project).where(
            Project.user_id == uid,
            Project.creation_context["request_id"].as_string() == str(request_id),
        ))
        if existing is not None:
            return existing
    today = func.date_trunc("day", func.now())
    created = db.query(Project).filter(
        Project.user_id == uid, Project.created_at >= today).count()
    if created >= settings.books_per_day_max:
        raise BookCountExceeded()
    project = Project(user_id=uid, title=title, genre=genre, target_words=target_words,
                      form=form,
                      creation_status="draft", creation_context={
                          "request_id": str(request_id) if request_id else None,
                          "premise": premise, "chapter_count": chapter_count,
                          "form": form, "chars_per_chapter": chars_per_chapter,
                          "storyline": storyline})
    db.add(project)
    db.flush()
    db.execute(text("SELECT set_config('app.tenant_id', :pid, true)"),
               {"pid": str(project.id)})
    db.add(ProjectSettings(project_id=project.id, genre_pack=genre_pack or {}))
    return project


def _persist_short_outline(db, pid: uuid.UUID, payload: dict) -> None:
    """短篇大纲落库 + 置 ready，**没有 setup_confirmed 闸门**。

    `put_outline` 的短篇分支与对话式建书的 commit 共用这一段：对话动线没有设定页，
    那张方案卡就是设定。硬前提——短篇生成要求 creation_status ∈ {ready, legacy_ready}。

    调用方负责 commit。
    """
    validate_short_outline(payload)
    project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
    if project is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    project.creation_status = "ready"
    project.creation_context = {**(project.creation_context or {}),
                               "outline_draft": payload}
    row = get_volume_outline(db, pid, 1)
    if row is None:
        db.add(VolumeOutline(project_id=pid, volume_seq=1, title="整书大纲", outline=payload))
    else:
        row.outline = payload
```

- [ ] **Step 3: `create_project` 改走 helper（行为逐条对齐）**

`create_project` 的 `with new_session() as db:` 段变成：

```python
    with new_session() as db:
        # Serialize the daily count and insert for this user; creation is one transaction.
        if db.scalar(select(User.id).where(User.id == uid).with_for_update()) is None:
            raise HTTPException(status_code=403, detail="身份非法")
        target_words = _check_target_words(body.target_words, field="每章目标字数")
        genre_pack: dict = {}
        if "primary_id" in body.model_fields_set:
            try:
                genre_pack = build_book_pack(body.primary_id, body.secondary_id, body.genre_fields)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            genre = display_genre(body.primary_id, body.secondary_id)
        else:
            genre = body.genre.strip() or "仙侠玄幻"
        try:
            project = _create_project_row(
                db, uid, title=title, genre=genre, premise=body.premise,
                chapter_count=body.chapter_count, chars_per_chapter=body.chars_per_chapter,
                storyline=body.storyline, target_words=target_words, form=form,
                genre_pack=genre_pack, request_id=body.request_id)
        except BookCountExceeded:
            return _book_cnt_response()
        db.commit()
    return project_payload(project)
```

**与原文的两处差异，都是有意的、也是这个任务唯一的行为改动：** ① `request_id` 命中的那条现在会多走一次 `db.commit()`（原来是提前 return、由 `with` 退出时回滚）——commit 一个没有改动的会话是空操作；② 命中时不再提前 return，末尾统一 `return project_payload(project)`，两条路径的响应体完全一致。如果既有测试对这两点有断言（不太可能），在这里停下并报告，不要改测试迁就代码。

- [ ] **Step 4: `put_outline` 的短篇分支改走 helper**

```python
    with tenant_session(project_id) as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if project.form == "short":
            payload = build_persisted_short_outline(
                objective=body.objective, volumes=body.volumes or [],
                premise=body.premise, chapter_count=body.chapter_count,
                storyline=body.storyline)
            _persist_short_outline(db, pid, payload)
        else:
            payload = build_persisted_outline(...)          # 原文不动
            validate_creation_outline(payload)              # 原文的 DRAFT_STATES / ready 分支不动
            ...
        db.commit()
    return {"outline": payload}
```

长篇分支那一整段（`if project.creation_status in DRAFT_STATES:` / `elif ... == "ready":`）**逐字保留**，只有短篇走 helper。`build_persisted_short_outline` 的调用提到分支里，避免为长篇也算一遍。

短篇走 helper 后，旧向导的 `put_setup`（置 `setup_confirmed`）→ `put_outline` 仍然成立（helper 不看状态、只管落库与置 ready）——**这就是「行为不变」的判据**。

- [ ] **Step 5: 跑测试对比基线**

Run: `python -m pytest tests/ -q`
Expected: 与 Step 1 完全一致地全绿。

- [ ] **Step 6: 提交**

```bash
git add src/myink/api/routes_book.py
git commit -m "refactor: 抽出建书行与短篇落纲两段共用逻辑（行为不变）"
```

---

## Task 13: `POST /short/creation/commit`——确认即开写

**Files:**
- Modify: `src/myink/api/routes_short_creation.py`、`src/myink/api/schemas.py`
- Test: `tests/test_short_creation.py`（追加）

**Interfaces:**
- Consumes: `_create_project_row` / `_book_cnt_response` / `_short_outline_draft` / `_persist_short_outline`（Task 12）、`resolve_short_lengths`（`short/form.py`）、`get_settings`、`STYLE_PRESETS`（`myink.seed`）
- Produces: `POST /api/v1/short/creation/commit` body `{card?, style_item_id?}` → `{project_id, lengths_compressed, plan_warning, style_name}`；**不负责入队**（前端拿到 `project_id` 后调既有 `POST /projects/{id}/short/generate`，配额与成本只有那一条实现）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_short_creation.py`：

```python
_FULL_CARD = {field: "有" for field in creation.REQUIRED_CARD_FIELDS} | {
    "working_title": "最后一班渡船", "genre": "现实主义", "chapter_count": 3,
    "chars_per_chapter": 4000,
}


def _seed_session(user: str, card: dict | None = None):
    """直接把会话摆好：这些用例验的是 commit，不验聊到这一步的过程。"""
    with new_session() as db:
        session = ShortCreationSession(user_id=uuid.UUID(user), status="active",
                                       card=creation.merge_user_card(creation.default_card(), card or _FULL_CARD))
        db.add(session)
        db.commit()


def test_commit_builds_a_ready_short_book_with_a_persisted_plan(temp_user, chain_stub):
    _seed_session(temp_user)
    out = client.post("/api/v1/short/creation/commit", json={},
                      headers=identity_headers(temp_user)).json()
    with new_session() as db:
        project = db.get(Project, uuid.UUID(out["project_id"]))
        assert project.form == "short"
        assert project.creation_status == "ready"
        assert project.creation_context["chapter_count"] == 3
        assert project.creation_context["creation_conversation"]["conflict_core"] == "有"
    with tenant_session(out["project_id"]) as tdb:
        outline = get_volume_outline(tdb, uuid.UUID(out["project_id"]), 1)
    assert outline is not None and len(outline.outline["volumes"][0]["chapters"]) == 3


def test_commit_refuses_an_incomplete_card(temp_user):
    _seed_session(temp_user, {"working_title": "半张卡"})
    resp = client.post("/api/v1/short/creation/commit", json={},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "CARD_INCOMPLETE"


def test_commit_twice_does_not_build_a_second_book(temp_user, chain_stub):
    """Review Focus 4：中途失败/手滑再点一次，不能建出两本。"""
    _seed_session(temp_user)
    first = client.post("/api/v1/short/creation/commit", json={},
                        headers=identity_headers(temp_user)).json()
    second = client.post("/api/v1/short/creation/commit", json={},
                         headers=identity_headers(temp_user))
    assert second.status_code == 409                     # 会话已 committed
    assert second.json()["detail"] == "SESSION_COMMITTED"
    with new_session() as db:
        assert db.query(Project).filter(Project.user_id == uuid.UUID(temp_user)).count() == 1
        assert db.get(ShortCreationSession, uuid.UUID(first_session_id(temp_user))).book_id is not None


def test_commit_respects_the_daily_book_cap(temp_user, chain_stub, monkeypatch):
    """Review Focus 3：上限用满时点确认 → 网关同款 429 信封，不是 500。"""
    from myink.api import routes_book
    monkeypatch.setattr(routes_book.settings, "books_per_day_max", 0)
    _seed_session(temp_user)
    resp = client.post("/api/v1/short/creation/commit", json={},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 429
    assert resp.json() == {"error": "BOOK_CNT_EXCEEDED"}
    with new_session() as db:                             # 会话没被弄脏，用户配好额度后能重来
        assert db.scalar(select(ShortCreationSession)
                         .where(ShortCreationSession.user_id == uuid.UUID(temp_user))).status == "active"


def test_commit_applies_a_library_style_and_rejects_someone_elses(temp_user, chain_stub):
    with new_session() as db:
        mine = StyleLibraryItem(user_id=uuid.UUID(temp_user), name="渡口冷白描",
                                profile={"pov": "第三人称限知"}, sample_chars=1200)
        other_user = User(username=f"style-{uuid.uuid4().hex[:8]}")
        db.add_all([mine, other_user])
        db.commit()
        mine_id, other_id = str(mine.id), other_user.id
    _seed_session(temp_user)
    out = client.post("/api/v1/short/creation/commit",
                      json={"style_item_id": mine_id},
                      headers=identity_headers(temp_user)).json()
    with new_session() as db:
        settings_row = db.get(ProjectSettings, uuid.UUID(out["project_id"]))
        assert settings_row.style_profile["pov"] == "第三人称限知"
        session = db.scalar(select(ShortCreationSession)
                            .where(ShortCreationSession.user_id == uuid.UUID(temp_user)))
        assert session.style_name == "渡口冷白描"

    # 借别人的 item id：404，不是 403、更不是静默忽略
    _reset_session(temp_user)
    _seed_session(temp_user)
    resp = client.post("/api/v1/short/creation/commit", json={"style_item_id": str(uuid.uuid4())},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 404


def test_commit_accepts_a_builtin_preset_by_key(temp_user, chain_stub):
    _seed_session(temp_user)
    out = client.post("/api/v1/short/creation/commit",
                      json={"style_item_id": "builtin:xianxia-jiuzhou"},
                      headers=identity_headers(temp_user)).json()
    with new_session() as db:
        assert db.get(ProjectSettings, uuid.UUID(out["project_id"])).skill_pack == "xianxia-jiuzhou"
```

`_reset_session(user)`/`first_session_id(user)` 这类小工具按需在文件顶部加（都是三行 `new_session` 查询），不要为了省几行把它们写成 fixture 链。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_short_creation.py -q -k commit`
Expected: FAIL —— 404 `commit`

- [ ] **Step 3: 实现**

`src/myink/api/schemas.py`：

```python
class ShortCreationCommitBody(BaseModel):
    card: dict | None = None
    style_item_id: str | None = None


class ShortCreationCommitOut(BaseModel):
    project_id: UUID
    lengths_compressed: bool
    plan_warning: str | None
    style_name: str | None
```

`src/myink/api/routes_short_creation.py` 追加：

```python
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
    if patch.get("outline_error") or not outline.get("volumes"):
        # 书已经在库里（session.book_id 记着），这一步失败用户重按一次即可——
        # 不会建出第二本，也不会卡在「方案空了但状态是 ready」上
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
```

文件顶部补导入：`from myink.api import routes_book as _book`、`from myink.api.routes_book import OutlineDraftBody`（或直接用 `_book.OutlineDraftBody`——两者择一，别都写）、`from myink.db import new_session, tenant_session`、`from myink.memory.repository import get_settings`、`from myink.models import Project, ProjectSettings, StyleLibraryItem, User`、`from myink.short.form import resolve_short_lengths`。

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_short_creation.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/myink/api/routes_short_creation.py src/myink/api/schemas.py tests/test_short_creation.py
git commit -m "feat: 确认即开写——落书出方案置 ready，重试不建第二本"
```

---

## Task 14: 前端建书对话页

**Files:**
- Create: `web/src/lib/shortCreationApi.ts`、`web/src/lib/shortCreationApi.test.ts`
- Create: `web/src/pages/ShortCreationPage.tsx`、`web/src/pages/ShortCreationPage.module.css`、`web/src/pages/ShortCreationPage.test.tsx`
- Modify: `web/src/router.tsx`、`web/src/lib/projectCreation.ts`、`web/src/lib/projectCreation.test.ts`

**Interfaces:**
- Consumes: `styleLibraryApi`（Task 6）、后端四端点（Task 11/13）
- Produces: `/short/new` → `ShortCreationPage`；`projectHref` 对短篇（含草稿）一律 `/projects/<id>`

- [ ] **Step 1: 写失败测试（调用层 + 页面 + 跳转口径）**

新建 `web/src/lib/shortCreationApi.test.ts`（形态照 Task 6 那份）：

```ts
import { beforeEach, expect, it, vi } from 'vitest'
import { authenticatedGet, authenticatedSend } from './api'
import { shortCreationApi } from './shortCreationApi'

vi.mock('./api', () => ({ authenticatedGet: vi.fn(), authenticatedSend: vi.fn() }))

beforeEach(() => {
  vi.mocked(authenticatedGet).mockReset()
  vi.mocked(authenticatedSend).mockReset()
})

it('reads the session from the creation endpoint', async () => {
  vi.mocked(authenticatedGet).mockResolvedValue({ session: {}, messages: [], ready: false })
  await shortCreationApi.get('t')
  expect(authenticatedGet).toHaveBeenCalledWith('/api/v1/short/creation', 't', undefined)
})

it('sends a message together with the current card', async () => {
  vi.mocked(authenticatedSend).mockResolvedValue({ session: {}, messages: [], ready: false })
  await shortCreationApi.send('t', '我想写渡口', { working_title: '渡船' })
  expect(authenticatedSend).toHaveBeenCalledWith(
    'POST', '/api/v1/short/creation/messages', 't',
    { content: '我想写渡口', card: { working_title: '渡船' } }, undefined)
})

it('commits with the card and the chosen style', async () => {
  vi.mocked(authenticatedSend).mockResolvedValue({ project_id: 'p1' })
  await shortCreationApi.commit('t', { working_title: '渡船' }, 'builtin:xianxia-jiuzhou')
  expect(authenticatedSend).toHaveBeenCalledWith(
    'POST', '/api/v1/short/creation/commit', 't',
    { card: { working_title: '渡船' }, style_item_id: 'builtin:xianxia-jiuzhou' }, undefined)
})

it('resets the conversation', async () => {
  vi.mocked(authenticatedSend).mockResolvedValue({ ok: true })
  await shortCreationApi.reset('t')
  expect(authenticatedSend).toHaveBeenCalledWith(
    'DELETE', '/api/v1/short/creation', 't', undefined, undefined)
})
```

追加到 `web/src/lib/projectCreation.test.ts`：

```ts
it('sends short drafts to the workspace, not to the long-form wizard', () => {
  // 短篇没有「设定 → 大纲」两步可回填，草稿回到对话页毫无意义；长篇草稿仍然回向导续填。
  expect(projectHref({ id: 'p1', form: 'short', creation_status: 'draft' })).toBe('/projects/p1')
  expect(projectHref({ id: 'p2', form: 'long', creation_status: 'draft' })).toBe('/long/new?draft=p2')
  expect(projectHref({ id: 'p3', form: 'short', creation_status: 'ready' })).toBe('/projects/p3')
})
```

按该文件已有的样本形状调整入参（现有用例怎么造 `Project`，就怎么造）。

新建 `web/src/pages/ShortCreationPage.test.tsx`：

```tsx
// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { shortCreationApi } from '../lib/shortCreationApi'
import { styleLibraryApi } from '../lib/styleLibraryApi'
import { useAuth } from '../context/AuthContext'
import ShortCreationPage from './ShortCreationPage'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../lib/shortCreationApi', () => ({
  shortCreationApi: { get: vi.fn(), send: vi.fn(), commit: vi.fn(), reset: vi.fn() },
}))
vi.mock('../lib/styleLibraryApi', () => ({
  styleLibraryApi: { list: vi.fn(), extract: vi.fn(), save: vi.fn(), remove: vi.fn() },
}))

const session = {
  id: 's1', status: 'active', card: {}, style_item_id: null, style_name: null, book_id: null,
}

const payload = (over = {}) => ({
  session: { ...session, ...over.session },
  messages: over.messages ?? [{ id: 1, role: 'assistant', content: '想写个什么样的短篇？', card: null, model_id: null, cost_est: 0, error: null, created_at: '2026-01-01T00:00:00Z' }],
  ready: over.ready ?? false,
})

function renderPage() {
  const router = createMemoryRouter([
    { path: '/short/new', element: <ShortCreationPage /> },
    { path: '/projects/:projectId', element: <div>工作台</div> },
  ], { initialEntries: ['/short/new'] })
  return { ...render(<RouterProvider router={router} />), router }
}

beforeEach(() => {
  vi.mocked(useAuth).mockReturnValue({
    session: { token: 't', userId: 'u1', username: 'alice', tier: 'normal', role: 'user', roleVerified: true, expiresAt: Date.now() + 60000 },
    status: 'authenticated', revalidate: vi.fn(), logout: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>)
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload())
  vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [] })
})

afterEach(() => { cleanup(); vi.clearAllMocks() })

it('shows the greeting and the editable plan card', async () => {
  renderPage()
  expect(await screen.findByText('想写个什么样的短篇？')).toBeTruthy()
  expect(screen.getByLabelText('暂定名')).toBeTruthy()
  expect((screen.getByLabelText('章数') as HTMLInputElement).value).toBe('5')
})

it('disables confirm until every required field is filled', async () => {
  renderPage()
  const confirm = await screen.findByRole('button', { name: '确认，开写' })
  expect((confirm as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(screen.getByLabelText('方向'), { target: { value: '一句话方向' } })
  expect((confirm as HTMLButtonElement).disabled).toBe(true)   // 只有一格还不够
})

it('sends the message and renders both sides of the turn', async () => {
  vi.mocked(shortCreationApi.send).mockResolvedValue(payload({
    messages: payload().messages.concat([
      { id: 2, role: 'user', content: '渡口的故事', card: null, model_id: null, cost_est: 0, error: null, created_at: '2026-01-01T00:00:01Z' },
      { id: 3, role: 'assistant', content: '主角的压力是什么？', card: null, model_id: 'm', cost_est: 0.002, error: null, created_at: '2026-01-01T00:00:02Z' },
    ]),
  }))
  renderPage()
  fireEvent.change(await screen.findByLabelText('对助手说'), { target: { value: '渡口的故事' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  expect(await screen.findByText('主角的压力是什么？')).toBeTruthy()
  expect(screen.getByText('渡口的故事')).toBeTruthy()
})

it('confirms, then leaves for the workspace so writing starts there', async () => {
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({
    ready: true,
    session: { card: { working_title: '最后一班渡船', direction: 'd', conflict_core: 'c', genre: 'g', protagonist_pressure: 'p', emotional_payoff: 'e', plot_sketch: 's', chapter_count: 5, chars_per_chapter: 4000 } },
  }))
  vi.mocked(shortCreationApi.commit).mockResolvedValue({
    project_id: 'p1', lengths_compressed: false, plan_warning: null, style_name: null,
  })
  const { router } = renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '确认，开写' }))
  // commit 只落书不出稿：入队由工作台那条路做（配额与成本只有一份实现）
  await waitFor(() => expect(shortCreationApi.commit).toHaveBeenCalled())
  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p1'))
})

it('starting over clears the conversation', async () => {
  vi.mocked(shortCreationApi.reset).mockResolvedValue({ ok: true })
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '重新开始' }))
  await waitFor(() => expect(shortCreationApi.reset).toHaveBeenCalled())
})
```

- [ ] **Step 2: 跑测试确认失败**

Run（在 `web/` 下）: `npm test -- src/lib/shortCreationApi.test.ts src/pages/ShortCreationPage.test.tsx`
Expected: FAIL —— 模块不存在

- [ ] **Step 3: 实现调用层**

新建 `web/src/lib/shortCreationApi.ts`：

```ts
/** 对话式短篇建书：取会话 / 发一句 / 确认开写 / 重新开始。
 *
 * commit 只落书不出稿——入队走既有的 POST /projects/{id}/short/generate，
 * 配额与成本估算只有那一份实现。
 */
import { authenticatedGet, authenticatedSend } from './api'

export interface ShortCreationCard {
  working_title: string
  genre: string
  direction: string
  protagonist_pressure: string
  conflict_core: string
  emotional_payoff: string
  plot_sketch: string
  chapter_count: number
  chars_per_chapter: number
}

export const REQUIRED_CARD_FIELDS = [
  'working_title', 'genre', 'direction', 'protagonist_pressure',
  'conflict_core', 'emotional_payoff', 'plot_sketch',
] as const

export interface ShortCreationMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  card: Partial<ShortCreationCard> | null
  model_id: string | null
  cost_est: number
  error: string | null
  created_at: string
}

export interface ShortCreationSession {
  id: string
  status: 'active' | 'committed'
  card: Partial<ShortCreationCard>
  style_item_id: string | null
  style_name: string | null
  book_id: string | null
}

export interface ShortCreationPayload {
  session: ShortCreationSession
  messages: ShortCreationMessage[]
  ready: boolean
}

export interface ShortCreationCommit {
  project_id: string
  lengths_compressed: boolean
  plan_warning: string | null
  style_name: string | null
}

export const shortCreationApi = {
  get: (token: string, signal?: AbortSignal): Promise<ShortCreationPayload> =>
    authenticatedGet('/api/v1/short/creation', token, signal),

  send: (token: string, content: string, card: Record<string, unknown>, signal?: AbortSignal):
    Promise<ShortCreationPayload> =>
    authenticatedSend('POST', '/api/v1/short/creation/messages', token, { content, card }, signal),

  commit: (token: string, card: Record<string, unknown>, styleItemId: string | null, signal?: AbortSignal):
    Promise<ShortCreationCommit> =>
    authenticatedSend('POST', '/api/v1/short/creation/commit', token,
                      { card, style_item_id: styleItemId }, signal),

  reset: (token: string, signal?: AbortSignal): Promise<{ ok: boolean }> =>
    authenticatedSend('DELETE', '/api/v1/short/creation', token, undefined, signal),
}
```

- [ ] **Step 4: 实现页面**

`web/src/pages/ShortCreationPage.module.css`：

```css
/* 两栏：左边聊，右边卡。窄屏堆成一列（聊在上，卡在下）。 */
.wrap { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 380px); gap: 16px; height: 100%; min-height: 0; }
.thread { display: flex; flex-direction: column; min-height: 0; }
.stream { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding: 12px 0; }
.turn { max-width: 42em; padding: 10px 12px; border-radius: 10px; white-space: pre-wrap; }
.mine { align-self: flex-end; background: var(--accent-soft, #eef2ff); }
.theirs { align-self: flex-start; background: var(--panel-soft, #f5f5f5); }
.failed { border: 1px solid var(--danger, #c00); font-size: 0.85em; }
.composer { display: flex; gap: 8px; align-items: flex-end; padding-top: 8px; }
.composer textarea { flex: 1; min-height: 3.2em; resize: vertical; }
.card { display: flex; flex-direction: column; gap: 8px; min-height: 0; overflow-y: auto; }
.card label { display: flex; flex-direction: column; gap: 2px; font-size: 0.85em; }
.card small { opacity: 0.7; }
@media (max-width: 900px) { .wrap { grid-template-columns: minmax(0, 1fr); } }
```

`web/src/pages/ShortCreationPage.tsx`：

```tsx
/** 短篇建书：与助手聊清楚 → 右边那张卡可以随手改 → 「确认，开写」。
 *
 * 与长篇向导的分工：长篇要先填设定、再确认大纲，两步都不能省；短篇这里聊完那一刻
 * 方案卡就是设定，后端在确认时一次把逐章方案落库（生成需要它）。
 */
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { formatApiError } from '../lib/apiError'
import { shortCreationApi, type ShortCreationCard, type ShortCreationPayload }
  from '../lib/shortCreationApi'
import { styleLibraryApi, type StyleLibraryItem } from '../lib/styleLibraryApi'
import styles from './ShortCreationPage.module.css'

const FIELDS: Array<[keyof ShortCreationCard, string]> = [
  ['working_title', '暂定名'],
  ['genre', '题材'],
  ['direction', '方向'],
  ['protagonist_pressure', '主角压力'],
  ['conflict_core', '核心冲突'],
  ['emotional_payoff', '情绪回报'],
  ['plot_sketch', '大致情节'],
]

const REQUIRED_TEXT: Array<keyof ShortCreationCard> = [
  'working_title', 'genre', 'direction', 'protagonist_pressure',
  'conflict_core', 'emotional_payoff', 'plot_sketch',
]

const BUILTIN_STYLES: Array<[string, string]> = [
  ['builtin:xianxia-jiuzhou', '仙侠·九州'],
  ['builtin:changan-yexing', '长安夜行'],
  ['builtin:xingjian-yuanzheng', '星舰远征'],
  ['builtin:dushi-yiguan', '都市异观'],
]

function isReady(card: Partial<ShortCreationCard>): boolean {
  return REQUIRED_TEXT.every((field) => String(card[field] ?? '').trim() !== '')
}

export default function ShortCreationPage() {
  const { session } = useAuth()
  const token = session?.token ?? ''
  const navigate = useNavigate()
  const [data, setData] = useState<ShortCreationPayload | null>(null)
  const [card, setCard] = useState<Partial<ShortCreationCard>>({})
  const [styleItemId, setStyleItemId] = useState('')
  const [styleItems, setStyleItems] = useState<StyleLibraryItem[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const stream = useRef<HTMLDivElement>(null)

  const apply = useCallback((next: ShortCreationPayload) => {
    setData(next)
    setCard(next.session.card ?? {})
    setStyleItemId(next.session.style_item_id ?? '')
  }, [])

  const reload = useCallback(async () => {
    try {
      apply(await shortCreationApi.get(token))
    } catch (reason) {
      setError(formatApiError(reason, '打不开建书对话，请稍后重试'))
    }
  }, [apply, token])

  useEffect(() => { void reload() }, [reload])
  useEffect(() => {
    styleLibraryApi.list(token).then((out) => setStyleItems(out.items)).catch(() => setStyleItems([]))
  }, [token])
  useEffect(() => { stream.current?.scrollTo({ top: stream.current.scrollHeight }) }, [data])

  const run = async (action: () => Promise<void>, fallback: string) => {
    setError(null)
    setBusy(true)
    try {
      await action()
    } catch (reason) {
      setError(formatApiError(reason, fallback))
    } finally {
      setBusy(false)
    }
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const content = draft.trim()
    if (!content || busy) return
    void run(async () => {
      apply(await shortCreationApi.send(token, content, card as Record<string, unknown>))
      setDraft('')
    }, '这句话没发出去，请重试')
  }

  const confirm = () => void run(async () => {
    const out = await shortCreationApi.commit(token, card as Record<string, unknown>, styleItemId || null)
    // commit 只落书不出稿：进工作台点「开始写全篇」才入队
    navigate(`/projects/${out.project_id}`, {
      state: { beginShortWriting: true, planWarning: out.plan_warning },
    })
  }, '确认失败，请重试')

  const restart = () => void run(async () => {
    await shortCreationApi.reset(token)
    await reload()
  }, '重置失败，请重试')

  if (!data) return <div className="empty">{error ?? '正在打开建书对话…'}</div>
  const ready = isReady(card)

  return (
    <div className={styles.wrap}>
      <section className={styles.thread} aria-label="建书对话">
        <header className="row-between">
          <h2>新建短篇</h2>
          <button type="button" className="btn btn-quiet" onClick={restart} disabled={busy}>重新开始</button>
        </header>
        <div className={styles.stream} ref={stream}>
          {data.messages.map((message) => (
            <div key={message.id}
                 className={[styles.turn, message.role === 'user' ? styles.mine : styles.theirs,
                             message.error ? styles.failed : ''].join(' ')}>
              <p>{message.content}</p>
              {message.error && <small role="alert">这一轮没成功：{message.error}</small>}
            </div>
          ))}
        </div>
        {error && <div className="banner banner-error" role="alert"><span>{error}</span></div>}
        <form className={styles.composer} onSubmit={submit}>
          <label>
            <span className="visually-hidden">对助手说</span>
            <textarea aria-label="对助手说" className="input" value={draft} maxLength={4000}
                      placeholder="说说你想写的故事，或者说「就这样，开写吧」"
                      onChange={(event) => setDraft(event.target.value)} />
          </label>
          <button type="submit" className="btn btn-primary" disabled={busy || draft.trim() === ''}>发送</button>
        </form>
      </section>

      <aside className={`panel ${styles.card}`} aria-label="方案卡">
        <h3>方案卡（随手改）</h3>
        {FIELDS.map(([key, label]) => (
          <label key={key}>
            <span>{label}{REQUIRED_TEXT.includes(key) ? '（必填）' : ''}</span>
            <textarea className="input" rows={key === 'plot_sketch' ? 4 : 2}
                      aria-label={label} value={String(card[key] ?? '')} maxLength={4000}
                      onChange={(event) => setCard({ ...card, [key]: event.target.value })} />
          </label>
        ))}
        <label>
          <span>章数（1–10）</span>
          <input className="input" type="number" min={1} max={10} aria-label="章数"
                 value={card.chapter_count ?? 5}
                 onChange={(event) => setCard({ ...card, chapter_count: Number(event.target.value) })} />
        </label>
        <label>
          <span>每章字数（1000–8000）</span>
          <input className="input" type="number" min={1000} max={8000} aria-label="每章字数"
                 value={card.chars_per_chapter ?? 4000}
                 onChange={(event) => setCard({ ...card, chars_per_chapter: Number(event.target.value) })} />
        </label>
        <label>
          <span>文风（建书后不可改）</span>
          <select className="input" aria-label="文风" value={styleItemId}
                  onChange={(event) => setStyleItemId(event.target.value)}>
            <option value="">不指定</option>
            {BUILTIN_STYLES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            {styleItems.map((item) => <option key={item.id} value={item.id}>{item.name}（我的）</option>)}
          </select>
        </label>
        <small>文风在确认时定下来，之后没有换的入口；想导入自己的文章，去「账号」页的文风库。</small>
        <button type="button" className="btn btn-primary" disabled={!ready || busy} onClick={confirm}>
          确认，开写
        </button>
        {!ready && <small>还差几个必填项——也可以直接告诉助手，它会补上。</small>}
      </aside>
    </div>
  )
}
```

`web/src/router.tsx`：

```tsx
import ShortCreationPage from './pages/ShortCreationPage'
```

```tsx
      { path: '/short/new', element: <ShortCreationPage /> },
```

（`/long/new` 与 `/projects/new` 不动。）

`web/src/lib/projectCreation.ts` 的 `projectHref`：草稿分支只在 `form !== 'short'` 时回向导。

- [ ] **Step 5: 跑测试与类型闸**

Run（在 `web/` 下）: `npm test -- src/lib/shortCreationApi.test.ts src/lib/projectCreation.test.ts src/pages/ShortCreationPage.test.tsx && npm run lint && npm run build`
Expected: 全绿（`build` 是真类型闸）。`ProjectRail` 上的 `visually-hidden` 类若样式表里没有，换成仓库里现成的隐藏类名（`grep -rn "visually-hidden\|sr-only" web/src`）。

- [ ] **Step 6: 手工过一遍浏览器（Chrome/Edge）**

`/short/new`：开场白立刻出现（不等网络）；发一句 → 两边都有气泡；在右栏改「暂定名」→ 再发一句 → 你的改动还在；填满 7 格 → 「确认，开写」亮起 → 点它进 `/projects/<新 id>`。**这一步不做完不要报告本任务完成**（前端改动必须以浏览器为准，vitest 只能证明组件逻辑）。

- [ ] **Step 7: 提交**

```bash
git add web/src/lib/shortCreationApi.ts web/src/lib/shortCreationApi.test.ts web/src/pages/ShortCreationPage.tsx web/src/pages/ShortCreationPage.module.css web/src/pages/ShortCreationPage.test.tsx web/src/router.tsx web/src/lib/projectCreation.ts web/src/lib/projectCreation.test.ts
git commit -m "feat: 短篇建书对话页——聊出来的方案卡，确认才开写"
```

---

## Task 14b: 工作台接住「刚确认完」的那一次进入

Task 14 的 `navigate(..., { state: { beginShortWriting: true, planWarning } })` 需要一个接住它的人：进工作台就把短篇生成入队，否则用户建完书还要自己再点一次按钮。

**Files:**
- Modify: `web/src/pages/WorkspacePage.tsx`
- Test: `web/src/pages/WorkspacePage.test.tsx`（追加）

**Interfaces:**
- Consumes: 既有短篇生成入队函数（`grep -n "short/generate" web/src/lib/*.ts web/src/pages/WorkspacePage.tsx` 找到现成的那个，别新写一条调用路径）
- Produces: 无（一次性副作用）

- [ ] **Step 1: 写失败测试**

追加到 `web/src/pages/WorkspacePage.test.tsx`（照该文件现有的短篇用例搭挂载与 mock）：

```tsx
it('starts the short-form writing as soon as the creation assistant hands over', async () => {
  // 从建书对话页跳进来：commit 只落了书，出稿要在这里入队
  renderWorkspace({ form: 'short' }, { state: { beginShortWriting: true } })
  await waitFor(() => expect(startShortGeneration).toHaveBeenCalledTimes(1))
})

it('does not enqueue again on a plain visit', async () => {
  renderWorkspace({ form: 'short' })
  await waitFor(() => expect(startShortGeneration).not.toHaveBeenCalled())
})
```

用该文件已有的挂载辅助（`renderWorkspace` 是示意名——按实际形状写）与实际的入队函数名替换。

- [ ] **Step 2: 跑测试确认失败**

Run: `npm test -- src/pages/WorkspacePage.test.tsx`
Expected: FAIL —— 断言未通过

- [ ] **Step 3: 实现**

在 `WorkspacePage` 里取 `useLocation()`，加一个「只跑一次」的 effect：

```tsx
  // 建书对话页确认完跳进来时带了这个 state：那次 commit 只落书不出稿，入队归这里。
  // 用 ref 记住已经跑过——React 18 的 StrictMode 下 effect 会跑两次，跑两遍就是两次配额。
  const handedOver = useRef(false)
  useEffect(() => {
    if (!isShortBook || handedOver.current) return
    const intent = (location.state ?? {}) as { beginShortWriting?: boolean; planWarning?: string | null }
    if (!intent.beginShortWriting) return
    handedOver.current = true
    if (intent.planWarning) setShortWarning(intent.planWarning)   // 复用页面里现有的提示位
    void startShortGeneration()                                    // 现成的入队函数
  }, [isShortBook, location.state])
```

`setShortWarning` 若没有现成的提示位，就把 `planWarning` 直接用现有的 banner 状态显示（`grep -n "banner\|setError" web/src/pages/WorkspacePage.tsx` 找现成的那个），不要为它新造一套。

- [ ] **Step 4: 跑测试与类型闸**

Run（在 `web/` 下）: `npm test -- src/pages/WorkspacePage.test.tsx && npm run build`
Expected: 全绿

- [ ] **Step 5: 手工验证闭环**

浏览器：`/short/new` → 聊到 ready → 确认 → 落在 `/projects/<id>`，**正文区自己开始出稿**（不需要再点「开始写全篇」）；刷新该页不再重复入队（看任务列表只有一次）。

- [ ] **Step 6: 提交**

```bash
git add web/src/pages/WorkspacePage.tsx web/src/pages/WorkspacePage.test.tsx
git commit -m "feat: 确认完跳进工作台即开写，刷新不重复入队"
```

---

# 一期 C：短篇工作台收口 + 账号成本口径

## Task 15: 管理面板的成本归属口径

**Files:**
- Modify: `src/myink/api/routes_admin.py`
- Modify: `src/myink/api/admin_schemas.py`
- Test: `tests/test_admin.py`（追加）

**Interfaces:**
- Consumes: `AgentRun.user_id`（Task 3）
- Produces: `/admin/users` 的 `metrics.cost_est` 含账号级花费；`/admin/runs?user_id=` 与列表显示的归属同源；`AdminRun.project_id/username/project_title` 可空

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_admin.py`：

```python
def test_user_cost_includes_account_level_runs(temp_user, temp_project):
    """Review Focus 5：没有书的调用（建书对话）也要算进这个人的花费，且点得进去看明细。"""
    with new_session() as db:
        db.execute(text("UPDATE projects SET user_id = :uid WHERE id = :pid"),
                   {"uid": temp_user, "pid": temp_project})
        db.add(AgentRun(user_id=uuid.UUID(temp_user), node="short_creation", role="Planner",
                        model_id="m", input_tokens=10, output_tokens=20, cost_est=7.5))
        db.commit()

    users = admin_client.get("/api/v1/admin/users", params={"q": temp_user}).json()["items"]
    assert users[0]["metrics"]["cost_est"] >= 7.5

    runs = admin_client.get("/api/v1/admin/runs", params={"user_id": temp_user}).json()
    assert any(run["node"] == "short_creation" for run in runs["items"])
    account_run = next(run for run in runs["items"] if run["node"] == "short_creation")
    assert account_run["project_id"] is None
    assert account_run["project_title"] is None
    assert account_run["username"] is not None       # 账号名兜底填上，列表不会开天窗

    detail = admin_client.get(f"/api/v1/admin/runs/{account_run['id']}")
    assert detail.status_code == 200                 # 详情页也要能直接打开
```

（`admin_client` 与 `temp_project`/`new_session` 按该文件现有写法对齐；`temp_user` 来自 conftest。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_admin.py -q -k account_level`
Expected: FAIL —— `users[0]["metrics"]["cost_est"]` 不含 7.5，或 `/runs` 直接 500/空（外连接之前，`project_id` 为 NULL 的行被内连接丢掉）

- [ ] **Step 3: 实现**

`src/myink/api/routes_admin.py` 的 `users()`：

```python
    owned = select(Project.id).where(Project.user_id == User.id).correlate(User)
    # 归属口径与 _run_statement 显示的同源：有书看书的作者（老行没有 user_id），
    # 没有书才看账号（建书对话、文风提取）。两处不一致，列表里的行数就与总花费对不上。
    run_owner = or_(AgentRun.project_id.in_(owned),
                    and_(AgentRun.project_id.is_(None), AgentRun.user_id == User.id))
```

`*_metric_columns(AgentRun.project_id.in_(owned))` → `*_metric_columns(run_owner)`。`_task_average_columns` 那行不动（任务永远属于一本书）。

`_run_statement`：

```python
def _run_statement(detail=False):
    fields = ("id", "project_id", "task_id", "node", "role", "model_id", "input_tokens", "output_tokens",
              "cost_est", "duration_ms", "cache_hit", "degraded", "retry_count", "created_at", "updated_at")
    columns = [getattr(AgentRun, f) for f in fields]
    if detail:
        columns += [AgentRun.detail, AgentRun.error]
    # 外连接：账号级运行没有 project_id，内连接会把它们整行丢掉（成本就对不上了）。
    # username 用 coalesce 兜底到账号名，列表里不会开天窗。
    account = aliased(User)
    return select(*columns,
                  func.coalesce(Project.user_id, AgentRun.user_id).label("user_id"),
                  func.coalesce(User.username, account.username).label("username"),
                  Project.title.label("project_title"))\
        .outerjoin(Project, Project.id == AgentRun.project_id)\
        .outerjoin(User, User.id == Project.user_id)\
        .outerjoin(account, account.id == AgentRun.user_id)
```

`runs()` 的用户筛选：

```python
    if user_id:
        stmt = stmt.where(or_(Project.user_id == user_id,
                              and_(AgentRun.project_id.is_(None), AgentRun.user_id == user_id)))
```

顶部导入补 `aliased`、`and_`（`or_` 已有）。

`src/myink/api/admin_schemas.py` 的 `AdminRun`：

```python
    project_id: UUID | None          # 账号级运行（建书对话/文风提取）没有书
    user_id: UUID
    username: str | None
    project_title: str | None
```

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_admin.py -q`
Expected: PASS（新用例 + 既有全绿）

- [ ] **Step 5: 提交**

```bash
git add src/myink/api/routes_admin.py src/myink/api/admin_schemas.py tests/test_admin.py
git commit -m "feat: 管理面板认账号级花费——总账与明细同源"
```

---

## Task 16: 管理面板用户 tab 与用户详情页

**Files:**
- Modify: `web/src/lib/adminApi.ts`、`web/src/pages/AdminPage.tsx`、`web/src/router.tsx`
- Create: `web/src/pages/admin/UserDetail.tsx`
- Test: `web/src/pages/AdminPage.test.tsx`（追加）

**Interfaces:**
- Consumes: `adminApi.listUsers`（已存在）、`adminApi.listRuns(token, { userId })`（已存在）、`AdminRun` 放宽后的类型、`shared.tsx` 的 `DetailPage`/`useResource`/`RunTable`
- Produces: `/admin/users/:userId` 路由；TABS 里的「用户」

- [ ] **Step 1: 写失败测试**

追加到 `web/src/pages/AdminPage.test.tsx`。先扩 `buildRouter` 的 children：

```tsx
        { path: 'users/:userId', element: <UserDetailPage /> },
```

再写用例：

```tsx
it('lists users with their total spend and opens one user detail page', async () => {
  vi.mocked(adminApi.listUsers).mockResolvedValue({
    items: [{
      id: 'user-1', username: 'alice', tier: 'normal', role: 'user',
      project_count: 2, chapter_count: 8, word_count: 9000, task_count: 3,
      metrics: { ...metrics, cost_est: 12.3456 }, task_averages: taskAverages,
    }], total: 1, limit: 25, offset: 0,
  })
  vi.mocked(adminApi.listRuns).mockResolvedValue({
    items: [{
      id: 30, project_id: null, user_id: 'user-1', username: 'alice', project_title: null,
      task_id: null, node: 'short_creation', role: 'Planner', model_id: 'model-a',
      input_tokens: 10, output_tokens: 20, cost_est: 0.5, duration_ms: 900,
      cache_hit: false, degraded: false, retry_count: 0,
      created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:01Z',
    }], total: 1, limit: 25, offset: 0,
  })
  const { router } = renderPage()
  fireEvent.click(screen.getByRole('button', { name: '用户' }))

  expect(await screen.findByText('12.3456')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '查看用户 alice' }))

  expect(router.state.location.pathname).toBe('/admin/users/user-1')
  expect(await screen.findByRole('heading', { name: /alice/ })).toBeTruthy()
  // 没有书的那次调用也要看得见，且作品一栏不开天窗
  expect(await screen.findByText('short_creation')).toBeTruthy()
  expect(adminApi.listRuns).toHaveBeenCalledWith('token-admin', { userId: 'user-1', limit: 25, offset: 0 }, expect.any(AbortSignal))

  fireEvent.click(screen.getByRole('link', { name: '返回' }))
  expect(router.state.location.pathname + router.state.location.search).toBe('/admin?tab=users')
})


it('keeps a taskless run row readable when the book is gone', async () => {
  vi.mocked(adminApi.listRuns).mockResolvedValue({
    items: [{
      id: 31, project_id: null, user_id: 'user-1', username: 'alice', project_title: null,
      task_id: null, node: 'style_extract', role: 'StyleExtract', model_id: 'model-a',
      input_tokens: 1, output_tokens: 2, cost_est: 0.01, duration_ms: 10,
      cache_hit: false, degraded: false, retry_count: 0,
      created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:01Z',
    }], total: 1, limit: 25, offset: 0,
  })
  renderPage('/admin/users/user-1')
  expect(await screen.findByText('style_extract')).toBeTruthy()
  expect(screen.getAllByText('—').length).toBeGreaterThan(0)
})
```

- [ ] **Step 2: 跑测试确认失败**

Run（在 `web/` 下）: `npm test -- src/pages/AdminPage.test.tsx`
Expected: FAIL —— `UserDetailPage` 未导入 / 没有「用户」按钮

- [ ] **Step 3: 实现**

`web/src/lib/adminApi.ts` 的 `AdminRun`：

```ts
  project_id: string | null
  project_title: string | null
  username: string | null
```

`web/src/pages/admin/UserDetail.tsx`：

```tsx
/** 用户详情：这个人的总花费，以及构成它的每一次调用（含没有任何作品的那些）。 */
import { useCallback } from 'react'
import { useOutletContext, useParams } from 'react-router-dom'
import { adminApi, type AdminRun, type AdminUser } from '../../lib/adminApi'
import {
  type AdminOutletContext,
  DetailPage,
  formatCost,
  formatDate,
  LoadState,
  Metrics,
  PAGE_SIZE,
  useResource,
} from './shared'
import { RunTable } from './RunDetail'
import styles from '../AdminPage.module.css'

export function UserDetailPage() {
  const { token, onForbidden } = useOutletContext<AdminOutletContext>()
  const { userId = '' } = useParams()
  const loadUser = useCallback(
    (signal: AbortSignal) => adminApi.listUsers(token, { q: userId, limit: 1, offset: 0 }, signal),
    [token, userId],
  )
  const loadRuns = useCallback(
    (signal: AbortSignal) => adminApi.listRuns(token, { userId, limit: PAGE_SIZE, offset: 0 }, signal),
    [token, userId],
  )
  const user = useResource(loadUser, onForbidden)
  const runs = useResource(loadRuns, onForbidden)
  const value: AdminUser | undefined = user.data?.items[0]
  const [selected, setSelected] = useState<number | null>(null)

  return (
    <DetailPage heading={value ? `${value.username} · 账号详情` : '账号详情'} backTab="users">
      <LoadState {...user} empty={!value}>
        {value && <div className={`panel ${styles.panel}`}>
          <h3>总花费 {formatCost(value.metrics.cost_est)}</h3>
          <p>{value.tier} · {value.role} · 作品 {value.project_count} 本 · 创建于 {formatDate(value.id)}</p>
          <Metrics value={value.metrics} />
        </div>}
      </LoadState>
      <section className={`panel ${styles.panel}`}>
        <h3>调用明细</h3>
        <LoadState {...runs} empty={runs.data?.items.length === 0}>
          {runs.data && <RunTable runs={runs.data.items} onSelect={(run) => setSelected(run.id)} />}
        </LoadState>
      </section>
      {selected !== null && <RunDetailView token={token} runId={selected} onForbidden={onForbidden} />}
    </DetailPage>
  )
}
```

上面有两处占位到要落地时必须核实：`formatDate(value.id)` 是错的（`created_at` 才是时间；`AdminUser` 若没有 `created_at` 就删掉这半句），以及 `RunDetailView` 的导出名与 props（`grep -n "RunDetailView" web/src/pages/admin/RunDetail.tsx`）。**`RunTable` 需要能忍受 `project_title: null`**：改 `RunDetail.tsx` 里那一格为 `{run.project_title ?? '—'}`。

`AdminPage.tsx`：`TABS` 加 `['users', '用户']`（放在 `['projects','作品']` 之前），`type Tab` 加 `'users'`，加 `UsersView`：

```tsx
function UsersView({ token, onForbidden }: { token: string; onForbidden: () => void }) {
  const [draftQ, setDraftQ] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const navigate = useNavigate()
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listUsers(token, { q, limit: PAGE_SIZE, offset }, signal),
    [offset, q, token],
  )
  const resource = useResource<PageResult<AdminUser>>(load, onForbidden)
  const submit = (event: FormEvent) => { event.preventDefault(); setOffset(0); setQ(draftQ.trim()) }
  return (
    <section className={styles.view} aria-labelledby="users-heading">
      <div className={styles.viewHead}><div><h2 id="users-heading">用户</h2></div><RefreshButton onClick={resource.retry} /></div>
      <form className={styles.filters} role="search" aria-label="用户筛选" onSubmit={submit}>
        <label><span>用户名或 ID</span><input className="input" value={draftQ} maxLength={128} onChange={(e) => setDraftQ(e.target.value)} /></label>
        <button className="btn btn-primary" type="submit">筛选</button>
      </form>
      <LoadState {...resource} empty={resource.data?.items.length === 0}>
        {resource.data && <>
          <div className={styles.tableWrap}><table><thead><tr>
            <th>用户</th><th>等级</th><th>作品</th><th>章节</th><th>字数</th><th>运行</th><th>总花费</th><th>操作</th>
          </tr></thead>
            <tbody>{resource.data.items.map((user) => <tr key={user.id}>
              <td><strong>{user.username}</strong></td>
              <td>{user.tier}</td>
              <td>{user.project_count}</td>
              <td>{user.chapter_count}</td>
              <td>{user.word_count.toLocaleString()}</td>
              <td>{user.metrics.run_count}</td>
              <td>{formatCost(user.metrics.cost_est)}</td>
              <td><button type="button" className="btn btn-quiet" aria-label={`查看用户 ${user.username}`} onClick={() => navigate(`/admin/users/${user.id}`)}>查看</button></td>
            </tr>)}</tbody></table></div>
          <Pagination total={resource.data.total} offset={offset} onChange={setOffset} />
        </>}
      </LoadState>
    </section>
  )
}
```

并在 `AdminConsole` 的 tab 渲染里加 `{tab === 'users' && <UsersView token={token} onForbidden={onForbidden} />}`，`AdminUser` 类型按需导入。

`web/src/router.tsx`：`import { UserDetailPage } from './pages/admin/UserDetail'`，children 加 `{ path: 'users/:userId', element: <UserDetailPage /> }`。

- [ ] **Step 4: 跑测试与类型闸**

Run（在 `web/` 下）: `npm test -- src/pages/AdminPage.test.tsx && npm run lint && npm run build`
Expected: 全绿

- [ ] **Step 5: 手工验证**

管理面板 →「用户」→ 有人的总花费数字 → 点「查看」→ 跳到 `/admin/users/<id>`，明细里能看到 `short_creation` 这种没有作品的行，「作品」一栏是 `—`；「返回」回到用户 tab。再点开某一行 → 运行详情整页打开。

- [ ] **Step 6: 提交**

```bash
git add web/src/lib/adminApi.ts web/src/pages/admin/UserDetail.tsx web/src/pages/admin/RunDetail.tsx web/src/pages/AdminPage.tsx web/src/router.tsx web/src/pages/AdminPage.test.tsx
git commit -m "feat: 管理面板用户 tab——总花费点进去看每次调用"
```

---

## Task 17: 短篇工作台收口（去掉长篇那套设定/阶段）

短篇没有 L1/L2 账本、没有伏笔池、没有全局审计，也没有「先确认逐章方案再写」这一步。前端别再给用户摆这些入口。

**Files:**
- Modify: `web/src/pages/WorkspacePage.tsx`
- Modify: `web/src/components/ProjectRail.tsx`
- Test: `web/src/pages/WorkspacePage.test.tsx`、`web/src/components/ProjectRail.test.tsx`（各追加）

**Interfaces:**
- Consumes: 现有 `isShortBook`（`WorkspacePage.tsx:66`）
- Produces: 无（纯收口）

- [ ] **Step 1: 写失败测试**

追加到 `web/src/pages/WorkspacePage.test.tsx`（照该文件的短篇用例形状）：

```tsx
it('never shows the plan stage or the plan confirmation for a short book', async () => {
  renderWorkspace({ form: 'short' })
  await waitFor(() => expect(screen.queryByRole('button', { name: '方案' })).toBeNull())
  expect(screen.queryByText('逐章方案')).toBeNull()
})
```

追加到 `web/src/components/ProjectRail.test.tsx`：

```tsx
it('hides the long-form ledger entries inside a short book', () => {
  renderRail({ projectId: 'p1', projects: [{ id: 'p1', title: '渡船', form: 'short' }] })
  expect(screen.queryByRole('link', { name: '设定' })).toBeNull()
  expect(screen.queryByRole('link', { name: '全局审计' })).toBeNull()
  expect(screen.queryByRole('link', { name: '创作设置' })).toBeNull()
})
```

（`renderRail` 是示意名——按该文件现有渲染辅助写；断言里的链接名按实际文案。）

- [ ] **Step 2: 跑测试确认失败**

Run（在 `web/` 下）: `npm test -- src/pages/WorkspacePage.test.tsx src/components/ProjectRail.test.tsx`
Expected: FAIL —— 短篇工作台仍渲染「方案」按钮与三处 rail 链接

- [ ] **Step 3: 实现**

`WorkspacePage.tsx`：把「计划视图」的判据收成一处，nav 与内容都用它——

```tsx
  // 短篇一次成稿：没有逐章方案要确认，也没有 Plan 阶段。后面几处「续跑后跳回计划视图」
  // 的调用点仍然会 setCenterView('plan')，所以判据必须落在渲染侧，而不是它们的调用侧。
  const showPlanView = !isShortBook && centerView === 'plan'
```

`{centerView === 'plan' ? <ChapterPlanPanel ... /> : ...}` 换成 `showPlanView ? ...`；`<nav className={styles.stageTabs}>` 那个 Plan 按钮整块用 `{!isShortBook && (...)}` 包起来（只有一个阶段时不留空 nav）。

`ProjectRail.tsx`：`pageLinks` 那一段外面加 `{!isShortBook && (...)}`，其中 `isShortBook` 从已算好的当前作品取：

```tsx
  // 短篇没有设定页/全局审计/分形态的创作设置——这三个入口只对长篇成立。
  const current = projects.find((project) => project.id === projectId)
  const isShortBook = current?.form === 'short'
```

- [ ] **Step 4: 跑测试与类型闸**

Run（在 `web/` 下）: `npm test -- src/pages/WorkspacePage.test.tsx src/components/ProjectRail.test.tsx && npm run lint && npm run build`
Expected: 全绿

- [ ] **Step 5: 手工验证**

打开一本已有短篇：看不到「方案」阶段标签、看不到逐章方案确认；右栏只有整篇成稿面板（无审计/待确认/写作经验）；左栏只有「导出 .md」「删除本书」，没有设定/创作设置/全局审计。打开一本长篇：这些**全都在**（这是本任务最重要的反向验证）。

- [ ] **Step 6: 提交**

```bash
git add web/src/pages/WorkspacePage.tsx web/src/components/ProjectRail.tsx web/src/pages/WorkspacePage.test.tsx web/src/components/ProjectRail.test.tsx
git commit -m "feat: 短篇工作台收口——不再摆长篇的设定与阶段"
```

---

## Task 18: 导出契约 + 全量验证

**Files:**
- Modify: `spec/api-openapi.json`
- Test: `tests/test_api_contract.py`、全套

**Interfaces:**
- Consumes: 前面全部任务
- Produces: 与 `app.openapi()` 逐字节一致的契约文件

- [ ] **Step 1: 导出**

Run: `myink contract export`
Expected: `spec/api-openapi.json` 更新（新增 `/api/v1/style-library*` 与 `/api/v1/short/creation*` 共 8 条路径操作）

- [ ] **Step 2: 后端全量**

Run: `python -m pytest tests/ -q`
Expected: 全绿。**若有 skip，逐条确认是环境缺失还是真跳过**（集成测试需要隔离的 PostgreSQL/Redis/RabbitMQ），并把 skip 清单写进最终报告——跳过的检查不算通过。

- [ ] **Step 3: 前端全量**

Run（在 `web/` 下）: `npm run lint && npm test && npm run build`
Expected: 全绿

- [ ] **Step 4: 手工端到端（浏览器只用 Chrome/Edge）**

1. `/short/new`：开场白立现 → 聊到 ready → 右栏改一个字段 → 确认 → 进工作台自动开写 → 整篇成稿出现在一页里。
2. 再进 `/short/new`：看到上一场的对话与「已建好书」状态 →「重新开始」→ 回到干净的开场白。
3. 文风库：`/account` 或建书页导入一段文章 → 命名保存 → 新建一本短篇时选中它 → 建出来的书 `ProjectSettings.style_profile` 是那份文风；**工作台里没有换文风的入口**。
4. 管理面板 →「用户」→ 总花费含刚才那次建书对话的花费 → 点进去看到 `short_creation` 的行。
5. 长篇建书与长篇工作台**逐项对照改动前**：向导、设定、大纲确认、Plan 阶段、审计/待确认/经验面板全在，行为没变。

- [ ] **Step 5: 提交**

```bash
git add spec/api-openapi.json
git commit -m "chore: 导出 API 契约（文风库 + 建书对话）"
```

---

## Self-Review

**1. Spec 覆盖**

| spec 要求 | 落点 |
| --- | --- |
| 短篇建书 = 对话式、可编辑、独立于长短篇入口 | Task 7-14（`/short/new` 两栏页） |
| 一期只短篇，长篇不动 | Global Constraints + Task 12（长篇分支逐字保留）+ Task 18 Step 4.5 反向验证 |
| 方案卡字段（暂定名/方向/主角压力/核心冲突/章数/每章字数/文风） | Task 7（卡 schema）+ Task 14（右栏表单） |
| 章数/每章字数：卡给默认、可改、保留护栏 | Task 7（默认 5/4000）+ Task 13（`resolve_short_lengths` 归一）+ Task 14（1–10 / 1000–8000 输入） |
| 短篇工作台 = 整篇一页 + 分章目录 | Task 17（去 Plan 阶段与账本 rail）；分章目录用现有 `ChapterList`，`导出 .md` 已有 |
| 文风：建书时导入文章提取、可命名保存、之后长短篇都能用 | Task 4/5/6（文风库）+ Task 13（`_style_for` 落进 `ProjectSettings`） |
| 文风建书后不可改 | Global Constraints；Task 14 的 `<small>` 明说；无换文风端点 |
| 成本记账 + 管理面板显示总花费、点开看每次明细 | Task 3（归属放宽）+ Task 15（口径）+ Task 16（用户 tab 与详情页） |
| 对话角色 = `planner` | Task 9（`role="Planner"`）与 Task 10 的测试断言 |
| 不流式、不删旧端点 | 无流式实现；`NewProjectPage`/既有 style 端点都保留 |
| 硬前提 1：commit 同步产出并落库逐章方案 | Task 12（`_persist_short_outline`）+ Task 13 |
| 硬前提 2：状态推到 `ready`、绕过 `setup_confirmed` | Task 12 的 `_persist_short_outline` |
| 硬前提 3/4：`agent_runs` 可无 project_id、新表不带 project_id | Task 3、Task 1/8 |

**2. 占位扫描**

没有 TBD/「稍后实现」类步骤。Task 11 与 Task 16 里各有一处**明确标注的核实点**（`generate_short_creation_turn` 的返回元组要带上 `resp`；`UserDetail.tsx` 里 `formatDate(value.id)` 与 `RunDetailView` 的导出名），都是有具体替代动作的，不是留白。Task 5 与 Task 10 各有一处「先看清再写」的指令（`validate_profile` 是否抛错、`disable_thinking` 是否要传），理由也写在了原处。

**3. 类型一致性**

- `generate_short_creation_turn` 在 Task 10 以三元组引入、在 Task 11 明确升为四元组，两处都写了这一处耦合，不会各写各的。
- `creation.*` 的六个函数名（`default_card`/`card_patch`/`card_normalize`/`merge_model_card`/`merge_user_card`/`card_ready`/`card_premise`）在 Task 7 定义，Task 11/13 只按这些名字调用。
- `_create_project_row` 的关键字参数在 Task 12 定义，Task 13 的调用逐字对齐（含 `target_words` 缺省 `None`）。
- `ShortCreationOut` 的形状在 Task 11 固定，Task 13（`session.book_id`）与 Task 14（前端类型）都按同一形状读。
- `_run_statement` 的 `coalesce(...).label("user_id")` 与 `runs()` 的筛选条件在 Task 15 里同源，`AdminRun.user_id` 保持非空。

**4. Review Focus 的测试落点**

五条分别落在 Task 7/11（非空合并）、Task 10/11（坏 JSON）、Task 12/13（429 信封）、Task 13（重试不建第二本）、Task 15（账号级花费与明细同源），每条都有可运行断言。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-24-short-creation-assistant.md`. Please review the plan. Which execution approach would you prefer?

- **Subagent-driven** — 每个任务一个新子代理实现 + 一个新审查者把关，最后再整支审查。最彻底；代价是每任务、每次审查各一份新上下文。
- **Native** — 我在本次会话里逐任务实现，最后用一个最强模型的审查者审整支。最省最快；中间没有独立审查直到最后。

**这份计划我推荐 Subagent-driven**，理由：任务是三个相对独立的子系统（文风库 / 建书对话 / 成本口径），但相互之间靠一串精确签名咬着（`make_user_chain`、`_owner_ids`、`generate_short_creation_turn` 的返回元组、`_create_row` 的 kwarg、`ShortCreationOut` 形状）——错一个签名，后面的任务会在错误的接口上继续建，而每个任务的失败都是一次真实前端/数据库状态。逐任务审能把这类错挡在下游之前。

计划是否说到了你要的？选哪种执行方式？
