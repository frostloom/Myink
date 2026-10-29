# 最终独立综合审查

2026-10-25，审查基线 `a96066c43b41e535da4b73e260a998ba9350c415`，分支 `codex/vue3-migration`。审查对象包含全部未跟踪的 Vue 实现，不能用空的 HEAD 差异代替工作区审查。读取了 AGENTS、brief/progress/coverage、complete plan、三份模块独立审查及其已通过的窄范围复审。本审查未重复列出已经修复并复审批准的问题。

**最终窄范围复审结论（23:27）：规格批准，质量批准。原两项问题及相邻验收均已修复；详见文末复审证据。** 以下保留初审记录：初审规格与质量均需修改，发现两个新的跨模块问题，P1 一项、P2 一项；通过四个真实失败测试确认。没有修改生产代码、创建子代理、提交、推送、合并或发布。Hindsight 本地服务未连接，已按规则跳过。

## 规格审查

### P1 — 重写操作在等待资源检查或请求返回时改读当前选中章节

位置：`web/vue/src/components/GenerationPanel.vue:118`、`:122`、`:130`；调用方 `web/vue/src/pages/WorkspacePage.vue:842` 按账号/作品为 GenerationPanel 设置 key，同书切章不会销毁该组件。

确认弹窗在第110行明确询问“重写第1章”，但 `await beforeGenerate()` 后用 `selectedChapter.value.id/chapter_seq` 构造请求。资源检查网络请求期间，作者可以切选第2章；检查完成后发送的实际请求变成 `generateChapter('book','second',{seq:2,rewrite:true,mode:'auto'})`，重写一个没有被确认的章节。原 React 回调捕获发起当次的章节，Vue 转换后把这个快照改成了实时引用。这违反完整保留原行为以及不可撤销重写须对应确认目标的要求。

第二个复现覆盖另一个时间窗：POST 已正确发送第1章，响应返回前切选第2章，`onTaskStart` 却上报第2章。这会把工作台活动任务/活动章节和恢复数据关联到错误章节。

复现文件 `web/vue/src/review-final-integration.test.ts` 前两项：分别暂停资源预检与生成响应、改变 `selectedChapter`，观察实际请求目标或回调章节与原确认不一致。两项都真实 RED。修复应在确认/提交时捕获不可变项目、章节、模式和提交参数，让预检、POST、回调、提示使用同一操作快照，并保留现有项目/账号变更失效保护；也应检查同类 next/batch 的请求与回调快照，避免正文/批次数变化导致结果标错。

### P2 — 后台仍把 token 当成页面生命周期，续期直接丢未保存编辑

位置：`web/vue/src/pages/AdminPage.vue:11`、`:22`。

后台 `identity` 是 `userId:token`，RouterView key 又包含该 identity。同账号的自动续期或其他标签更新 token 时，整个后台子树被销毁。独立实测打开真实模型编辑弹窗、输入“未保存的后台配置”、仅替换同账号 token，弹窗直接消失，草稿丢失。App 外层已经按 userId 保留页面，内层 key 又引入了同一个旧问题。brief 第91行明确要求“续期保持编辑与任务上下文，退出/换账号清理”，因此不能以旧 React 曾有相同缺陷为由忽略。

修复范围还必须包含当前 token 的读取接口。只删除 RouterView token key 会暴露 setup 捕获旧凭证的问题：`AdminConsole.ts:464`、`ProjectDetail.ts:144`、`TaskDetail.ts:113`、`RunDetail.ts:67`、`UserDetail.ts:11` 在 setup 解构 `useAdminContext().token`，把父层 getter 变成了常量。第四项测试保留真实 AdminConsole 实例、更新注入 getter 的 token、点击“刷新当前视图”，实际请求仍传 before-renewal。这是续期修复的相邻验收条件，当前路由重挂恰好掩盖它，不计为第三个独立缺陷。父层应保留 context 的当前读取，子层 props 和 useResource 可以随之响应；角色撤销、403清空与跨账号/跨详情销毁仍需保留。

## 质量审查

上述两项也是确定的异步状态所有权与生命周期缺陷，而非风格偏好。未发现需要单独阻断交付的项目编码规则违反项。原生 Vue SFC/渲染函数、共享 API/类型/CSS 单源、Vue 独立 root/dist/typecheck/test include、保留 React 生产入口以及没有 Pi 改动，均符合本轮架构约束。

已核对 App/router/main、四态会话、游客项目页前置拦截、管理员 roleVerified/403、同账号与跨账号边界、短篇两种导航 state、资源 gate、草稿归属和 SSE 生命周期、CI/构建输出边界。已修复模块发现的处理与独立复审记录一致。没有用路由存在或测试数目推断所有功能已验收。

