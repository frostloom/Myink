# 短篇对话式建书（对齐 inkos）+ 账号级文风库 + 成本口径

日期：2026-09-24　形态范围：**只做短篇，长篇完全不动**

## 目标与范围

短篇建书现在与长篇共用同一套三步向导（形态 chip → 设定 → 大纲），只是把第 1 步的开关拨到「短篇」。
这不对：短篇是**一次 LLM 调用出整篇**的独立管道，没有账本、伏笔池、全局审计、跨章一致性问题，
长篇建书那些步骤（设定确认、逐章大纲确认、章节流转）对短篇全是多余产物。

目标：把短篇建书改成 inkos 的做法——**与一个初始大模型对话，模型理解意图后给出方案卡，用户可编辑确认，确认即开写**。
同时把三件挂在这条动线上的事做掉：文风在建书时可导入文章提取并**存成可复用的命名标签**、短篇工作台**只留整篇一页 + 分章目录**、
账号级（尚未建书）的 LLM 耗费**必须记账**且在管理面板能按用户查看总额并下钻到每次调用。

三块工作按序落地，一期只碰短篇：

1. **工作流 1：账号级文风库**（新建表 + 端点，长篇暂时不接入口）
2. **工作流 2：对话式短篇建书**（替换 `/short/new` 的三步向导）
3. **工作流 3：短篇工作台收口 + 成本口径 + 管理面板用户详情页**

## 非目标

- **长篇建书、长篇工作台、长篇的设定/大纲/审计，一行不改。** 现有 `NewProjectPage`、`/long/new`、
  `PUT /projects/{id}/setup`、`PUT /projects/{id}/outline` 的长篇分支全部原样保留。
- 不改 `form` 建后不可变的规则（`ProjectUpdateBody` 仍只暴露 title/genre/target_words）。
- 不做短篇的流式输出（一次请求一次返回，网关已有 180s 长转发足够）。
- 不删 `PUT /projects/{id}/outline`、`PUT /projects/{id}/setup`、`POST /projects/{id}/outline-draft`
  这些老端点。短篇新动线不再调它们，但删除会牵动长篇与旧测试，收益为零。
- 不做「长篇建书时选文风库」的入口（数据模型一期就位，长篇入口以后另开一单）。

## 参照 inkos 的结论（已核对）

- inkos 短篇是独立顶层命令（`packages/cli/src/commands/short-fiction.ts`），不共享长篇建书动线。
- 短篇对话面（`packages/core/src/agent/agent-system-prompt.ts:158-206` `buildShortPrompt`）是纯对话面，
  只有 `propose_action` / `ingest_material` / `retrieve_material` 三个工具；一旦「核心冲突 + 主角压力」清楚
  **就立刻出确认卡**（`propose_action(action=short_run)`，携带 `{direction, chapters, charsPerChapter, cover}`），
  确认后直接跑 `short_fiction_run`，**不建 `books/` 项目**。
- 长篇的对应面（`buildBookCreatePrompt`，同文件 120-156）是同一套「左表单 + 右对话 + 草稿卡」的两栏页
  （`packages/studio/src/pages/BookCreate.tsx`），`canCreateFromDraft` 要求 title+genre+platform+worldPremise+protagonist+conflictCore 齐备。
- 短篇数值口径（`packages/core/src/agents/short-fiction.ts:20-25`）：章数默认 12、区间 12–18；每章字数默认 1000、区间 900–1200。
  **Myink 用自己的口径**（见下），不照搬这三个数。

Myink 与 inkos 的差异点必须落在本设计里：Myink 的短篇**要建项目**（成稿要落库、要审稿/改稿、要记账），
inkos 的短篇不建。所以「确认」这一步在 Myink = 建项目 + 落逐章方案 + 入队生成，比 inkos 重。

## 已确认的决策（用户拍板，不可再改）

| 项 | 决策 |
| --- | --- |
| 建书形态 | 对话式且可编辑，抄 inkos 的「AI 客服」样式，**独立于长短篇建书入口之外**，一期只做短篇 |
| 入口位置 | **短篇分区内的独立对话页**：`/short/new` 变成两栏整页（左=对话流，右=方案卡+确认按钮） |
| 章数/字数 | 确认卡给默认值、**用户可改**，沿用现有护栏 |
| 短篇工作台 | **整篇一页 + 分章目录**（去掉 Plan/正文 阶段 tab、去章节方案确认、去掉书内 设定/全局审计 入口） |
| 文风 | 建书时**可导入文章提取文风**，可**命名保存成标签**，进**账号级文风库**，长篇短篇以后都能用 |
| 文风建后能否换 | **不能换**（所以建成的短篇里没有文风入口） |
| 成本 | 账号级耗费**必须记账**；管理面板只显示用户**总花费**，点击下钻到**每次调用详情** |
| 对话角色 | 对话走 `planner` 角色 |

