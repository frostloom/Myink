# Myink 全前端迁移 Vue 3：调研与决策方案

日期：2026-10-25。状态：用户已批准开始迁移；2026-10-25另行授权独立worktree与分支，Pi暂不处理；未授权提交、合并或发布。

## 1. 目标与约束

用户希望以后重点学习 Vue 3，将 Myink 与 ai-gateway 统一为 Vue 3 + TypeScript。目标是统一长期学习、阅读和维护方式，完整保留现有产品行为；不以性能提升或减少代码量作为未经验证的承诺。

此次迁移覆盖用户端、游客态、管理员后台、公共组件、主题媒体、前端测试与构建发布链。不同时重设计 UI、不改后端协议、不引入 SSR/Nuxt、不更换编辑器或整套组件库、不合并两个产品的认证系统。现有 API、数据库和任务执行服务继续使用。

迁移按模块开发、逐阶段验收；生产最后统一切换。不是一次写完全部代码，也不默认在生产长期同时运行 React/Vue。

用户不需要先学完 Vue 才能开始迁移。实施交付同时提供模块阅读顺序、关键概念说明及小型练习，优先让用户理解实际页面的数据流；不能让学习练习成为安全上线的前置人工操作。

## 2. 已核实的基线及调查限制

- 当前目录 `/Users/a1/项目/Myink`，分支 `main`，调查 HEAD `a9947e50241d7f0636fecfc9fb73a829027d4ec5`。
- 工作区已有 `src/myink/workflow/{nodes,runner,state}.py`、`tests/test_chapter_summary.py`、`tests/test_review_finalization_resume.py` 和 `.DS_Store` 的无关修改；不覆盖、不纳入迁移提交。实施前再次检查，不能假设本报告记录仍是最新状态。
- 前端 React 19、Router 7、TypeScript 6、Vite 8、Vitest 4、CSS Modules、ECharts。69 个生产 TSX 文件约 16,540 行，40 个非测试 TS 文件约 5,735 行，41 个 CSS 文件约 7,969 行，72 个测试文件约 10,341 行。文件/行数不等于测试用例数或覆盖率。
- 新建作品约 1,393 行、外观约 1,105 行、工作台约 1,089 行；复杂度主要在状态与行为，不是标签语法。
- 管理分支本地头 `06c94cee`，`main...codex/admin-control-plane` 为 `24/0`：该头已是 main 祖先，main 已有后台，必须迁移。前期“可能还有未合后台”只是初查猜测，本次本地 Git 核实后不再作为事实。
- Pi 本地头 `f553a3cf`，与 main 分歧 `39/158`。本次未发现 Pi 自 merge-base 引入 web/Caddy 修改；Pi CI 有 markers 和 offline-ops 差异。没有查询远端最新状态，不代表将来或其他未提交工作仍无差异。
- ai-gateway 已使用 Vue 3.5 + TS + Vite，但采用双 HTML 入口和动态组件切页，没有 Vue Router/Pinia。它可以参考 SFC 写法，不能直接复制 Myink 的路由、认证和发布架构；Myink Bearer 会话与其 Cookie 会话也不同。
- 本次由架构、业务兼容、测试发布三个子代理只读调查，并进行方案反方复核；没有运行产品测试、构建、集成环境、付费推理或线上健康检查。Hindsight 未连通，按项目规则跳过。

## 3. 路线比较与推荐决定

| 方案 | 优点 | 成本与风险 | 决定 |
| --- | --- | --- | --- |
| 同仓库逐模块开发 Vue，开发期双构建，整体验收后生产切换 | 新旧可对照、生产生命周期简单、回滚范围明确 | 迁移期间需控制功能漂移，完整收益较晚 | 推荐 |
| 生产按路由或用户分组逐步切换 | 较早获得真实反馈 | 需可靠分组、入口/版本绑定、整页跳转及状态交接，现无现成灰度设施 | 不作为默认；周期显著拉长再评估 |
| 一个页面嵌套 React/Vue | 可逐组件替换 | 双 Router、双生命周期、状态桥接与 Portal/Teleport 复杂 | 不采用 |
| 新建 web-vue 与 web-core 独立工程 | 依赖和边界隔离强 | 两套锁、共享库抽取、Docker COPY 与 CI 变更多 | 目前不需要 |

