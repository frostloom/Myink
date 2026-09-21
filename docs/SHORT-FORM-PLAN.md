# 短篇形态施工单

2026-09-21。落实 [SHORT-FORM.md](SHORT-FORM.md) 那份决策文档的施工计划。

分工：**决策文档说「为什么」，本文说「改哪个文件、按什么顺序、每步怎么验」**。设计逻辑不在本文重复，有疑问回决策文档。

## 验收目标

建一本短篇 → 走一遍 `方案 → 成稿 → 审稿 → 改稿 → 落库` → 章节列表里能看到 N 章正文、整篇可导出。全程不产生任何记忆层写入（无 extract / audit / 台账）。

## 关键设计决定（本文定的，决策文档留白处）

| 问题 | 决定 | 理由 |
|---|---|---|
| 短篇走不走 LangGraph | **不走**。`short_runner` 是普通同步函数 | 短篇没有「章」这个调度单位，图的价值（跨章状态、checkpoint 续跑）在这里没有对象 |
| 方案/审纲放哪 | **复用现有建书流程**（`outline_draft` → `put_outline`），两处按 `form` 分叉 | 已有一整套 draft → setup_confirmed → ready 的状态机、路由与前端页；短篇的「方案」就是「1 卷 N 章」的大纲，语义完全对得上 |
| 短篇的 LLM 角色 | **复用 `planner` / `writer` / `audit`**，不新增角色 | 新角色默认未配置 → `MissingModelProvider`（[providers/__init__.py:111](../src/myink/providers/__init__.py#L111) 的 `_project_primary` 只认 `CONFIGURABLE_ROLES`）。加了角色等于短篇开箱即坏，必须先配 6 个模型。runner 里角色名走显式常量，将来要拆成 6 个只改常量 |
| 整篇版本怎么存 | **每章各存一行 `ChapterVersion`，改稿时整批 +1** | 不需要新表：读 v1 全篇 = 逐章取 v1。既得「整篇版本」语义，又复用现有版本 UI |
| 8000 字上限 | 保持平坦的 `[1000, 8000]` | 总量 ≤ 2 万这条已经自然给出「章数少则每章长」（决策文档 §5 的表），再给上限加条件分支没有增量 |
| 单文件导出 | **本次不做** | 章表拆好之后导出是独立小功能，不阻塞主链路 |

## Phase 0 · 门禁：实测单次输出不被截断

**这一步不过，后面全部作废**（决策文档 §7 第一条）。

写 `scripts/probe-short-output.py`（必须显式 `--live`，直调 provider，不碰数据库，仿 [eval-logic.py](../scripts/eval-logic.py)）：

- 用一篇 2 万字的假稿 prompt，`max_tokens = int(20000 * 1.43 * 1.25)`（对齐 [nodes.py](../src/myink/workflow/nodes.py#L245-L249) 的写手换算），跑所配端点。
- 记录：实际 output_tokens、是否 `finish_reason == "length"`、耗时、成本。
- 同时确认**输入**这一侧：方案 + 已写正文一起进 prompt 时，`request_token_budget=64000` 的闸门（[nodes.py:149-164](../src/myink/workflow/nodes.py#L149-L164)）不会把调用拦掉。

**验证**：2 万字输出完整返回，`finish_reason != "length"`。不通过就回来找用户改总量上限，不要硬着头皮往下走。

## Phase 1 · 形态字段与参数

### 1.1 `Project.form`

[models/project.py](../src/myink/models/project.py) 加一列：

```python
form: Mapped[str] = mapped_column(
    String(8), nullable=False, default="long", server_default="long",
    comment="作品形态：long=长篇管道 / short=短篇整篇一次成稿",
)
```

[db.py](../src/myink/db.py) 加 `ensure_project_form()`，照 `ensure_user_tier` 的幂等范式（`ALTER TABLE projects ADD COLUMN IF NOT EXISTS form VARCHAR(8) NOT NULL DEFAULT 'long'`），并在启动补列序列里挂上。

**存量书零影响**：`server_default='long'`，所有旧书落为长篇。

### 1.2 参数联合约束

新建 `src/myink/short/__init__.py` + `src/myink/short/form.py`（纯函数，无 I/O，方便直接测）：

```python
SHORT_CHAPTER_MIN, SHORT_CHAPTER_MAX = 1, 10
SHORT_CHARS_MIN, SHORT_CHARS_MAX = 1000, 8000
SHORT_TOTAL_MAX = 20000

def resolve_short_lengths(chapter_count: int, chars_per_chapter: int) -> tuple[int, int, bool]:
    """返回 (章数, 归一后的每章字数, 是否发生过压缩)。"""
```

规则：章数夹进 `[1, 10]`；每章字数先夹进 `[1000, 8000]`；若 `章数 × 每章字数 > 20000`，则 `每章字数 = max(SHORT_CHARS_MIN, 20000 // 章数)`，并在返回值里标出「已压缩」，让路由把它回给前端提示。

注意 `20000 // 10 == 2000` 正好在上限内；`20000 // 1 = 20000` 会被 8000 夹住 → 1 章 8000 字，与决策文档的表一致。

**验证**：`tests/test_short_form.py`，逐行覆盖决策文档 §5 那张表（1/2/5/10 章），外加边界 `(10, 8000) → (10, 2000, True)`、`(1, 5000) → (1, 5000, False)`。

## Phase 2 · 短篇的方案与审纲（复用建书流程）

### 2.1 两个 prompt

[workflow/prompts.py](../src/myink/workflow/prompts.py) 加：

- `SYSTEM_SHORT_PLAN` —— 对应决策文档 §2 第 1 步。必须写进 prompt 的三条硬要求：**信息密度够一次成稿**（逐章给标题方向、关键场面、角色动作、压力升级或回报、章尾钩子）；**禁止输出「本卷共 N 章」这类空壳**；**故事必须完整，不是长篇前 N 章的启动包**。
- `SYSTEM_SHORT_PLAN_REVIEW` —— 第 2 步。只判一件事：这份方案能不能支撑一次写完整篇。输出 `{"verdict": "pass"|"revise", "reason": "..."}`。

`book_outline_messages` 旁边加 `short_plan_messages(...)` / `short_plan_review_messages(...)`，仿现有 `*_messages` 的写法。

### 2.2 大纲路由按 form 分叉

[routes_book.py](../src/myink/api/routes_book.py)：

- `OutlineDraftBody`（:90）的 `chapter_count` 现在是 `ge=50, le=1000`。改成在**路由体内**按 `project.form` 校验，而不是靠 Field 约束——Field 拿不到 form。短篇走 `1–10`。
- `outline_draft`（:441 的检查）同样按 form 选区间。
- 短篇分支里，出完方案**紧接着跑一次审纲**；`revise` 则带上 reason 重出一次，仍不过就用第一版并回一个 warning（对齐决策文档 §2 第 2 步「保留 v001」）。两次调用都走 `planner` 角色，各记一条 `agent_runs`。
- `put_outline`（:476-479）调 `validate_creation_outline` 前按 form 分叉到 `validate_short_outline`。

### 2.3 `validate_short_outline`

[creation.py](../src/myink/creation.py) 里 `validate_creation_outline` 旁边加。要求比长篇弱得多：

- `chapter_count ∈ [1, 10]`；
- **恰好一卷**，`chapter_start=1`、`chapter_end=chapter_count`；
- 有 `objective`，卷有 `goal`；
- 新增：卷内 `chapters` 必须**逐章**存在（`chapter_seq` 连续覆盖 1..N），每章有非空 `goal`。

最后一条是短篇特有的：长篇 prompt 明令「禁止输出逐章 chapters」（[prompts.py:64-101](../src/myink/workflow/prompts.py#L64-L101)），短篇则**必须**逐章——总共不到 10 章，没有 JSON 爆炸风险，而写手要靠它一次成稿。

存储不变：仍写 [VolumeOutline](../src/myink/models/chapter.py#L68) 的 volume_seq=1 那一行。

**验证**：把 `creation_status` 从 `draft` 推到 `ready` 一次（短篇，5 章），确认 `validate_short_outline` 放行，且 `(5, 3000)` 被压成 5 章 × 4000 字。

## Phase 3 · `short_runner` 最小闭环

新建 `src/myink/workflow/short_runner.py`。**普通函数，不是图**：

```python
def run_short_story(*, project_id: str, task_id: str, form: ShortParams) -> dict:
    """成稿 → 审稿 → 改稿 → 落库。方案已由建书流程确认落库，这里只读。"""
```

三步：

1. **成稿** —— 一次 `write` 调用，输入 = 确认后的逐章方案 + 题材包 + 文风档案，`max_tokens` 按 Phase 0 实测的口径算。用宽容解析器拆块（Phase 4）。
2. **审稿** —— 一次 `audit` 调用，整篇，编辑视角。prompt 明写「不要做确定性打分」，检查项照决策文档 §2 第 4 步列。输出 `{"verdict": "pass"|"revise", "issues": [...], "suggestions": [...]}`。
3. **改稿** —— 仅当审稿 `revise` 时，一次整篇重写。prompt 明写「输出完整正文，不要只列修改建议、不要只改几章片段」。

`verdict == "pass"` 则跳过第 3 步。改稿失败 → 保留首稿 + warning，不抛异常。

每一步 `record_run` 记成本（角色分别 `planner` / `writer` / `audit`，节点标签用 `short_write` / `short_review` / `short_revise`）。

**显式不跑**（决策文档 §3 那条要写死在代码路径里）：不 import 也不调用 `extract` / `recall` / `l1` / `ledger_l2` / `node_audit` / `run_global_audit` / 待确认池。不要靠「没有数据所以不触发」——那会让将来新增的数据流悄悄点亮一套为长篇设计的检查。

**验证**：单测用 stub provider（照现有 `conftest` 的打桩方式），断言三步的调用序列，以及 `verdict=pass` 时改稿**零调用**。

## Phase 4 · 分块解析器与字数观测

新建 `src/myink/workflow/short_parse.py`：

- `parse_short_draft(text: str, chapter_count: int) -> list[str]` —— 逐章四级回退：`=== 第 N 章 ... ===` tagged block → markdown 标题（`## 第 N 章` / `# N`）→ 序号前缀 → 最后手段把整篇按章数均分。单章全失败 → **空字符串，不抛异常**。
- `find_empty_chapters(chapters: list[str]) -> list[int]` —— 返回空章号。
- 补写：`continue_draft(missing, written, params)` 把**已写正文 + 缺失章号**一起回喂，有次数上限（一次）。

新建 `src/myink/validation/short.py`：

- `observe_lengths(chapters, target) -> list[Finding]` —— 复用现有比值口径 `_LEN_LOW_RATIO = 0.8` / `_LEN_HIGH_RATIO = 1.3`（[service.py:24-25](../src/myink/validation/service.py#L24-L25)），**只记 observation，不阻塞**。短篇没有 revise 循环去消化它（改稿那一次是编辑视角驱动的，不喂字数）。

**验证**：

- 三种格式各一份样本喂进 `parse_short_draft`，都能拆出正确章数。
- 喂一份**被截断的**输出 → 得到「部分章空 → 触发补写」，而不是崩、也不是静默落库半成品。
- 喂一份完全无格式的散文 → 不抛异常，降级到均分。

## Phase 5 · 落库

复用 `repo.save_chapter`（[memory/repository.py:299](../src/myink/memory/repository.py#L299)）：

- 逐章写 `Chapter` 行，`status="confirmed"`，`chapter_seq = 1..N`。短篇不走 `ensure_chapter_placeholder` / `_guard_write_order`（那是为按章续写顺序设计的，短篇没有「下一章」）。
- `ChapterVersion` 每章一行 v1；改稿落地时整批写 v2。**这样「整篇 v2」= 逐章取 v2**，不需要新表。
- 短篇不写 `summary`、不写 `Message`、不写待确认池。

`Project.current_chapter = N`。

**验证**：`tests/test_short_persist.py` —— 5 章落库后章表 5 行、版本表 5 行；再跑一次改稿 → 版本表 10 行（每章 v1+v2），逐章取 v2 拼回全篇等于改稿输出。

## Phase 6 · 任务层接线

| 位置 | 改动 |
|---|---|
| [models/runs.py:18](../src/myink/models/runs.py#L18) `TASK_TYPES` | 加 `"short_generate"`。当前**没有任何代码读它**（定义孤岛），顺手让它与实际派发对齐 |
| [processor.py:179](../src/myink/worker/processor.py#L179) `_dispatch` | 加 `short_generate` 分支：读 `form` → `resolve_short_lengths` → 调 `run_short_story`。**不调** `_guard_write_order` / `ensure_chapter_placeholder` |
| [processor.py](../src/myink/worker/processor.py) `_mark_empty_writing_chapters` | **不加** `short_generate`：短篇不建空占位，进了反而会把已落库的正文标成失败 |
| [routes_tasks.py](../src/myink/api/routes_tasks.py) | 新路由 `POST /projects/{pid}/short/generate`，仿 `batches/generate`（:132-148）：`quota_n = chapter_count`、`cost_est = cost_per_chapter * chapter_count`、`_assert_writable` 前置 |
| [routes_tasks.py:391](../src/myink/api/routes_tasks.py#L391) resume 映射 | `short_generate` → `short_resume`；`_dispatch` 加对应分支：已落库成稿则直接从审稿/改稿阶段接，否则从头跑 |
| [gateway/internal/handlers/router.go](../gateway/internal/handlers/router.go) · [caddy/Caddyfile](../caddy/Caddyfile) | SSE 只拆 `/tasks/:task_id/events`，新路由无需改；确认一遍即可 |

**验证**：`tests/test_worker.py` 加一例，断言 `short_generate` 派发到 `run_short_story`（打桩），且**未**调用 `_guard_write_order`。

## Phase 7 · 前端

- **建书表单**：`NewProjectPage.tsx` 加形态选择（长篇/短篇）。选短篇时章数输入切到 `1–10`、多一个「每章字数」输入；`50–1000` 那几处硬编码（:213 / :314 / :876 / :880）按 form 取值。超限时显示 Phase 1.2 回传的「已压缩」提示。
- **大纲页**：短篇分支渲染逐章方案（而不是卷+阶段），复用现有确认按钮。
- **进度页**：`short_generate` 的任务卡复用现有 `TaskTimeline`，标签按五步显示（方案 / 审纲在入队前已完成，任务本身只跑成稿 / 审稿 / 改稿）。
- **审稿结果必须显示出来**：决策文档 §8 那条风险——短篇没有全局审计，审稿是唯一出口，不显示用户会以为「审过了没问题」。
- `web/src/lib/api.ts` 加 `generateShort`。若后端 schema 有变，重跑 OpenAPI 生成。

## Phase 8 · 端到端

一篇 **5 章 × 2000 字**：建书 → 确认设定 → 出方案 → 确认大纲 → 开始写 → 章节列表 5 章有正文 → 导出全篇。

再加两个反向用例：一篇 1 章 8000 字（验证「章数少则每章长」真的通），一篇审稿判 `revise` 的（验证改稿真的跑）。

## 回归面

- `EMBED_ENABLED=0 python -m pytest tests/ -q`（对齐 [scripts/ci-local.sh:38](../scripts/ci-local.sh#L38)）全绿。
- `tests/test_project_creation.py` / `test_creation_migration.py` —— `form` 补列与 `creation_status` 状态机被动过，重点看。
- `tests/test_flow.py` / `test_worker.py` / `test_chapter_versions.py`。
- `tests/test_gates_parity.py` —— 新路由走 `enqueue`，闸门口径应与 Go 一致。
- **断言短篇路径下 `agent_runs` 中没有 extract / audit(单章) / global_audit 记录** —— 证明记忆层真的没跑（决策文档 §7 第三条）。

## 风险

- **Phase 0 未过就往下写**是最贵的错误：整套「整篇一次成稿」押在单次输出上限上。
- **`_bounded_generate` 的 64000 卡的是输入**。写第二版时输入 = 方案 + 首稿全文，接近翻倍，要盯着别被自己的闸门拦掉。
- **`put_outline` 是共享路由**，按 form 分叉时务必确认长篇分支逐字节不变。
- **`_assert_writable` 依赖 `creation_status ∈ {ready, legacy_ready}`**。短篇必须走完建书流程才能生成——如果将来想让短篇跳过确认直接写，改的是这里，不是 `_guard_write_order`。

## 落地顺序

Phase 0 门禁 → Phase 1 形态字段与参数 → Phase 2 方案/审纲 → **Phase 3 runner 最小闭环（跑通再往下）** → Phase 4 解析器 → Phase 5 落库 → Phase 6 任务层 → Phase 7 前端 → Phase 8 端到端。

## 附注：盘点中撞见的一处既有问题（与短篇无关）

前端 [api.ts:273-278](../web/src/lib/api.ts#L273-L278) 的 `pauseBatch` / `resumeBatch` / `cancelBatch` 打的是 `POST /api/v1/batches/{id}/{pause|resume|cancel}`，但**后端没有这条路由**——只有 `/tasks/{task_id}/{pause|resume|cancel}`（[routes_tasks.py:362](../src/myink/api/routes_tasks.py#L362) / :375 / :485）和 `/projects/{pid}/batches/generate`。网关只路由 `/tasks/:task_id/events`，Caddy 也只拆这一条，所以这三个方法一定是 404。

[verify-auth-isolation.py:101-102](../scripts/verify-auth-isolation.py#L101-L102) 也在探这两个路径，但它断言的是「别人拿不到」，路由存不存在不影响它通过——所以这个 bug 现在没有任何测试挡着。

按「不动没让动的代码」的约定，这里只报不改。修法二选一：把前端三个方法改指 `/tasks/{id}/...`（注意批次任务同样走 `/tasks/{id}` 那套控制路由），或在后端补 `/batches/{id}/{action}` 的转发。