## 硬前提（决定了编排形状，先写清楚）

1. **短篇生成依赖已落库的逐章方案。** `short_runner.short_params_for()` 的章数取自 `volume_outlines` 第 1 卷
   （`row.outline["chapter_count"]`，回退 `creation_context`），`_outline()` / `_load_brief()` 读同一行。
   所以「确认开写」必须**同步产方案并落库**，否则入队后 worker 拿不到方案。
2. **`_assert_writable` 要求 `creation_status ∈ {ready, legacy_ready}`**（`routes_tasks.py:85`）。
   旧向导里 `ready` 是 `PUT /outline` 在 `setup_confirmed` 之后才置的。对话动线没有「确认设定」这一步，
   所以 commit 必须自己把状态推到 `ready`。
3. **`_load_brief` 直读设定不召回**（`short_runner.py:215-240`）：`world_rules` / `hard_constraints` /
   `characters` / `factions` / `locations` / `style_profile` / `genre_pack`。对话产出里唯一该物化进去的是
   **文风**（用户选的），其余留空是正确语义——短篇本来就没有设定页，写手靠方案本身。
4. **账号级调用今天记不进账。** `agent_runs.project_id` 是 NOT NULL，而 `record_run` 只收 `project_id`。
5. **RLS 是按列名自动开的**（`db.py:96-119`）：一张表只要有 `project_id` 列就会被 `ENABLE + FORCE ROW LEVEL SECURITY`，
   策略读 `current_setting('app.tenant_id')`。账号级请求没有租户上下文，所以**新建的账号级表不能有 `project_id` 列**
   （名字也不能叫 `project_id`，`book_id` 或 `run_id` 都不触发）。`agent_runs` / `tasks` 在 `_NO_RLS_TABLES` 白名单里，不受此规则。

---

# 工作流 1：账号级文风库

## 数据模型

新文件 `src/myink/models/creation.py`，并在 `models/__init__.py` 里导出（`Base.metadata.create_all` 会自动建表）。

```python
class StyleLibraryItem(Base, TimestampMixin):
    """账号级文风标签：user_id 归属，无 project_id（见「硬前提 5」）。"""
    __tablename__ = "style_library_items"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_style_library_user_name"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)   # 与 ProjectSettings.style_profile 同构
    note: Mapped[str] = mapped_column(String(200), nullable=False, default="") # 用户备注，可空串
    sample_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0) # 抽取所用样例总字数
```

`profile` 形状 = 现有 `StyleProfile`（`validate_profile` 把关的那份），与 `ProjectSettings.style_profile` 一致，
这样「库里取出来直接写进书」不需要任何转换。

## 端点（新文件 `src/myink/api/routes_style_library.py`，全部 `require_user`）

身份一律取自 token，**没有任何 `project_id` 路径参数**，访问控制靠 `where(user_id == uid)` 显式过滤。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/style-library` | 返回 `{items: [...]}`：内置 4 个 `STYLE_PRESETS`（`id="builtin:<preset_key>"`, `builtin=True`, `removable=False`）在前，用户项在后（`builtin=False`）。一次请求喂满选择器。 |
| POST | `/api/v1/style-library/samples` | 体 `{samples: [str]}`（1–2 篇、合计 ≤12000 字，沿用 `_MAX_SAMPLES` / `_MAX_TOTAL_CHARS`）→ `analyze_sample_stats` + `extract_style_profile(..., user_id=uid)` → **不落库**，返回 `{"draft": {...}}`：`merge_style_draft(stats, llm_profile, extract_error=...)` 已经把统计与提取失败并进同一份 draft（含 `source` 与 `extract_error`），所以不另外暴露 `stats`/`error` 两个顶层键。 |
| POST | `/api/v1/style-library` | 体 `{name, profile, note?}` → `validate_profile` → 落库返回 item。重名 409 `NAME_TAKEN`（不静默覆盖）。 |
| DELETE | `/api/v1/style-library/{item_id}` | 删自己的；`builtin:` 前缀或不存在的 id → 404。 |

`GET /skill-presets`（`routes_style.py`）保持原样不动——长篇设置页的「预设导入」还在用它。

## 抽取改造成账号级

`style_extract.py:extract_style_profile` 加一条账号级路径：

```python
def extract_style_profile(samples, stats, *, project_id=None, user_id=None, db=None):
    # project_id 与 user_id 二者必居其一；db 非 None 时二者之一必填（agent_runs 归属）
