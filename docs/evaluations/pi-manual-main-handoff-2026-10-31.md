# 人工 main 更新后的 Pi 接续验证

当前 main 与 Pi be306 的原四项CI均已通过；服务器仍是 f230，旧周期观察尚未完成。人工直接更新 main 会使原候选的观察身份与新进程不符，故新增仅供root的元数据交接，复用原Gate、原manager、原50元费用库及9笔未知预留，不发布产品、不调用模型。

- 旧周期的task/package/approval/deployment保持原样；显式人类批准绑定旧包/收据、新物理身份、driver/profile摘要及最多1小时有效期。最终事件是 observation_interrupted/insufficient_evidence，无comparison_complete。
- 原nightly与maintenance两把锁串行交接。核验真实三进程、Python包、Git revision、源码快照、维护身份、profile/固定模板及新env；导出原审计后再次核对，verified回执持久化后才最后提交Gate终结。
- 新source issuer使用独立人工基线，而不是旧Pi完成比较；每次重新读实际源码/版本窗口，签发新的有限输入。source-stage comparison_sha256=null，baseline_receipt_sha256单独保留。模拟用例跨3天仍能签发，坏收据/模板/observer/cohort/跨版本窗口均拒绝。
- 独立审查发现并修复3项：实际PG源未绑定、旧控制器可被误接受、更换操作UUID可绕过未知意图。12个新增失败用例先RED，再修复；相关110项通过。PG查询测试使用真实PsqlMetricsReader的固定SQL/只读role校验和显式假Docker返回值，不能当ACTUAL生产PG资格。

Final exact-source offline suite: 4531 passed, 63 deselected, one existing SyntaxWarning, 497.60 seconds. Related tests: 110 passed. The earlier preliminary 4519-pass run is retained in the logs. Dedicated/live-model cases were not executed.

[实现计划](../superpowers/plans/2026-10-31-pi-manual-main-handoff.md)、[操作者步骤](../pi/admin-console.md)及[增强边界](../pi/agent-enhancements.md)说明配置与失败处理。ACTUAL Linux/root/systemd/peer/产品替换与人类新main观察交接均未执行；没有新增真实模型请求或费用。不能据此宣称整体线上闭环完成。

ACTUAL existing-version window: 2026-10-31 06:59-07:59 UTC (14:59-15:59 Shanghai), observer-20261031T075900Z-85aa8a269f5c. Eligible samples: 0; insufficient_evidence; availability unknown. Export published to original audit. Original manager SHA a588accf...f1eff and fee SHA fe7c37ea...44afb are unchanged before/after. No model requests, next-day assessment or product release. This evidence belongs to the old f230 version, not the new handoff.
