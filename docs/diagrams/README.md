# Myink 项目流转图

生成：2026-10-08。工具：[Archify](https://github.com/tt-a1i/archify)，用户级安装目录 `~/.codex/skills/archify`；本次回执中的版本为 3.0.1。输出全部位于本项目。

- [交互 HTML](2026-10-08-runtime-flow/2026-10-08-runtime-flow.html)：浏览器离线打开，支持来源查看、亮暗主题和导出。
- [可维护 JSON](2026-10-08-runtime-flow/candidate.json)：以后改结构从这份语义源更新。
- [最终验证摘要](2026-10-08-runtime-flow/review-final/2026-10-08-runtime-flow.finalize-summary.json)：validate / deliver / strict check / browser-check 均通过。
- [浏览器回执](2026-10-08-runtime-flow/review-final/2026-10-08-runtime-flow.browser-check.json)：实际浏览器检查，不等同于人工视觉评价。
- [截图联系页](2026-10-08-runtime-flow/review-final/visual-check/2026-10-08-runtime-flow.visual-check.html)：1440×900 与 2048×1320 的亮暗主题截图。

## 图的含义与来源

图从作者请求、API 归属检查、额度闸门、RabbitMQ 队列、Worker 开始，分别进入长篇状态图或短篇链，展示人工等待/恢复、结果持久化、批次复盘、Redis Stream / SSE 和用户交付。

源证据固定在 `326c4b366cdae38c374d253b12340c63615133c1`（生成时 HEAD），每个节点带已提交代码路径和行号。当前工作区的工具预算与缺省章号修复尚未提交，因此没有把它们伪装成该提交中的远程源码；修复见 [P0 验收](../evaluations/interview-p0-verification.md)。新提交后可更新 `meta.repository.revision`，并重新核对所有源行号。

流程条件：只有批次收尾经过复盘/全局审计；单章路径不必经过该节点。短篇成稿/审改与长篇的三层记忆/候选确认不是同一执行链；短篇审稿失败会携带 warning 保留稿件。MCP 榜单只用于建书灵感，不是生成节点的数据源。观测快照是选择性留存，不是任意历史任务的完整可执行录像。

## 长篇单章细节

当前完整节点：`load_state → recall → plan_cast → plan_chapter → plan_gate → write → extract → validate → audit → route`。

| 条件 | 实际路径 |
|---|---|
| 手动规划 | 在 plan_gate 等待；确认后恢复该节点继续 write，不重跑 Planner |
| pass 且规则允许 | 进入 persist 的候选/正文保存检查，再为已确认章 summarize |
| rewrite 或重大冲突，预算尚余 | revise 或 patch → extract → validate → audit，再路由 |
| replan chapter | reset_replan 清旧草稿/候选/报告 → plan_cast，重新规划 |
| replan batch | 退出单章子图，外层重规划剩余章节；已完成章节保留 |
| 预算用尽、严重冲突、新人物卡等 | persist 保存待确认草稿与候选，任务 awaiting_review；不把预算用尽当通过 |
| 人工拒绝并要求修订 | resolve_review → revise → 完整复审，处理旧候选 |
| 人工已处理候选 | 从保存状态 finalize；不通过重新生成来模拟确认 |
| 失败 | 保留对应 checkpoint/任务状态，按单章或批次恢复入口处理 |

## 重建与验证

在项目根目录执行（技能路径按用户环境替换）：

```powershell
node "$env:USERPROFILE/.codex/skills/archify/bin/archify.mjs" finalize workflow docs/diagrams/2026-10-08-runtime-flow/candidate.json docs/diagrams/2026-10-08-runtime-flow/2026-10-08-runtime-flow.html --repo-root . --quality showcase --out-dir docs/diagrams/2026-10-08-runtime-flow/review-next --json
```

更改 JSON 后使用新的证据目录，避免覆盖上一份浏览器证据。工具的自动门禁和截图采集均通过；本轮实际查看了 1440×900 亮暗两张图，确认节点、标签、人工恢复路线和长短篇分支可辨。2048×1320 由自动浏览器检查，不声称逐张人工检查。主路径高亮只强调请求/调度阶段，其余业务步骤仍由箭头和条件说明。
