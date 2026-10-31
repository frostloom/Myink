# Pi 当前会话计划选择修复

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. 用户已授权在当前隔离工作区执行、验证、分批提交与推送，不重复请求方案批准。

**Goal:** 修复 008 实测发现的跨轮次计划汇总污染，保留历史与独立审批。

**Architecture:** 在既有 verify_stopped_phase 中，从当前会话的工具调用和结果中选取唯一 propose_plan。逐条 broker.lookup 已认证身份和账本回执；不再在最终宿主汇总中查询全账本前缀。成功验证返回 proposed_plan（operation_id、plan、plan_hash），不等于独立审批或部署。

**Tech Stack:** Python、pytest、SQLite；本轮无模型、native、数据库服务或镜像运行。

**Spec:** docs/evaluations/pi-local-trial/runtime008-2026-10-13.md

## Global Constraints

主工作区和 dirty B12 保留；既有 008 冻结源码、native 证明和失败不改写。local-trial-1 仍累计100次/20元，阶段15/45/30/10不变。新 consumer 放单独私有离线修复目录，不启动009，不伪造008成功。自动发布和语义质量仍未验收。

## Review Focus

- 历史成功计划与当前相同阶段标签：只选当前已认证计划，历史行不改。
- 当前两个有效计划：拒绝，不能择一。
- 规则 blocked 或 failed：拒绝，即使 tool receipt done。
- 外来 binding、调用ID或修改过的回执：拒绝。
- 无当前计划、只有旧账本计划：拒绝。

### Task 1：受认证的计划交接

**Files:** Modify ops/pi/trial_runtime.py; tests ops/pi/tests/test_trial_runtime.py。私有 consumer 为 .superpowers/sdd/2026-10-11-pi-local-trial/c19-host-plan-selection-fix/phase_host.py，从008复制，仅替换末尾全局账本选择段，不改冻结008。

**Interfaces:** verify_stopped_phase(...) 的现有参数不变；plan 成功返回 proposed_plan={operation_id,plan,plan_hash}，其它phase无需此字段；返回的计划仍需单独 host review。宿主使用 result[proposed_plan] 再写当前 proof，不全局查询 ledger。

- [x] RED：真实 ControlledTools/SQLite 中保留旧成功计划，用当前会话调用新计划，断言返回的是当前计划和operation ID；原实现缺少交接字段而失败。
- [x] GREEN：最小实现选择当前会话唯一调用，认证规则成功并核实 Plan 计算哈希；保持已有开发最后补丁之后候选检查约束。
- [x] 覆盖上述5类输入，验证旧操作/事件保持不变、没有新预算事件或模型调用。
- [x] 验证私有consumer实际选择段已使用上述返回值，保留exact-one检查的拒绝行为；不修改旧阶段标签、超时或授权。
- [x] 聚焦 trial_runtime/tools/plans/budget 等受影响测试；再在独立干净源码副本运行离线ops套件，明确SKIP/deselected。完整服务缺失不宣称通过。
- [x] 独立源码审查；两份冻结审查均 Approved。事实文档审查、第二批文档提交与远端 SHA 核对在交付阶段执行，以 Git 历史与最终答复为准。不能把离线修复写成真实闭环完成。

## 回归中发现的验证问题与实际结果

首次干净归档回归 2 failed。额外只修改 ops/pi/tests/test_lab_gates.py 的夹具隔离（已加载真实 Settings 用 monkeypatch 刷新并恢复），以及私有 Windows pytest 入口的 main guard；生产校验与账本保持。最终 clean a79bf12 + 三文件覆盖回归为 998 passed、2 skipped、19 deselected。源码提交 baee005571edd8ad52955ac461ca9141de142b04。完整失败/GREEN、维护边界和 consumer 差异见 [验收记录](../../evaluations/pi-local-trial/plan-selection-fix-2026-10-13.md)。