```

- 路由选择：`project_id` 非空 → 走今天的 `make_chain("extract", project_id=..., db=...)`（长篇/旧路径不变）；
  否则 `make_chain_for_user("extract", user_id)`。
- 记账：`record_run(db, project_id=project_id, user_id=user_id, ..., node="style_extract", ...)`。

## 模型路由：新增账号级链

`providers/__init__.py` 加：

```python
_USER_ROLE_FALLBACK: dict[str, tuple[str, ...]] = {
    "planner": ("writer", "extract"),   # 建书对话是用户第一次接触产品，planner 没配也得能用
    "extract": ("planner", "writer"),
}

def make_user_chain(role: str, user_id, db=None) -> FallbackChain:
    """账号级链：只看 users.environment 里的自备连接，不做项目归属解析。"""
```

- 用 `myink.environment.packed_models(user_id)` 取连接，`_lookup_override(role, packed)` 命中自定义路由，
  再按 `_USER_ROLE_FALLBACK` 回退；`thinking_enabled_for_user(user_id)` 决定 thinking。
- **不动 `_ROLE_INHERIT`**：那是项目级的（audit/summarize），改了会波及长篇。
- 一个都没配 → `_no_model_chain`，端点回 200 + 明确错误文案「请先在环境配置里添加模型连接」，
  前端把它当 assistant 消息渲染（不是 500，也不是静默无边）。

## 测试（工作流 1）

`tests/test_style_library.py`：

- 列表含 4 个内置（`builtin=True`）+ 自己的项；**看不到别人的项**（两个 user 交叉验证）。
- `samples` → 落回 `{"draft": {...}}`（`stats` 已并入 draft，不另开顶层键），且 `agent_runs` 多一行 `node="style_extract"`、`project_id IS NULL`、`user_id` = 本人。
- 命名保存后再列表能看到；重名 409；删除后列表消失；删内置 404。
- `validate_profile` 拒绝非法 profile（400）。

---

# 工作流 2：对话式短篇建书

## 页面：`/short/new` 两栏

```
┌─────────────────────────────────┬──────────────────────────┐
│ 对话流（正序，自动滚到底部）        │ 方案卡（可编辑）           │
│  · assistant 气泡（reply）        │  暂定名 / 题材方向        │
│  · 方案卡内联渲染成一张卡           │  主角压力 / 核心冲突      │
│  · user 气泡                      │  情绪回报 / 大致情节      │
│                                   │  章数 [5] / 每章字数[4000] │
│                                   │  文风 [选择器 ▾]          │
│                                   │  [确认，开写]             │
├─────────────────────────────────┤                          │
│ [输入框………………………………] [发送]      │                          │
└─────────────────────────────────┴──────────────────────────┘
```

- 左侧对话流是真相来源；右侧卡是**同一份 card 的可编辑视图**。合并规则只有一条：
  **模型返回的字段只覆盖它非空的字段**（空字段保留现值）。这样用户改过的字段不会被模型的空字段抹掉，
  用户确实想改标题就直接改，模型下一轮给出新标题时也顺理成章地接过去。用户改完卡可以直接点确认（不再发话），
  也可以继续发话让模型接着聊。
  代价：模型无法把某个字段**清空**（只能用户自己在卡上删）——比模型一轮走神就把用户写好的一段抹掉划算。
- 章数/每章字数可编辑，护栏沿用 `resolve_short_lengths`（1–10 / 1000–8000 / 合计 ≤20000，超限按比例压并提示）。
- 文风选择器列「内置预设 + 我的文风库」，可**导入文章现场提取**（选文件/粘正文 → `POST /style-library/samples` →
  展示 draft → 命名保存 → 自动选中）。文风是**可选**的。这一行属于**会话**（`style_item_id`/`style_name`），
  不是模型卡的字段——理由见下。
- 顶部一行「重新开始」：清空本会话（`DELETE /short/creation`），从头聊。

## 会话数据模型（同 `models/creation.py`）

```python
class ShortCreationSession(Base, TimestampMixin):
    """每用户一条活跃建书会话。无 project_id 列（RLS 规则）；书名列叫 book_id。"""
    __tablename__ = "short_creation_sessions"
    id: Mapped[uuid.UUID] = ...          # PK
    user_id: Mapped[uuid.UUID] = ...     # nullable=False, unique（一期：一人一条）
    card: Mapped[dict] = ...             # JSON，当前卡（用户编辑后的版本）
    book_id: Mapped[uuid.UUID | None]    # 确认后指向建成的那本书
    status: Mapped[str] = ...            # 'active' | 'committed'，String(16)
    style_item_id: Mapped[str | None]    # 'builtin:<key>' 或库里 item id，String(48)
    style_name: Mapped[str | None]       # String(64)，展示用

