# Pi Selection Abandonment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline; one fresh independent final review, no implementer delegation.

**Goal:** 在同一manager中以追加证据放弃选择阶段已停止的任务，保留原uncertain并安全接收全新任务。

**Architecture:** `selection_abandonment.py`验证原生证据图与费用/清理事实，生成10分钟审计及独立审查绑定；apply只在原manager锁内追加reconciliation记录。manager识别已核对的放弃，raw状态保持并单列effective结果。

**Tech Stack:** Python3.12、stdlib、现有Ledger/ProbeHost与独立FileReview格式；不增加依赖。

**Spec:** `docs/superpowers/specs/2026-10-27-pi-selection-abandonment-design.md`

## Global Constraints

- 仅ACTUAL、选择停止、无开发开始；旧receipt/原费用/control不改，无自动重试/退费/采纳。
- 默认检查只读；audit/apply明确Docker只读，固定本地daemon、单次15秒。
- 私有600/700、普通单链接、全部角色隔离先于写入；原manager锁保证串行。
- 独立审查、费用/所有产物指纹与10分钟期限；pending resolution继续冻结。

## Review Focus

- 仅凭verified/cleanup字段不能放行，必须绑定真实原生上下游及原账本。
- control/frame/worker或prepared任一显示额外执行时不能放弃。
- 追加过程中崩溃、同/异请求并发、旧审计失效不能释放或重放。
- 恢复时审查/报告丢失或账本副文件硬链接不能读写绕过。
- 原unknown和费用保留，放弃不能出现在成功数中；新任务仍用原独立审批入口。

## Tasks

- [x] 1. `ops/pi/selection_abandonment.py`证据检查、审计/独立审查请求；`ops/pi/tests/test_selection_abandonment.py`先RED后GREEN，包含真实图的合成fixture及拒绝分支。
- [x] 2. manager追加resolution、幂等/锁/恢复/status与新登记门禁；同测试加pending崩溃/篡改/队列恢复，RED→GREEN。
- [ ] 3. 独立最终审查、针对性修复；核对原真实冻结任务、追加放弃、独立进程恢复；新runtime/新身份/原账本新审查后执行一次合成闭环，记录所有失败及费用。
- [ ] 4. 全Pi/Node、指标与边界文档、阶段提交推送并等待远程4门禁，完整交付与续接记录。
