# Vue 3 迁移首阶段实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在独立分支建立 Vue 候选构建、作品列表切片和防遗漏测试门禁；React 仍是生产前端。
**Architecture:** web 单 package/lock，Vue root=web/vue，显式复用既有 TS 与 CSS，产物 dist-vue 与 React dist 隔离。
**Tech Stack:** Vue3 / Router4 / TS6 / Vite8 / Vitest / Testing Library / Playwright。
**Spec:** ../../work-items/vue3-migration-20261025/brief.md

## Global Constraints

- 用户已明确授权新 worktree 和 codex/vue3-migration 分支，覆盖此前默认不新建分支的约定；Pi暂不处理。
- 基线 a96066c43b41e535da4b73e260a998ba9350c415，仅复制方案文档，不复制原目录未提交后端代码。
- 不合并、不提交、不推送、不发布，不改生产Docker入口和API协议。
- 首阶段不是完整迁移；登录/注册/MFA界面、续期、主题交互、工作台和后台均保留待迁移状态，发布阻断。
- 首阶段会话仅恢复并服务端校验测试会话、处理跨标签变化和退出；不宣称完整AuthContext已替代。

## Review Focus

- 缓存admin不能直接授信，校验失败不得发作品请求；网络失败不能视为匿名。
- 切账号/卸载后的旧列表与删除回包不得进入新上下文。
- 长短篇列表、草稿链接、删除409与取消行为不能遗漏。
- Vue深链必须返回Vue HTML；React/Vue测试与输出不得相互覆盖。
- 任一未迁移路径显式提示，不冒充已实现，默认生产构建仍React。

### Task 1: 测试基线与独立工程

**Files:** web/package*.json, web/vite*.config.ts, web/tsconfig.vue*.json, web/eslint.vue.config.mjs, web/vue/index.html, .github/workflows/ci.yml。
**Interfaces:** dev:vue端口5174；build:vue输出web/dist-vue；test:vue仅vue/src/**/*.test.ts；原测试仅src/**/*.test.{ts,tsx}。
- [x] 记录React lint/test/build基线，确认已存在失败与警告。
- [x] 固定兼容依赖，明确root/publicDir/outDir/fs.allow与独立typecheck。
- [x] 先写候选交互失败测试，再实现Vue页面；CI新增Vue门禁，React门禁保留。

### Task 2: 会话校验与作品列表

**Files:** web/vue/src/session.ts, App.vue, router.ts, pages/ProjectsPage.vue, pages/MigrationPendingPage.vue及相邻测试。
**Interfaces:** createSessionScope返回status/session/error/revalidate/start/dispose/logout；ProjectsPage props form/username；账号变化按userId重建候选子树。
- [x] RED：未登录/验证不可用/旧账号晚回/失效会话测试。
- [x] GREEN：使用现有api/token实现候选会话范围，销毁监听器与校验请求。
- [x] RED：长短篇隔离、草稿入口、删除取消/409、空态/错误/晚回测试。
- [x] GREEN：迁移真实列表UI与侧栏，复用现有CSS和API。
- [x] RED→GREEN：Router实际跳转到未迁移页面时明确提示；不把未知路径兜底当已迁移。

### Task 3: 浏览器与防遗漏追踪

**Files:** docs/work-items/vue3-migration-20261025/coverage.md, web/scripts/vue-browser-smoke.mjs, scripts/evaluate-browser.cjs。
**Interfaces:** 旧脚本新增--dist；新脚本仅访问loopback并提供合成API，输出回执；无真实账户/模型调用。
- [x] 登记所有现有路由/72份测试的迁移归属，未迁移必须pending，不能算通过。
- [x] 浏览器验证Vue根/深链、真实API封装的鉴权请求、列表删除409、刷新、窄屏与缺失页面提示。
- [x] 旧React完整合成浏览器场景继续运行；新列表冒烟不能替代工作台端到端验收。

### Task 4: 整体验证与审查

- [x] React lint / 599项基线测试 / build，Vue lint / typecheck / test / build。
- [x] 同一worktree运行两个合成浏览器脚本并分开记录结果。
- [x] 独立审查实现/测试/范围，修复重要问题后复验。
- [x] 更新verification.md，列明已迁移、pending、未运行真实服务集成与发布状态。

## 执行结果

首阶段完成，详细命令结果、失败与修复、未验证范围见`../../work-items/vue3-migration-20261025/verification.md`。所有勾选仅指本首阶段，不表示brief中P2-P8完成。成果保留未提交工作区；执行中的实质调整：校验到期竞态修复、路由测试运行期加载React边界、旧浏览器资源fixture补全。