class ShortCreationMessage(Base, TimestampMixin):
    __tablename__ = "short_creation_messages"
    __table_args__ = (Index("ix_short_creation_messages_session", "session_id", "id"),)
    id: Mapped[int] = ...                # BigInteger PK autoincrement
    session_id: Mapped[uuid.UUID] = ...  # index
    role: Mapped[str] = ...              # 'user' | 'assistant'
    content: Mapped[str] = ...           # Text
    card: Mapped[dict | None] = ...      # 仅 assistant 带
    model_id: Mapped[str | None] = ...   # String(64)
    input_tokens / output_tokens: int    # 默认 0
    cost_est: Mapped[float] = ...        # 默认 0.0
    error: Mapped[str | None] = ...      # String(512)
```

两张表的列名刻意避开 `project_id`（见「硬前提 5」）。`book_id` 是**普通 UUID 列**，不建外键约束
（RLS 表与外键的组合会让跨表校验复杂化，且这里只需要一个指针）。

## 端点（新文件 `src/myink/api/routes_short_creation.py`，前缀 `/api/v1/short/creation`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `` | 取（没有则建）本人活跃会话，返回 `{session, messages, ready, card}`。空会话时**不调模型**，直接落一条固定开场白（省一次调用，也避免首次进页面就失败）。 |
| POST | `/messages` | 体 `{content, card?}`（`card` = 用户编辑过的版本）→ 落 user 消息 → 组历史 → **一次** `planner` 调用 → 解析 → 落 assistant 消息 + 更新 session.card → 返回同 GET 的结构。 |
| POST | `/commit` | 体 `{card, style_item_id?}` → 见「确认编排」。返回 `{project_id, lengths_compressed, plan_warning}`。 |
| DELETE | `` | 清空本人会话（连消息），下次 GET 得全新开场白。 |

## 对话回合

- **一次 LLM 调用**，`json_mode=True`，`disable_thinking=True`（建书对话要快；深度思考交给后面的方案/成稿），
  `node="short_creation"`，`role="planner"`，`task_id=None`，`max_tokens=nodes._MAX_TOKENS["short_creation"]`（新增键，取 1500）。
- 输出契约（Pydantic `ShortCreationTurn`）：`{reply: str, card: ShortCreationCard, ready: bool}`。
- **解析容错沿用 `nodes._parse_json`**：解析失败 → 不 500、不清空卡；把模型原文当 `reply` 返回、
  保留上一版 card、`error` 记进 assistant 消息。前端照样能显示，用户重说一次即可。
- **`ready` 由后端自己算**，不信模型自报（对齐 inkos 的 `canCreateFromDraft`）：
  `working_title / genre / direction / protagonist_pressure / conflict_core / emotional_payoff / plot_sketch` 全部非空。

### 卡字段

```python
class ShortCreationCard(BaseModel):
    working_title: str = ""          # 暂定名；模型缺了要自己拟一个并说明可改
    genre: str = ""                  # 题材方向
    direction: str = ""              # 一句话方向/卖点
    protagonist_pressure: str = ""    # 主角压力
    conflict_core: str = ""          # 核心冲突
    emotional_payoff: str = ""       # 情绪回报
    plot_sketch: str = ""            # 大致情节
    chapter_count: int = 5           # 默认 5
    chars_per_chapter: int = 4000    # 默认 4000（5×4000=20000，正好是 §5 的总量上限）
