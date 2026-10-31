# Pi硬读取与完成预算

用户已确认继续此方向并授权自主常规决策。使用既有Pi工作树，只改开发控制器与针对性测试/说明，不动产品、原财务政策或付费账本，不提交推送。本轮先离线与真实LinuxSDK MOCK验收，不重放失败身份。

- [x] RED/Green：ControlledTools增加仅宿主可设的source_read_limits=(4096,12288)，以canonical ASCII JSON文本字节限制单次和本次绑定的累计成功读取；在现有跨进程锁内由durable receipt核算，跨文件/重复新call/重建broker/补丁均不清零，同call重读不重复计数（幂等旧回执原样返回，仍消耗RPC）。超额为可认证有界blocked反馈，无源码泄漏，默认未启用时其他入口兼容。
- [x] RED/Green：开发Limits启用8RPC收尾保留，工具与verify共用原总额；剩10RPC或更少时进入只收尾模式。首次进入时若尚有恰10RPC，首个新read_source返回一次可认证blocked反馈并剩8RPC；不足10或继续读取立即停止，不侵占这批保留。允许status(2)、patch且还够unit+status(6)、unit(4)、最终status(2)路径，仍需原真实完成协议，绝不宿主代跑或伪造成功。拒绝lint/contract冒占收尾路径。静态prepare要求max_tools>=12，启动提示说明真实计数及ASCII读取限制。
- [x] 相关Pi tests与完整离线、Node协议边界、独立最终审查，冻结当前runtime做LinuxPi/SDK MOCK的预算拒绝反馈→小段读取→patch→unit→status认证，并核对清理。
- [x] 核对原账本/关闭策略/凭据摘要、产品及无关脏文件不变；保存验收报告/readiness/本机Myink记忆。未跑的真实付费有效性明确保留。

根因证据：001单读UTF8上限未防67780 ASCII超限；002 10读333行后14逻辑调用/28含认证RPC耗尽。固定12KiB累计是保守的本次运行预算，不宣称足以解决全部复杂任务；4096是文本JSON片段预算，完整消息仍受原64KiB保护。收尾保留提供有效路径的额度，不保证模型正确调用、修复成功或拥有足够剩余时间/模型请求；重复无效请求仍会安全停止。

完整首跑旧analysis流溢出组3失败，时间上限先于聚合上限；修改前/tmp副本同case也失败，当前串行可过。独立审查同意仅将该压力夹具50000个合法ping精确按64条分块（最后16），保留1150000字节、多块、同1MiB+1／unknown保留／cleanup断言，所有生产限额和时限不变；极小块另有relay_stream覆盖。先跑全部8参数再完整重跑，旧失败和中断证据保留。

验收记录：docs/evaluations/pi-read-completion-budget-2026-10-26.md。记忆服务若超时只记录结果未知，不伪称已保存。
