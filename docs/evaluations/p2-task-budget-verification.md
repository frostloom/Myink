# P2 任务总预算验收

日期：2026-10-10。实现代码提交：c1f7a84；发布状态由部署回执确认。

## 自动验证

- Python 全量：1568 passed、1 skipped、5 xfailed；没有失败。命令 python -m pytest tests/ -q -ra，隔离 PostgreSQL 15432、Redis 16380、RabbitMQ 15673，EMBED_ENABLED=0。
- 跳过项是评测数据库身份保护。读取本轮专用 PostgreSQL system_identifier 并设置 MYINK_EVALUATION_SYSTEM_ID 后，test_evaluation_comparison_integration.py 两项通过，无跳过、无模型 HTTP。所有实际测试都有执行证据，5 个既有 xfail 仍为已知冲突检测缺口。
- 前端：58 个测试文件、457 项通过；npm run lint 无错误（既有警告）；TypeScript 和 Vite 生产构建通过，保留既有大包警告。
- compileall、评测 validate（20 个审核案例、40 个目录条目）、数据库初始化连续两次、OpenAPI 94 路径导出且 git diff 无变化，均通过。
- 真实 HTTP 慢速分块用例证明总体 deadline 不能由 read timeout 的逐块刷新绕过。
- 单章/批次/短篇暂停后保留成果、工具结果复用、落库副作用幂等、实际请求重试/降级预算、账号权限、追加操作重放与并发、RabbitMQ 确认失败边界都有针对性测试。

首轮全量有一个多进程测试的锁断言失败；第二次也复现。日志显示任务完成且重复消息被跳过，测试把“队列已取走”当成“消费者已返回”，在短暂持锁窗口断言。改为测试专用 Worker 返回收据后，该文件 3 项通过，最终全量也通过；生产锁逻辑未为此更改。

## 浏览器

实际 EnvironmentPage 与 TaskBudgetPanel，合成账号和 API 响应；1440px 与 390px 两个视口均完成预算保存、请求额度追加和排队状态反馈。检测无页面横向溢出。此浏览器验证不冒称真实模型端到端测试。

- [浏览器回执](p2-task-budget/browser-receipt.json)
- [390px 截图](p2-task-budget/browser-390.png)
- [桌面截图](p2-task-budget/browser-1440.png)

## 独立审查

一次新上下文 gpt-6-astra 全分支只读审查，范围 b59fa39..0ff86a7；无 Critical，7 项 Important 全部接受并在一个修复轮次完成：混合缓存计费、缺失输出用量/流结束标记、批次重规划代次、旧暂停原因、释放后的 Worker 状态防护、短篇预算面板、绝对时间 deadline。每项新增用例观察 RED，再修复 GREEN；后端针对性 87 项通过，前端全量及最终 Python 全量均通过。

## 使用与证据边界

详见 [维护说明](../TASK-BUDGET.md)。默认 100 次、5 元、1800 秒，0 不限；每个新任务独立快照。费用为保守估算；缺失可信用量保留预留。恢复增加上限，不重置累计消耗。

供应商已接收的请求无法撤销，超时后主任务停止等待和推进，后台在途网络操作可能继续至返回/连接超时；迟到结果不结算、不缓存，预留保留。任意进程崩溃下不保证供应商请求绝对恰好一次。未新增真实模型质量评测或 P1 实验。

## 实施取舍与代价

- Ruling: test init shell script was checked out with CRLF and PostgreSQL cannot execute it; normalize test worktree script bytes to LF without semantic changes — prevents Windows-only infrastructure failure — cost if wrong: restore original checkout bytes.

- Ruling: cap cost settings at 9e12 yuan to fit signed microyuan storage — preserves 0/unlimited and practical budgets — cost if wrong: extremely large finite settings rejected.

- Ruling: managed task global daily cost uses durable charged plus unknown reserves and atomic Redis per-task delta — avoids double billing after pause/resume and captures provider retries — cost if wrong: unknown requests conservatively consume daily allowance; per-task Redis receipt remains until operational cleanup.

- Ruling: add amqp.publish_once for managed resume because existing publish retries ambiguous confirms internally — durable operation must distinguish nack from uncertain delivery and bound connect/wait — cost if wrong: extra one-off queue connection per resume, no automatic republish of uncertain operation.

- Task 5 Ruling: Extend useTaskEvents and WorkspacePage with the server budget snapshot — avoids duplicate TaskTimeline requests and lets both short and chapter panels use authoritative state — cost if wrong: stale displayed counters until refresh.

- Final: Ruling: Conservative higher input rate rather than mixed-cache tariff reconstruction; Anthropic cache-specific unknown rates retain reservation — prevents underbilling using incomplete existing metadata — cost if wrong: more budget consumption than supplier invoice.

- Final: Ruling: Absolute deadline uses bounded daemon network waits, ignores/closes late results, never refunds unknown calls — supplier calls already sent cannot be revoked — cost if wrong: in-flight remote processing may continue after local pause and retains conservative reservation.

- Final: Ruling: Retain last owner token with inactive lease after release — fences delayed old status reports — cost if wrong: owner_token alone no longer means active; lease/active_since are authoritative.

- Final: Ruling: Parent batch replan starts a new child generation; pending checkpoint within same generation resumes — actual new plans must execute — cost if wrong: generation identity/schema must stay compatible with persisted checkpoints.

- Final: Ruling: Clear active pause reason after successful resume admission, dispatch pending graph nodes before final review — avoids stale reason hiding review actions — cost if wrong: historical pause reason lives in operation/log history rather than active field.

- Final: Ruling: Multi-process test waits for test-only Worker process-return receipt instead of queue-ready count — twice-reproduced red was dequeue-before-lock acquisition observation race, not duplicate persistence — cost if wrong: test helper adds isolated Redis receipt, production consumer unchanged.

- Final: Ruling: Arbitrary provider crash exactly-once is not guaranteed; externally configured tariffs are estimates; deployment/browser/doc coverage require actual evidence — matches achievable behavior and approved scope — cost if wrong: supplier-side idempotency/reconciliation would require separate work.
