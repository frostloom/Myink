# Vue 认证页面与应用集成报告

Task 2 已实现，未提交、推送、合并或发布。改动仅覆盖 authContext.ts、LoginPage.vue/LoginPage.test.ts、App.vue/App.test.ts、router.ts、router-parity.test.ts（整合审查追加授权）与本报告。

- App 创建唯一 SessionScope，经 provide/inject 供登录页使用，启动与销毁跟随应用生命周期。
- /login 在 checking、anonymous、unavailable 均公开；根路径仅依据服务端校验后的 roleVerified 选择 /admin 或 /long。未知路径经 / 回退，并按已验证角色分流。
- 注册复用密码策略，用户名先 ASCII 校验再小写；旧短密码仍可登录。邀请码仅内存，MFA 挑战与验证码仅内存；切号清理旧挑战。
- 提交期间阻止重复提交、切换模式及返回。卸载后的响应不导航，跨标签在途换号的旧响应不导航。成功导航检查已验证身份。
- 受保护页面 key 仅 userId，同账号 token 轮换保持页面实例；其他未迁移页面继续 pending。

## TDD 证据

1. RED `npm run test:vue -- vue/src/App.test.ts`：26 passed / 3 failed。新公开登录与实际登录导航测试均因旧匿名闸门缺少用户名表单失败。
2. RED `npm run test:vue -- vue/src/pages/LoginPage.test.ts`：13 failed。公开登录未实现导致无法进入表单。
3. 追加 MFA 跨标签换号回归 RED：13 passed / 1 failed，旧验证码输入仍可见；增加身份监听清理挑战后 GREEN。
4. 测试中修正两项不成立的假设：Vue Router 卸载会重置路由，因此比较卸载后的路径；作品列表没有搜索框，因此直接验证原 main DOM 实例保留。

## 最终验证

- `npm run test:vue`：6 files，88 tests passed。
- `npm run lint:vue`：通过。
- `npm run build:vue`：类型检查及构建通过。

真实服务、浏览器合成验收及 React 回归由主代理统一执行，本报告不声称这些检查已通过。

## 整合审查修订

发现旧未知路径直接回 /long，绕过已验证管理员首页选择。先添加 App 未知路径 admin 验收：`npm run test:vue -- vue/src/App.test.ts` 得 32 passed / 1 failed，实际 /long 而预期 /admin。随后 catch-all 改为 /，App 统一按已验证角色分流；同步修正 router-parity 的路由层期望，更新已迁移页面注释。

复验 `npm run test:vue`：6 files / 92 tests passed；`npm run lint:vue`、`npm run build:vue` 均通过。

## 独立 UI 审查 P2 修复

App 的 unavailable 校验失败分支原先仅提供重试，遗漏离线退出出口。增加真实会话测试：缓存会话校验离线、远端退出也离线时，点击退出登录仍清除本地会话、显示匿名入口和退出 notice。

- RED `npm run test:vue -- vue/src/App.test.ts`：33 passed / 1 failed，无法找到“退出登录”按钮。
- 添加按钮调用现有 auth.logout，保留重试和公开登录行为。
- GREEN 同定向命令：34 passed；`npm run test:vue`：6 files / 98 passed。
- `npm run lint:vue`、`npm run build:vue`：通过。
- 本修复未修改 session 或浏览器脚本。
