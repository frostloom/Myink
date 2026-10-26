# Replacement readiness：Task 1 独立复审

2026-10-26，独立测试/复审角色。范围为 `session.ts` 的成功密码修改竞态与 `WorkspacePage.vue` 的初始章节/历史恢复竞态；未修改生产文件，未提交、推送、合并或部署。已阅读 AGENTS、readiness plan Task 1、开发修复记录及两处产品代码；无更深适用 AGENTS。Hindsight recall 连接失败（curl exit 7），按规则跳过。

## Spec 结论

本次限定范围内未发现新的确认产品缺陷，两项原 P2 的回归均通过。

- session 将成功登录（含 MFA/register）的 loginVersion 与一般校验 generation 分开：同 token revalidate 不能吞掉密码成功的本地退出，普通 renew/token rotation 不被误认作后来成功登录；真正后来成功登录不被旧操作清除。
- storage token 改变时重新向服务器验证，而不是清除未知归属凭证；撤销结果退出并提示密码已改，仍有效跨 tab 凭证保留。离线校验维持原有已验证同账号 session 策略，不把网络异常当作已确认撤销；该行为没有提供服务器撤销完成的证明。
- Workspace 初始自动选章和全项目历史查询在读取前后检查 taskStartVersion、同步 workspaceVersion、projectId 和 disposal；新任务以及账号/项目往返使旧初始化失效。现有初始恢复、saved active write、正常任务/导出生命周期用例仍通过。

## Quality 结论

改动围绕原竞态收口，owner/version/lifecycle 守卫与现有风格一致；没有为普通校验引入新的登录状态含义。未发现需阻断 Task 1 的质量问题。此结论只覆盖本次限定复审，不等于整站替换准备完成或真实服务验收通过。

## 独立补充与实际验证

新增 `web/vue/src/readiness-fix-review-session.test.ts` 六例：storage 已换不同 owner 而事件未到；同 owner rotated token 离线；跨 tab logout；后来失败 login；后来成功 MFA；dispose 后旧密码操作返回。六例均通过。新增用例是边界验证，未撤销生产守卫执行 RED，故不称其为独立 RED/GREEN 证明。

最终有效关联命令在 `web` 执行：

```sh
npm run test:vue -- vue/src/readiness-fix-review-session.test.ts vue/src/review-second-session.test.ts vue/src/pages/review-second-spec-history.test.ts vue/src/session.test.ts vue/src/session.auth.test.ts vue/src/pages/AccountPage.test.ts vue/src/pages/WorkspacePage.test.ts vue/src/pages/WorkspacePage.live.test.ts vue/src/components/WorkspaceLifecycle.test.ts vue/src/components/WorkspaceExportLifecycle.test.ts
```

结果：10 文件、105 tests passed，无 skip，exit 0。两个既有缺陷文件包含原三条缺陷复现及新增边界。

之后 `npm run typecheck:vue && npx eslint --config eslint.vue.config.mjs vue/src/readiness-fix-review-session.test.ts && npm run test:vue -- vue/src/readiness-fix-review-session.test.ts` 整链 exit 0，最后 1 文件 6 tests passed。

透明记录：首轮测试命令误写若干不存在路径，实际仅运行 5/6 文件，因此不据此宣称完整关联验证；上面的最终命令已纠正。新增测试初稿 remote fixture 的 role 推断为 string，typecheck 真实报三处错误；仅改为 `'user' as const` 后完成上述最终检查。这是独立测试 fixture 问题，不是产品缺陷。

未运行 full Vue suite、构建、浏览器、Python/Go 或真实 API/worker；这些由总流程其他验收负责。报告完成后停止写入。

## 追加：真实 TLS 阻断的原生事件修复独立复审

2026-10-26，产品冻结后复审 `ChapterPlanPanel.vue` 的 `ListField` 与 `StyleLibraryPage.vue` 的 `MainField`。已读开发记录新增真实 TLS 发现与其 RED 证据；本角色未重建或重跑真实浏览器链路，未把旧构建 receipt 计为修复后通过。

结论：限定两处修复的 spec 与 quality 审查通过，未发现新的确认问题。无 props 声明的 functional component 会把 `onChange` 作为 fallthrough listener 加到单一 label 根；业务回调接收数组/字符串，与原生 Event 不兼容。两处 `inheritAttrs = false` 精确阻断该透传，函数参数依然拿到业务回调，显式调用路径保持不变。当前全部调用点只传入这些业务值/回调及 key，没有依赖被关闭的 class/style/aria/native listener 透传；因此未发现可达的兼容性退化。

同类审查覆盖 Vue functional render helpers 的原生事件风险：`ProfileFields` 根为 Fragment；`VerdictReport` 只有非原生 `onNavigateChapter`；其他展示函数无同源业务原生 listener。admin `Fields`/`ResourceBodyFields`、`Pagination`、`RefreshButton` 等已有明确 `.props` 与 `inheritAttrs=false`，不会重现本次透传。`StructuredTextField`、`AutoTextarea`、`GenrePackFields` 的业务 `onChange` 由 `defineProps` 消费，不会作为未知 attrs 自动落到 DOM。此审查针对当前代码可达调用，不是对未来新增 functional helper 的保证。

实际独立验证（web）：

```sh
npm run test:vue -- vue/src/components/ChapterPlanPanel.test.ts vue/src/pages/StyleLibraryPage.test.ts
```

结果 2 文件、11 tests passed，无 skip，exit 0（Vitest v4.1.12，11:46:16 开始）。新增 input→bubbling change→blur→确认/保存用例均检查最终提交的数组值，可捕获原本 Event 污染，验证并非只检测页面仍在。此次未额外增加测试，未修改产品或开发回归；全量 suite、构建和新资产真实 TLS 链路由主流程继续验证。本角色在追加此节后停止写入。
