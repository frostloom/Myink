# 全量Vue候选验证

> 本文件保留首轮迁移验收的历史证据。2026-10-26扩展“可替换React”验收以replacement-readiness.md及各readiness报告为准；当前Vue76/564、LHE构建，另包含真实链路发现的共享SSE重放后端补丁。原“不改后端”和旧测试总数不能作为扩展验收最终结论。

工作区`/Users/a1/.codex/worktrees/myink-vue3-migration/Myink`，分支`codex/vue3-migration`。全部改动未提交；HEAD只是基线，候选身份见`build-provenance.json`。Pi和现有开发后端不在改动范围。没有合入、推送或发布。

## 已实际运行

| 检查 | 结果 |
| --- | --- |
| React `npm test` | 72文件599项通过，无skip |
| React `npm run lint` | exit0；12项既有warning |
| React `npm run build` | exit0；大chunk既有warning |
| Vue `npm run test:vue` | 最终23:27运行：72文件533项通过，无skip |
| Vue `npm run lint:vue` | exit0；7项warning（4项同文件内部组件、3项测试fixture多组件），无error |
| Vue `npm run build:vue` | exit0，包括vue-tsc和node配置严格类型检查 |
| Vue实际产物依赖门禁 | 818modules构建通过；禁止React运行时和旧TSX进入生产chunk |
| Vue合成API浏览器 | 25项通过，receipt路径如下 |
| Vue工作台合成API浏览器 | 10项通过，page_errors和unknown_routes均空 |
| React同一工作台浏览器 | 相同10项通过，page_errors和unknown_routes均空 |

浏览器均为真实Chromium加载实际构建；API/SSE受控fixture，不算真实后端/数据库/模型验证。

- Vue冒烟：`/var/folders/sw/_x387kld25bgsp22s4n5rfjm0000gn/T/myink-vue-browser-pOlG2d/receipt.json`
- Vue工作台：`/tmp/myink-vue-full-browser-final-2328/receipt.json`
- React工作台：`/tmp/myink-react-browser-2311/receipt.json`
- 移动端截图：`/tmp/myink-vue-full-browser-final-2328/04-mobile.png`，已实际查看。
- 主题保存截图：`/var/folders/sw/_x387kld25bgsp22s4n5rfjm0000gn/T/myink-vue-browser-pOlG2d/vue-theme.png`，已实际查看。

工作台10项覆盖登录、Plan确认、两次正文增量、SSE断线游标、刷新后人工驳回、续跑、刷新已保存正文、409保留草稿禁止覆盖、390px无横向溢出。25项冒烟还覆盖游客无保护请求、错误密码/注册校验/MFA、长短篇分区与草稿、短篇创建深链、主题持久化与IndexedDB壁纸刷新恢复、文风目录、删除取消和409、退出及管理员深链刷新。

## 审查与修复

- general账号/设置审查已修正RouterLink state和复用路由history；core原SSE11和编辑9用例通过。
- theme-general-core-review：5个P2及焦点相邻回归实测RED→GREEN，最终复审通过。
- admin-creation-review：趋势首次挂载、返回链接slot和CSS长度3项实测RED→GREEN，最终复审通过；创建原64项独立复跑通过。
- workspace-integration-review：章节列表初挂P1、Plan同版本覆盖P2、跨书导出P2实测RED→GREEN，新增晚成功/失败隔离；最终复审通过。
- 真实构建浏览器还捕获并修复main初始路由未ready被首页抢跳，原浏览器失败保留记录，最终重跑通过。
- 最终综合审查额外发现重写目标快照P1、后台续期编辑丢失P2；修复动态token、所有生成请求快照、流式暂停跟随后，独立11文件65项复审通过。
- 真实隔离服务已通过108项Python回归、19项API/fixture检查、12项真实浏览器、5项真实Caddy HTTP检查；最终index-BWgRncmt.js已再次通过真实19/12/5检查；自建API/Compose/Caddy全部清理，既有环境保持运行，详见real-integration-report。未把中间失败报告为通过。

## 限制与发布门槛

尚未执行正式发布、同源新旧双向切换、旧资产长期缓存演练、真实付费模型完整worker链路。最终构建VueJS约1.70MB（gzip约563KB），有大chunk提示；React同次约1.89MB（gzip604KB）。没有通过隐藏warning宣称零风险。

真实服务证据将单独写入`real-integration-report.md`；最终综合审查写入`final-review.md`。发布另行授权，具体准备见`preview-and-rollback.md`。

CI已固定运行Vue25项冒烟及工作台回归，并保留React同一工作台回归。新增CI YAML经实际解析通过，git diff --check无错误。真实模型/worker、TLS及生产发布演练仍是明确未验范围，不影响本轮代码迁移候选交付，不能据此批准上线。

最终真实浏览器回执：`/var/folders/sw/_x387kld25bgsp22s4n5rfjm0000gn/T/myink-vue-real-browser-pJdyle/receipt.json`，passed=true、12 checks、pageErrors=[]，已由主代理读取核实。


## 用户要求的再次评审补充（2026-10-25 23:55）

**新增两个未关闭P2，当前新增回归为RED，候选需修复后重新验收。** 同账号续期会清空AccountPage密码/MFA上下文，也会使EnvironmentPage覆盖未保存偏好。详见review-standards-20261025.md与review-spec-20261025.md。主代理本次实际重跑4文件：2项失败、17项通过，无skip，exit1；失败均为新复现review-audit-standards-account.test.ts。此前533项与构建/浏览器通过是当次历史记录，不代表新增加的续期场景已通过。本轮评审未修改生产代码。


## 2026-10-26 续期缺陷修复完成

上一轮两个P2已修复并独立复审批准：同owner续期保留账号密码/MFA以及高级设置草稿和保存状态；换账号、退出、撤权仍同步清理；存储撤权事件排队时也拒绝旧MFA回包。新增8项回归含实际RED→GREEN证据。完整Vue73文件541项、lint/严格类型/build均通过；新构建合成冒烟27项、工作台10项通过。最新产物index-DgQ77hkA.js，来源摘要已更新。详见renewal-fix-verification.md和renewal-fix-review.md。本次没有重启旧真实服务栈，没有修改共享React/后端生产代码，没有提交、推送、合并或发布。


## 2026-10-26 继续评审：两个新P2开放

规范/质量轴发现session.ts229密码修改成功被同owner会话校验的generation变化吞掉；规格轴发现WorkspacePage.vue285–314初始化历史慢回覆盖刚启动的新任务。新增3项复现均RED，原相关11项通过。上一轮8项账号/环境续期回归仍通过；本轮无生产代码修改。详见review-second-summary-20261026.md。当前不能把历史541GREEN当作包含新增用例的完整批准。
