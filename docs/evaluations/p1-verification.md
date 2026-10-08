# P1 评测基础与首轮基线验收

日期：2026-10-08。基线提交 `326c4b366cdae38c374d253b12340c63615133c1`，工作区已有 P0/演示及其他未提交内容，本轮全部保留。没有提交、推送或部署。

## 本轮交付

| 设计阶段 | 实际交付 | 状态 |
|---|---|---|
| A 资产整理 | 40 例规范/测试覆盖清单、15 例固定审核数据（8 阳性/7 阴性） | 已实现；标签 proposed，正式语义需复核 |
| B 离线判分 | 严格输出解析、证据/目标候选、人工复核、动态汇总/HTML | 已实现，自动和 confirmed 分开 |
| C 审核运行 | validate/plan/run/score/report、预算、单次 SDK 请求、完整产物/哈希 | 已实现；无业务数据库访问 |
| D 首轮基线 | 15 个真实模型审核输出及分类报告 | 已运行；暂定自动 13/15，正式指标待人类复核 |
| E 恢复接入 | check-recovery 复查既有完整恢复记录 | 11 条确定性断言通过；没有重跑恢复或故障矩阵 |
| F 生成对照 | direct/full 与模块消融 | 未运行，仍是下一阶段 |

代码入口：[scripts/evaluate.py](../../scripts/evaluate.py)、[evaluation 包](../../src/myink/evaluation/runner.py)。操作与维护：[evals/README.md](../../evals/README.md)。[本轮完整报告](p1-baseline-2026-10-08/report.html)。

## 授权与真实请求

用户明确批准：已有 DeepSeek 配置、15 个审核案例、最多 20 次请求、估算费用上限 5 元。实际执行 15 次，SDK 自动重试禁用；无额外模型重跑。模型请求/实际响应标识与配置见 manifest。

15/15 请求 completed，无 provider_error/timeout/budget_stopped。输入 11219 / 输出 4296 tokens，估算费用 0.056806 元。使用仓库空闲单价乘 2 的保守估算，不计缓存折扣，不是供应商账单；不声明未来 API 单价不会变化。

所有 cases/messages/results 保留，归档扫描确认没有包含本地 API 密钥。当前请求不读写作品库，不启动生产/测试 worker。

## 正式指标边界与真实发现

暂定自动通过 **13/15**；其余两条发现目标问题，也提出额外问题，尚未人工判断是 label_gap、duplicate 或误报。全部 **19 条引用逐字和章号检查通过**。详情见归档 README。

15 个 label=proposed、结果 review=provisional，confirmed precision/recall 等保持 null。不把 13/15 当成真实准确率，不把模型自己的置信度当标签，不伪造人类复核。

第一次离线评分漏收一个明确提供的历史片段，将其引用误标无效；修正为“所有输入源做有效性检查，目标标签源单独做匹配”，加入回归后使用同一批原始响应重评分。早期与最终评分版本均保留，没有篡改模型结果。

原生字段、预算中止、未执行和中断后的在途未知状态分别保存；score 对人类否定结果或不完整复核返回 1。run 返回 1 可表示暂定质量条件未满足，并不表示 15 个请求失败。

## 验证

聚焦命令（Windows 为 pytest 指定本轮全新的仓库内临时目录）：

```text
python -m pytest tests/test_evaluation.py tests/test_tool_boundaries.py tests/test_snapshots.py -q --tb=short --basetemp <全新忽略目录>
python scripts/evaluate.py validate
python scripts/migrate-evaluation-cases.py
```

最终聚焦测试 **77 项通过，无跳过，耗时 2.57 秒，退出码 0**。已实际通过的范围包括严格字段/章号/指针、伪造引文、额外 findings、重复计数、无关 rewrite、非法 JSON、正式/暂定分母、预算和 SDK 不重试、源哈希/复核绑定、部分运行/JSONL 尾部恢复、HTML 转义和现有工具/快照回归。

数据校验：15 审核案例和 40 catalog 条目通过，迁移重跑只对账，不执行旧脚本、不覆盖已编辑数据。CI 仅新增无模型调用的 validate 步骤；现有 pytest 会覆盖新离线测试。

归档核对：案例和结果的规范化 JSON 哈希与 manifest 一致，首页报告/汇总与最终评分版本逐字节一致，全部归档 JSON 可解析。静态 HTML 包含 15 个案例区块且没有脚本；维护/验收/归档/计划中的 17 个本地文档链接有效。`git diff --check` 通过。

代码审查按 requesting-code-review 技能执行了一次只读子代理审查，范围仅本轮 P1 文件。修复错误章号来源、宽松模型字段、人类复核退出码、中断记录可评分及案例/复核哈希绑定；补齐原子 manifest 和断尾恢复的检查。没有使用子代理开发、运行模型或修改其他文件。

本机测试进程结束时 pyreadline3 控制台析构会打印 Windows 句柄告警；pytest 的实际结果与退出码单独核对。第一次系统 tmp 目录不可写，后续使用仓库内全新 basetemp；一次测试读取 HTML 未指定 UTF-8 导致 GBK 解码失败，已修正测试。均不计为通过前的业务失败。

## 未覆盖

本节是首轮审核时的范围。后来新增运行和回归见 [剩余P1验收](p1-completion-verification.md)，历史数据和本报告不覆盖重写。

未运行全量 Python/前端/镜像/部署验证，未跑 CI 远程 job。没有进行 direct/full 效果对照、召回/Reflexion 消融、真实 embedding 质量评测、provider/worker 故障矩阵或前端业务 E2E。HTML 做静态内容/转义核对，不声称本轮浏览器视觉验证。

设计原文中的扩展模式仍是规划；本轮完成审核评测基础和授权范围内的第一轮运行，**不是所有 P1 条目全量完成**。下一步先让维护者复核两个额外问题及各案例标签，再确定对照与召回实验范围。
