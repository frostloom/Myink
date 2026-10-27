# 观察→提案→可验证任务实施计划

1. `ops/pi/observations.py` + `ops/pi/tests/test_observations.py`：严格宿主清单，JUnit/cycle/metrics归一，来源身份、未知、跳过和混杂保留；check只读，freeze显式私有快照。
2. `ops/pi/proposals.py` + `ops/pi/tests/test_proposals.py`：宿主规则映射固定任务包、去重、拒绝分母、有限原隔离基线；桥接已独立封存cycle到inbox，不自批准。
3. 复用现有固定checker与管理器，实际复现多分支观察/提案与一次ACTUAL合成任务的完整接线；代码、费用和清理审计，更新工程指标台账与脱敏复现源。主代理实现、一次独立最终代码审查、作者红绿修复、完整Pi/相关Node验证后阶段提交推送。

Review focus：输入变化与输出重叠/链接；XML实体/日志隐私；重复观察、未知度量不等于0；阈值样本和版本混杂；无gold自动化；观察不产生权限；基线错误/绿色/跳过/大库存/清理结果；取消后不继续；执行/发布原子性、并发幂等；真实新账本审批不能复用；分母和模拟/真实口径不得混用。

## 实际结果与续接

步骤1/2已实现并验收；步骤3四分支实际checker和真实发布/分派已执行，但选择协议异常，未进入开发，真实闭环目标没有完成。该失败保留，不扩大授权或重放原意图。独立代码审查3P2均作者RED→GREEN修复。真实异常后离线重现writer flush/关闭竞态并修复，读写故障分开诊断；旧实际根因未确认，不冒称修复已付费验证。最终2775通过/19未选、56观察相关、108 RPC/选择、Node54通过。完整实测/费用/恢复分母见docs/evaluations/pi-observation-proposals-2026-10-27.json。

下一阶段处理追加式显式证据核对与冻结恢复，再以新身份/runtime/独立审批验收；当前不删除账本、释放原意图或新开队列绕过冻结。私有进度与原始材料在.local/pi-observation-proposals-20261027/progress.md。
