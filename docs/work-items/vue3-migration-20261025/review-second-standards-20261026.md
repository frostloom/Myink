# 第二轮规范与质量独立评审 — 2026-10-26

基线与 HEAD：`a96066c43b41e535da4b73e260a998ba9350c415`。审查对象包含相对基线的工作区改动及未跟踪 Vue 源码；没有把空的提交差异误认为没有迁移改动。

资源/后台指定范围未确认新增问题；根代理随后提供会话竞态复现，本审查独立确认以下一个 P2。上一轮 AccountPage、EnvironmentPage 续期问题已有修复，本轮不重复报告。

依据：根 AGENTS.md 的最小范围、先读代码及真实验证要求；README.md、web/README.md；迁移 brief 的身份/权限生命周期、异步请求归属、generation/revision、409 保留编辑及后台读写边界契约；progress.md 与 renewal-fix-verification.md。检索未发现更深 AGENTS.md。Hindsight recall 服务未连通，按项目规则跳过。

重点读取 WritingResourcePicker、ResourceUpdates、WritingResources、PlatformConfiguration、ModelManagement、AdminDialog、shared，以及公共资源 wrapper、RolePromptFields、PlatformResources、实际 App/AdminPage/SettingsPage/WorkspacePage 调用点、API/token 边界及对应 React 实现。已核对：Settings 的 picker 和工作台 updates 按 projectId 销毁，App 按 userId 销毁，后台按 owner 与 route.path 销毁；同账号 token 续期不靠 token key 重挂；公共 API 拒绝跨 owner 回包，资源调用在发送时读取当前 token；后台 historyRequest 区分快速详情切换，useResource 用 AbortSignal 与 sequence 拒绝旧请求；对话框 busy/原生 modal 阻止保存中切换编辑目标；资源保存继续传 expected_generation、expected_revision 与 target_generation，409 保留本地编辑。

没有把缺少局部序号的代码形状直接推断为用户可触发缺陷；结合真实父 key、销毁位置、busy 与 API owner 规则后，未取得新编辑状态被污染的确定证据。重复 setter、长渲染函数等气味仅为启发式；未证实具体影响，因此未机械列为违反标准。Vue h 渲染函数符合本仓说明。

实际执行（web 目录）：

```sh
npm run test:vue -- vue/src/pages/admin/WritingResources.test.ts vue/src/pages/admin/ModelManagement.test.ts vue/src/pages/admin/PlatformConfiguration.test.ts vue/src/pages/admin/picker.test.ts vue/src/pages/admin/updates.test.ts vue/src/pages/admin/access.test.ts vue/src/pages/admin/renewed-token.test.ts
```

结果：7 文件、71 项通过，无跳过，退出 0。没有新增复现测试；未重跑全量 lint/build、浏览器或后端集成，不把历史 541 项通过当成本轮执行结果。仅新增本报告，未改生产代码、既有测试、提交、推送、合并或发布。


## [P2] 同账号会话校验让密码修改成功后的退出失效

位置：`web/vue/src/session.ts:227–232`，直接错误边界为第229行。

修改密码 POST 尚未返回时，同账号调用 revalidate（包括 storage 触发的校验）会递增 generation；即使 userId 和 token 完全相同，POST 成功后也因 generation 不同直接返回，既不清除已失效凭据，也不显示“密码已修改，请重新登录”。因此页面仍认为 authenticated，继续保留受保护页面和业务状态，直到后续401/到期才被动退出。后端 `src/myink/api/auth.py:506–515` 成功事务自增 auth_version；第282行认证核对版本，故成功前签发的凭证均已失效。这违反 brief 6.1 的身份生命周期及账号安全行为保持要求。

React `web/src/context/AuthContext.tsx:386–398` 的同token成功路径只检查当前及存储token，随后清理会话，没有上述 generation 早退；因此同token情景是新增迁移回归。另一个已复现情景是同owner token轮换后密码修改成功，最新凭证亦已被后端撤销，但第229行也跳过有效性核对；此形状在旧React已有，不单独计作第二个迁移缺陷。修复应按账号owner处理成功结果并核对后续凭证，避免误清真正切换后的其他账号，不能仅删掉所有安全边界。

独立重跑 `npm run test:vue -- vue/src/review-second-session.test.ts vue/src/session.account.test.ts`：新两项均实际 RED（expected anonymous，received authenticated），原账号测试3项通过，无skip，退出1。新测试由根代理添加；本代理仅读取并运行，未改任何生产/测试代码。最终规范轴发现数为1，最高P2；前述71项通过仅覆盖资源/后台，不代表当前完整套件通过。
