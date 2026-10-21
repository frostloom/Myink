# Pi 整轮费用与期限执行计划

> **For agentic workers:** 使用 executing-plans 内联执行，最后按 requesting-code-review 独立审查。用户已授权提交推送 Pi 分支，不合并、不部署、不发真实模型请求。

**Goal:** 将30槽分析轮次的显式费用上限和绝对期限绑定到已有 local-trial-1 累计20元账本的实际预留与 HTTP 转发。
**Architecture:** 新增 analysis_budget.py 保存不可变运行预算绑定；AnalysisRun.bind_budget(policy, *, cap_microyuan, deadline) 在认领前绑定。现有 gateway_handler 自动携带宿主槽位上下文，经 control → forward_messages → reserve；在同一 BEGIN IMMEDIATE 事务里核验绑定、槽位、本轮额度、全局累计额度和期限，标记 canonical model-attempt，复用原结算。不存在第二份费用账本。
**Tech Stack:** Python 3.12、SQLite、pytest、loopback HTTP、模拟 provider。
**Spec:** docs/pi/analysis-and-scoring.md；docs/HANDOFF-2026-10-20.md；用户确认的下一步预算/期限目标。

## Global Constraints

- 仅在既有 codex/pi-autonomy-design worktree 开发，不动 main/admin。
- 不读取或改写真实付费账本/凭据，不创建真实付费授权。
- 要求已有原始 scope 和有效20元 fee-only 修订；空账本不能自动创建 scope。
- cap/deadline 必须由可信宿主显式提供，无默认授权；同一run不能续期/重置额度。
- 历史未知预留全额保留；本轮未知计费阻塞后续槽位。认领后预留失败仍不重放。
- 原低层未绑定 API 兼容保留，只用于可信宿主；不构成付费运行许可。

## Review Focus

- 历史未知费用后结算不能抵消本轮消费；不同run竞争同一累计余额。
- 重启、多线程/多进程竞争和崩溃不扩大额度，也不重复预留槽位。
- 时间在等待 SQLite 锁时耗尽，必须在锁内再次检查；发送与流式响应仍受总期限约束。
- 冻结policy内嵌可变对象不得漂移；仅允许HTTP剩余timeout缩短。
- 缺失/变化的绑定、scope、原轮次身份和未知本轮usage均拒绝；旧handler不能绕过后来新增绑定。

### Task 1: 绑定、原子预算与实际转发

**Files:** 新增 ops/pi/analysis_budget.py、ops/pi/tests/test_analysis_budget.py；修改 ops/pi/analysis_run.py、budget.py、model_gateway.py、control.py。
**Interfaces:** AnalysisRun.bind_budget(policy, *, cap_microyuan, deadline)；内部 AnalysisBudgetSlot 在 reserve 事务内 authorize；reserve/forward_messages/make_gateway_handler 新增宿主专用 analysis_slot 可选参数。

- [x] 写RED：显式绑定、拒绝空账本和重置、政策漂移、历史余额、本轮额度、认领和重复预留、未知计费、重启/并发、锁等待期限、HTTP实际消费与总期限。
- [x] 观察测试预期失败后最小实现；canonical attempt 增加 analysis_run_id/analysis_slot_index，费用仍用原reserved/charged。
- [x] targeted GREEN；独立审查、完整offline ops、compileall、diff检查。
- [x] 更新验收与交接文档。后续提交推送、远端SHA及myink记忆核验结果见交付消息。

## Decisions

- 冻结policy全字段；运行时只允许缩短timeout。源码/config真实性仍由可信宿主提供hash与实际文件校验。
- 预算上下文在handler构建时冻结绑定，锁内逐次比较；构建后新增绑定导致旧handler拒绝，避免越过后来约束。
- 同一绑定的幂等重开不续期；已认领的旧run不能补挂预算。期限使用绝对Unix时间，并沿用网关单调时钟限制。

## 验证结果

新增初始32项RED→GREEN，追加6项崩溃/期限边界及3项可变输入RED→GREEN，最终41 passed。相关基线264 passed；最终完整offline ops1809 passed、0 skipped、19 deselected（44.63秒），compileall/diff通过。独立审查及窄复核无剩余发现；审查者38 passed、3项HTTP受其沙箱权限未运行，主代理实际通过全部41项。

实现中修正既有reserve测试包装器透传新增kwargs，以及扩展测试误替换的一处body变量；均已复跑验证。期限前取得完整EOF/usage的SQLite提交延迟不算迟到模型响应；未知预留不因迟到响应退款。最终提交/推送及myink记忆核验见本轮交付。
