# Pi 提示与评分口径离线核对（2026-10-22）

结论：本次真实 baseline 的非目标领域评价是冻结目标规则下的有效失败样本。baseline/candidate 一直共用基础 validator 与目标 scorer，没有发现两臂使用不同评分规则，也没有发现需要据此放宽规则或改写历史输出的缺陷。当前候选模板已含目标唯一约束；本轮没有新增真实请求或生成 candidate 输出。

## 提示、输入与评分

| 项目 | baseline | candidate |
| --- | --- | --- |
| 提示构造 | legacy_shared_writing_prompt，历史共享模板 | build_writing_prompt，现有分域模板 |
| 目标限制 | 未显式要求只有当组可观察；operations 可引用报告 | 明确 only target may be trace_observation，非目标 unknown/无 refs；operations 例外仅限 operations 自身目标 |
| 基础校验 | validate_writing_analysis | 相同 |
| 进一步评分 | score_contract_output，非目标必须 unknown 且无引用 | 相同 |
| 当前真实诊断 | 基础通过，目标规则不通过 | 本次未运行 |

旧模板允许较宽的输出而新模板明确目标任务，二者按同一目标规则比较是原合同实验的设计，baseline 不保证通过或必定失败。只要 baseline 恰好产生目标限定的合法输出，仍会通过；candidate 产生同样的非目标评价，也同样拒绝。两个模板同时还在索引、字面引用、格式、rollback 和 DATA 元数据说明上存在差异，因此比较因素是**整份提示模板**，不能把任何差异归因于单独一句目标约束，更不能据此宣称模型能力或写作语义质量提升。

从已冻结真实输入重新生成全部 30 槽，与原保存槽完全一致；对 5 组 × 3 重复的 15 对逐项核对：同对 view/report、完整动态 system、模型、max_tokens=2048、stream、thinking 及其余请求参数相同，出站请求只在 prompt 消息内容上不同。DATA 中共同 view/operations/quality_catalog/permissions 完全相同；baseline 的 family_rubrics/rubric_detail 与 candidate 的 target_domain/target_constraint 差异保留在提示因素中。未公开任何私有提示、数据或输出正文。

历史 2026-10-17 的 10 次对照记录为 baseline 0/5、candidate 2/5，且报告明确之后又修改了提示措辞，修改版当时未付费对照。本次没有把该旧结果当作当前措辞的效果证明，也没有把单个新 baseline 样本并入新 30 槽试验或冒充新的成对比较。

freeze_contract_trial 的 validator 字段仅写基础 validator 名称，不能单看该字段就遗漏目标 scorer；早期预注册正文与实际 run_contract_slot/verify_result 都要求目标评分。该函数不是完整费用/执行清单；本轮不改其 schema、hash 或旧冻结记录。

## 执行协议的实际差异

2026-10-18 的不可执行草案允许：已知且已计费的普通 provider/schema 失败，若其他门禁仍满足，可记录后继续。2026-10-22 的可信宿主 pilot 设计则要求宿主合同、session、已知计费、清理全部成功才前进；实际 launcher 在 result_verify 失败时停止，保留 claim 和 NOT_RUN。**当前实现符合自己的严格 pilot 设计，但不是早期完整试验草案的执行器。** 本次真实请求的目标规则失败因此阻断后续，并非对照已经跑完。

保留两个层级：分析槽未获完整接纳可为 UNCERTAIN；同一请求若 usage 已知，model-attempt 仍为 done，保留真实已知的保守结算。本次已有 6034 微元结算不能退回、改成 unknown 或释放历史 unknown。提前停止保留全部槽及失败事实；不能只统计已通过的样本，也不能把 NOT_RUN 当作模型输出失败率。

要进行未来完整对照，需要另行设计并验证实验执行模式：先独立证明来源、会话/运行边界、请求身份、已知账本结算及精确清理，再区分可记录的普通输出合同失败与必须停止的协议/身份/账本/未知费用故障。普通失败不得伪装 DONE/合同通过，保留原输出和明确失败结果；继续策略、配对选择、预算与期限要在运行前冻结。目前 pilot 不改，不通过手动跳槽、换序、重置 run 或低 cap 来绕过前缀选择。

## 本轮验证

- 15 对真实冻结槽输入/系统/参数一致性，全部通过；只读加载已保存 baseline 并复现同一非目标错误，未生成任何真实候选。
- 90 个合成 mock-engine 案例覆盖全部 30 槽、两臂、五组和三次重复：30 个目标限定正例接受、60 个非目标观察或非目标 unknown 带引用的反例拒绝；90 个先通过基础 validator。两臂各 45 案例，均 15 接受/30 预期拒绝。这里只验证评分行为，不模拟候选成功率。
- 审计核心禁止 provider、Docker、子进程及网络连接，也不加载真实凭据；mock Engine 调用均在内存。第一次合成会话因 macOS 临时路径符号链接保护被拒，改用物理 /private/tmp 后复核通过，首次失败日志保留；没有修改该保护或生产源码。
- 既有 test_analysis_trial/test_analysis_execution/test_writing_analysis/test_analysis_launcher 实际运行 **396 passed，0 skipped**；测试包含隔离 SQLite、本地 loopback 与模拟外部边界，不访问真实 provider/Docker。没有重跑全 Pi 2112 项回归，不将历史测试算本轮结果。
- 原账本前后只读逻辑观察相同，DB/WAL、全局 policy、原输入/报告、旧真实回执与输出字节不变；source-reviewed 与当前生产源码闭包一致，没有容器执行。账本仍 211 attempts/203 known/8 unknown/0 pending，保守余额 **2087591 microyuan（2.087591 元）**，全局 live=false。

公开机器记录包含检查计数、来源及 7 份私有证据摘要，不含写作正文或凭据。见[机器记录](pi-contract-audit-2026-10-22.json)。本轮只交付离线核对和执行协议限制，未实施新试验模式，未生成 live 清单、未合并 main 或部署；真实 candidate/账单/45 项质量仍未完成。

独立只读复审完成：0 Critical / 0 Important / 0 Minor。核对源码/spec、公开文档和获准脱敏证据（含7份摘要），未访问真实输入/输出/session/attach/credentials、未联网或调用Docker/执行入口，396项测试只核验本轮日志。交付前另对15对完整请求仅替换prompt文本后的结构相等性复核通过。