推荐保持一个 `web/package.json` 和 lockfile，通过独立 Vite root 隔离候选 Vue 页面。共享现有无 React 依赖的 TS 源，暂不抽跨包 web-core，不复制两份 API。具体工程设计如下，文件名属于提案，尚不存在：

```text
web/
  package.json / package-lock.json       # 单一依赖锁
  src/                                  # 既有 React，迁移期保留
    lib/ types.ts styles/               # Vue 直接复用的单源资产
  index.html / vite.config.ts           # React 原入口与配置
  vue/
    index.html                         # Vue root 的根 HTML
    src/
      main.ts / App.vue
      app/router.ts
      layouts/                         # UserShell / AdminShell / GuestShell
      features/                        # auth/projects/creation/workspace/admin 等
      composables/                     # 有明确销毁范围的 Vue 适配
      stores/                          # auth/theme 等少量应用状态
      components/                      # 公共 UI，沿用既有视觉与 CSS Modules
  vite.vue.config.ts / vitest.vue.config.ts
  tsconfig.vue.json / tsconfig.vue.node.json
  dist/                                # React 候选/回滚构建
  dist-vue/                            # Vue 候选构建
```

Vue Vite root 明确指向 `web/vue`；publicDir 指向 `web/public`；outDir 用绝对解析指向 `web/dist-vue`，开发 fs allow 仅开放需要的 web 范围。明确emptyOutDir只清理该候选目录，不清理React产物或历史发布资产。由正常 `index.html` 构建，候选根 URL 与深链均回退 Vue HTML。避免 `vue.html` 输出后没有 index.html、深链回退 React 的陷阱。两个候选不能写同一输出目录。

Vue 引用 `src/lib`、`types.ts`、CSS 的别名只允许已审计的入口，检查传递依赖不得进入 React hook/TSX。共享代码的修改同时验 React/Vue。先保持现有网络与持久化逻辑，只在确实需要测试/复用时抽局部纯函数，不先重写所有业务控制器。

## 4. 工具链与编码选择

- Vue 3 稳定版、Composition API、`<script setup lang="ts">`、Vue Router 4；Pinia 仅管理 auth/theme 等应用级共享状态，不强行全局化页面/任务/章节状态。
- 保持 Myink 现有 TS/Vite 主版本，先用兼容性验证确定 plugin-vue/vue-tsc 等精确锁定版本。不得照搬 ai-gateway 的 Vite 6/TS 5.6 或顺带升级整套工程。若 Vue 工具不兼容，先给出可复现结果，再单列版本调整方案。
- 核对 lockfile 中 Node engine 与本机/CI/Docker；当前依赖存在 `^20.19.0 || >=22.12.0` 要求。实际采用仍受支持且满足依赖的同一 Node 主/次版本，锁定后同步三处；不把“Node 20”泛称为所有小版本均可用。实施时核实维护状态。
- 使用 vue-tsc 检查模板与类型。现有 oxlint 不自动等于 Vue 模板 lint；核实 SFC 能力，不足时给 Vue 单独 ESLint/vue 规则，保持 TS 严格检查，不用全局 any 或关闭检查来过关。
- 保留 Vitest/jsdom；组件测试以 Vue Testing Library 为主，必要时使用 Vue Test Utils。现有纯 TS 测试继续执行，不重复复制。
- 两套 Vitest include 显式隔离：旧 `src/**/*.test.{ts,tsx}` 与新 `vue/src/**/*.test.ts`；保留 `css:true`，否则 `tokens.css?raw` 行为会改变。
- Vue tsconfig 只包含 Vue源/必要声明，import 的共享 TS 自然参与检查；不把所有旧 TSX 测试拉进 Vue 编译。各自独立 tsBuildInfo；新 Vite/Vitest config 纳入 node 配置类型检查。
- 继续使用 CSS Modules、tokens.css/global.css 和 `#root`，不同时改成 scoped/Tailwind。HTML 启动主题脚本继续防闪白。ECharts 保留原库，明确 mounted 初始化、ResizeObserver 清理和 unmount dispose。
- 默认不用 KeepAlive；其缓存会改变路由离开、SSE 和草稿的销毁规则。高频流用浅响应或批次更新，避免全文每 token 深层遍历；以真实长文测量决定优化，不承诺换框架自然加速。

