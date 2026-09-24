# 短篇建书 v2 + 文风库模块 + 短篇工作台收口

日期：2026-09-24　形态范围：**只改短篇；长篇只加一个「文风」下拉，其余一行不动**

本文件是 [`2026-09-24-short-creation-assistant-design.md`](2026-09-24-short-creation-assistant-design.md)（下称 v1）的修订。
v1 已落地的部分（对话式建书、账号级文风库、账号级记账、管理面板用户花费下钻、短篇工作台去阶段 tab）
**不回退**；本文件只改其中被推翻的四处，并补三块新工作。

## 为什么改

v1 上线后实际使用反馈，四条：

1. **建书页常驻方案卡不对。** 应该像参照对象那样：先正常聊天，模型认为聊得差不多了才**弹出建书选项**，
   点了才出现方案卡，改完确认才真正开写（三段式）。
2. **短篇的对话方式不对。** v1 的提示词是「一回合只问一个」的问卷机，把聊天天花板压成了填表。
   参照对象的助手是**合作者**：普通讨论直接回答、主动提方案，只有题材/主角压力/核心冲突太空时
   才问**一个**关键问题。
3. **文风运营位不对。** 文风不该长在建书页里，应该是一个**顶层模块**，与「环境配置」「主题」同级，
   自己新建 / 命名 / 删除；建书时只**选标签**，不再现场导入。
4. **短篇工作台右栏是长篇的残留。** 「章节流转」「生成与重写」「短篇审稿」这些对短篇要么是长篇概念、
   要么是空壳，整栏不该出现。

外加两条：扫榜的环境配置里还挂着已废弃的 MCP 文案与死字段；以及上一轮终审留下的 10 条缺陷。

## 非目标

- **长篇的对话式建书不引入。** 长篇仍是三步向导（作品信息 → 设定骨架 → 整书大纲）。
  长篇本轮**唯一**的改动是①里多一个「文风」下拉。
- **MCP 服务不拆。** `integrations/mcp.py`（`McpClient` / `McpError`）保留，以后接别的 MCP 工具用。
  本轮只拆**扫榜那条** MCP 线（配置字段 + 探针端点 + 前端按钮）。
- 不做短篇的流式输出；不删 `PUT /projects/{id}/outline`、`PUT /setup`、`POST /outline-draft` 等老端点。
- 不需要对存量数据做迁移（`mcp_url` 留在用户环境 JSON 里无害，只是不再被读）。

## 已确认的决策

| 项 | 决策 |
| --- | --- |
| 建书对话形态 | 三段式：**聊天** →（服务端判定齐备）**冒出「开始建书」选项** → 点击**弹出可编辑方案卡** → 确认**即开写** |
| 「够了」由谁定 | **服务端算**（卡上七个文本字段全非空），不信模型自报；不新增后端状态 |
| 开写时机 | 确认后**前端连着**调 `POST /projects/{id}/short/generate`，不再让用户去工作台点「开始写全篇」 |
| 文风库位置 | 顶层模块 `/styles`，左栏「全局设置」分区里，与「环境配置」「主题」同级 |
| 文风库能力 | 新建（**粘文章 → 提取 → 可编辑草稿 → 命名 → 存**）/ 重命名 / 删除 / 档案键值预览 / 备注。内置 4 个不可删 |
| 建书选文风 | 短篇与长篇建书都从文风库**选标签**；建书页不再有导入入口 |
| 文风建后能否换 | 短篇**不能**（v1 决策不变）；长篇建后仍可在「创作设置」页改（现状） |
| 扫榜配置 | 去掉 MCP 文案与 `mcp_url` 死字段；只留 启用 / 超时 / 条数 |
| 遗留缺陷 | 全部修（M-1 至 M-10） |

## 硬前提（决定实现形状）

1. **`ready` 已在服务端算好**（`src/myink/short/creation.py` 的 `card_patch` + 七字段判定，
   见 v1 §「`ready` 由后端自己算」）。三段式**只改前端呈现**：卡不再常驻，`ready=true` 时才摆出
   「开始建书」选项。后端**不新增状态、不改契约形状**。
