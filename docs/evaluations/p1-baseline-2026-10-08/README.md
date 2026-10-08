# 2026-10-08 P1 固定文本审核基线

打开 [报告](report.html)。这是本轮 15 个合成固定文本的真实 DeepSeek 审核输出，不是直接生成与完整工作流的效果对照。

- 15 请求全部完成；实际模型 `deepseek-v4-flash`，输入 11219 / 输出 4296 tokens。
- 估算费用 0.056806 元，采用仓库单价 ×2，不计缓存折扣；不是供应商账单。
- 暂定自动通过 13/15；目标候选匹配仍需人工语义复核。confirmed 指标为 null，不能声称 86.7% 的真实准确率。
- 19/19 引用可在给定输入的对应章号找到。逐字有效不等于语义结论一定正确。
- 8 个阳性、7 个阴性；首次完整基线选择 all，holdout 是本地公开保留组，不是外部独立评测。

## 两个需要复核的案例

1. `continuity.mechanical_opening_repeated`：模型发现机械重复，同时提出一个“时间线回退/接续断裂”问题。后一条引用确实来自输入，但不属于当前唯一目标标签；需决定它是合理额外问题、重复表达，还是误报。
2. `continuity.pending_threat_dropped`：模型发现未交代威胁解除，同时指出“章节计划守住后门未完成”。引用有效，但当前标签只覆盖第一项，需要复核并决定是否补标签。

这些记录不被删除，也不通过临时放宽匹配规则改成全绿。额外问题默认保持待复核，不自动记 FP。

## 文件与来源

- [manifest.json](manifest.json)：实际模型配置、调用限制、来源和哈希。
- [cases.json](cases.json)：运行时固定输入与期望快照。
- [results.jsonl](results.jsonl)：全部原始运行记录，未改写。
- [summary.json](summary.json)：当前归档报告对应的动态统计。
- [review-template.json](review-template.json)：待人类填写，绑定结果与案例哈希。
- [恢复记录检查](recovery-check.json)：对稍早运行的完整恢复案例做 11 条离线断言检查，无新请求。
- 当前报告的评分版本：[scores/20261008T190829-ec5220](scores/20261008T190829-ec5220/scoring-manifest.json)。根目录 report/summary/template 是该版本的冻结副本。

目录复制自 `.local/evaluation-runs/2026-10-08-p1-baseline`，复制前后不修改输入或模型输出。早期 scores 版本保留用于追溯评分器修正：第一版漏映射一段实际提供的历史，曾显示 18/19 引用有效；修正后离线重评分为 19/19。没有重跑模型、没有额外费用。缺失的未处理原始响应字段仍保持缺失，不能补造。

需要再次评分时执行 `python scripts/evaluate.py score --run-dir docs/evaluations/p1-baseline-2026-10-08`；它生成新 scores 目录，不覆盖本归档根报告。维护操作见 [evals/README.md](../../../evals/README.md)。