## 5. 必须覆盖的功能范围

路由逐一登记，包括 `/login`、`/`、`/long`、`/short`、`/long/new`、`/short/new`、`/projects`、`/projects/new?draft=...`、`/account`、`/environment`、`/theme`、`/appearance`、`/styles`、`/projects/:projectId` 及 settings/audit/lore 子页。

后台包括 `/admin`、models/model-routes/defaults/prompts/genres/writing-resources、projects/tasks/runs/users 详情和旧 configuration 跳转。未知路径回首页、旧别名、hash 定位、浏览器前进后退、深链刷新都需保持。

页面名不是充分验收：还必须覆盖反馈、游客壳、媒体背景、桌面灯、图表、下载、键盘快捷键、移动导航、资源克隆/采用/更新、版本回退、记忆校正、长短篇差异、计划确认/审核/候选采纳及任务历史。

## 6. 核心行为契约与实现边界

### 6.1 身份、权限和路由生命周期

- 保留 checking/authenticated/anonymous/unavailable 四态，网络错误不能直接当未登录。游客壳不发受保护页面的挂载请求。
- 缓存 admin 一律重新验证 roleVerified，普通用户/未验证角色不能先发管理请求再隐藏内容。403 清理受保护内容并重新验证。
- 登录/注册/MFA/跨标签同步使用代次校验，旧账号请求或旧401不能覆盖/清空新账号。MFA票、密码和待确认密钥不持久化。
- 换账号/退出销毁旧请求、SSE、内存业务状态及监听器；同账号 token 续期与换账号区别处理。
- 已发现现状矛盾：AuthContext/API/SSE按 userId 避免续期中断，但 router 的 Outlet key 为 userId:token，会在续期重挂受保护树。先写定向复现/测试，明确目标为“续期保持编辑与任务上下文，退出/换账号清理”。把这项语义调整作为显式验收单元，不悄悄声称原实现已保障。
- Vue 路由参数变化可能复用组件，必须 watch 身份/项目/章节或按正确 key 销毁；不依赖 React 原来的卸载机制。反馈在 RouterView 外的受保护壳中，普通路由切换不清输入。
- 离开保护覆盖链接、浏览器back/forward及同组件参数更新；Vue onBeforeRouteLeave不足以覆盖参数复用，需配合onBeforeRouteUpdate或统一导航阻断，并在阻止导航时保留当前编辑状态。

### 6.2 草稿、保存和内容安全

- 草稿按 user/project/chapter 隔离；请求晚到不能跨章/跨账号修改状态。
- 保存捕获不可变提交快照；保存期间新输入仍 dirty，成功只确认已提交内容并更新新 baseVersion。保存前读请求失效，已卸载编辑器的保存回包不能清掉重开后新草稿。
- 409 保留本地草稿、展示服务器版本；明确确认后才覆盖/丢弃。读取失败不假装空正文。
- sessionStorage失败保留内存草稿、路由离开拦截和beforeunload；浏览器强退无法保证恢复。现有实现有提示/拦截，独立复制或导出按钮属于安全增强提案而非现状：P0确认范围，若增加则单列验收；最低保障是提示用户在切换前手动复制正文，不声称内存草稿可跨刷新恢复。
- 脏正文不允许绕过现有校正记忆/版本回退限制；短篇不开放不适用的逐章校正。