2. **`commit` 已经能建出 `creation_status='ready'` 的书并落逐章方案**（v1 工作流 2 步骤 4）。
   本轮只把「入队生成」由用户手动点改成确认后前端紧接着调一次现有端点。
3. **文风落地有两个消费方，解析逻辑必须共用**：短篇 `commit`（v1 已写）与长篇建书（本轮新增）。
   `builtin:<key>` → `style_profile = STYLE_PRESETS[key]["style_profile"]` 且 `skill_pack = key`；
   库 item id → `style_profile = item.profile` 且 `skill_pack = None`。抽成一个函数，两处调用。
4. **`agent_runs` 已是可空 `project_id` + 可空 `user_id`**（v1 工作流 3 已落），
   账号级文风提取的记账不动。

---

# 工作块 1：扫榜环境配置去 MCP（保留 MCP 服务）

`mcp_url` 对扫榜是**死字段**：`rankings_view_for_user`（`environment.py:95-105`）根本不读它，
`RankingsService` 也不读。它唯一的作用是被 `POST /environment/test-rankings` 拿去当探针地址。

## 后端

- `src/myink/config.py`：删 `rankings_mcp_url`。
- `src/myink/environment.py`：`default_rankings()` 删 `"mcp_url"` 项；`merge_rankings()` 删
  `mcp_url` 的读取分支（存量 JSON 里留着这个键会被自然忽略，无需迁移）。
- `src/myink/api/routes_environment.py`：
  - `RankingsBody` 删 `mcp_url`；`_validate_rankings` 删对应分支；
  - 删 `RankingsProbeBody` 与 **`POST /environment/test-rankings`** 整个端点；
  - **保留** `from myink.integrations.mcp import McpClient, McpError` 所指向的模块本身
    （本文件不再 import 它，`integrations/mcp.py` 原样保留）。
- `src/myink/api/schemas.py`：删 `RankingsProbeOut`（确认无其他引用后）。
- `.env.example`：删 `RANKINGS_MCP_URL` 行与其上方的 MCP 注释；`RANKINGS_ENABLED/TIMEOUT/LIMIT/CACHE_TTL` 保留。
- `src/myink/integrations/rankings.py` 顶部 docstring 里「扫榜已整体前移」等描述**不改**（仍准确）；
  `integrations/__init__.py` 的 docstring 也仍准确（它已经写着「扫榜不再经它取数」）。

## 前端

- `web/src/types.ts`：`RankingsSettings` 删 `mcp_url`。
- `web/src/lib/api.ts`：删 `testRankings`；更新 `:412` 那条把扫榜说成 MCP Client 的注释。
- `web/src/pages/EnvironmentPage.tsx`：
  - 默认值删 `mcp_url: 'https://daosearch.io/api/mcp'`；
  - 删 `rankProbe` 状态、`testRankings` 调用、`saveRankings` 里的 URL 校验分支；
  - 区块标题「MCP 服务」→「扫榜」；字段只留 启用开关 / 超时 / 条数；
  - 删「MCP 地址」输入与「测试 MCP 连接」按钮；
  - 说明文案改为：数据来自番茄榜单，只作建书前灵感，不进记忆层。
- `web/src/pages/EnvironmentPage.test.tsx`：删 MCP 探针用例（`:177-196`），
  保留并改「保存扫榜配置」用例的载荷（不再含 `mcp_url`）。

## 契约

`spec/api-openapi.json` 必须与 `app.openapi()` 字节一致（`tests/test_api_contract.py`）——
删了一个端点，收尾重新 `myink contract export`。

---

# 工作块 2：文风库顶层模块

## 后端：补一个重命名端点

`src/myink/api/routes_style_library.py` 已有 `GET` / `POST` / `DELETE` / `POST /samples`。
本轮**新增**：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| PATCH | `/api/v1/style-library/{item_id}` | 体 `{name?, note?}`。只改自己的项；`builtin:` 前缀 → 404；重名 → 409 `NAME_TAKEN`；`name` 空白 → 400。 |

