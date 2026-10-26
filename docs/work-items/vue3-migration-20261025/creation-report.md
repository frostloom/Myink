# Task 4：长短篇创建 Vue 迁移报告

日期：2026-10-25。分支：`codex/vue3-migration`。未提交、推送、合并或发布。

## 实现边界

只新增 `web/vue/src/pages/NewProjectPage.vue`、`ShortCreationPage.vue`、对应 `.test.ts`，及 `web/vue/src/components/RankingsPanel.vue`、对应测试。本报告为本任务专属文档。未修改共享表单组件、App、路由、session、主题或后台文件。路由接入由主代理负责。

三个组件均为原生 Vue `defineComponent/setup/ref/computed/watch/h`，模态使用 Vue Teleport，导航使用 Vue Router 对象的 `state`。无 React 包装、iframe、兼容 hooks runtime；复用现有 API、领域类型和 CSS Modules。长篇完整保留原 1393 行页面的功能与编辑结构，短篇完整保留原 481 行页面流程。

## 原功能 → Vue 行为与测试

| 原功能 | Vue 对应 | 验证 |
| --- | --- | --- |
| 长篇题材分组、主辅题材与平台题材包 | 发布目录选择，辅题材依赖主题材，不提交可编辑根字段 | 原 published genre / realm ladder 用例移植 |
| 文风选择、内置/我的来源标记 | 原样提交 style_item_id 或 null | 原 3 个文风用例移植 |
| 长短篇入口、篇幅校验、显式 form | 长篇50–1000章/500–20000字；旧短篇向导兼容逐章方案 | 原 long/short 入口与请求体用例移植 |
| 创建幂等与浏览器存储失败 | 原 `myink.pending-project-creation` key；创建前先持久化ID，get/set失败拒绝创建；失败重试/重挂载复用ID | 原幂等重试/重挂载/getItem、setItem失败用例移植 |
| 草稿旧链接与持久恢复 | `?draft=` 恢复后台创建上下文；已完成作品跳工作台；创建成功replace URL | 原草稿恢复/新建清空/B失败/A晚回用例移植 |
| 设定草稿、分区编辑与确认 | 境界、世界规则、硬约束、势力、人物、地点；StructuredTextField保留局部输入 | 原题材能力与部分键/空行输入用例移植；保留完整新增/删除控件与提交形状 |
| 设定/大纲并行提案与降级重试 | 两个请求都结束才解除创建锁；单独重试，空大纲可手编，不把降级说成成功 | 原并行/degraded用例移植 |
| 长篇卷/阶段编辑、短篇逐章编辑 | 保留卷标题/主题/目标/KR/末事件/章范围、阶段节拍/增删；短篇固定一卷逐章7字段 | 原短篇逐章确认用例移植；原长篇全部编辑结构与API字段保留 |
| 分别确认、确认全部、保留草稿返回 | 设定/大纲按原顺序落库，标题同步，未完成作品不开放写作 | 原恢复与确认测试移植 |
| 压缩字数、审纲警告 | 后台回执与本地短篇归一预览 | 原压缩/审纲/小数截断用例移植 |
| 短篇服务端ready门禁与三段流程 | 对话 → 开始建书入口 → 模态方案；必填齐全才允许commit；已committed禁发禁确认 | 原门禁/必填/committed用例完整移植 |
| 短篇历史、新建、切换、删除 | 每会话独立记录；列表默认收起，删除确认，不删除成品 | 原历史/新建/切换/删除/取消用例完整移植 |
| 聊天即时用户消息、发送失败恢复 | 输入立即清空、pending用户消息即时显示；成功替换；失败保留下一句或恢复旧句 | 原消息/Enter/失败/继续编辑/下一句用例移植 |
| IME/Shift+Enter | composing Enter不发送，Shift+Enter保留换行 | 原IME与键盘用例移植 |
| 模态焦点与输入自增长 | 初始关闭键、Tab首尾循环、Escape/遮罩关闭、焦点返回入口；textarea单滚动区域 | 原焦点/遮罩/自增长用例移植 |
| 直达工作台自动开始意图 | `state: {beginShortWriting:true,planWarning}` | 原handover用例移植；意图一次消费由工作台负责 |
| 先选资源意图 | `/projects/:id/settings#writing-resources`，仅 `configureBeforeWriting/planWarning`，不带beginShortWriting | 原资源优先用例移植；Vue Router显式拆分path/query/hash |
| 扫榜灵感 | 登录预热、折叠缓存、强制刷新、实时/样例标记、错误可重试 | 新5个Vue用例 |
| 离页、换草稿、账号切换与续期 | 所有异步续接校验generation；退出清空旧数据；同账号token续期保留会话与输入 | 新创建/设定/commit晚回、账号切换、logout、续期用例 |
| 新建会话失败保留输入、重复commit锁 | 切换/创建成功才清空输入，busy同步阻止重复提交 | 新失败保留/commit失败保留编辑与单次提交用例 |

