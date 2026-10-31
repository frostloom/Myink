# Pi v2 一次真实有界试运行

2026-10-23。用户在[具体方案](pi-v2-real-preflight-2026-10-23.md)后明确回答“允许”，授权本轮cap2.087591元、1800秒按原顺序最多30槽、发送冻结私有输入、临时启用并收尾关闭；不重试、不恢复、不扩额度、不释放历史unknown。

**本次真实发送6次，完成3 DONE/3 FAILED；第7槽被本地预算门禁429拦截，没有发往DeepSeek。** 总体按预先允许的提前停止语义结束为blocked。全局模型开关已恢复false，7个真实容器全部移除。没有重试、续跑或追加请求。

## 真实结果与有限结论

| 序号 | 冻结槽 | 状态 | 宿主判定 | 账本已知计量/元 |
| --- | --- | --- | --- | ---: |
| 1 | r1:recall.events:baseline | FAILED | output_invalid：引用未匹配保留片段 | 0.008962 |
| 2 | r1:recall.events:candidate | DONE | 通过 | 0.017684 |
| 3 | r1:recall.plot:baseline | FAILED | output_invalid：引用未匹配保留片段 | 0.007706 |
| 4 | r1:recall.plot:candidate | DONE | 通过 | 0.018214 |
| 5 | r1:recall.characters:baseline | FAILED | output_invalid：引用未匹配保留片段 | 0.016197 |
| 6 | r1:recall.characters:candidate | DONE | 通过 | 0.018514 |

六次真实上游HTTP均为200，六个新session均不同；已完成六槽的宿主HTTP序列均为403/403/200/403，身份、原始session及源码验证、已知结算与精确清理通过后才落DONE或FAILED。

三个FAILED的输出本身均为合法JSON，但至少一处quote不能在指定保留excerpt内逐字连续匹配，触发原validator的 `quote outside one contiguous retained excerpt`，宿主映射为output_invalid并保留原文后继续。没有裁剪/修复引用或输出，没有因失败重发。三个candidate在当前合同下通过；这只是在首轮前三组上的3对结果，不是完整30槽对照，也不是写作质量提升或统计显著性的结论。extract/operations和后两轮未完成。

## 为什么余额仍有约2元却停止

| 项目 | microyuan | 元 |
| --- | ---: | ---: |
| 本轮授权cap/运行前保守余额 | 2087591 | 2.087591 |
| 6笔已知计量合计 | 87277 | 0.087277 |
| 运行后保守余额 | 2000314 | 2.000314 |
| 下一笔发送前必须完整预留 | 2016384 | 2.016384 |
| 下一笔预留缺口 | 16070 | 0.016070 |

原1M输入上界与2048输出上限未变，所以每次发送前仍需2.016384元。此时余额低于完整预留；本轮cap和原累计scope也都无法再容纳该预留。启动器没有自动提高cap、降低输入上界或释放历史unknown。

第7槽（index6，r1:extract:baseline）已有不可重放claim，随后网关reserve拒绝，session记录429、引擎failed；宿主未确认确定结果，故保守保留UNCERTAIN。**这个UNCERTAIN不代表新增未知费用：该槽没有model-attempt预留，也没有外发模型POST。** 六个新增model-attempt均为done/usage_known=true；原8笔unknown数量及16.114944元预留完全未变，pending仍为0。不能为该槽再发一次或续跑原run。

原receipt保留 `stop_reason=execution_failed`、stage=result_verify/http_status429；本报告结合真实POST日志、canonical attempt归属和预算不等式，将观察到的原因另记为 `local_budget_reservation_denied`，不改写原始receipt或槽状态。完整分母仍是30：3 DONE、3 FAILED、1 UNCERTAIN、23 NOT_RUN。

这里0.087277元是原价格策略按已知usage写入canonical账本的计量金额；没有把它冒充独立平台账单核验，billing_verified仍为false。

## 账本、配置与清理复核

- 运行前211 attempts/203 known/8 unknown/0 pending，运行后217/209/8/0。known累计从1.797465增至1.884742元，unknown保持16.114944元，原总额度20元不变。
- 原750条operations及原1202条events逐字段/完整前缀保持一致；本轮只添加新run、绑定、claim、结果与6笔模型attempt等记录，未改写历史行。独立audit确认最终accounting与运行收尾一致、scope及关闭状态的policy SHA符合原pin。
- 策略仅临时改变live_enabled；finally按本轮写入内容条件恢复原关闭版本，原凭据和冻结输入字节不变。没有新增预算scope、修改原输入或变更模型/价格/输出上限。
- 7个确切CID均有removed回执，随后在正确daemon重新扫描本run操作标签为空；cleanup_complete=true且没有model-attempt pending。
- 当前已推送代码f553a3cf，代码闭包SHA `86de1961a9f921b65dc7b1c296f2d7529fa83fbceea8c6b5c55e4039c3b5fbb2`，输入SHA `72c13d1a4c7d50dde071072406f8d4b901e1722771c85421c3b6a3ef358fd7a3`；固定Linux ARM64/Node24.22.0/Pi1.1.0 source/runtime复核一致。

## 执行与证据

只调用一次execute，使用新run_id `pi-v2-real-prefix-20261023-001`、新绝对期限和匹配临时policy的新证据/清单。原关闭策略的诊断清单未重放。生产_provider实际HTTPS调用，观察包装器只记录请求SHA/时间并校验固定顺序，不改写请求/响应，不模拟、不重试；无tools。

[机器记录](pi-v2-real-run-2026-10-23.json)包含实际POST数、canonical新增attempt、各槽脱敏判定、预算变化、恢复/清理结果及执行者/审计/授权/清单/回执SHA。私有请求意图、原始frame/session/usage/attach日志、前后账本快照、原策略备份和清单在当前worktree `.local/pi-v2-real-run-20261023/attempt-001/`；执行脚本、独立audit及日志在其父目录。凭据只留在宿主内存，未写入这些新文件；没有向公开报告写模型正文、引用、凭据、其摘要或账户余额数值。

本轮只做已授权的一次真实试运行与结果分析，未改生产代码，未合并main或部署，报告未自动提交/推送。原始输出、失败、未运行槽及历史unknown全部保留，不自动补齐30槽；未来任何真实请求仍须另行授权并满足现有门禁。
