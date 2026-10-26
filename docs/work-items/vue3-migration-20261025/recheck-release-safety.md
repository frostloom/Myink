# 再次双轴复审（2026-10-26）

最新状态：发布安全P2已修复并完成新产物验收；见[safe-update-fixes.md](safe-update-fixes.md)。下文保留对应历史阶段事实。

当前结论：发现发布安全需求遗漏，撤回“无阻断、可直接合入替代”的笼统结论。此前测试/镜像通过证据仍有效，但未覆盖下面需求；不应理解为已通过这些场景。本轮仅检查，未改产品、提交、合并或部署。

## Standards

独立审查实际dirty/untracked源代码，未确认新增规范或正确性问题。

## Spec

1. P2：React过渡/回退仍自动刷新。brief.md188明确要求默认只提示、用户确认刷新；web/src/components/AppVersionGuard.tsx39–40在新入口出现时直接reload。未保存内存表单可能丢失，Vue守卫无法保护仍运行React的客户端。
2. P2：Vue更新入口缺少保存锁及完整离开保护。brief.md188要求保存中禁切换、所有内存表单有明确离开保护或确认。AppVersionGuard.vue26/30无条件reload，NewProjectPage标题/构思及EnvironmentPage内存设置没有beforeunload/路由离开保护。另brief189要求manifest与HTML绑定同release；目前仍仅解析index文件名前缀，未实现明确版本绑定。

独立Spec审查与主代理源码复核一致，未执行真实浏览器丢数据操作，以上为确定代码路径/缺少保护的静态发现。既有P3测试超时profile清理仍暂缓，非新发现。

## 本轮验证

源码/产物与build-provenance摘要匹配，9组浏览器回执均passed；没有将其当作本轮重跑浏览器。helper4/4本轮通过；配置和安全合并Node5/5本轮通过（初次2项被沙箱EPERM阻止配置缓存写入，原命令获准重跑后通过）；git diff --check通过。没有重跑完整前后端或Docker。