`GET` 已返回 `builtin` / `removable` / `profile` / `note` / `sample_chars`，够页面用，不改形状。

**提取质量是本块的重点**（用户点名要求）。现有 `POST /style-library/samples` 已经把
统计层（`analyze_sample_stats`，确定性）与 LLM 提炼（`extract_style_profile`）合并进一份
`draft`，并在 LLM 失败时降级只回统计层 + `draft.extract_error`。本块**不改这段逻辑**，
但要在页面上把这份 draft **完整摆出来给用户改**（键值逐个可编辑），而不是盲存。
`profile` 形状沿用 `StyleProfile`（`validate_profile` 把关的那份），与
`project_settings.style_profile` 同构，这样「库里取出来直接写进书」不需要转换。

## 前端：新页面 `web/src/pages/StyleLibraryPage.tsx`

版式照 `AppearancePage`（主题页）：左列表 + 右详情/编辑。

```
┌─────────────┬──────────────────────────────────────┐
│ 内置         │  文风名 [福尔摩斯腔        ]          │
│  · 仙侠九州   │  备注   [冷峻、短句、大量内心独白]      │
│  · 都市烟火   │  ─────────────────────────           │
│  · 悬疑克苏鲁 │  档案（可改）                         │
│  · 轻喜剧     │   视角      [第三人称限知     ]       │
│ 我的         │   句式风格  [短句为主，少复句  ]       │
│  · 福尔摩斯腔 │   对话      [……]                     │
│  · 冷硬派     │   禁忌      [不要网络流行语   ]       │
│ [+ 新建]     │  [保存]  [重命名]  [删除]             │
│             │  ─────────────────────────           │
│             │  新建：粘贴文章 → [提取文风] → 草稿 →   │
│             │        命名 → [保存]                  │
└─────────────┴──────────────────────────────────────┘
```

- 路由 `/styles`，加进 `web/src/router.tsx`；
- `web/src/components/ProjectRail.tsx` 的「全局设置」分区（`:88-103`）加「文风库」`NavLink`，
  与环境配置、主题同级。
- 交互：`新建` 展开粘贴区 → `styleLibraryApi.extract` → 渲染可编辑草稿（含 `extract_error`
  降级提示）→ 命名 → `save`。选中项可改档案与备注 → `PATCH`；`删除` 二次确认（内置不给删的按钮）。

## 测试

- 后端 `tests/test_style_library.py` 补：`PATCH` 改名成功；重名 409；`builtin:` 404；
  改别人的项 404；空白名 400。
- 前端 `web/src/pages/StyleLibraryPage.test.tsx`：列表渲染内置+我的；新建流（粘文章 → 提取 → 命名 → 保存
  → 出现在列表并选中）；内置项没有删除按钮；`extract_error` 时显示降级提示。

---

# 工作块 3：建书时选文风标签

## 短篇建书页

`web/src/pages/ShortCreationPage.tsx` 删掉内联的「导入文章存成我的文风」整块
（`importOpen` / `importText` / `importDraft` / `importName` / `extractStyle` / `saveStyle`），
文风行只留：

- `[选择器 ▾]`（内置 + 我的，选项文案 `名称（内置）` / `名称（我的）`）；
- 一个 `<Link to="/styles">去文风库添加</Link>`。

样式 `ShortCreationPage.module.css` 里 `.import*` 一并删。

## 长篇建书

- 后端 `src/myink/api/routes_book.py`：`CreateProjectBody` 加可选 `style_item_id: str | None`；
  在建项目**同一事务**内解析并写 `project_settings.style_profile`（+ `skill_pack`）。
  解析函数与短篇 `commit` 共用（见「硬前提 3」）。
- 前端 `web/src/pages/NewProjectPage.tsx`：① 作品信息里加一个「文风（可选）」下拉，
  与短篇同款；提交时带 `style_item_id`。`form='short'` 的分支不受影响（短篇不走这个页面）。
- 契约：`CreateProjectBody` 变更要重新导出 `spec/api-openapi.json`。

## 测试