### 6.3 SSE、长任务与重复提交

- 保留 fetch SSE + Bearer，不改为无法带同样认证语义的裸 EventSource。
- 保留 last_event_id、分片解析、心跳、坏 JSON 容错、AbortController、指数退避、EOF与410快照核对；410不等于任务终态。
- 慢快照不能覆盖新SSE状态；切任务/切书后旧回包无效。节点快照保持250ms合并语义，不每事件请求全量快照。
- 同task续跑resumeKey、awaiting_plan/awaiting_review事件重放、attempt与artifact边界、Unicode code point offset必须继承，特别测试emoji/中文/重叠增量。
- 工作台加载快照、流连接、物化等待、结果完整性是不同状态；task done但缺章不能当完整成功。Plan直到真实Write artifact出现再切正文。
- activeWrite保护worker尚未生成数据库行的窗口；刷新/回滚恢复原taskId，不重新POST生成、不默认取消服务器任务。
- 短篇自动启动intent跨路由传递只消费一次。React location.state与Vue Router history.state不是相同接口：定义显式业务state字段，避免覆盖Vue保留的history字段；刷新、后退、重复挂载与响应丢失都不得再次扣额度/提交任务。
- 显式保留短篇两条路径：chooseResourcesFirst进入`/projects/:id/settings#writing-resources`并携configureBeforeWriting与planWarning；普通路径进入工作台并携beginShortWriting与planWarning。仅确认isShortBook且任务历史ready后消费，先接管已有activeTask再决定是否POST；清除启动intent时保留warning和Vue内部history字段。
- 配置优先路径保存资源后回工作台仅携planWarning，不携beginShortWriting，仍由作者手动“开始写”。保存资源、返回工作台、刷新不能被Vue迁移误改为自动生成触发。
- 创建request id先可靠持久化，失败则不创建；请求响应丢失先查询/恢复，不能盲重发；resume走服务器resume接口，不仅重连前端流。

### 6.4 表单、资源与后台

- 环境配置仅保存本节dirty leaves，false不能当空，继承值/单叶reset/脏sibling保留；加载失败禁保存。
- 资源generation、expected_revision、target_generation原样传递；409保留编辑。未知字段/隐藏技术字段不能被表单重新序列化删掉。
- 内置资源只读，自有资源改名/删除、克隆/取消、原子批量采用、override与精确release忽略均保持。
- 后台模型路由、默认值、提示词、题材和资源管理保留只读/写入边界、敏感字段遮罩与错误内容呈现；不为迁移放宽权限或改后端返回。
- Enter发送、Shift+Enter换行、IME组合输入、发送失败恢复、发送期间新输入不清空。弹窗焦点圈定/返回、Escape、屏幕阅读器label和键盘顺序保留。

### 6.5 主题、媒体和反馈

- 主题预览立即显示但确认前不持久化；取消还原，离页保护。官方主题的样式设置也保留。
- 图片2MB、视频50MB及类型白名单、poster、IndexedDB fallback、加载竞态和object URL回收保持；实际视频/图片行为需真浏览器测试。
- 反馈跨路由保留，提交失败保留输入与附件；附件鉴权下载和路径记录保持。反馈File/未上传媒体等纯内存态不能假装刷新可恢复。

## 7. 浏览器数据兼容表

