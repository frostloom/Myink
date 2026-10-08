# 评测资料入口

维护者先读 [评测操作说明](../../evals/README.md) 和 [评测体系设计与维护约定](../EVALUATION-DESIGN.md)。固定文本审核入口已实现，原设计中的扩展模式以验收记录所述范围为准。

| 资料 | 用途 |
|---|---|
| [冲突规范](../../spec/conflict-samples.md) | 40 个机制场景及正反对照 |
| [机制套件](../../tests/test_conflict_sample_suite.py) | 实际检测逻辑，模型判定/embedding 使用替身；保留缺口 |
| [logic-smoke.json](logic-smoke.json) | 10 个真实模型逻辑案例的历史结果 |
| [continuity-smoke.json](continuity-smoke.json) | 接续案例及生成过程的历史结果 |
| [workflow-recovery.json](workflow-recovery.json) | 历史恢复统计，缺少完整正文 |
| [workflow-recovery-2026-10-08-live.json](workflow-recovery-2026-10-08-live.json) | 本轮完整合成恢复案例，含初稿、反馈、修订和落库 |
| [完整案例说明](../interview/README.md) | 真实运行与浏览器验证范围、重建方法 |
| [P0 验收](interview-p0-verification.md) | P0 修复及当时选定的 97 项回归证据 |
| [P1 验收](p1-verification.md) | 审核评测实现、首轮 15 请求基线和范围边界 |
| [P1 归档目录](p1-baseline-2026-10-08/README.md) | 完整固定输入、实际输出、评分版本和报告 |
| [剩余 P1 验收](p1-completion-verification.md) | 召回修复前后、生成及补跑、worker中断、浏览器与全量回归 |
| [剩余 P1 交付包](p1-completion-2026-10-08/README.md) | 原始产物、合并报告、盲评表、操作与历史输入限制 |

历史结果不自动代表当前版本通过。新增实验优先保存在被忽略的 `.local/evaluation-runs/`；只有检查过的合成快照才归档到这里。原始记录不覆盖，未知历史配置不补造。