- 后端 `tests/test_book*.py`：带 `style_item_id`（内置 key 与库 item id 各一）建书 → `project_settings`
  的 `style_profile` / `skill_pack` 正确；不带 → 与今天一致（无 `project_settings` 行或档案为空）。
- 前端 `NewProjectPage.test.tsx`：下拉列出内置+我的；选中后提交载荷含 `style_item_id`。
- 前端 `ShortCreationPage.test.tsx`：文风行只剩选择器 + 链接，没有导入按钮（原导入用例改写）。

---

# 工作块 4：短篇建书三段式

## 页面状态机（纯前端，后端不变）

```
chat   ── 只有对话流 + 输入框。回车发送（Shift+Enter 换行）。
       │  顶部「重新开始」。
       │
       ├─ data.ready === false ─→ 继续 chat
       │
card   ── data.ready === true ─→ 对话流末尾冒出「开始建书」这个选项（一张可点的条）。
       │  点它 → 右侧/下方滑出可编辑方案卡（暂定名/题材/方向/主角压力/核心冲突/
       │  情绪回报/大致情节/章数/每章字数/文风）。
       │  卡上「确认，开写」。
       │
done   ── 确认 → commit → 紧接着 POST /projects/{id}/short/generate → 跳工作台。
```

- **回车发送**：`textarea` 加 `onKeyDown`——`Enter`（无 Shift）提交并阻止换行；
  `Shift+Enter` 换行。发送按钮保留（中文输入法下 `Enter` 可能落在组合态，
  用 `event.nativeEvent.isComposing` 跳过组合中的 Enter）。
- **「开始建书」选项出现后仍可继续聊**：它只是多出来一个可点的条，不锁输入框。
  聊出新信息后卡会跟着更新（`ready` 可能变回 false，选项随之消失）。
- **确认后不再回到工作台点第二次**：`commit` 拿到 `project_id` 后立即
  `POST /projects/{id}/short/generate`，成功即 `navigate('/projects/'+id)`；
  入队失败不回滚已建的书——跳工作台并在状态带上给重试（见工作块 5）。
- `plan_warning`（v1 遗留缺陷 M-5）随 `navigate` 的 `state` 带过去，在工作台状态带上**渲染出来**。

## 提示词改写（`src/myink/workflow/prompts.py` 的 `SYSTEM_SHORT_CREATION`）

从「问卷机」改成「合作者」，要点：

- **普通讨论直接回答**。用户问「这个题材行不行」「你觉得哪个更好」这类问题，就正常答，
  不要每轮都反问；也不要为了凑回合数追问细节。
- **只有题材 / 主角压力 / 核心冲突太空时才问一个问题**（不是「一回合问一个」的机械节奏）。
- **这三个一明确，就把卡填满**（含自己拟的 2–8 字暂定名、默认章数与字数），
  不要在文字里复述一遍方案再等用户二次确认——卡就是方案。
- 用户说「就这样 / 开写 / 确认」→ 立刻把卡填满。
- 结尾一句「想开始就说一声，或者直接改右边卡」这类**可选**提示，不要每轮都问同一个问题。
- 保持：不承诺已建书或已开写（建书由用户点确认触发）；用中文；不用 markdown 表格/标题。
- 卡字段留空 = 这轮没有新信息，系统保留用户已写的值（**这条规则不变**）。

## 测试

- 后端 `tests/test_prompts.py`：`short_creation_messages` 仍喂全历史 + 当前卡；
  系统提示含「直接回答」与「三个字段一明确就填满卡」这两个标志串。
- 后端 `tests/test_short_creation.py`：`ready` 语义不变（现有用例保持绿）。
- 前端 `ShortCreationPage.test.tsx`：`ready=false` 时没有「开始建书」选项、没有方案卡输入框；
  `ready=true` 时出现选项；点选项后卡出现；确认后**连着**调了 `commit` 与
  `POST /projects/{id}/short/generate`（用假 api 断言两次调用与顺序）；
  **回车发送**：`keyDown Enter` 触发发送、`Shift+Enter` 不触发。

---

