# P2 Task Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给账号新任务提供可配置的请求、费用和运行时间上限，超限自动暂停，追加预算后复用成果继续执行。

**Architecture:** PostgreSQL 保存根任务预算、实际请求收据和可复用模型结果；Provider 在每次实际 HTTP 请求前预留额度。既有 LangGraph 检查点与短篇阶段恢复承载执行进度，账号环境页和任务面板提供配置、查看及幂等追加。

**Tech Stack:** Python 3.12、SQLAlchemy/PostgreSQL、LangGraph、httpx/OpenAI SDK、RabbitMQ/Redis、FastAPI/Pydantic、React/TypeScript/Vitest。

**Spec:** `docs/superpowers/specs/2026-10-09-task-budget-design.md`（用户已在本会话确认）。

## Global Constraints

- 新任务默认 100 次请求、5 元、1800 秒；各维度 0 表示不限。
- 批次子线程共享根任务预算；重试和 fallback 各计实际请求。
- 全局环境配置仅属于当前账号；任务保留入队时快照，追加不清零累计值。
- 排队和人工暂停不计运行时间；进程重启不重置账本；取消状态优先。
- 费用是估算；失败、未知结果和缺失用量保留保守预留；不能以未知价格的 0 估价绕过预算。
- 复用成功调用成果，不承诺外部供应商请求在任意崩溃窗口内恰好一次。
- 不覆盖无关工作区修改，不提交密钥/私钥/.env/.local；保留已上线 Anthropic 思考开关修复。
- 不恢复退场 Go 网关，不扩大到账号级无任务调用，不跑取消的 P1 模型实验。
- 集成测试必须使用独立 PostgreSQL、Redis、RabbitMQ，固定 `myink-test` 不能并行使用。

## Review Focus

- Provider/节点宽泛捕获异常可能把预算暂停降级成重试：Task 2、3 钉住传播与零后续 HTTP。
- 同一节点中的多轮工具或改 JSON 调用在恢复时可能重复付费：Task 3 钉住稳定调用身份和成果复用。
- 旧 Worker、重复消息和追加请求重放可能获得额外额度：Task 1、4 钉住租约、行锁和操作幂等。
- 时间限制在工具等待、退避和 Worker 崩溃后可能失效：Task 1、2、3 钉住累计时间、deadline 和租约。
- 发布成功但确认结果不明可能被补偿或再次追加：Task 4 钉住状态、预算、发布三者的一致性。

## Task 1：配置快照与持久预算账本

**Files**
- Create: `src/myink/task_budget.py`, `src/myink/models/task_budget.py`, `tests/test_task_budget.py`。
- Modify: `src/myink/models/__init__.py`, `src/myink/db.py`, `src/myink/cli.py`, `src/myink/environment.py`, `src/myink/api/routes_environment.py`, `src/myink/api/schemas.py`, `src/myink/worker/enqueue.py`, `src/myink/workflow/runner.py`。
- Test: `tests/test_environment_routes.py`, `tests/test_enqueue_gates.py`。

**Interfaces**
- `TaskBudgetLimits`: `max_requests: int = 100`, `max_cost_yuan: Decimal = Decimal('5')`, `max_runtime_seconds: int = 1800`；严格非负/有限校验，费用最多 6 位小数。
- `TaskBudgetPaused(Exception)`: 结构化 `reason`、`stage`；`TaskBudgetUnavailable(Exception)` 表示持久存储不可用，不混入网络错误。
- `TaskBudget`: 根任务唯一，包含 project_id、user_id、limits、requests_used、cost_used_micros、cost_reserved_micros、runtime_used_ms、owner_token、lease_until、active_since、pause_reason、version。
- `TaskBudgetAttempt`: attempt UUID 唯一，保存请求预留和结算状态；`TaskBudgetCall`: `(task_id, operation_key, input_hash)` 唯一，保存 ModelResponse JSON；结果不含密钥或请求头。
- `budget_defaults(user_id) -> TaskBudgetLimits`：账号配置或默认值；`snapshot_budget(user_id) -> dict`：仅由可信入队入口生成。
- `ensure_task_budget(task_id, project_id, user_id, snapshot: dict | None) -> None`：快照存在才建立账本，重复物化不覆盖；旧任务缺快照保持旧行为。
- `budget_view(task_id) -> dict | None`：限额、累计值、未确认预留、stage、pause_reason，供 Task 4 使用。
- `claim_budget(task_id, owner_token)`、`renew_budget(task_id, owner_token)`、`release_budget(task_id, owner_token)`：短事务、行锁、所有者校验和累计运行时间。

