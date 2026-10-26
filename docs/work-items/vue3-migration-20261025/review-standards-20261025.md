# Vue 迁移规范与代码质量独立审查

2026-10-25。基线与 HEAD：`a96066c43b41e535da4b73e260a998ba9350c415`；审查对象是未提交工作树，包括 `git diff` 与未跟踪的 Vue 源码、配置、脚本。只新增本报告及独立复现测试；未修改生产、既有测试，未提交、推送、发布或启动共享测试服务。

## 发现

### [P2] 同账号 token 续期会清空账号安全页未提交表单

位置：`web/vue/src/pages/AccountPage.vue:24–26`（清理内容定义在第23行）。

触发：作者停留 `/account` 输入当前密码、新密码，或管理员正在设置 MFA；会话自动续期或另一标签更新同账号 token。watcher 把 token 变化视为清理边界，递增 generation 并无条件执行 clearSecrets，清空密码、待确认 MFA 密钥、URI、验证码和 enrolling 状态。App 已按 userId 保留页面，该清理仍会丢掉表单上下文；MFA 用户会从确认步骤退回重新生成步骤。此问题不要求退出或切换账户。

实证：新增 `web/vue/src/review-audit-standards-account.test.ts`。真实 AccountPage 填入密码，只替换相同 userId 的 token，断言原输入保持，实际收到空字符串。测试 RED，失败位置第24行，`expected '' to be 'current-password'`。这违反 brief 身份生命周期契约“续期保持编辑与任务上下文，退出/换账号清理”。应把 owner/权限清理和 token 更新后重新读取状态分开，保留真正的换账号及销毁清理。

### [P2] 高级设置的数组 getter watcher 在同账号续期后覆盖未保存偏好

位置：`web/vue/src/pages/EnvironmentPage.vue:96`，关联第70–84行 load/applyEnvironment。

触发：在高级设置修改扫榜超时、任务预算或模型偏好后，同账号 token 轮换替换 session 对象。虽然 watcher 字面上仅列出 status 和 userId，它的单 getter 每次都返回新数组；session 对象变化会触发 getter，新旧数组引用不同，仍调用 load。load 把 original 清空并从服务器读回，applyEnvironment 无 pending 参数，直接重置所有表单。用户编辑被无提示覆盖；保存中的 generation 也可能失效。这是独立于 AccountPage 的另一处生命周期错误，应使用标量 watch sources 或明确 owner 变化判断。

实证：同一新增测试文件第二项，真实 EnvironmentPage 展开高级设置，把扫榜超时由10改为8，仅轮换同账号 token。flushPromises 后预期8，实际10，RED。此处由主代理静态发现后交本审查独立复现。

## 复核与验证

已阅读根 AGENTS.md、README.md、web/README.md、brief 和 complete plan；`rg --files -g AGENTS.md` 未发现更深目录指令。检查了 session/App/router 的身份与卸载边界、管理员上下文/getter/useResource、AccountPage、Lore/Audit/Settings/图谱/版本历史/附件/反馈与资源选择器，并查看 Vue Vite/Vitest/package/CI 和共享 TS 差异。未把 h 渲染函数或机械格式作为缺陷。其他范围未获得足以单独报告的确定缺陷；不将此抽查描述为逐行全仓覆盖。

独立运行：

```sh
cd web
npm run test:vue -- vue/src/review-audit-standards-account.test.ts vue/src/pages/admin/access.test.ts vue/src/pages/admin/renewed-token.test.ts vue/src/review-final-integration.test.ts
```

结果：**1 个失败文件 / 3 个通过文件，2 项失败 / 17 项通过，无跳过，退出1**。两个失败都是本报告复现。此前无提权运行因 Vite cache 写入 EPERM 未启动测试；随后使用授权的提权运行得到上述真实结果。

原已关闭的 GenerationPanel 提交目标快照、AdminPage 同账号续期保留编辑、当前 token 读取、403/权限/身份边界再次通过相关17项，不重复作为开放发现。未重新运行完整 lint/build/全量测试或浏览器/后端集成；不引用其他人的执行记录充当本次运行。Hindsight recall 未连通，按项目规则跳过。


## 2026-10-26 续期缺陷修复完成

上一轮两个P2已修复并独立复审批准：同owner续期保留账号密码/MFA以及高级设置草稿和保存状态；换账号、退出、撤权仍同步清理；存储撤权事件排队时也拒绝旧MFA回包。新增8项回归含实际RED→GREEN证据。完整Vue73文件541项、lint/严格类型/build均通过；新构建合成冒烟27项、工作台10项通过。最新产物index-DgQ77hkA.js，来源摘要已更新。详见renewal-fix-verification.md和renewal-fix-review.md。本次没有重启旧真实服务栈，没有修改共享React/后端生产代码，没有提交、推送、合并或发布。