# 工作块 5：短篇工作台收口

`web/src/pages/WorkspacePage.tsx` 的 `isShortBook` 分支（`:796-839`）：

- **右栏（`aside.right`）整栏不渲染** —— `GenerationPanel` / `TaskTimeline` / `ShortStoryPanel`
  三块在短篇下都去掉。长篇分支原样（回归）。
- **生成状态与重试**挪到中间栏顶部一条**细状态带**（`role="status"`）：
  未开始 / 进行中 / 失败可重试 / 完成四种态，失败时给重试按钮。
  这是「确认即开写」之后唯一的重试入口，不能省。
- **续写触发**：原先靠 `GenerationPanel` 的 `autoStartShort`；改为工作台挂载时若
  `handover.beginShortWriting` 为真且还没任务，就调一次生成（沿用现有 `handleTaskStart` 路径）。
- **审稿结论**：`ShortStoryPanel` 的内容（整篇审稿报告）**并进中间栏**，放在整篇正文下方，
  默认折叠、有报告才显示。`ShortStoryPanel.tsx` 本身保留（被中间栏复用），不再是并列的右栏面板。
- 左栏（章节目录 / 导出 .md / 删除本书）**不动**——短篇本来就没有「删除本章」「矫正记忆」这些入口。

**测试** `WorkspacePage.test.tsx`：短篇分支**没有**右栏三块、**有**状态带；
`autoStartShort` 的续写触发仍生效；有审稿报告时中间栏出现结论；长篇分支回归不变。

---

# 工作块 6：上一轮遗留缺陷（M-1 ~ M-10）

全部修。逐条对应：

| # | 缺陷 | 处置 |
| --- | --- | --- |
| M-1 | Review Focus 1 的端点级测试空转（`_STUB_TURN` 的卡省略了 `working_title`，删掉实现也照样绿） | 改成卡**带** `working_title` 而模型返回空串，断言合并后保留用户的旧值——补上真正的端点级 RED |
| M-2 | 非有限浮点（`Infinity` / `NaN` / `1e400`）经 `int()` → `OverflowError`/`ValueError` → `POST /short/creation/messages` 500 | `src/myink/short/creation.py` 的 `_known` 数值分支加 `math.isfinite` 守卫，非有限即当作「没给」 |
| M-3 | `commit` 第 4 步没有防「会话在途中被删」 | `routes_short_creation.py` 的 commit 在写回会话前重新取一次并判存在；不存在则跳过状态写回（书与方案已落，返回仍成功） |
| M-4 | 数字能写进文本字段 → `Project(title=<int>)` → 500 | `_known` 里文本字段（`working_title` 等）只接受 `str`；非字符串当「没给」 |
| M-5 | `plan_warning` 一路带到工作台后被丢弃 | 工作台状态带渲染它（见工作块 5） |
| M-6 | `DELETE /short/creation` 会留下失败 commit 建出的孤儿草稿书，而该书已吃掉当日建书额度 | `reset` 时若会话的 `book_id` 指向一本**当日创建且仍无任务**的书，连带删除该书；有任务则不动（用户可能已在写） |
| M-7 | `UserDetail` 拿 `listUsers(q=<uuid>, limit=1)` 当 get-by-id，未知 id 不给 404 | `routes_admin.py` 加 `GET /admin/users/{user_id}`；`adminApi.getUser`；`UserDetail` 改用它，404 显示「用户不存在」 |
| M-8 | `GenerationPanel.tsx:53` 的 `react-hooks(exhaustive-deps)` 警告 | 补齐依赖；工作块 5 若已让短篇不再渲染 `GenerationPanel`，长篇小说分支仍要修掉 |
| M-9 | `/admin/overview` 全局花费 ≠ 各用户之和（孤儿 `agent_runs` 行） | `routes_admin.py` 的全局 metrics 也加 `owner.is_not(None)` 条件，与列表口径一致 |
| M-10 | 部署文档缺一行：某个早于 `dbb62e9` 的环境建过 `style_library_items`，缺 `note` 列与唯一约束，`create_all` 不会补 | 在 `docs/DEPLOY.md` 加一行一次性 `DROP TABLE style_library_items` + `myink init` 的说明 |

