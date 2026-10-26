# Task 2：主题、外观、文风库、反馈迁移

2026-10-25；分支 `codex/vue3-migration`。本任务不提交、不推送、不部署。保留所有既有修改；未改 App、router、session、共享库或原 React 实现。

## 实现与接入

- `web/vue/src/themeContext.ts` 导出 `createThemeScope`、`themeKey`、`useTheme`。scope 的 `theme/presets/activePresetId/style/lampPreview/video` 都是 Vue refs；`video.value` 为 `{ url, poster, config } | null`。
- App `provide(themeKey, scope)`、挂载 `scope.start()`、销毁 `scope.dispose()`。视频层由 App 挂载 `CanvasMedia.vue`，props 直接展开 `video.value`。start 幂等，dispose 使未完成读库失效并回收 URL。
- 方法：`setTheme/selectPreset/savePreset/deletePreset/saveStyle/setWallpaperPreview/setLampPreview`，参数保持原契约。`setWallpaperPreview(null)` 恢复已保存背景；草稿 URL 由调用页面拥有。
- `AppearancePage.vue`、`StyleLibraryPage.vue`、`FeedbackWidget.vue` 使用真正 Vue `defineComponent/setup/ref/computed/watch/h` SFC，无 React hook/runtime、iframe 或 React 挂载。复用原 CSS 和纯 TS 库。`CanvasMedia.vue` 和 `AttachmentChip.vue` 使用 script setup/template。
- `AttachmentChip.vue` default export，props `{ feedbackId: string; attachment: FeedbackAttachment }`，供管理员反馈复用。
- 反馈事件仍为 `myink:feedback`。主代理将其置于 RouterView 外，并在账号边界销毁；路由内普通跳转不会清除表单。

## 功能核对

- 官方主题确认应用、固定万古魔尊工作台缩略/放大预览、已使用标记。
- 自定义预设新建/编辑/颜色校验/命名/限额/保存/删除二次确认；只有保存写盘。
- 字体/字号/透明度/吊灯/灯光即时草稿预览，官方主题也生效；还原、收起确认、路由离开/参数变更确认、beforeunload、卸载恢复。
- 图片 2 MB、视频 50 MB、白名单、视频 poster 抓取、图片 cover/tile、视频 cover、缩放、拖拽位置、去掉、IndexedDB 与内存/legacy fallback 均复用原库和 schema。
- 系统减少动态时用保存的 poster；用户偏好变化监听清理。吊灯四套 SVG 完整保留，SVG属性与 CSS px 单位已适配 Vue。
- 文风库内置只读/个人重命名备注/删除确认/提取/新建保存/失败保留、八维中文、未知统计字段、已知列表保存时归一化、样本字符数、提取 busy 锁、暂存面板切换保留；新增离页与 beforeunload 保护。
- 反馈桌面灯/拖拽存储/隐藏尖端/下方反馈牌/控件点击让位/鼠标遮罩让位/窄屏事件入口，模态焦点圈定/Escape/回焦/滚动锁。
- 反馈分类、描述/联系、文件类型/大小/四文件上限、预览/移除、页面路径、我的反馈/刷新/状态/附件；提交仅允许 authenticated + roleVerified。
- 附件鉴权取字节、用户激活时同步预开页、失败关闭页、延迟 URL 回收；提交失败保留输入和附件。

## TDD 与实际验证

先为空组件/scope 写行为断言并实际观察失败，再实现；保留输出摘要如下。

- CanvasMedia：RED 缺 video/poster，GREEN 2 项。
- Theme scope：RED 缺 savePreset/setTheme，GREEN 保存/官方样式。
- 页面与反馈首批：RED 无按钮/表单，GREEN 草稿保存取消/目录/失败保留。
- AttachmentChip：RED 无附件名称按钮，GREEN 鉴权取件、tab URL/opener。
- 原外观 **17**、文风库 **14**、反馈 **8** 用例迁成 Vue 回归；外观回归进一步暴露并修复预览/离页派生状态遗漏，最终全部通过。
- 延迟 wallpaper 读取覆盖草稿：RED `blob:saved` 覆盖 `blob:draft`，GREEN，并验证 dispose 后晚读不创建 URL。
- ResizeObserver：RED observe 期望 3 次实际 0 次，改 onMounted + onScopeDispose 后 GREEN，卸载 disconnect 3 次。
- 提交回包吞掉新增反馈：RED 新描述消失，GREEN 以不可变提交快照清理已提交字段/附件，新输入保留。
- 主题/反馈/文风 beforeunload：RED 未阻止，GREEN 未保存草稿触发保护。
- 吊灯 Vue CSS 数值长度：RED width 空字符串，GREEN `104px`；props 灯光更新也通过。
- 壁纸异步保存期间新改名称：RED 回包覆盖新名，GREEN 仅确认对应草稿快照；卸载后不提交预设。