| 数据 | 当前协议 | 迁移和回滚要求 |
| --- | --- | --- |
| 会话 | localStorage `myink.session`，旧token/user_id/username键 | 保留格式与升级读取，缓存角色不可信；不强制全员清存储 |
| 章节草稿 | sessionStorage `myink.draft:<user>:<project>:<chapter>`，content/baseVersion | 新旧双向可读，不搬localStorage，不跨标签覆盖 |
| 活动写作 | sessionStorage `myink.activeWrite.<user>.<project>`，taskId/chapterSeq/batchTotal | 保留，恢复原任务；不能视为完整SSE游标备份 |
| 创建幂等 | sessionStorage `myink.pending-project-creation` | 保留ID及清理规则，不重新生成导致重复创建 |
| 外观偏好 | `myink.theme`/custom/presets/style/lampX/lampPos、`myink.sidePanel` | 不改schema，保留旧位置升级和边界校正 |
| 壁纸 | IndexedDB `myink-theme` v1 / `files`，preset ID、`:poster`、旧wallpaper | 保留DB/version/Blob与旧fallback，不能先做破坏性升级 |

同源是兼容前提。5173与5174、不同域名/协议的localStorage/IndexedDB/sessionStorage不能视为共享；开发对照用去敏fixture导入各自上下文。生产保持原域名/协议/根路径；同标签刷新可保留sessionStorage，换新标签不能承诺自动恢复原标签草稿。不记录token、正文或敏感附件到诊断日志。

## 8. 阶段、产物与验收门槛

| 阶段 | 交付 | 通过后才进入下一阶段 |
| --- | --- | --- |
| P0 基线与矩阵 | 路由/组件/存储/行为对应表，运行现有门禁并记录基线失败，功能变更登记规则 | 无未说明基线失败；既有未提交修改归属清楚 |
| P1 双工程配置 | 单锁双root/双构建/双测试/双类型检查，Vue根页及深链、共享源审计 | 新依赖后React门禁仍通过，Vue产物独立可服务，输出不互相覆盖 |
| P2 基础与普通页面 | auth/theme/路由壳/反馈，列表、账号、环境和资源页 | 游客/权限/续期/跨标签和旧链接测试通过；反馈不丢 |
| P3 创建与内容配置 | 长短篇创建、settings/lore/audit、资源采用和更新 | 幂等、短篇intent、409、未知字段与IME用例通过 |
| P4 核心工作台 | 草稿编辑、历史/回退、候选/审核/计划、SSE/任务恢复 | 归属P4及之前阶段的P0行为测试、断网重连、物化窗口与Unicode流通过；全矩阵在P6验收 |
| P5 管理后台 | 控制台、模型/路由/默认值、提示词/题材/资源、详情/趋势/反馈管理 | 全路由角色矩阵、并发编辑与错误/空态通过 |
| P6 候选整体验收 | 合成浏览器+真实隔离链路、长文/移动端/媒体、双向回滚演练 | 无数据丢失、重复提交、越权；已知阻塞明确关闭 |
| P7 切换准备 | 安全更新过渡版本、旧assets保留、镜像/来源清单、操作与回退手册 | 回退可独立操作；过渡React与最终Vue的实际发布均另需用户明确授权 |
| P8 稳定后清理 | 移除React依赖/旧测试，归并Vue目录、更新文档/脚本 | 观察期及回滚窗口经确认结束，再做单独审查 |

P2列表页是学习与开发的第一块；复杂外观/媒体可以跨阶段逐步完成，但P6前必须完整验收。P4与P5可在共享接口冻结后并行，由单一集成人员维护共同入口，不让多个代理同时改同一文件。每个开发单元包含测试→实现→复验→审查；默认不自动提交/推送。

## 9. 测试与证据策略

现有72份测试保留其行为断言，不能通过删除旧测试、只检查Vue能挂载来宣布迁移完成。建立“旧测试/行为→新测试→浏览器场景→状态”追踪表。

已有 `scripts/evaluate-browser.cjs` 是Playwright Chromium+真实构建产物+合成API/SSE，包含计划确认、真实增量可见、重连游标、409草稿和390px检查。它是可用资产，修正之前“未发现浏览器测试”的初查结论。其`web/dist`硬编码需参数化并锁定Playwright依赖；`WorkspacePage.live.test.tsx`也使用替身，不是真实服务集成。

