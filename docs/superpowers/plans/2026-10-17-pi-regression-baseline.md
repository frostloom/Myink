# Pi 回归基线修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if the user chooses delegation. Steps use checkbox syntax for tracking.

**Goal:** 复现并处理 runtime032 记录的十项业务回归失败，建立后续 Pi 写作分析实验可依赖的测试基线。

**Architecture:** 保留 main 及 Pi 工作区的既有修改，在 codex/pi-autonomy-design 的现有工作区中按根因分批修改。先复现，再用最小修复关闭每一类失败；不通过放宽安全断言、删除失败案例或扩大跳过范围制造绿灯。

**Tech Stack:** Python 3.12、pytest、PostgreSQL/pgvector、Redis、RabbitMQ、Docker Compose；依赖版本参照 docker/constraints.txt。

**Spec:** docs/evaluations/pi-local-trial/development-runtime032-2026-10-15.md；用户 2026-10-17 授权按 Superpowers 执行，每个完成的小目标提交并推送 GitHub。

## Global Constraints

- 不合并 main、不发布生产、不启动服务器每日自治。本计划不发送付费模型请求。
- 保护既有修改：ops/pi/lab/build_lab.py、ops/pi/lab/provision.sh、ops/pi/lab/verify.py、ops/pi/resources.py；不纳入当前提交。
- 测试使用独立 PG/Redis/RabbitMQ、独立 Compose 项目和端口；不用已有 postgres、redis 或业务数据。
- 不并发运行固定 myink-test 资源。需要初始化脚本 LF 转换时，仅在临时副本处理，不混入无关源文件修改。
- 每个修复先观察相关失败，再实现和验证；未运行、SKIP、环境阻塞、xfail 分开记录。
- 每个完成的小目标先审查、验证，再仅暂存明确文件、提交并推送功能分支；推送失败如实保留本地提交并报告。
- 写作语义质量实验、发布和服务器验收另设后续计划；格式校验通过不代表写作质量提升。

## Review Focus

1. 权限测试：模拟 Unix 身份不能在 Windows 缺失 geteuid 时崩溃，也不能绕过真实维护权限检查。
2. 批次恢复：人工审核/预算等待不得被维护恢复覆盖，已完成章节不得重复写入。
3. 队列权威：旧投递或过期 owner 不能推进新执行或重复扣额度。
4. 消费故障：瞬时故障必须保留消息，不能 ACK 丢失，也不能重复产生业务副作用。
5. 平台差异：Windows 终止码与 POSIX 信号码不同；仍要验证进程停止、checkpoint 和副作用。

### Task 1: 恢复失败清单与复现环境

**Files:** tests/test_cli_auth_safety.py、tests/test_multiprocess.py、tests/test_task_budget_routes.py、tests/test_worker.py、tests/test_queue_handoff.py、相关批次和维护测试；docs/evaluations/pi-regression-baseline-2026-10-17.md（新建记录）。

**Interfaces:** 消费 runtime032 的失败分类；产出准确 pytest node ID、失败签名、运行环境、命令及基线结果，供后续任务选择测试。

- [x] 查阅测试与 fixtures，映射 CLI 权限 3 项、批次 2 项、多进程 1 项、队列/预算 3 项、消费者 1 项；不凭分类猜定实际失败数。
- [x] 检查可用 Python、锁定依赖、Docker 镜像与独立端口；建立临时测试环境并 seed。
- [x] 执行相关文件并保存失败输出和 node ID；无法复现的项标为未复现，缺设施标为阻塞。
- [x] 输出基线记录，自查未泄漏凭据；作为独立诊断小目标提交并推送。

### Task 2: 跨平台权限和进程验收

**Files:** tests/test_cli_auth_safety.py、tests/test_multiprocess.py；仅在证明产品缺陷时修改 src/myink/cli.py 或对应进程实现。

**Interfaces:** 消费 Task 1 的准确失败案例；产出跨平台行为正确的权限和终止测试。

- [x] 重跑相关失败，阅读权限与进程生产路径，明确是产品缺陷还是测试的平台假设。
- [x] 先增加或修正行为测试，观察预期失败；覆盖非特权拒绝和进程确实退出，避免仅验证 mock 调用。
- [x] 最小修复；运行相关完整测试文件，并记录平台及跳过项。
- [x] 独立代码审查，处理 Critical/Important；提交并推送此目标。

### Task 3: 批次暂停恢复与队列一致性

**Files:** 按 Task 1 定位的批次测试、tests/test_task_budget_routes.py、tests/test_queue_handoff.py、tests/test_worker.py；对应 src/myink/workflow/、src/myink/worker.py、维护/预算模块中已证明有缺陷的最小路径。

**Interfaces:** 消费准确 node ID 和根因证据；保持现有 owner/generation、outbox、预算及人工等待协议。

- [x] 按根因拆小目标：批次恢复、旧投递/预算恢复、瞬时故障重入队；每个目标独立完成以下循环。
- [x] 在真实隔离设施复现，追踪任务/owner/generation、outbox 与 ACK 的边界；不记录敏感正文或凭据。
- [x] 增加能够抓住根因的失败测试，最小修复，验证重复投递无重复落库或扣费。
- [x] 运行对应完整测试文件，独立审查并处理 Critical/Important，每个目标分别提交和推送。

### Task 4: 完整基线验收与交接

**Files:** docs/evaluations/pi-regression-baseline-2026-10-17.md；确有必要时更新最新维护入口，保留旧报告原始失败事实。

**Interfaces:** 消费各小目标提交和回归结果；产出明确可用/阻塞的基线及下一阶段输入。

- [x] 执行 python -m pytest tests/ -q -m 'not pi_lab and not pi_live'，记录全部失败名、SKIP 和 xfail；不能用选集通过代替全量。
- [x] 执行 python -m pytest ops/pi/tests/ -q -m 'not pi_lab and not pi_live'、compileall、评测 validate、OpenAPI 导出与漂移检查。
- [x] 按实际修改和 CI 要求运行前端 lint/test/build 与镜像构建；依赖或资源阻塞单独列出。
- [x] 审查本轮全部差异，确认无既有修改被提交、无测试设施残留；更新验收记录，提交并推送。
- [x] 后续写作分析稳定性另写计划：保持严格校验器，先做离线契约测试；新付费对照需提供预注册方案、模型与费用范围供确认。

## 计划自查

2026-10-17：已覆盖 runtime032 的五类十项历史失败；准确 node ID 和根因需由 Task 1 确认，未把历史分类当作本机复现。各目标有 RED/GREEN、审查及单独提交推送入口。没有新增产品功能，调研与修复按 systematic-debugging 执行。

## 当前状态

2026-10-18：用户已批准并选择 inline 执行，Task 1–4 完成。十项历史失败对应的测试隔离、状态和平台假设已修正，另修复一项离线主机路径测试；业务源码未改。业务全量 1612 passed、1 skipped、159 deselected、5 xfailed；最终 c4af844 干净归档 ops 全量 1422 passed、2 skipped、19 deselected。前端 457 项、契约、校验及两个镜像构建完成，专属设施已清理。已知跳过、平台差异、旧快照 RPC 截止时间敏感失败保留于验收报告，不能据此声称 Ubuntu 全 CI 等价或零稳定性风险。独立迭代审查、额外路径修正审查和文档证据审查通过；各小目标已单独提交推送。后续计划为 docs/superpowers/plans/2026-10-18-pi-analysis-stability.md，仅完成规划，尚未执行付费实验或部署。
