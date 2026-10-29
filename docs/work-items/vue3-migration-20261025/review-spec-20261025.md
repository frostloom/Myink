# Vue3 完整迁移规格独立评审

日期：2026-10-25。基线 `a96066c43b41e535da4b73e260a998ba9350c415` 与当前 HEAD 相同；审查对象包括全部未提交 diff 和未跟踪 Vue 源码。未修改生产或既有测试，未提交、推送、合并、发布或启动固定端口服务。

## 开放发现

### [P2] 账号安全页把同账号续期误当成销毁边界

规格：`brief.md:90–91`：“同账号 token 续期与换账号区别处理”“续期保持编辑与任务上下文，退出/换账号清理”；`brief.md:89` 要求敏感字段不持久化，并不要求续期清掉仍在使用的内存表单。

生产位置：`web/vue/src/pages/AccountPage.vue:24–26`；`clearSecrets` 定义在第23行。

触发：同一 userId 在 `/account` 已输入密码，或管理员处于 MFA 确认阶段时，自动续期或跨标签同步替换 token。watch 直接观察 token，无条件 `clearSecrets()`，密码、新密码、验证码、待确认密钥和 enrolling 都被重置。虽然 App 以 userId 保留组件，页面本身仍清空编辑上下文；MFA 会退回生成步骤。

可复现证据：独立规范审查新增 `web/vue/src/review-audit-standards-account.test.ts:11–26`，挂载真实 AccountPage，填入当前密码及新密码，仅替换同 userId 的 token。第24行期待 `current-password`，实际空字符串，RED。需把身份/权限销毁与 token 更新后的状态读取分开。

### [P2] 高级设置同账号续期后无提示回填服务器值，丢弃编辑

规格：`brief.md:90–91` 同上，另 `brief.md:118`：“环境配置仅保存本节dirty leaves……脏sibling保留”。用户未提交的偏好必须在同身份生命周期内保留。

生产位置：`web/vue/src/pages/EnvironmentPage.vue:96`；回填路径第64–84行，`applyEnvironment` 第46–57行。

触发：展开高级设置，把扫榜超时10改为8；会话保留相同 userId，只轮换 token。单 getter `watch(() => [status.value, session.value?.userId], ...)` 每次构造新数组；session 引用变更会使 getter 重跑，即使两个业务字段没变仍触发 load。load 清空 original，重新读取后不带 pending 参数应用，8 被服务器的10覆盖。预算/模型/思考模式等同样受影响；generation 递增还会使正在保存的旧回包失效。

可复现证据：同一独立测试文件第28–44行，真实 EnvironmentPage 把超时改8，仅更换同账号 token，最终实际10，RED。应使用稳定标量 watch sources 或明确身份变化比较；网络重验证不得覆盖未提交偏好。

## 审查范围与证据边界

阅读根 AGENTS、brief、coverage、complete plan；检查根 Git 状态，未发现 web 下更深 AGENTS。Hindsight recall 服务未连通，按规则跳过。对照原 React 阅读了 App/session/router、Projects/Account/Environment/Settings/Lore、Workspace/草稿/SSE/Plan/生成、短篇 intent、新建作品幂等、资源选择/更新、后台权限上下文、主题预览与媒体、反馈与附件。检查了已跟踪共享 TS/配置差异及未跟踪 Vue 实现，未把 Vue 原生 h 渲染函数作为兼容 runtime 缺陷。

两个 RED 由另一独立审查实际执行，结果在 `review-standards-20261025.md`：2项失败、17项通过、无跳过；本规格审查检查了测试和生产触发路径，未重复执行或冒称自己运行。其余抽查未获得新的确定规格遗漏或越权扩展；不代表逐行穷尽覆盖，也不将 coverage 的“已通过”声明当成验证证据。原已修 GenerationPanel 快照、Admin 同账号续期、403、详情当前 token 等不重复列为开放问题。

结论：完整迁移候选仍有上述两项显式身份生命周期验收缺口；应修复并回归后再关闭规格验收。未重新运行全量 lint/build、浏览器或真实后端集成，因此不对这些门禁作新的通过声明。


## 2026-10-26 续期缺陷修复完成

上一轮两个P2已修复并独立复审批准：同owner续期保留账号密码/MFA以及高级设置草稿和保存状态；换账号、退出、撤权仍同步清理；存储撤权事件排队时也拒绝旧MFA回包。新增8项回归含实际RED→GREEN证据。完整Vue73文件541项、lint/严格类型/build均通过；新构建合成冒烟27项、工作台10项通过。最新产物index-DgQ77hkA.js，来源摘要已更新。详见renewal-fix-verification.md和renewal-fix-review.md。本次没有重启旧真实服务栈，没有修改共享React/后端生产代码，没有提交、推送、合并或发布。