- [ ] 写失败测试：`test_defaults_and_partial_environment_update`，断言默认 100/5/1800、只更新预算不清模型路由、账号隔离。
- [ ] 写参数校验测试：0 可用，负数/布尔值/NaN/Infinity/非法精度拒绝；环境配置保持既有省略语义。
- [ ] 写数据库测试：`test_duplicate_snapshot_keeps_original_limits`、`test_legacy_task_without_snapshot_is_unmanaged`、`test_lease_rejects_stale_owner`、`test_runtime_survives_restart_excludes_pause`。
- [ ] 运行并确认测试在缺少新接口或行为时失败；实现模型、幂等初始化/权限、配置读取及可信入队快照。
- [ ] 运行初始化两次，确认新旧数据库兼容、RLS/归属和删除行为；针对性测试转绿。
- [ ] 提交仅本任务相关文件：`feat: persist task budget configuration and ledger`。

## Task 2：实际请求准入、结算与调用成果

**Files**
- Modify: `src/myink/task_budget.py`, `src/myink/providers/base.py`, `src/myink/providers/deepseek.py`, `src/myink/providers/openai_compatible.py`, `src/myink/providers/anthropic.py`。
- Create: `tests/test_task_budget_providers.py`。
- Test: `tests/test_custom_providers.py`, `tests/test_provider.py`, `tests/test_provider_errors.py`, `tests/test_think_tag_stripper.py`。

**Interfaces**
- `bind_task_budget(task_id, owner_token)`：ContextVar 作用域，任务以外不改变既有调用行为。
- `bind_budget_operation(operation_key: str)`：为节点内一次逻辑模型调用提供稳定身份。
- `reserve_attempt(model_id, messages, max_tokens, prices=None) -> AttemptPermit | None`：无管理上下文返回 None；受管理任务在实际请求前原子增加次数和预留费用；Permit 包含 deadline 和 attempt_id。
- `finish_attempt(permit, response: ModelResponse | None) -> None`：有效用量结算，不明结果保留预留；独立事务不随正文回滚。
- `load_call(operation_key, input_hash) -> ModelResponse | None`、`save_call(operation_key, input_hash, response) -> None`：输入摘要包含消息、工具、模型链、价格及生成参数；保存成功返回成果。
- `AttemptPermit.remaining_seconds() -> float`：约束网络等待和重试退避，不允许租约丢失或余额不足后继续发请求。

- [ ] 写失败测试：单节点重试消耗多次额度，1 次上限允许恰好一次，第二次不触 HTTP；不同模型 fallback、流式重试共享预算。
- [ ] 写失败测试：受管理 OpenAI SDK 没有隐藏重试；Anthropic/DeepSeek 拦截前无网络调用；预算异常不被宽泛 catch 或 FallbackChain 吞掉。
- [ ] 写失败测试：并发预留不超额；完整用量结算、缺失用量/断流保留预留、未知价格正数预留、账本故障不发请求。
- [ ] 写失败测试：剩余秒数限制 HTTP 超时和退避；复用结果不增加请求/费用，输入和模型参数变化不复用。
- [ ] 跑红测试后，接入每个实际 HTTP 尝试；预算作用域中禁用 SDK 内部重试。定价运算内部用整数微元/Decimal，展示才换单位。
- [ ] 跑 Provider 全套相关测试，保留已有 thinking、工具、流式及错误脱敏行为；提交 `feat: enforce task budget before model requests`。

## Task 3：安全暂停与长篇、批次、短篇恢复

