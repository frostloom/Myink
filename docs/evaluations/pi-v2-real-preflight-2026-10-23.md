# Pi v2 真实有界试运行：只读预检与待授权方案

2026-10-23T14:23:09.072439+08:00。基线f553a3cf，现有v2功能、2190项离线测试和8场景37容器Linux合成验收均已提交推送；本轮只做真实输入/原账本/官方资料的只读核查，不包含模型执行授权。

## 当前事实

- 原冻结输入内容SHA未变，重建全部30槽，仍为五组×两臂×三重复。固定模型deepseek-flash、thinking disabled、max_tokens2048、无tools、共同cwd与原顺序不变。正文未上传模型，本报告不公开正文、凭据或账户余额数值。
- 原累计scope预算20元，211次attempts：203 known、8 unknown、0 pending。known保守结算1.797465元，历史unknown完整保留16.114944元，当前保守余额2.087591元。不是重新给一个20元额度。
- 官方价格、Anthropic兼容和缓存三页重新下载封存，原始字节SHA与前次审阅资料一致。当前模型仍为DeepSeek-V4.1-Flash-1017；沿用峰值输入/输出每百万2/8元及原策略，不更改为离线估计的更紧上界。见[官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)与[兼容说明](https://api-docs.deepseek.com/guides/anthropic_api/)。
- 现有input_token_bound仍为1M上下文容量保守上界；[离线token计数](pi-token-calibration-2026-10-23.md)未证明更低API上界，官方也以实际usage为准。见[官方用量说明](https://api-docs.deepseek.com/zh-cn/quick_start/token_usage/)。每笔发送前预留2.016384元，下一笔预留后仅有0.071207元空间。余额只覆盖一个最坏费用包络，不能保证完成任何槽的有效结果，更不能保证完整30槽。
- 原凭据只在宿主内存验证，并进行一次官方GET /user/balance；账户当时可用。该GET不证明模型调用、实际usage语义或账单已验收。没有模型POST、run或容器创建。
- 使用与Linux验收相同的新source闭包SHA `86de1961a9f921b65dc7b1c296f2d7529fa83fbceea8c6b5c55e4039c3b5fbb2`，runtime仍固定Node24.22.0/Pi1.1.0。只读核对原daemon和缓存image身份正常。
- 显式禁用Ledger writer、provider和容器create的check返回checked/selected_slots30/launch_ready=false，root不存在。全局live=false。锁内前后audit相同，DB/WAL、policy、credential和冻结输入字节相同，未写scope、attempt、operation或event。

## 建议授权范围

如果用户愿意接受可能只完成前缀，可批准一次真实有界试运行：

| 条目 | 明确限制 |
| --- | --- |
| 本轮cap | 至多2.087591元；同时受原累计20元额度约束 |
| 发送数量 | 按原固定顺序最多30次，不跳槽；实际可能只发送一部分 |
| 输入外发 | 将既有冻结的私有写作证据/报告发送到当前配置的DeepSeek模型接口 |
| 执行窗口 | 授权后重新生成未来1800秒内的绝对deadline；主动清理最多120秒，最终持久化无整个调用的硬墙钟保证 |
| 单槽时限 | 原worker45秒、exchange60秒不变 |
| 策略变化 | 仅本次临时live_enabled false→true；原价格、输入上界、模型、输出限制、总预算均不变；收尾恢复关闭 |
| 必停条件 | 未知费用、预算不足、期限/中断、身份/来源/协议/session/清理异常均停止 |
| 普通合同失败 | 只有唯一session、HTTP负控、已知费用、精确清理及期限均通过，才记FAILED并继续 |
| 不允许事项 | 不重试、不恢复、不重置run/scope、不释放历史unknown、不扩总预算、不合并或发布 |

已完成DONE/FAILED不改写；未完成claim为UNCERTAIN，未发送保留NOT_RUN，报告保留30槽分母。第一次输出不合格不会单独阻止后续，但未知费用或门禁阻断会立即停止；这不是保证完整30槽的付费对照，也不能直接证明写作质量提升。

这是实现者建议的执行范围，**目前尚未获得用户的付费请求/输入外发授权**。此前“可以”只回答提交推送问题，不能转用为本次付费执行授权。普通“下一步”在本轮只用于准备可审阅方案。

## 授权后才执行的准备与收尾

重新核对当时账本、余额、锁、输入/源码/runtime、价格证据和Docker身份；若余额不足或身份漂移则停止，不自动提高预算或换配置。仅在原policy字节SHA未被其他操作改变时，临时启用该原policy并生成匹配新policy SHA的证据与清单，用新run_id执行一次；收尾只在内容仍为本轮写入版本时恢复原关闭策略，遇并发策略变化不覆盖他人修改并明确报告。

本轮check清单使用旧的关闭策略，且仅作诊断，绝不能直接改execute或重放。其当次deadline为 `2026-10-23T06:53:04.302913+00:00`，到期即失效；未来执行要重新生成新期限、新run和证据，不把诊断回执视作授权。

## 验证与记录

[机器记录](pi-v2-real-preflight-2026-10-23.json)含脱敏budget、scope/policy/input/source摘要、只读check结果和私有回执SHA。私有原始HTML、只读清单、账户GET结果及完整回执在当前worktree `.local/pi-v2-real-preflight-20261023/check-001/`；旧清单与历史证据未改写。

本轮0模型POST、0付费请求、0新run、0容器，只有官方公开资料GET和一次余额GET；不更改生产代码，无需重复上一轮完整回归。报告/回执哈希、预算算术与非执行边界已核对；最终仍须git diff --check。本轮文档尚未提交或推送，不合并main、不部署。
