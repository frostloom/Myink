# 同账号续期修复独立复审

2026-10-26。结论：**批准此次限定范围修复**；原报告两项 P2 均已关闭，未发现此修复新增的可报告问题。

## 范围与规范结论

阅读根 AGENTS.md、review-standards-20261025.md，检查 Git 状态及适用指令（仅根 AGENTS.md）。直接审查未跟踪源码 AccountPage.vue、EnvironmentPage.vue、review-audit-standards-account.test.ts；只读 session.ts 和相关既有测试核实相邻身份生命周期。没有用空 git diff 推断未跟踪迁移代码无改动，没有复审全量迁移，没有改生产或既有测试。

符合原生命周期规格：AccountPage 以 owner、已验证管理员访问权及 status 作为同步清理边界；相同 owner 只替换 token 时保留密码、MFA pairing、验证码及 busy。MFA 状态读取独立刷新，以版本与 owner generation 拒绝过期状态，并避免覆盖 pairing。EnvironmentPage 使用多个标量 source，而非返回新数组的单 getter；同账号 token 变化不重新 load，不清除草稿或使保存响应失效。

## 代码质量与边界结论

修改局限于状态归属及 watcher 责任划分，没有引入无关抽象。权限撤销、账号切换、退出与卸载会使旧 generation 失效；同步 watcher 避免旧响应在下一次 Vue 调度之前写回。MFA 新请求从当前 session 取得 token；已发送请求按 owner 和 generation 处理结果，允许同账号续期，保留跨账号与权限边界。stillCurrent 检查持久存储 owner，并要求已存在的存储会话仍是 role=admin 且 roleVerified=true，以避免另一标签账号变更或同账号撤权的 storage 事件尚未处理时接受旧结果。busy 不因同账号续期解除，可阻止重复提交。

## 独立运行的验证

在该 worktree 的 web 目录实际运行：

```sh
npm run test:vue -- vue/src/review-audit-standards-account.test.ts vue/src/pages/AccountPage.test.ts vue/src/pages/EnvironmentPage.test.ts vue/src/session.account.test.ts
```

结果：**4 个文件通过，29 项通过，0 失败，无跳过，退出码 0**。包含密码草稿续期、MFA pairing 与验证码续期、当前 token 确认、续期期间 enrollment busy、撤权/换账号/退出隔离、高级设置草稿及保存跨续期、新增第八项“持久存储已撤销同账号管理员权限但 storage 事件尚未到达时拒绝旧 enrollment”，并回归既有账号、环境偏好与会话行为。

本次没有运行全量 lint/build、浏览器及后端集成；上述通过结论只针对实际运行的定向检查。本次未新增复现测试。Hindsight recall 连接失败，按项目规则跳过。

补充复核：已阅读 AccountPage.vue 第101行新存储权限条件及新增第八项回归；该检查保留同账号已验证管理员续期，同时关闭持久权限先变更的相邻竞态。再次独立运行上述命令，4 文件 / 29 项通过，无跳过，退出0。此前报告未覆盖此条件，现以本次复核结果更新。