**Files**
- Modify: `src/myink/worker/processor.py`, `src/myink/workflow/runner.py`, `src/myink/workflow/nodes.py`, `src/myink/workflow/state.py`, `src/myink/workflow/chapter_graph.py`, `src/myink/workflow/batch_graph.py`, `src/myink/workflow/short_runner.py`, `src/myink/task_budget.py`。
- Create: `tests/test_task_budget_recovery.py`。
- Test: `tests/test_short_runner.py`，以及实际发现的 batch/runner/processor/plan-gate 测试文件。

**Interfaces**
- Worker 物化 Task 后以根任务 ID 建立预算作用域；批次派生 `:chN` 线程仍使用根 ID。
- `_llm`、工具循环、批次规划/审计/复盘等入口使用稳定 operation_key（节点、章号、replan/revision 次数、节点内调用序号）。同一节点恢复时重建同一键，新一轮修订产生新键。
- `resume_thread` 的预算暂停分支以当前 LangGraph 版本正确的续跑入口恢复未完成工作；原人工确认分支保持单独语义。
- `save_short_progress(task_id, stage, payload)` / `load_short_progress(task_id)`：持久化短篇成稿/补写/审稿/改稿位置及成果，以 TaskBudgetCall/任务数据复用，不另建调度器。
- Worker 捕获 TaskBudgetPaused：保存 `paused`、pause_reason 和 stage，发送 SSE 元数据，不自动 retry；基础设施异常保留现场并报告，取消优先。

- [ ] 写可计数 StubProvider 测试：单章在审核前超预算，恢复后正文调用次数仍为 1；验证真实图恢复语义而非只检查 payload。
- [ ] 写工具循环测试：第二轮模型请求前暂停，第一次工具调用结果/模型结果恢复后可复用，无重复付费。
- [ ] 写批次测试：第二章中途超预算，第一章没有重跑、子线程累计于父额度；最后审核/Reflexion 仍受限。
- [ ] 写短篇测试：成稿→审稿前、审稿→改稿前暂停，服务重启后从对应阶段继续，已落库稿不重复覆盖版本。
- [ ] 写异常传播测试：摘要、复盘、批次异常兜底都不吞预算暂停；重复队列消息与旧 Worker 不推进状态；手动取消不会被预算暂停覆盖。
- [ ] 测试先红再修恢复入口、阶段持久化和预算作用域；测试转绿后提交 `feat: pause and resume agent workflows on budget limits`。

## Task 4：查询与幂等追加预算 API

**Files**
- Modify: `src/myink/api/routes_tasks.py`, `src/myink/api/schemas.py`, `src/myink/task_budget.py`, `src/myink/worker/processor.py`, `spec/api-openapi.json`。
- Create: `tests/test_task_budget_routes.py`。
- Test: 既有 tasks 所有者/控制端点测试。

**Interfaces**
- TaskDetail/TaskSummary 新增 `budget: TaskBudgetView | None`，None 表示旧任务未启用。
- `ResumeBudgetBody`: `operation_id: UUID`、`add_requests: int = 0`、`add_cost_yuan: Decimal = 0`、`add_runtime_seconds: int = 0`；仅含正数追加时必须有 operation_id；空体沿用旧 resume 调用。
- `extend_and_resume_budget(task_id, user_id, body) -> dict`：同事务锁任务和预算，按 operation_id 幂等；记录操作收据和发布状态，确认失败与结果不明分别处理。
- 无余量的预算暂停任务收到普通 resume 时返回 409，保持暂停并提示追加；没有超限的手动暂停按旧行为续跑。

- [ ] 写红测试：他人不能查询或追加；done/cancelled 不可追加；已用值不归零；修改全局默认不改变旧任务。
- [ ] 写红测试：双击同 operation_id、响应丢失重放、不同 operation_id 并发，追加一次、发布一次；同键不同参数 409。
- [ ] 写红测试：发布 nack 可重试但不重复追加，发布确认超时不能撤销可能已生效状态，重投消息不能重新获取默认预算。
- [ ] 实现验证与操作收据；导出契约并审查兼容性；针对性 API 测试转绿后提交 `feat: expose task budgets and idempotent extensions`。

