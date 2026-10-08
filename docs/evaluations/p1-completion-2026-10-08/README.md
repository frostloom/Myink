# 2026-10-08 剩余 P1 交付

先打开 [生成对照合并报告](comparison-combined/report.html)，再看 [验收记录](../p1-completion-verification.md) 与 [操作维护说明](../../../evals/README.md)。

| 路径 | 内容 |
|---|---|
| `comparison-primary/` | 首轮 60 请求、8 completed、4 budget_stopped；完整请求/响应、状态快照、正文和配置 |
| `comparison-supplement/` | 用户批准仅补 4 条；39 请求、4 completed；绑定原始输入与结果哈希 |
| `comparison-combined/` | 离线派生报告；12 selected、16 attempts、99 请求、估算 1.017986 元；包含所有中止 |
| `retrieval-before/`、`retrieval-after/` | 相同 8 例的生产关键词召回与 lexical-vector/RRF 替身实验；必要事件 4/7 → 6/7 |
| `browser/` | 真实 Chromium、真实构建前端、合成 API/SSE 的 10 项检查回执及桌面/390px截图；历史失败回执另存 `failures/` |
| `checks/` | 相关测试、完整回归与前端日志、JUnit、案例校验和资源清理记录 |
| `source-snapshot/` | 本次验收时的相关源码和维护文档快照；运行时版本以各原 manifest 的哈希为准 |
| `archive-verification.json` | 文件 SHA-256、JSON 可解析和实际密钥未出现的扫描结果 |

## 结论边界

这是合成开发任务上的流程、成本、恢复与召回机制证据。所有标签仍 proposed，正文质量没有真实人类评分。历史 direct 未提供前章尾文与明确别名映射，而 full/no_hybrid 提供了这些素材，因此**不能用这批结果声称系统优于直接生成**。以后 runner 已补齐输入，旧请求保持原样，没有重跑已完成槽位。

生成 completed 表示没有生成调用错误，`awaiting_review` 并不代表整个工作流已落库完毕。原报告中的“same raw history”仅涉及 history/constraints，完整的输入差异以本说明和合并报告为准。向量关闭；lexical fixture 不证明真实 embedding 质量。单章图没有批次 Reflexion，对照未测它；真实服务浏览器端到端、负载性能和公平质量对照仍需后续实验。

盲评先看 [cases](comparison-combined/cases.json) 和 [blind-review](comparison-combined/blind-review.json)，保留真实 reviewer、时间与说明；然后才打开 `blind-key.json`。该包含 16 个尝试，中止项作为运行失败保留，不对不完整正文强行打质量分。需要复核的初轮审核额外 finding 见 [人类复核提示](human-review-notes.md)，不要将 Agent 提示作为人类确认。

## 离线重建

在根目录安装项目依赖后执行，不需数据库或 API：

```text
python scripts/assemble-comparison.py --primary docs/evaluations/p1-completion-2026-10-08/comparison-primary --supplement docs/evaluations/p1-completion-2026-10-08/comparison-supplement --output .local/evaluation-runs/<new-offline-report>
```

输出目录必须全新。原始运行的绝对来源路径保留为历史记录；重建通过 run/results 字节哈希绑定，而非要求原机器路径存在。不同运行保存不同源码哈希，不用当前代码冒充历史版本。