**报告项、不改代码**（记录在此，不进本轮改动）：`AGENTS.md:26` / `docs/DEPLOY.md:76` /
`docs/RELIABILITY.md:21` 里仍写着已放弃的 Go 网关（`AGENTS.md` 本就不入提交）；
`web/src/lib/api.ts` 的 `pauseBatch/resumeBatch/cancelBatch` 指向不存在路由（既有 bug，与本轮无关）。

---

# 要动的文件清单

**后端新增**：无新文件（`routes_style_library.py` 已在）。

**后端改动**：`config.py`、`environment.py`、`api/routes_environment.py`、`api/schemas.py`、
`api/routes_style_library.py`、`api/routes_book.py`、`api/routes_short_creation.py`、
`api/routes_admin.py`、`api/admin_schemas.py`、`short/creation.py`、`workflow/prompts.py`、
`.env.example`、`docs/DEPLOY.md`、`spec/api-openapi.json`（导出）。

**前端新增**：`pages/StyleLibraryPage.tsx` + `.module.css` + `.test.tsx`。

**前端改动**：`router.tsx`、`components/ProjectRail.tsx`、`pages/EnvironmentPage.tsx` +
`.test.tsx`、`pages/ShortCreationPage.tsx` + `.module.css` + `.test.tsx`、
`pages/NewProjectPage.tsx` + `.test.tsx`、`pages/WorkspacePage.tsx` + `.module.css` + `.test.tsx`、
`pages/admin/UserDetail.tsx`、`lib/api.ts`、`lib/adminApi.ts`、`types.ts`。

# 验证

1. 后端：`source .local/env-test.sh` + conda `aiink` → `python -m pytest tests/ -q`；
   重点 `tests/test_environment_routes.py`、`test_style_library.py`、`test_short_creation.py`、
   `test_book*.py`、`test_admin*.py`、`test_api_contract.py`、`test_prompts.py`。
2. 前端（`web/`）：`npm run lint`、`npm test`、`npm run build`（**真类型闸是 `npm run build`**）。
3. 手工 E2E（浏览器只能 Chrome / Edge）：
   - 环境配置 → 扫榜区没有 MCP 字样、没有地址输入与「测试 MCP 连接」按钮；保存与刷新后仍在。
   - 文风库 → 新建：粘一篇文章 → 提取出可改的档案 → 命名 → 保存 → 出现在「我的」里；
     重命名；删除；内置项不能删。
   - 短篇建书 → 只有对话；连聊几句（回车发送，Shift+Enter 换行）；聊到齐备时冒出「开始建书」；
     点开卡、改一个字段、选一个文风标签 → 确认 → 直接开始写并落在工作台；
     工作台右栏没有那三块，顶部有状态带，失败能重试。
   - 长篇建书 → ①里选一个文风标签 → 建出来的书在「创作设置」页看到的档就是那个标签的档。
   - 管理面板 → 用户详情页手改一个不存在的 id → 显示「用户不存在」而不是空页。

# 风险与取舍

- **确认即开写把「建书」与「入队」合成一次用户动作**，中间仍隔着两次 HTTP。第二次失败会留下
  「有书有计划、没在写」——工作台状态带就是这个状态的重试入口，且入队失败时明确提示。换成
  后端一次事务里入队会把额度/计费逻辑复制一份，代价更大（沿用 v1 的判断）。
- **「开始建书」的时机由服务端 `ready` 决定**，不是模型的措辞。好处是不信模型自报；代价是模型
  可能在卡没填满时就在文字里显得很有把握，用户看不到选项。这是刻意选择的安全侧。
- **右栏整栏去掉后，短篇没有「本次任务阶段」的可见性**了——短篇本来一次调用出整篇，
  阶段时间线对它没有信息量，用一条状态带替代表达更准，不是信息丢失。
- **M-6 的连带删除**只删「当日创建 + 无任务」的书，宁可漏删也不误删正在写的书。
