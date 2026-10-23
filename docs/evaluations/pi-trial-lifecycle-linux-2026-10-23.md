# Pi 期限与中断：真实 Linux 容器合成验收

2026-10-23。接续[离线实现与审阅](pi-trial-lifecycle-2026-10-23.md)，本轮完成8个场景，创建37个真实隔离容器，其中36个启动worker，1个在启动/请求前被中断。37个确切ID均有成功移除回执；独立重新扫描8个operation标签均为空。36次外部模型传输均由本地MockTransport模拟，0真实模型POST、0付费请求。

## 环境与证据边界

- 真实Docker、Linux ARM64、Node v24.22.0、Pi 1.1.0，生产launcher/provider/gateway/stdio relay/worker/verifier及canonical结算函数。容器保留原network=none、uid65534、只读文件系统和资源限制，禁止pull新镜像。原本地daemon与缓存镜像再次核实。
- 新独立source快照的完整代码闭包SHA为 `86de1961a9f921b65dc7b1c296f2d7529fa83fbceea8c6b5c55e4039c3b5fbb2`，固定runtime SHA仍为 `6e169d5462405f59c070365267eec24fddc005a3c141819ba7a1f548a592c528`。当前7个变更生产文件SHA与上一轮2190项通过记录一致；所有场景前后source/runtime校验一致，未复用旧代码闭包。
- 输入、报告、凭据、policy和ledger均独立合成；不读取真实凭据、真实账本或账户余额，不更改真实policy、20元scope及unknown。合成scope的初始化只属于测试夹具，不是允许重置生产额度。外部HTTPS挂载MockTransport，宿主Python TCP仅允许loopback；容器仅通过stdio relay访问宿主网关。
- create/cleanup测试钩子仍调用原始真实Docker方法，只在指定边界触发OS信号；流中信号通过独立宿主进程的真实SIGTERM发送。使用生产signal_scope路径并核实原处理器恢复；不是从外部调用完整argparse CLI的另一层验收。
- monotonic到期场景人为缩短宿主生命周期的monotonic终点，不修改系统时钟。这是明确的故障注入，不是等待真实1800/3600秒到期；完整30槽实跑约322.940秒，也没有进行超过600秒的持续运行验收。本轮结果不能承诺真实模型在相同时间完成。

## 场景结果

每行仍保留30槽分母；容器/调用列为真实创建数/模拟模型传输数。旧pilot原接口只选首对，但首次合同不合格仍按原规则停止。

| 场景 | 容器 / 模拟调用 | 最终槽状态 | 停止原因 |
| --- | ---: | --- | --- |
| 完整30槽：预设3类合同失败 | 30 / 30 | 3 FAILED、27 DONE | 完整完成 |
| SSE流中实际SIGTERM | 1 / 1 | 1 UNCERTAIN、29 NOT_RUN | interrupted |
| 已知结算/清理后实际SIGINT | 1 / 1 | 1 UNCERTAIN、29 NOT_RUN | interrupted |
| 创建后/请求前实际SIGTERM | 1 / 0 | 30 NOT_RUN | interrupted |
| 119秒窗口不足 | 0 / 0 | 30 NOT_RUN | insufficient_slot_window |
| 流中monotonic到期注入 | 1 / 1 | 1 UNCERTAIN、29 NOT_RUN | deadline_exceeded |
| 普通失败后未知费用 | 2 / 2 | 1 FAILED、1 UNCERTAIN、28 NOT_RUN | execution_failed |
| 旧pilot严格停止 | 1 / 1 | 1 UNCERTAIN、29 NOT_RUN | 旧入口无新字段 |

完整30槽使用显式1800秒清单，27 DONE/3 FAILED；30个不同session的HTTP负控/实际/重放顺序均为403/403/200/403，全部正常退出后删除。预设普通目标域、JSON和schema失败被保留后继续，没有修复或重放输出。

实际SIGTERM流中中断后约2.050秒返回；已知费用后的SIGINT约1.088秒；请求前SIGTERM约0.866秒。时钟故障注入后约3.122秒返回。这些为本次环境的观测值，均不是未来延迟保证。信号/到期后未出现下一槽请求，当前未完成claim保持UNCERTAIN，未claim保持NOT_RUN。

合计33笔known、3笔terminal unknown，无pending。known每笔合成usage输入17/输出100，对应834 microyuan；unknown按合成策略的1000输入上界完整预留19384 microyuan。这些是模拟计量，**不是提供方真实账单或真实输入上界证明**。已知费用后的中断保留known结算834，不把槽结果追认DONE；未知费用保持原预留不释放。v2各场景cleanup_complete=true，表示该场景容器清空且结算终结；不表示unknown已经核实。

## 独立复核与交付

主验收脚本8场景全部断言通过、exit0。独立audit逐项核对最终receipt与私有验收回执相同、SHA相符、所有created ID都有removed记录、8个operation标签重新扫描为空、37个CID互异、36份attach日志、33 known/3 unknown及源码闭包未变化。[机器记录](pi-trial-lifecycle-linux-2026-10-23.json)保留脱敏结果、来源与脚本/回执摘要。

私有源码快照、合成配置、原始session/frame/usage/attach日志与回执位于当前worktree `.local/pi-lifecycle-linux-20261023/attempt-001/`；主日志为 `.local/pi-lifecycle-linux-20261023/attempt-001.log`，audit为同目录 `audit.py/audit.log`。未覆盖任何历史尝试、输入或证据。

本轮没有生产代码变化，不重复上一轮2190项离线回归；本轮新增的是实际Linux集成验收证据。git diff --check及文档/机器记录一致性核查作为交付检查。本轮未提交、推送、合main或部署。

[输入token校准](pi-token-calibration-2026-10-23.md)仍未证明可替换1M策略的提供方上界，因此完整付费对照仍未就绪，也没有获得本轮真实执行授权。若以后真实执行，必须重新冻结当时的源码、真实输入、价格/输入证据、预算与新绝对deadline；本轮合成清单不能用于真实模型。
