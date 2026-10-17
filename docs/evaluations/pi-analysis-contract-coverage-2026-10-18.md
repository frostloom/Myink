# Pi 写作分析离线合同覆盖（2026-10-18）

## 范围与基线

本轮从 `062f346d1d9f09a8ff3dc19d76e16ffde445ce38` 开始，仅补测试与文档。执行依据为 `docs/superpowers/plans/2026-10-18-pi-analysis-stability.md`，用户已批准离线补测和对照准备；未调用模型、读取私有正文或启动业务服务。

原有三文件测试为 49 passed、1 skipped（1.00s）；新增 255 个参数化案例后，相关完整三文件为 304 passed、1 skipped（2.14s）。跳过的是 `test_symlink_intake_is_denied`，原因是本机 Windows 符号链接权限；未计通过。测试使用 Windows Python 3.12（现有 aiink 环境），没有声称完全锁定的 Ubuntu CI 环境。

## 实际补齐的覆盖

已有测试覆盖了部分 recall.events/operations 目标规则、数组 rollback、空 observation、重复 JSON key、伪造引用、直接跨 excerpt 拼接等；这些原测试保留，没有为凑数量重复创建同一组用例。本轮补齐整张目标域矩阵与经过提示 JSON/输出 JSON 传输后的字面引用行为。

| 目标域 | 有引用的目标观察可接受 | 其他十域 trace_observation 被拒绝 | 其他十域 unknown 但带 refs 被拒绝 | 目标无引用观察 |
| --- | --- | --- | --- | --- |
| recall.events | 1 | 10 | 10 | 拒绝 |
| recall.plot | 1 | 10 | 10 | 拒绝 |
| recall.characters | 1 | 10 | 10 | 拒绝 |
| recall.facts | 1 | 10 | 10 | 拒绝 |
| extract | 1 | 10 | 10 | 拒绝 |
| write | 1 | 10 | 10 | 拒绝 |
| audit | 1 | 10 | 10 | 拒绝 |
| repair | 1 | 10 | 10 | 拒绝 |
| tools | 1 | 10 | 10 | 拒绝 |
| operations | 1 | 10 | 10 | 允许 body-free report 例外 |
| experience | 1 | 10 | 10 | 拒绝 |

对应 `test_analysis_trial.py` 的三个新增测试：目标正例 11、非目标观察/引用反例 220、无引用例外 11，共 242 案例。非目标反例先经过真实 JSON 解析和严格基础合同，携带有效字面引用，再要求目标域 scorer 拒绝，避免因错误字段提前失败而伪装覆盖 scope。

`test_writing_analysis.py` 的两个新增测试共 13 案例：字面反斜线+n、真实换行、带转义的引号、中文 Windows 路径各经过 UTF-8/ASCII-escape 两种 JSON 输出编码，8 个正例均保留原 quote；另外 5 个反例拒绝转义互换、删除反斜线/引号转义、拼接分离的 start/end excerpt。提示 builder、解析器和引用校验均为真实实现；输入 view 保持原样。

这是既有行为的契约补测，首次执行即通过，未把它包装为发现了生产缺陷或修复 RED。没有改动 `writing_analysis.py`、`analysis_trial.py` 或降低验收条件。

## 测试敏感性检查

另用两个独立 Python 进程进行内存故障注入，磁盘生产源码不变：只省掉 scorer 目标域检查（保留基础合同）时，220 个非目标案例全部失败；省掉引用校验时，5 个转义/拼接反例全部失败。两个注入进程退出码均为预期的 1，JUnit 确认失败数为 220 和 5。此结果只证明新增测试能抓到对应校验退化，不是实际产品红测或质量效果。

## 完整验证与限制

离线 ops 全量从 `062f346` 的干净归档叠加上述两个测试文件运行，归档内两文件字节与提交前工作区逐项一致，排除工作区既有四项 ops 文件修改。命令 `python -m pytest ops/pi/tests/ -q -ra --tb=short -m "not pi_lab and not pi_live"`：**1677 passed、2 skipped、19 deselected（353.58s），退出码 0**。两个 skip 分别为 writing_analysis 的 symlink_intake 与 writing_evidence 的 symlink_inside_root，用例完整名称见 JUnit，均因本机符号链接权限；19 项 pi_lab/pi_live 未执行，不计通过。JUnit SHA256：`c74fba517a06b2ac98d161e4f92a0b64dfdc13ff4f8bd4c8b390970676a40d1b`。

独立只读代码审查无 Critical/Important/Minor。未对未运行的 Windows symlink 行为、真实模型效果或部署作验收。四个既有 ops 文件的哈希保持不变，不纳入本轮提交。本轮只改 ops 测试，因此运行完整离线 ops 门禁；未重跑业务数据库、前端或镜像门禁，不把上一轮结果当成本轮执行。

本轮验证不证明模型会稳定生成合法输出，也不证明 45 项语义质量改善。历史 025 的 1/10 合同有效和质量方案未获采纳结论保持原样。真实付费对照需另有完整预注册、模型价格及费用确认。