| 层级 | 场景 | 证明范围 |
| --- | --- | --- |
| 纯TS | API错误/会话、SSE parser、资源/草稿协议等 | 共享规则兼容 |
| Vue组件与composable | fake timers测续期/重连，deferred promise测保存/读取晚回，watch清理 | 框架交互与生命周期 |
| 双产物合成浏览器 | 同fixtures对照React/Vue；扩展创建/短篇/后台/跨标签/主题/IME | 浏览器行为，不证明真实后端 |
| 真实隔离集成 | 测试Caddy→API→PG/Redis/RabbitMQ→worker，模型确定性替身 | 真鉴权/RLS、入队物化、SSE代理及409 |
| 发布演练 | 冷热缓存、旧chunk、运行中任务、脏/存储失败草稿、React↔Vue | 切换和回退可用 |
| 人工重点 | 中文输入法、长文选择与滚动、视频、焦点/键盘、移动端 | 自动化不足部分 |

浏览器主验Chromium；WebKit与Firefox覆盖编辑、下载、媒体和路由关键冒烟，具体操作系统组合以现有用户设备为依据记录。屏宽至少390/768/1440；长文按现有真实最大样本加余量，使用去敏/合成文本，不把私密作品复制到公开测试。

现有门禁：`cd web && npm ci`，随后`npm run lint`、`npm test`、`npm run build`。迁移期新增拟定命令 `lint:vue`、`typecheck:vue`、`test:vue`、`build:vue`、`dev:vue`，不是声称现在可执行。lint/test/build在切换前保持React，候选Vue单独运行；正式切换后默认命令覆盖共享TS+Vue，保留`*:react`用于回退验证。

新增`test:browser`参数化dist路径，两个产物分别留存结果，不重复调用真实模型。新增依赖的`npm ci`后两套门禁都跑。安全测试只用隔离测试账号，真实模型烟测若确需调用需另列授权与预算。

完整CI还包括Python编译、`python scripts/evaluate.py validate`、全新库初始化、API契约导出/diff、全量pytest和Python/Caddy镜像构建。现有`ci-local.sh`不包含全部CI步骤，不能把脚本通过等同于所有CI项通过。

`bash scripts/ci-local.sh`固定Compose名myink-test和端口15432/16380/15673，退出清理卷；跨会话/worktree不得并行。当前test Compose仅有基础设施，真实浏览器集成另需隔离API/worker/Caddy配置。不得指向开发或生产数据。若没配置独立资源则串行，不凭worktree声称隔离。运行前检查契约既有差异。

## 10. 发布、过渡与回滚

当前AppVersionGuard首次挂载、30秒、聚焦/可见时抓根HTML，看到`/assets/index-*.js`变化即reload；没有判断草稿/附件。迁移必须处理这一已存在的发布风险。

