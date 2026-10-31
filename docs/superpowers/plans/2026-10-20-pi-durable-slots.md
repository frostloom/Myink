# Pi 持久化槽位与防重放执行计划

> 在现有 Pi worktree 使用 executing-plans 内联执行；用户已授权恢复环境并完成本目标。完成后独立审查；用户随后授权途中提交推送；不合并或部署。

**Goal:** 恢复 Mac Python 测试基线，为现有30槽分析实验添加持久化、原子认领及防重放控制。
**Architecture:** 复用 Ledger 的 BEGIN IMMEDIATE 事务和不可变 operations/events，不改 schema 或真实预算。每轮冻结 run/source/config/slots 身份，预先登记全部槽位；按可信宿主指定序号认领，以绑定序号的 request_guard 接入现有 HTTP 网关。认领后未完成的槽位保留 UNCERTAIN，恢复时禁止重跑和继续下一槽。
**Tech Stack:** Python 3.12、pytest、SQLite、现有 HTTP mock。
**Spec:** docs/HANDOFF-2026-10-20.md §12；docs/pi/analysis-and-scoring.md §分析合同执行接入；docs/superpowers/specs/2026-10-10-pi-autonomy-design.md。

## Global Constraints

- 仅修改 codex/pi-autonomy-design worktree，保护主目录及其他 worktree。
- 不调用外部模型，不读取凭据或改写真实累计20元账本，不创建新预算授权。
- 30槽固定顺序；不自动重试；未知状态保留，不把协议有效当语义质量提升。
- 整轮预算/期限、隔离验收和真实30槽实验仍是后续目标。

## Review Focus

- 同一请求在多个baseline槽位字节完全相同时，旧槽位guard仍不能消费下一槽。
- 多线程及多进程只能有一个认领成功；崩溃后不重复请求。
- run/source/config/输入身份漂移必须在网关预算预留前拒绝。
- 失败、未知和未运行有完整30槽分母；未认领槽位不能伪造结果。
- 账本不可用、运行不存在或原有槽位丢失时拒绝，不自行修复重建。

### Task 1: Python 环境与基线

**Files:** worktree .venv（忽略）；本计划和验收报告。
**Interfaces:** .venv/bin/python -m pytest。

- [x] 创建 Python >=3.11 环境与必要离线依赖。
- [x] 运行交接的五个定向文件及完整 offline ops，准确记录失败/跳过/未选入。

### Task 2: 持久化槽位控制及 HTTP 接入验证

**Files:** 新建 ops/pi/analysis_run.py、ops/pi/tests/test_analysis_run.py；更新 docs/pi/analysis-and-scoring.md、docs/pi/README.md、验收报告。
**Interfaces:** AnalysisRun.create(ledger, run_id, slots, *, source_sha256, config_sha256)；AnalysisRun.open(同参数)；guard(slot_index) -> callable(body)；finish(slot_index, *, status)；gateway_handler(slot_index, policy, transport, *, scope_token)；snapshot() -> 30槽无正文状态。

- [x] 先写测试并确认RED：30槽初态、身份漂移、请求漂移、顺序、重放、相同body的旧guard、多线程/进程、崩溃重开、不可用存储。
- [x] 最小实现：原子创建 run+30槽；原子校验/认领；必须前槽有明确done/failed终态才可继续；未完成认领/uncertain/blocked一律阻塞。
- [x] 真实loopback HTTP mock验证重复请求只有一次预留/转发，拒绝无费用，重启仍拒绝。
- [x] 定向GREEN与完整offline ops；审查后修复有证据的问题，记录限制，不代替真实计费或隔离验收。

## 执行记录

- 初始HEAD a0b8100，工作区干净。Python3默认3.9.6；发现可用python3.12 3.12.15及uv。Hindsight未启动，按项目规则跳过。

- 追加边界：相同baseline请求不能仅靠正文哈希隔离。gateway_handler 持久绑定独立槽位令牌摘要，禁止同一账本跨槽/跨运行复用，旧令牌在认证阶段拒绝。
- 原基线首次收集失败（缺少sqlalchemy/myink）；已按CI约束安装项目dev依赖。完整原基线复现23 failed/1715 passed/19 deselected：15项Linux root夹具、2项Windows内存替身、5项root安装夹具、1项解析器错误类型差异；只修正测试夹具，不修改这些生产检查。
- 新模块RED 22 failed → GREEN 22 passed；独立令牌追加RED 8 failed → GREEN 30 passed。平台夹具定向139 passed。

- 原基线修复1738 passed/0 skipped/19 deselected；独立审查139 passed、无发现，已提交推送8821831。
- 新模块独立审查无发现；审查者28项通过、2项HTTP被其沙箱bind阻塞，主执行者已实际通过全部30项。
- 最终全量offline ops：1768 passed、0 skipped、19 deselected，39.90秒；compileall和diff --check通过。详见 docs/evaluations/pi-durable-slots-2026-10-21.md。