```

- `chapter_count=5 / chars_per_chapter=4000` 是**和 `docs/SHORT-FORM.md` §5 的表自洽的默认**，不是随便挑的。
- **文风不进 card 的模型契约**：`style_item_id` / `style_name` 是会话行上的字段，由**前端选择器**写。
  模型不了解库里有哪几个标签，让它填 id 只会编出不存在的东西。（inkos 的卡里也没有文风。）

### 提示词（`workflow/prompts.py` 新增）

`short_creation_messages(history: list[dict], card: dict) -> list[dict]`，系统提示的要点：

- 你的任务：通过对话弄清 题材方向 / 主角压力 / 核心冲突 / 情绪回报 / 大致情节 / 暂定名，然后给方案卡。
- 一回合**只问一个**最关键的问题，不要一次抛三个。
- **核心冲突与主角压力一明确就立刻出卡**，不要继续追问细节（inkos 的口径）。
- 暂定名缺失就自己拟一个，并说明可以改。
- 不承诺已经建书或已经开始写作——建书由用户点「确认，开写」触发。
- 章数/每章字数没被提及就用默认值放上卡。
- 用中文，别用 markdown 表格（前端是气泡，不是文档）。

## 确认编排（`POST /short/creation/commit`，同步）

1. `resolve_short_lengths(card.chapter_count, card.chars_per_chapter)` 归一。
   **超限按比例压、不报错**，`lengths_compressed=True` 带回前端提示（沿用 `_short_outline_draft` 的口径）。
2. **建项目**：把 `routes_book.create_project` 里的落库部分抽成内部函数
   `_create_project_row(db, uid, *, title, genre, premise, chapter_count, chars_per_chapter, storyline, form, request_id, genre_pack)`
   → `create_project` 与 commit 共用。**必须共用**：日建书上限（429 `BOOK_CNT_EXCEEDED`）与
   `request_id` 幂等都在这一段里，复制一份就会出现两条上限口径。
   - 参数：`form="short"`、`title=card.working_title`、`genre=card.genre`、
     `premise = direction\n\n核心冲突：…\n\n大致情节：…`（拼成一段，方案生成器只吃一个 premise 字符串）、
     `chapter_count/chars_per_chapter = 归一后的值`、`storyline="")`；**不传 `target_words`**（短篇不填每章目标字数，与现有向导一致）。
3. **产方案 + 审纲**：直接复用 `routes_book._short_outline_draft(project_id, OutlineDraftBody(...), genre, genre_pack, chapter_count, db)`
   → 拿到 `patch`（含 `outline_draft`、`outline_warning`）。审纲建议改稿 → 重出一版；两版都不过 → 保留第一版 + warning（现有行为，不改）。
4. **落方案并置 ready**：`build_persisted_short_outline(...)` + `validate_short_outline(payload)` →
   写 `VolumeOutline(project_id, volume_seq=1, title="整书大纲", outline=payload)`，
   `creation_status = "ready"`，`creation_context` 合入 `{premise, chapter_count, chars_per_chapter, outline_draft: payload, creation_conversation: {direction, conflict_core, plot_sketch}}`。
   - 这就是 `put_outline` 的短篇分支**去掉 `setup_confirmed` 闸门**的版本——对话动线没有设定页，
     设定卡就是那张方案卡。把这段抽成 `_persist_short_outline(db, pid, payload)`，`put_outline` 与新 commit 共用。
5. **写文风**（可选）：`style_item_id` 非空时写 `ProjectSettings.style_profile`：
   - `builtin:<key>` → `style_profile = STYLE_PRESETS[key]["style_profile"]`，同时 `skill_pack = key`
     （预设 id 就是 skill_pack marker，`routes_style.py:60` 的口径）。
   - 库 item id → `style_profile = item.profile`，`skill_pack = None`。
   - `version` 递增（对齐 `PUT /style-profile`）。
6. 会话置 `status='committed'`、`book_id=project_id`；返回 `{project_id, lengths_compressed, plan_warning}`。

**入队不放在 commit 里。** 前端拿到 `project_id` 后调**现有的** `POST /projects/{id}/short/generate`
（它自己算额度 `quota_n=chapter_count`、算 `cost_est`、`_assert_writable` 通过因为已 ready），
成功后跳 `/projects/{id}`。理由：把扣额度的逻辑复制进 commit 就会出现第二套计费口径，
而这里的部分失败是**可恢复的**——工作台上「开始写全篇」就是重试按钮，入队失败时跳工作台并提示重试，不静默。

## 测试（工作流 2）

`tests/test_short_creation.py`：

- `GET` 空会话 → 落开场白，**不打模型**（stub 断言零调用）。
- `POST /messages` → 模型返回 JSON → assistant 消息落库、card 更新、`ready` 计算正确
  （6 个文本字段缺一 → `ready=false`）。
- 模型返回非 JSON → 200、`reply` = 原文、card 不变、assistant 消息 `error` 非空。
- 用户带 `card` 提交编辑 → 落库 card 是用户的版本。
- `POST /commit`：
  - 建出 `form='short'`、`creation_status='ready'` 的书；`volume_outlines` 第 1 卷有逐章 `chapters`；
    `creation_context.chapter_count` = 归一后的章数。
  - `resolve_short_lengths` 触发压缩时 `lengths_compressed=true`，且落库值是压缩后的（不是用户填的）。
  - 带 `builtin:xianxia-jiuzhou` → `style_profile` 等于预设、`skill_pack` = 该 key；带库 item id → `style_profile` 等于 item.profile、`skill_pack` 为 None。
  - commit 之后可以直接 `POST /projects/{id}/short/generate` 成功（`_assert_writable` 通过，不因为状态卡住）。
  - 日建书上限仍然生效（第 N+1 本 → 429 `BOOK_CNT_EXCEEDED`）——验证与 `create_project` 共用同一段逻辑。
- 两个用户各聊各的，互相看不到对方的会话与消息。
- `DELETE` 后再 `GET` 是全新开场白。

`tests/test_prompts.py`（或就近）：`short_creation_messages` 把历史顺序与当前 card 都喂进去，系统提示含「一次只问一个」等约束标志串。

---

# 工作流 3：短篇工作台收口 + 成本口径

## 3.1 短篇工作台

`web/src/pages/WorkspacePage.tsx`（`isShortBook` 分支，现有分支已存在）：

- **删**中间栏的 Plan/正文 阶段 tab 与 `ChapterPlanPanel` 的章节方案确认；短篇只保留「整篇成稿」视图：
  分章目录（各章标题 + 字数 + 审稿结论） + 逐章正文渲染 + 「导出 .md」。
- 右栏保持（`ShortStoryPanel` + `GenerationPanel` + `TaskTimeline`）：审稿结论、生成入口、任务时间线。
- `web/src/components/ProjectRail.tsx`：短篇书（`form === 'short'`）**不渲染** 设定(`/lore`)、创作设置(`/settings`)、
  全局审计(`/audit`) 三条书内链接。**不给任何替代入口**（文风建后不能换）。
  `/projects/{id}/settings|audit|lore` 三条路由保留（不删，直接访问仍可达）——一期不做路由级封锁，
  只做入口级收口；`ProjectRail` 早有 `form` 判断（`section` 那行），在这里收敛成「短篇只留工作台链接」。
- `/short/new` 路由从 `NewProjectPage form="short"` 换成新的 `ShortCreationPage`。
  `NewProjectPage` 只服务于长篇（`/long/new` 与 `/projects/new`），**长篇路径一行不改**。
- `web/src/lib/projectCreation.ts` 的 `projectHref`：短篇书（**含 draft**）一律回 `/projects/<id>`
  （对话页无法「续接」一个建了一半的书），长篇草稿仍回 `/long/new?draft=<id>`。**遗留短篇草稿**见「风险」。

## 3.2 `agent_runs` 支持账号级记账

`src/myink/models/runs.py`：

```python
project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)   # 由 NOT NULL 改为可空
user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)      # 新增：账号级行只有它
```

`src/myink/db.py` 加幂等迁移 `ensure_agent_run_user()`（挂在 `cli.py` 的 init 序列里，照 `ensure_project_form` 的写法）：

```sql
ALTER TABLE agent_runs ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS user_id UUID;
CREATE INDEX IF NOT EXISTS ix_agent_runs_user_id ON agent_runs (user_id);
```

**纯 DDL，不做回填。** 原因：存量项目级行的 `user_id` 留 NULL 也能被正确统计——见下面的聚合口径。
不做回填就少一个数据步、少一个「回填跑了没跑完」的窗口，也不会在迁移里因为 RLS 读不到 `projects` 而静默失败。
`agent_runs` 在 `_NO_RLS_TABLES` 白名单里，改列对 RLS 无影响。

`workflow/nodes.py`：

```python
def record_run(db, *, project_id: str | None = None, user_id=None, task_id, node, role, resp, ...)
def record_plain(db, *, project_id: str | None = None, user_id=None, task_id, node, ...)
```

两个参数都可空、都不在调用点强制传（现有 30+ 个调用点一个不改）；至少一个非空（都空则 `ValueError`，
记账不能没有归属）。入库时 `project_id=uuid.UUID(project_id) if project_id else None`，`user_id` 同理。

## 3.3 管理面板：按用户总额 + 每次调用下钻

`routes_admin.py`：

- `/users`（端点已存在）的指标聚合条件改为**两列取或**：
  ```python
  per_user = or_(AgentRun.user_id == User.id, AgentRun.project_id.in_(owned))
  *_metric_columns(per_user)
  *_task_average_columns(lambda per_task: per_task.c.project_id.in_(owned))   # 任务维度只有项目级，不变
  ```
  `or_` 让存量行（只有 `project_id`）与新的账号级行（只有 `user_id`）都被计入**同一个用户总额**。
  修改点只有这两个条件，`_metric_columns` / `_task_average_columns` 本身不动。
- `_run_statement()`：`inner join Project/User` → **outer join**，否则账号级行（`project_id IS NULL`）在运行列表里**整行消失**：
  ```python
  select(*columns, Project.user_id, User.username, Project.title.label("project_title"))
    .outerjoin(Project, Project.id == AgentRun.project_id)
    .outerjoin(User, User.id == Project.user_id)
  ```
  账号级行的 `user_id` / `username` 从 `AgentRun.user_id` 补：再加一个 `aliased(User)` 按 `AgentRun.user_id` 连接，
  行里取 `coalesce(u_project.id, u_run.id)`、`coalesce(u_project.username, u_run.username)`（`_run_row` 里做）。
- `/runs` 的 `user_id` 过滤同样改成 `or_(AgentRun.user_id == user_id, Project.user_id == user_id)`，
  否则账号级调用按用户筛不出来。
- `admin_schemas.py`：`AdminRun.project_id: UUID | None`、`project_title: str | None`
  （`AdminRunDetail` 继承，跟着变）。`AdminUser` 不改（`metrics.cost_est` 就是总花费）。

前端：

- `web/src/lib/adminApi.ts` 的 `AdminRun` 类型跟着放宽两处。`listUsers` 与 `getProject` **都已存在**
  （`adminApi.ts:367`、`:377`），前端要新增的只有 `UserDetail.tsx` 与用户 tab。
- `AdminPage.tsx` 的 `TABS` 加 `['users', '用户']`：表格列 用户 / 等级 / 角色 / 作品 / 章节 / 字数 / 任务 / **总花费** / 操作，
  「总花费」=`formatCost(user.metrics.cost_est)`；「查看」→ `navigate('/admin/users/${user.id}')`。
- 新页 `web/src/pages/admin/UserDetail.tsx`（照 `ProjectDetail.tsx` 的写法，`DetailPage` + `backTab="users"`）：
  用户摘要（用户名/等级/角色/作品数/总花费/运行数）+ 该用户全部调用的 `RunTable`
  （`GET /admin/runs?user_id=<id>`，`RunTable` 已导出可复用）；点某次调用 → 现有 `/admin/runs/{id}` 详情页。
  `RunTable` 里 `project_title` 为 null 的行显示 `—`（账号级调用没有作品）。
- `web/src/router.tsx` 的 `/admin` 子路由加 `{ path: 'users/:userId', element: <UserDetailPage /> }`。

## 测试（工作流 3）

后端 `tests/test_admin.py` / 新增 `tests/test_admin_user_spend.py`：

- 同一用户：一本长篇 + 一条账号级调用 → `/admin/users` 的 `metrics.cost_est` = 两者之和；
  `run_count` = 两者之和。
- `/admin/runs` 能列出账号级行（`project_id`/`project_title` 为 null）；按 `user_id` 筛能筛到它。
- 账号级行的 `/admin/runs/{id}` 详情正常返回（含 detail 捕获）。
- 迁移：`ensure_agent_run_user()` 跑两遍幂等；老库（`project_id NOT NULL`）跑完能插入 NULL 行。

前端：

- `AdminPage.test.tsx`：用户 tab 渲染总花费、点「查看」跳 `/admin/users/<id>`、详情页点一次调用跳 `/admin/runs/<id>` 并回到 `?tab=users`。
- `RunTable` 里 `project_title` 为 null 不崩（渲染 `—`）。
- `WorkspacePage.test.tsx`：短篇分支**没有**阶段 tab、**没有**章节方案确认；长篇分支原样（回归）。
- `ProjectRail.test.tsx`：短篇书的书内链接只有工作台（无 设定/创作设置/全局审计）。
- 新增 `ShortCreationPage.test.tsx`：对话渲染、发送→card 更新、改章数→commit 载荷是改后的值、
  文风选择器可选内置与自建项、「确认，开写」的忙碌态与失败提示。

## 契约

`spec/api-openapi.json` 必须与 `app.openapi()` 字节一致（`tests/test_api_contract.py`）。
新增 6 个端点 + `AdminRun` 两处放宽 → 收尾用 typer 控制台命令重新导出：

```
myink contract export
```

---

# 要动的文件清单（便于估量）

**后端新增**：`models/creation.py`、`api/routes_style_library.py`、`api/routes_short_creation.py`、`short/creation.py`（卡 schema + ready 判定 + premise 拼装，纯函数好测）。

**后端改动**：`models/__init__.py`（导出）、`models/runs.py`（两列）、`db.py`（`ensure_agent_run_user`）、
`cli.py`（挂迁移）、`workflow/nodes.py`（`record_run`/`record_plain` 签名 + `_MAX_TOKENS` 加 `short_creation` 键）、
`workflow/prompts.py`（对话提示词）、`providers/__init__.py`（`make_user_chain`）、`style_extract.py`（账号级路径）、
`api/routes_book.py`（抽 `_create_project_row` / `_persist_short_outline`，行为不变）、
`api/routes_admin.py`（三处 SQL）、`api/admin_schemas.py`（`AdminRun` 两列可空）、`api/__init__.py`（注册两个新 router）。

**前端新增**：`pages/ShortCreationPage.tsx` + `.module.css` + `ShortCreationPage.test.tsx`、
`pages/admin/UserDetail.tsx`、`lib/styleLibraryApi.ts`（或并入 `lib/api.ts`）。

**前端改动**：`router.tsx`（`/short/new` + `/admin/users/:userId`）、`pages/WorkspacePage.tsx`（短篇整篇一页）、
`components/ProjectRail.tsx`（短篇书内链接收口）、`lib/projectCreation.ts`（短篇（**含草稿**）一律跳 `/projects/<id>`；长篇草稿仍跳 `/long/new?draft=<id>`）、
`lib/adminApi.ts`（`AdminRun` 类型放宽）、`pages/AdminPage.tsx`（用户 tab）、
`pages/admin/RunDetail.tsx`（null 项目名）。

# 验证

1. 后端：`source .local/env-test.sh` + conda `aiink` → `python -m pytest tests/ -q`，
   优先 `tests/test_short_creation.py`、`tests/test_style_library.py`、`tests/test_admin*.py`、
   `tests/test_short*.py`、`tests/test_book*.py`、`tests/test_api_contract.py`。集成测试需要隔离的 PostgreSQL/Redis/RabbitMQ。
2. 前端（`web/`）：`npm run lint`、`npm test`、`npm run build`（**真类型闸是 `npm run build`**）。
3. 手工 E2E（浏览器只能 Chrome / Edge）：`/short/new` 与模型聊三轮 → 卡齐备后「确认，开写」→
   落到短篇工作台且整篇写入排队 → 成稿后整篇一页 + 分章目录可读、可导出 .md、无阶段 tab、
   侧栏无 设定/创作设置/全局审计 → 管理面板「用户」tab 看到自己的总花费 → 点进去看到逐次调用 →
   点一次调用看到 run 详情（含账号级的、没有作品名的那几条）→ 文风：建书时导入一篇文章提取、命名保存、
   确认后本书 `style_profile` 生效且**建完后没有任何换文风入口**。

# 风险与已接受的取舍

- **遗留短篇草稿**（旧向导建到一半、`creation_status='draft'` 的短篇书）：新对话页无法续接，
  `projectHref` 把它们指向工作台，工作台里那些书没有方案、生成会被 400 挡住。
  处置：确认实际数量后手工删除重建（本地/开发库；这些是这一轮短篇功能自己产生的草稿，量极少）。
  **不做**自动迁移——自动把草稿喂进对话会伪造用户没说过的话。
- **commit 与入队分两次调用**：中间失败会留下「有书有计划、没在写」的状态。工作台的「开始写全篇」
  就是这个状态的重试入口，并在入队失败时明确提示。换来的是不复制额度/计费逻辑。
- **账号级调用依赖用户配过模型连接**：`planner` 没配时按 `writer → extract` 回退，全没有就给明确引导文案。
  这是第一次用产品的人最可能踩的坑，所以做的是「明确说清去哪配」，不是静默。
- **`user_id` 允许 NULL 且不回填**：存量行靠 `or_(user_id, project_id.in_(owned))` 计入。
  代价是两处聚合条件各多一个 `or_`；好处是账不会因为迁移没跑完而少算——少算账比多一行 SQL 糟得多。
- **`/short/new?draft=` 与老 `?draft=` 深链**：短篇一律跳工作台，不再落回对话页。
  如果以后要做「草稿续聊」，那是另一个需求。
- **短篇工作台删掉的入口**：`/projects/{id}/settings` 等路由仍在，只是短篇不再链接。
  真要封死是路由级的活，一期不做（长篇也在用同一批路由）。

# 落地顺序（一期三块，按序）

1. **文风库**：`models/creation.py` 的 `StyleLibraryItem` → `make_user_chain` + `record_run(user_id)` →
   `extract_style_profile` 账号级 → 四个端点 → 前后端测试。
2. **对话建书**：会话两张表 → 卡 schema/ready 判定/premise 拼装（纯函数 + 单测）→ 提示词 →
   `get/messages` → 抽 `_create_project_row`、`_persist_short_outline` → `commit` → `ShortCreationPage` → 测试。
3. **工作台与成本**：`ensure_agent_run_user` + `record_run` 签名 → 管理面板三处 SQL + schema 放宽 →
   用户 tab + `UserDetail` → 短篇工作台收口 + `ProjectRail` → 契约导出 → 测试。