最终定向命令涵盖 11 份测试文件，**59/59 项通过**（22:37:32 最终整组运行，11/11 文件）。完整命令为 `npm --prefix web run test:vue -- vue/src/themeContext.test.ts vue/src/themeContext.race.test.ts vue/src/pages/AppearancePage.test.ts vue/src/pages/AppearancePage.regression.test.ts vue/src/pages/StyleLibraryPage.test.ts vue/src/pages/StyleLibraryPage.regression.test.ts vue/src/components/FeedbackWidget.test.ts vue/src/components/FeedbackWidget.regression.test.ts vue/src/components/CanvasMedia.test.ts vue/src/components/PendantLamp.test.ts vue/src/components/AttachmentChip.test.ts`。

`vue-tsc --noEmit -p /tmp/task2-tsconfig.json` 已通过，包含本范围生产文件和全部新增测试（临时配置扩展仓库 tsconfig、保留 strict/noUnused，只收窄 include；并包含 vite/client 声明）。

定向 ESLint 退出 0，0 errors；剩 2 条 `vue/one-component-per-file` warnings，来自 AppearancePage 内部的 WorkspacePreview 与页面两个 Vue 组件；为不扩大文件所有权暂保留。oxlint 报告的一处重复条件已删除，最终重跑退出 0、无输出。主代理负责统一全量 typecheck/lint/test/build。

## 未验证与审查重点

未运行真实浏览器视频解码/IndexedDB持久化/真实视频poster、桌面拖拽遮罩命中/移动端CSS实际布局、真实鉴权反馈上传下载、全仓React回归、整仓Vue构建及服务集成；不将 jsdom 通过当成这些场景验收。App/router 接入与跨账号销毁由主代理验证。请独立审查主题多次快速保存/预设切换媒体竞态及反馈账号边界。

## 独立审查修复（22:59）

已读取 `theme-general-core-review.md`，保留 `web/vue/src/review-theme-regressions.test.ts` 全部五个原复现。22:56:18 重新实跑 **5/5 RED**，修复后 22:58:00 **5/5 GREEN**。

1. 反馈弹窗使用 Vue watch 的 `onCleanup` 注册滚动恢复与 keydown 移除，关闭和组件销毁都执行。测试额外断言两次打开后的监听器分别移除，组件卸载恢复此前 overflow。
2. 文风 token 改为 computed，list/retry/extract/save/rename/remove 在派发时读取 `token.value`。认证状态或 token 改变时重新加载目录，保留本地样本、名称和草稿；旧加载用 generation + AbortController 失效，卸载中止。
3. `LAMP_HANG` 改为 computed，CSS cord/beam/span 同步使用当前灯；复现加强为 cone/shade/globe/cube 四套的全部三个几何变量。
4. 游客/无 token 跳过 list，显示本地空目录；所有文风受保护操作在 run 边界拒绝游客调用。原目录数据测试修正为真实 authenticated fixture，保留原数据/输入断言；游客无请求断言由独立复现验证。
5. 附件请求传入 AbortSignal，记录 pending 空白页，在组件销毁时 abort/关闭尚未导航的空白页；晚响应通过 alive/controller 双重校验，不能创建 URL 或发布旧账号字节。已完成页不在 pending 内，卸载不关闭、不提前 revoke，维持原 60 秒读取窗口。新增第六个审查测试覆盖已完成页保留；原下载断言加强为检查 AbortSignal。

最终定向执行原 59 项 + 审查 6 项，**12 文件 / 65 项全部通过**（22:58:50，exit 0）。`vue-tsc --noEmit -p /tmp/task2-tsconfig.json` 包含新增审查测试，exit 0。定向 ESLint exit 0，仍只有上述 2 条内部组件 warnings；oxlint exit 0、无输出。未改共享 API、App、router 或其他工作范围。真实浏览器/服务集成限制同前。已停写，等待 scope re-review。

### 焦点相邻复审（23:03）

保留审查新增的打开时 `activeElement === 关闭按钮` 断言；23:02:38 实跑 1 RED /5 GREEN，复现 watch 打开分支注册 cleanup 后继续落入还焦点分支。现打开分支注册 cleanup 后直接 return；关闭时仍还焦点到灯按钮，额外加入该关闭后断言。23:02:55 重跑审查 6 项 + 原 59 项，12 文件 **65/65 GREEN**；本范围严格 vue-tsc exit 0。只修改 FeedbackWidget、复现断言与本报告，已停写待复审。