1. 先在React生产版本准备并验证安全更新策略：显式build manifest/版本提示，默认只提示、用户确认后刷新，不按新版本出现自动reload；保存中禁切换。确认前提醒检查章节、建书/短篇输入、后台表单、反馈附件、主题预览等未提交内容，存储失败先复制/导出。不为了迁移构建庞大的全局dirty框架，但所有内存表单都必须有明确离开保护或确认行为。候选开发环境关闭生产轮询或只检测自身入口，不能读另一个应用的根HTML。
2. Vue独立root产物维持正式index入口并显式固定/验证index入口chunk命名，兼容旧守卫识别；新守卫不能再仅靠文件名前缀判断版本。新旧manifest及HTML版本绑定同一release。
3. 旧旧版JS不会因发布新守卫自动获得保护；休眠/离线标签页可能数日后恢复。等待30秒不能证明收敛。小范围邀请试用应通知并确认活跃用户先保存/导出、关闭重开，保留旧资源；仅在内存且存储失败的草稿，服务器不能技术性挽救。明确记录残余风险，不能宣称零风险升级。
4. 不同release的hashed assets在切换和回退期间共存，保留当前/上一React与Vue版本所需资源。现有Caddy一年immutable只解决缓存，不保证旧未缓存chunk仍存在；旧路径必须返回JS/CSS文件而非SPA HTML。部署前用旧HTML及其依赖图中的资源路径验证新候选。回退发布也必须携带已经发布的Vue资产并集，不能直接换成仅含旧React资产的历史镜像；提前准备经过验证的React入口+双向资产回退镜像，或通过原子入口选择实现回退。
5. 完成P6后、用户明确发布授权后，默认build切Vue，Docker把`web/dist-vue`复制到原`/srv/web/dist`；保持API路径、SPA fallback、SSE flush_interval -1与静态压缩范围。保留React构建配置和不可变镜像digest，初次切换不删除React。
6. 记录前端artifact/digest、API revision、配置和协议版本。切换清单检查深链、登录权限、任务恢复、保存、资源404、JS错误；不得用真实生产写入测试代替隔离验收。
7. 回滚仅切静态入口/前端镜像，保留现有API/worker/DB和后台任务；不compose down、不回库。重启Caddy会短断SSE，客户端需从原task恢复；不重新提交生成。
8. 第一版Vue保持存储schema/API不变，回退旧React验证能读Vue产生的数据。若发现回退需要API/schema变化，则停止宣称前端独立回退，先补交叉兼容矩阵。
9. 默认安排至少一周稳定观察，且覆盖一次正常长短篇、管理员维护、断线恢复和回退演练；时间到不自动删旧资源。清理需结合仍活跃旧客户端、实际错误与用户确认。保留上一版本资源的期限须覆盖承诺支持的旧客户端窗口；一年cache并不意味着磁盘必须永久保存每版，也不意味着保留一周就足够。

任何数据丢失、跨账号串数据、重复生成、权限绕过都属于停止切换/立即回退条件。普通404、异常重连、保存冲突及草稿恢复失败建立基线并逐项调查；不能靠刷新率/错误被吞掉判断稳定。诊断仅采集版本、错误类别、状态与匿名关联信息，不采token/正文/密码。

## 11. 分支与功能漂移控制

- 迁移主线在main，遵守三长期分支规则，不默认新建Vue长期分支或worktree。
- main已有管理员代码照常迁移；不把老admin分支文件覆盖回main。管理员新功能仍按既有分支约定开发，迁移期如有新变更登记其Vue对应项。
- Pi独有逻辑不因本次迁移合入main；前端迁移补丁向Pi同步时只挑前端及构建适配范围，保留其CI markers/offline-ops，不整文件覆盖。
- 实施开始重新核对本地/远端HEAD与未提交差异，记录每个行为的来源；不将本地分支旧状态当最终生产事实。
- 迁移期间允许紧急修复，小功能也要登记React/Vue双修或明确延后；每个阶段结束重查shared TS与后端契约变化。最后候选验收设置短暂前端功能冻结窗口，紧急修复使受影响验收重新运行。
- 授权边界：本请求只授权子代理调研与方案。提交、推送、分支合入和发布分别依后续明确授权执行；本方案不是其替代。

## 12. 工作量、并行方式与估算不确定性

以下按熟悉Vue/TS、AI辅助、功能与样式基本等价、不同时重做后端估算；阶段包含本阶段测试，最后整体验收仅算跨模块/真实链路与发布演练，避免重复叠加工期。

| 工作包 | 人日 |
| --- | ---: |
| 基线、契约、工具兼容和双构建 | 5–8 |
| auth/theme/壳/公共组件与普通页面 | 8–12 |
| 长短篇创建、项目配置、资源流程 | 6–9 |
| 工作台、SSE、编辑与恢复 | 9–14 |
| 管理后台与详情/图表 | 6–9 |
| 跨模块验收、真实隔离集成、发布/回退 | 6–10 |
| 合计 | 40–62 |

