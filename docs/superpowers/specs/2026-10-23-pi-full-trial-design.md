# Pi 完整对照模式

用户已确认：开发独立完整对照模式，已确认费用、身份与清理正常的普通输出合同失败记录后继续，未知费用或协议异常停止；本轮仅离线实现与测试。

沿用 Python3.12、现有30槽顺序、输入/提示/源码/运行时哈希、累计scope和原子预算，不增加依赖。以独立清单 schema `pi-analysis-trial-v1` 和固定 `failure_policy=continue_known_contract_failure` 显式选择全部30槽；旧v1/v2 pilot接口及严格停止语义保留。禁止任意选槽、恢复、重试或重置run。

宿主独立验证引擎完成、无错误/工具/中断、请求身份、会话原始字节及SHA、唯一session、固定运行时、HTTP负控/实际/重放403/403/200/403、唯一已知结算和精确容器清理后，重新解析原始assistant文本并使用原validator/scorer。基础JSON/schema无效为output_invalid，目标域无效为target_scope_invalid；保留原frame/session，不修复输出。worker报告与宿主重算不一致属于协议异常。仅这些普通输出失败可finish failed；其余错误保持UNCERTAIN/blocked并停止后续。

全量执行完成只表示30槽都有确定结果，不表示合同全部通过、语义质量提升或发布。公开汇总列planned=30、DONE/FAILED/UNCERTAIN/BLOCKED/NOT_RUN，并按arm/domain保留全部分母。所有提前停止仍保留30槽，已知费用照常计费，unknown不释放。check默认只读，真实请求仍需另行冻结预算、期限、证据与授权。本轮不用真实凭据、输入、账本或Docker；不提交、推送、合main、部署。

验证：真实SQLite/loopback/stdio子进程，仅Docker/provider外部边界模拟；覆盖全部30槽、失败后继续、旧pilot仍停止、未知费用、会话/身份/源码漂移、重复session、清理失败、过期与低预算、重放、只读check、汇总分母与脱敏。