## TDD 实际证据

- 原行为测试移植后对空 Vue 组件运行：**51 failed / 51**。不是仅缺失导入；组件可挂载，但真实功能断言失败。随后实现并达到 **51 passed**。
- 新增6个安全回归：**5 failed / 52 passed（57总计）**，失败覆盖旧create/setup晚回、离页commit、账号切换、新建会话失败丢输入；重复提交保护用例首次即通过已有同步锁。修复后 **57 passed**。
- 榜单空组件基线：**3 failed / 1 passed（4总计）**，游客不预热用例本来可通过。实现后通过；再加入退出晚回用例。
- 同账号续期与榜单退出晚回实际RED：**2 failed / 39 passed（41总计）**。
- 长篇退出时create晚回实际RED：**1 failed / 22 skipped**，此处仅为 `-t 'after logout'` 定向筛选，不宣称22个跳过用例通过。
- 最终定向：**3 files / 64 tests passed**（长篇23、短篇36、榜单5）。
- Vue事件flush与Router卸载语义与React不同：适配为原生路由/事件；离页导航回归断言router.push未调用，避免把Router卸载自动重置到`/`误当业务行为；发送失败的即时清空由deferred成功用例验证，失败用例验证最终恢复。

## 实际命令与结果

工作目录均为 `web`：

```sh
npm run test:vue -- vue/src/pages/NewProjectPage.test.ts vue/src/pages/ShortCreationPage.test.ts vue/src/components/RankingsPanel.test.ts
npx eslint --config eslint.vue.config.mjs vue/src/pages/NewProjectPage.vue vue/src/pages/ShortCreationPage.vue vue/src/components/RankingsPanel.vue vue/src/pages/NewProjectPage.test.ts vue/src/pages/ShortCreationPage.test.ts vue/src/components/RankingsPanel.test.ts
npx oxlint vue/src/pages/NewProjectPage.vue vue/src/pages/ShortCreationPage.vue vue/src/components/RankingsPanel.vue vue/src/pages/NewProjectPage.test.ts vue/src/pages/ShortCreationPage.test.ts vue/src/components/RankingsPanel.test.ts
npm run typecheck:vue
npm test
npm run test:vue
```

- scoped ESLint/oxlint均exit 0，零错误/告警输出。
- 全局vue-tsc仍exit 2；本scope6个文件无诊断。已记录的模块外错误为工作台相关测试 unused imports（ChapterPlanPanel、GenerationPanel、ReviewFlow、RevisionScope、TaskBudgetPanel、WorkspacePage.live、WorkspacePage），交由对应代理；不把全局类型检查报成通过。
- React完整测试：**72 files / 599 tests passed**，exit 0。
- Vue完整测试当次：**61 files passed / 2 failed，494 passed / 2 failed**。失败分别为`router-parity.test.ts > connects every product route to a real Vue implementation`（当时主代理尚未完成路由接入）和`WorkspacePage.test.ts > auto-starts the short generation once on handover, then strips the intent`。已告知主代理；主代理随后反馈router-parity6项已GREEN，本任务不重跑或覆盖其集成工作。
- `/tmp/creation-red.log`、`creation-safety-red.log`、`creation-extra-red.log`、`creation-logout-red.log`、`rankings-red.log`保留本轮RED输出；`creation-final-tests.log`、`creation-react-suite.log`、`creation-vue-suite.log`和`creation-types-final.log`保留验证输出。

## 未验与边界

本子任务未运行构建、真实后端服务、合成浏览器、人工中文输入法/移动端/视觉回归或完整CI；主代理负责最终集成与独立审查。组件单测不等于真实服务与浏览器验收。Hindsight localhost:8888未连通，按项目规则跳过。未新增服务、未运行固定端口Compose。