## Task 5：环境页与任务预算交互

**Files**
- Modify: `web/src/types.ts`, `web/src/lib/api.ts`, `web/src/pages/EnvironmentPage.tsx`, `web/src/pages/EnvironmentPage.test.tsx`, `web/src/components/TaskTimeline.tsx`, `web/src/components/TaskHistory.tsx`。
- Create: `web/src/components/TaskBudgetPanel.tsx`, `web/src/components/TaskBudgetPanel.test.tsx`；样式沿用既有模块，必要时新增局部 CSS。
- Test: 实际发现的任务面板/任务历史测试文件。

**Interfaces**
- `TaskBudgetLimits`、`TaskBudgetView` 与后端契约一致；EnvironmentSettings 新增 task_budget。
- `api.resumeTask(tid, body?)` 支持既有空体与预算追加体，operation_id 在一次用户操作中保持稳定直到成功或明确放弃。
- `TaskBudgetPanel({task, onResumed})` 展示三个维度、未确认预留、阶段/原因；可追加请求、元和分钟，分钟转整数秒。

- [ ] 写红测试：环境页加载默认、只保存预算不改变模型路由；0 显示不限，非法值阻止提交。
- [ ] 写红测试：预算暂停区别于手动暂停、追加错误提示、操作中防双击、重试保留 operation_id、刷新读取服务端账本。
- [ ] 实现已有页面风格内的局部交互，不新增无关布局或管理端功能。
- [ ] 运行针对性 Vitest，随后 lint/test/build；提交 `feat: configure and extend agent task budgets in UI`。

## Task 6：整体验收、维护说明与发布

**Files**
- Create: `docs/TASK-BUDGET.md`, `docs/evaluations/p2-task-budget-verification.md`。
- Modify: 本计划复选框和必要项目导航文档；不要覆盖 docs/DEPLOY.md 的既有无关修改。
- Preserve and include: 已授权上线的 `src/myink/providers/anthropic.py` 思考开关修复及 `tests/test_custom_providers.py` 回归。

- [ ] 自查设计覆盖；执行独立全分支审查，修复阻塞问题。审查重点为权限、重试、恢复、副作用及未知费用。
- [ ] 检查 `myink-test` 未占用，配置隔离服务。跑 compileall、初始化幂等、评测 validate、API 契约检查及 Python 全量测试，记录通过/xfail/skip。
- [ ] 跑前端 lint、全量测试、build；构建 Python/Caddy 镜像；桌面和 390px 浏览器验证配置、预算暂停、追加恢复。
- [ ] 文档记录账本结构、调用身份、升级/清理、未确认费用和崩溃边界；保存验收数字和可复现命令，不编造未运行检查。
- [ ] 审查暂存文件和敏感信息，仅提交 P2 与已上线修复；整合至目标分支，推送 GitHub并核对远程 SHA。
- [ ] 从验证后的提交构建/传送镜像，备份线上旧镜像和数据库，确认队列/在途任务，执行幂等升级；保留新模型 `.env` 配置。
- [ ] 部署 API、Worker 和前端，核对镜像版本和 readyz；以隔离测试账号/素材验证预算配置持久化和恢复，失败回滚；避免读取或重放生产用户历史会话。
- [ ] 清理临时私钥、测试服务；最终报告代码/文档位置、测试证据、远程 SHA、线上版本和限制。

## 执行方式待选择

推荐 **Native（当前会话由主代理执行）**：这六项任务依赖同一套预算账本与恢复协议，统一实现可以减少接口漂移；仍保留独立全分支审查和全套集成测试。

另一种方式是 **Subagent-driven**：每项由独立子代理实现，再分别进行规格与代码审查；适合需要逐项独立审阅、愿意承担更多上下文成本的情况。

实施前须完成用户对本计划的审阅及执行方式选择；推送/部署已授权，验收通过后不重复请求发布批准。