## 独立运行的验证

- 2026-10-25 23:14:24：`npm run test:vue -- vue/src/review-final-integration.test.ts`，**3/3 FAILED**，退出1，确认上述两项。
- 23:15:59：追加 retained-admin current-token 验收后重跑同命令，**4/4 FAILED**，退出1。管理员模型测试的路由 harness 未注册导航链接 `/admin/model-routes`，有无匹配路由 warning；断言失败直接来自真实编辑弹窗消失，与该未点击链接无关。
- 23:15:06：独立运行 App、router-parity、session.auth、session.account、useTaskEvents.parity、useChapterDraft、SettingsPage、admin/access、admin/updates，**9文件88项通过**，退出0，无skip。这说明已有保护保持通过，也说明它们未覆盖本次新增竞态。
- 起初写入测试时使用了错误的相对路径，shell 未创建文件，随后的测试显示 No test files found；更正路径后才得到上述真实 RED。该次工具错误不算产品发现或验证通过。

本审查没有重跑整套 React/Vue lint/build，也没有运行真实 PG/Redis/Rabbit/API/worker、实际 Chromium、媒体解码、长文性能或同源双向发布回退。主代理全量门禁和浏览器回执、其他代理真实隔离服务报告应独立引用；不能把本审查定向88项通过替代这些结果。当前新增失败测试必须修复并独立复审，之后需主代理完成受影响回归与产物身份更新。生产发布、旧资产/缓存和同源回退仍受独立授权与验收边界约束。

**交接状态：报告与四项复现已完成，生产代码未改。等待实施者修复；本轮审查停止写入。**


## 最终修复波独立窄范围复审 — 2026-10-25 23:27

阅读 `final-fix-report.md`、两项修复及相邻生产逻辑和新增测试；本次不扩大审查范围，不修改生产文件。

**规格批准，质量批准。初审两项均已关闭，未发现本波引入的新相邻阻断问题。**

- **P1 已修复**：GenerationPanel 的 next/rewrite/batch 在任何 await 前捕获项目、章节 ID/序号、模式、指令、批次大小、preflight 与回调。重写确认、预检后的 POST、响应回调和提示始终使用同一快照；切章/新输入/新章节列表不会改变已确认操作的目标。项目标量 watcher 改为同步失效，作用域销毁清理会递增版本；原项目晚回、旧预检、新项目 busy 与账号所属实例卸载保护保留。
- **P2 已修复**：AdminPage key 仅包含 userId 与详情 path，同账号 token 更新不重建后台编辑器；跨账号、跨详情仍销毁旧子树。403 清理后的 forbidden 状态不会被续期清除，服务端 role/roleVerified 的限制仍控制挂载。五个管理员入口保留 context 对象，在 loader/render 中读取当前 token；子层 props 与 useResource 的响应式请求更新仍有 AbortController/序号保护。新增 retained-detail 测试覆盖 project/task/run/user 四条路径，原复现覆盖真实模型草稿与运营控制台刷新。
- **追加流式行为修复通过**：StreamingChapterView 使用 chapterSeq/artifactId 两个标量 watch 来源，同一 artifact 新文本不重置作者手动暂停；“回到最新”仍恢复跟随。初挂已有正文在 mounted 后滚动至末尾。五项原行为等价回归全部通过，未改变流协议、正文组装或完整性判断。

独立执行：

`npm run test:vue -- vue/src/review-final-integration.test.ts vue/src/components/StreamingChapterView.parity.test.ts vue/src/components/GenerationPanel.test.ts vue/src/pages/admin/renewed-token.test.ts vue/src/pages/admin/access.test.ts vue/src/pages/admin/ModelManagement.test.ts vue/src/pages/admin/TaskDetail.test.ts vue/src/pages/admin/UserDetail.test.ts vue/src/pages/admin/actions.test.ts vue/src/pages/admin/Analytics.test.ts vue/src/components/WorkspaceLifecycle.test.ts`

**11 文件 / 65 项通过，无 skip，退出0；开始于23:27:45，耗时10.05秒。** 原四项初审复现包含在本次通过结果中，未删除或放宽断言。没有把实施者报告的236项、完整typecheck或lint计为本复审亲自执行。

这次批准仅关闭已发现问题与本波相邻安全边界，不替代主代理接下来的全量 React/Vue 门禁、新构建产物/来源摘要和真实/合成浏览器复跑，也不扩大生产发布授权。审查者已完成报告更新并停止写入。