## 旧测试逐项对应

以下原测试名在对应Vue测试文件中保持，路由和事件仅做Vue原生适配：

### NewProjectPage

- `restores an unfinished book without creating a duplicate or exposing a skip button` → `web/vue/src/pages/NewProjectPage.test.ts`
- `clears the restored draft when the same component navigates to a fresh form` → `web/vue/src/pages/NewProjectPage.test.ts`
- `clears draft A and keeps the form locked when restoring draft B fails` → `web/vue/src/pages/NewProjectPage.test.ts`
- `does not let a late draft A response overwrite restored draft B` → `web/vue/src/pages/NewProjectPage.test.ts`
- `keeps creation locked until both proposals finish and never claims degraded generation succeeded` → `web/vue/src/pages/NewProjectPage.test.ts`
- `reuses one persisted request id when the first create attempt is retried` → `web/vue/src/pages/NewProjectPage.test.ts`
- `reuses the persisted request id after the page remounts` → `web/vue/src/pages/NewProjectPage.test.ts`
- `starts in the short form straight from its own section route, with no form switch to make` → `web/vue/src/pages/NewProjectPage.test.ts`
- `edits and confirms the short plan chapter by chapter` → `web/vue/src/pages/NewProjectPage.test.ts`
- `tells the user when the short plan was compressed or flagged by the plan review` → `web/vue/src/pages/NewProjectPage.test.ts`
- `keeps the long-form chapter range and declares the long form explicitly` → `web/vue/src/pages/NewProjectPage.test.ts`
- `lists the builtin style before mine, each marked with where it comes from` → `web/vue/src/pages/NewProjectPage.test.ts`
- `defaults to no style and sends null` → `web/vue/src/pages/NewProjectPage.test.ts`
- `submits the selected style item id with the project` → `web/vue/src/pages/NewProjectPage.test.ts`
- `offers the realm ladder only for genres that have one` → `web/vue/src/pages/NewProjectPage.test.ts`
- `drops the realm ladder for genres without power scaling` → `web/vue/src/pages/NewProjectPage.test.ts`
- `offers published genre selection without editable root fields` → `web/vue/src/pages/NewProjectPage.test.ts`
- `preserves partial world rule keys and empty newlines during setup editing` → `web/vue/src/pages/NewProjectPage.test.ts`
- 参数化 `sessionStorage.%s fails` 的 getItem/setItem 两例 → 同名Vue参数化用例。

### ShortCreationPage

- `keeps the card hidden until the server says it is ready` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `shows the start option once ready, then the card, then commits and hands off to the workspace` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `shows the greeting and the editable plan card` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `fills the card from the server and defaults the chapter count` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `disables confirm until every required field is filled` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `sends the message and renders both sides of the turn` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `sends on Enter and leaves Shift+Enter to insert a newline` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `shows the user turn as soon as Enter is pressed, before the reply lands` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `puts the message back in the composer when the send fails` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `does not send on an Enter that is only committing an IME composition` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `does not offer a confirm once the session is committed` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `keeps the conversation list tucked away in history, and marks what is already writing` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `starts a second conversation without touching the first one` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `switches back to an earlier conversation and shows its own transcript` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `deletes one conversation after confirming, leaving the others alone` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `keeps the conversation when the delete confirmation is dismissed` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `prevents messages from being submitted from a committed session` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `labels a pending commit as planning and locks the card against further changes` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `labels opening a new conversation separately from waiting for an assistant reply` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `keeps keyboard focus inside the modal and restores it to the opener` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `preserves the next draft typed while the previous message is in flight` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `keeps the rail so the creation page is not a dead end` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `warns that the per-chapter figure will be compressed before commit` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `does not warn when the card fits under the whole-book cap` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `does not warn when 章数 is fractional and truncation lands on the cap` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `does not warn when 每章字数 is fractional and truncation lands on the cap` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `offers the style selector and a link to the library, with no inline import` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `opens the plan card as a modal that Escape and a backdrop click both close` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `grows every field box to its content so the dialog keeps a single scrollbar` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `keeps the box editable and says it is replying while a turn is in flight` → `web/vue/src/pages/ShortCreationPage.test.ts`
- `lets the author configure writing resources before the first short-story generation` → `web/vue/src/pages/ShortCreationPage.test.ts`
