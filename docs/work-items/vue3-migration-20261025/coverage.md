# Vue 迁移功能与测试追踪清单

状态：全部产品路由已有原生Vue归属，整体验收及独立最终签核已通过（见replacement-readiness.md）。Pi不在本轮范围。旧React72文件599测试保留且独立运行，不与Vue计数相加。

## 路由与行为对应

| 范围 | Vue实现与验证 | 状态 |
| --- | --- | --- |
| /login认证 | session*.test、LoginPage.test、App.test；登录/注册/MFA/续期/跨账号晚回 | 已实现 |
| /long /short作品列表与侧栏 | ProjectsPage.test、ProjectRail.test；草稿形态、删除409、角色与反馈入口、游客无请求 | 已实现 |
| /account与/environment | AccountPage.test、session.account.test、EnvironmentPage.test；密码/MFA/叶子更新 | 已实现 |
| /long/new /short/new /projects/new | NewProjectPage.test、ShortCreationPage.test、RankingsPanel.test；原51用例+竞态/续期/存储/双路径intent，共64项 | 已实现，独立审查无创建缺陷 |
| /projects/:id工作台 | WorkspacePage.test/live.test及生成/计划/预算/审核/修订/任务组件；原85+生命周期2共87项；SSE与编辑原用例另测 | 已实现；独立复审通过 |
| 作品settings/lore/audit | SettingsPage.test、LorePage.test、AuditPage.test、WorldGraph.test；资源选择、历史state、图谱与审计 | 已实现 |
| /theme /styles及反馈媒体 | AppearancePage/StyleLibraryPage/FeedbackWidget/AttachmentChip/CanvasMedia/PendantLamp/themeContext测试，65项含审查回归 | 已实现；独立复审通过 |
| admin全路由 | admin/*.test与review-admin-creation-regressions，115项；权限403、配置资源版本、详情、趋势图、可读执行内容 | 已实现；独立复审通过 |
| 深链/错误/游客/旧客户端 | router-parity6、App19、GuestShell、RouteBoundary、AppVersionGuard；启动等待router.isReady；生产构建禁止React模块 | 已实现，真实构建浏览器持续验收 |

## 自动门禁与发布边界

- `npm test`保留原React/单源TS测试；`npm run test:vue`独立执行Vue交互与原行为迁移测试，未用skip移除失败。
- router-parity比较真实新旧路由注册并禁止MigrationPendingPage；App测试核对游客保护及后台权限，路由登记本身不等于行为验收。
- 原AppVersionGuard自动刷新改为明确的“保存后手动刷新”提示，保留beforeunload草稿保护；此项是安全性有意调整，不沿用会丢草稿的自动刷新断言。
- Vite `vue-production-boundary`检查实际输出chunk modules，不允许React runtime或旧TSX生产依赖。测试期对照React路由不进入生产包。
- 合成API浏览器与真实隔离服务证据分开报告。真实模型、完整worker、同源发布回滚等未验项目必须明确列出，不能把合成结果算成真实集成通过。
- React生产默认入口保留，Vue独立dist-vue；没有提交、合并、推送或发布授权。

## 既有72份测试逐文件登记

以下是固定基线清单。保留表示继续运行，不表示Vue已覆盖；未来删除/替换需在此登记对应新断言与证据，不得靠skip消除失败。

| 原测试（web/src） | 首阶段处理 | 后续要求 |
| --- | --- | --- |
| `components/AppVersionGuard.test.ts` | 原测试保留；Vue对应 `vue/src/components/AppVersionGuard.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/CanvasMedia.test.tsx` | 原测试保留；Vue对应 `vue/src/components/CanvasMedia.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/ChapterEditor.test.tsx` | 原测试保留；Vue对应 `vue/src/components/ChapterEditor.parity.test.ts + composables/useChapterDraft.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/ChapterPlanPanel.test.tsx` | 原测试保留；Vue对应 `vue/src/components/ChapterPlanPanel.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/ConnectionNotices.test.tsx` | 原测试保留；Vue对应 `vue/src/components/ConnectionNotices.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/FeedbackWidget.test.tsx` | 原测试保留；Vue对应 `vue/src/components/FeedbackWidget.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/GenerationPanel.test.tsx` | 原测试保留；Vue对应 `vue/src/components/GenerationPanel.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/ProjectRail.test.tsx` | 原测试保留；Vue对应 `vue/src/components/ProjectRail.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/ResourceBodyFields.usability.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/migration.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/ReviewFlow.test.tsx` | 原测试保留；Vue对应 `vue/src/components/ReviewFlow.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/RevisionScope.test.tsx` | 原测试保留；Vue对应 `vue/src/components/RevisionScope.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/StreamingChapterView.test.tsx` | 原测试保留；Vue对应 `vue/src/components/StreamingChapterView.parity.test.ts + ChapterViews.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/StructuredTextField.test.tsx` | 原测试保留；Vue对应 `vue/src/components/FormFields.test.ts（含原2项替换值回归）` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/TaskBudgetPanel.test.tsx` | 原测试保留；Vue对应 `vue/src/components/TaskBudgetPanel.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `components/WritingResources.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/picker.test.ts + updates.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `context/AuthContext.test.tsx` | 原测试保留；Vue对应 `vue/src/session.auth.test.ts + session.test.ts + App.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `hooks/useTaskEvents.test.tsx` | 原测试保留；Vue对应 `vue/src/composables/useTaskEvents.parity.test.ts（原11项）+ useTaskEvents.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `lib/activeWrite.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/adminApi.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/api.auth.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/api.short.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/apiError.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/autoGrow.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/bookDraft.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/candidates.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/duration.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/genrePacks.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/genres.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/graph.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/labels.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/passwordPolicy.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/projectCreation.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/rankings.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/resourceDisplay.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/shortCreationApi.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/sidePanel.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/snapshotView.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/sse.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/styleLibraryApi.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/taskChapter.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/taskFlow.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/theme.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/themeImage.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/themePreview.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `lib/token.test.ts` | 单源保留并继续执行 | 复用协议；涉及Vue生命周期另补交互测试 |
| `pages/AccountPage.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/AccountPage.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/AdminPage.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/access.test.ts + actions.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/AppearancePage.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/AppearancePage.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/EnvironmentPage.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/EnvironmentPage.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/LoginPage.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/LoginPage.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/LorePage.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/LorePage.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/NewProjectPage.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/NewProjectPage.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/ProjectsPage.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/ProjectsPage.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/SettingsPage.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/SettingsPage.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/ShortCreationPage.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/ShortCreationPage.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/StyleLibraryPage.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/StyleLibraryPage.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/WorkspacePage.live.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/WorkspacePage.live.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/WorkspacePage.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/WorkspacePage.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/admin/AdminTrends.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/AdminTrends.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/admin/Analytics.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/Analytics.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/admin/ExecutionContent.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/ExecutionContent.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/admin/ModelManagement.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/ModelManagement.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/admin/PlatformConfiguration.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/PlatformConfiguration.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/admin/PlatformResources.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/PlatformResources.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/admin/ResourceContent.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/ResourceContent.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/admin/RolePromptFields.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/RolePromptFields.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/admin/SnapshotView.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/SnapshotView.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/admin/TaskDetail.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/TaskDetail.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/admin/UserDetail.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/UserDetail.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/admin/WritingResources.test.tsx` | 原测试保留；Vue对应 `vue/src/pages/admin/WritingResources.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `pages/admin/shared.test.ts` | 原测试保留；Vue对应 `vue/src/pages/admin/migration.test.ts + review-admin-creation-regressions.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |
| `router.test.tsx` | 原测试保留；Vue对应 `vue/src/router-parity.test.ts + App.test.ts` | 行为范围与新增回归见各模块report；总体验证见最终verification |

## 扩展替换验收新增边界（2026-10-26）

最终前端LHE构建：76文件564 tests；标准27、workspace10、大文本/IME/媒体/反馈24均已新鲜通过。历史模块计数记录其原执行时点，不与新增边界机械相加。最终状态以replacement-readiness.md为准。

| 新增范围 | 实际覆盖 | 状态 |
| --- | --- | --- |
| 密码变更/续期/切换账号 | 同owner重验、token轮换、后续有效登录、其他账号保护 | 已修复并独立复审 |
| 初始化历史与新任务 | 晚到章节/历史不能覆盖新任务，项目/账号往返与卸载 | 已修复并独立复审 |
| Plan/文风原生输入 | input→bubbling change→blur→确认/保存，业务数组不被Event替换 | RED后修复，独立11通过，实际Plan持久化通过 |
| 两rail登出 | 显式prop、模板listener、auth fallback单次调用 | 2RED后修复，Vue完整564与独立7通过；最终真实两rail单POST200通过 |
| SSE终态后observer尾帧 | 五种终态、summarize/metrics、真实续跑queued/running、Last-Event-ID越过终态严格不重发并关闭 | 16RED/1GREEN后修复17GREEN；相关95与独立17通过；最终真实edge4通过（原真实尾帧复验） |
| 真实链路与回退 | 同源会话/主题/脏草稿、实际worker、资源优先手动短篇、multipart/blob、MFA/图表 | Ddk10已通过；LHE+新SSE最终11通过 |
| 旧客户端hash与镜像 | 捕获实际旧Cvlt和候选资产、内容碰撞/symlink拒绝、cleanup失败不可报绿 | helper/merge独立门禁通过；最终retained双镜像各7项通过，API镜像源码/依赖/契约/healthz通过 |


## Main cutover fixes final checkpoint — 2026-10-26

Both P2 CLOSED: partial-create cleanup4/4; all3browser engines each28/10/26 including768 and real downloads/media. DefaultVue shared191+Vue564; explicitReact599; lint/types/build and configNode5GREEN. DefaultVue and explicitReact images each7checksGREEN, cleanupErrors=[]; no owned runtime resources remain. Independent fresh review noImportant/Critical, one deferredP3 timeout-profile cleanup. ApplicationLHE JS byte-identical to prior realTLS evidence. No commit/push/merge/deploy. Definitive current report main-cutover-fixes.md and build-provenance.json.


## Safe update fix final checkpoint — 2026-10-26

Release-safety P2 CLOSED: bothguards prompt/confirm only, sharedmutation lock, allVue memoryform scopes, manifest+HTML identity and legacyfilename enforced. Final shared205+Vue576/React613,lints/types/buildGREEN; threeengines each28+10+26+10,12groupsGREEN. NewBkVue/ReactBc imageeach10checksGREEN,oldassetwindow10files,allownedruntimeclean. Three scoped reviews+fresh final review noImportant/Critical. Source changed fromLHE; priorrealTLS evidence remainshistorical, not rerun forBk. Definitive safe-update-fixes.md/build-provenance.json. No commit/push/merge/deploy.