建议留20%左右风险余量，预算约48–75人日。单人全职约10–15周，不是AI持续运行时长或承诺日期；用户边学边改还取决于每周可用时间。两名实施者加独立审查可在接口冻结后并行用户普通页/后台，核心auth/SSE/草稿由明确负责人集成，不能简单将人日除以人数。

子代理局部给出过25–42人日的开发估算和8–14人日的验证发布估算；主方案按完整范围重新归并，加入安全过渡/分支/跨端验证，因此采用更保守区间，而非把不同口径直接平均。P0/P1结束用实际依赖兼容和首模块耗时重新估算。

首个可评审里程碑建议为3–5人日的基础验证：双构建、共享API引用、Vue根与深链、作品列表、认证最小完整链路，并用测试壳先验证SSE与草稿控制器的危险竞态。这个范围不承诺完成完整编辑工作台或生产发布。如果工具链/状态恢复出现实质阻断，在扩大迁移前给出证据及修订预算。

## 13. 用户学习与交付组织

采用“公共按钮/作品列表 → 表单与API → composable → 路由与状态 → 编辑/流式”阅读顺序，使用ai-gateway作为相同语法的第二个参考，而非复制业务实现。每模块附简短说明：数据从哪里来、哪些是computed/ref、何时请求和销毁、错误如何处理。TS先用基本类型/interface与泛型ref，不因学习目标降低生产类型和行为保障。

实施方案确认后再拆成可逐项执行的细计划，写明文件、接口、失败测试、命令及审查边界；本报告是完整技术决策与阶段门槛，不伪装成所有函数签名已冻结的逐行施工单。

## 14. 完成定义

- main现有全部路由与业务行为有Vue归属，管理员与游客无遗漏。
- 共享TS测试与Vue交互测试通过；旧测试替代有对应证据，SKIP/环境阻塞不算通过。
- 合成浏览器与真实隔离集成分开报告；关键跨账号、草稿、重复提交、SSE恢复、资源并发、媒体行为通过。
- 候选根/深链、资源缓存、旧客户端、安全更新与双向回滚演练通过。
- lint、vue-tsc、build、完整适用CI均有命令与退出证据；未运行项明确列出。
- 版本/产物/回退手册可追溯，发布另获授权；稳定后清理是独立交付，初次切换不靠删除旧实现来证明完成。

## 15. 主要代码证据

`web/src/router.tsx`、`context/AuthContext.tsx`、`context/ThemeContext.tsx`、`hooks/useTaskEvents.ts`、`hooks/useChapterDraft.ts`、`pages/WorkspacePage.tsx`、`pages/NewProjectPage.tsx`、`pages/ShortCreationPage.tsx`、`pages/EnvironmentPage.tsx`、`pages/admin/*`、`components/FeedbackWidget.tsx`、`components/AppVersionGuard*`、`lib/api.ts`、`lib/sse.ts`、`lib/token.ts`、`lib/chapterDraft.ts`、`lib/activeWrite.ts`、`lib/theme*.ts`、`lib/writingResources.ts`、`web/index.html`、`web/vite.config.ts`、`scripts/evaluate-browser.cjs`、`scripts/ci-local.sh`、`docker-compose.test.yml`、`caddy/Caddyfile`、`caddy/Dockerfile`、`.github/workflows/ci.yml`、`docs/BRANCHES.md`。

## 执行补充（2026-10-25）

用户明确要求创建独立worktree与分支，在其中开始迁移，并暂不处理Pi。实际worktree为`/Users/a1/.codex/worktrees/myink-vue3-migration/Myink`，分支`codex/vue3-migration`，基线`a96066c43b41e535da4b73e260a998ba9350c415`。此明确授权覆盖上文第11节默认main实施及不创建分支的提案；原目录后端未提交修改不复制。首阶段详见实施计划。
