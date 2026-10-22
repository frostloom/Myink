# Pi 有界 SSE 分块传递验收（2026-10-22）

宿主不再先缓存整个 SSE 响应。生产入口通过 response_start、base64 response_chunk、response_end 帧将字节逐块传给容器；每写完一帧才继续拉取上游，断管或写入超时会关闭惰性 generator 及 HTTP context。两端独立校验 UTF-8、序号、块数、累计字节和结束帧计数，不把 transport end 当作有效 usage 或合同通过。worker 逐块 flush，并以 Connection: close 结束 HTTP；已发头后失败只关连接，不追加第二份 HTTP 错误正文。

## 边界与适用范围

| 边界 | 当前值 |
| --- | --- |
| 单块解码字节 | 16384（16 KiB） |
| 单次 200 的 SSE wire 总量 | 1048576（1 MiB），新设独立传输预算 |
| 单次非 200 / legacy 正文 | 65536（64 KiB），保持原值 |
| 单次块数 | 最多 1024 |
| stdio 后续帧 / 可信首帧 | 196608 / 524288 字节，保持原值 |
| 容器 stdout / 每槽 HTTP 请求 | 1048576 字节 / 4 次，保持原值 |
| session 字节 | 65536，保持原值 |

这明确改变了 200 SSE 的聚合传输上限，未放宽错误正文、文本会话、结果合同、预算或期限。base64 避免 JSON 转义把单帧撑大；UTF-8 可跨块，尾部不完整则拒绝。每次传输仍有硬上限，1 MiB 是本地实现选择，不是 provider 产量证明；单块 16 KiB 的读取也不承诺按单个 SSE event 零延迟转发。已有固定 synthetic probe 可继续发送 legacy bounded status/body 回复。

模型网关与结算逻辑未修改。未取得完整有效 usage 时继续保留全额 unknown 预留并停止后续槽；若 usage 已完整并已知结算，后来合同失败仍保留真实的合成已知计费，不改成 unknown、不退款。末次 relay 状态和字节计数仍只对应末次响应；失败计数饱和于该状态上限加一，清理异常不覆盖首因。

## 验证结果

协议先 RED 21 failed，再协议/原 runtime 63 passed；host/worker 集成先 RED 7 failed / 71 passed，再定向 **120 passed**。测试覆盖真实 stdio 子进程、真实 loopback HTTP、超过 64 KiB 的有效 SSE、两端累计/单块/序号/结束帧限制、UTF-8 跨块/非法/截断、断管后 generator 关闭、头后失败不追加错误、unknown 完整预留以及清理失败保留首因。

最终完整 Pi 离线 **2095 passed、0 skipped、19 deselected**，19 项 pi_lab/pi_live 没有运行，不能算通过。补充“合同失败后 model-attempt 仍为 done、usage_known=true、834 microyuan”的明确断言，相关两项通过；最终全量含该断言。compileall、git diff --check 通过。普通 sandbox 的 compileall 最初无法写 worktree pyc，按既有授权升权重跑成功。

独立审查无 Critical/Important，两个 Minor 建议：已补上述已知计费断言；直接 HTTP close spy 暂未新增，目前由真实断管 generator finally 测试和生产 HTTP context 的 with/finally 路径覆盖。审查者独立运行 21 项协议测试，未运行其两个 loopback 测试；主代理运行全部定向及完整离线检查。

## 实际 Linux Pi 合成验收

固定 Linux ARM64 Node 24.22.0 / Pi 1.1.0、真实隔离容器、生产 provider 函数和实际 worker；仅外部 HTTP wire 替换成 MockTransport。凭据、输入及账本均为独立合成数据。源码闭包 `f687d364dcea0ee11d8fe11df970ca326515944517330054debf837bc37c9a9d`；运行时、controller、worker 摘要及回执承诺见 [机器记录](pi-stream-relay-2026-10-22.json)。

| 场景 | 槽位与计费（仅合成） | 清理 |
| --- | --- | --- |
| 每请求增加 4000 ping（92000 字节）再接完整有效 SSE，start null / delta standard | 2 DONE / 28 NOT_RUN；各 403/403/200/403、新 session、合同有效；两笔 known 共 1668 microyuan | 两容器 exit 0、删除，精确 operation label 为空 |
| 50000 ping，超过 1 MiB | 1 UNCERTAIN / 29 NOT_RUN；仅 1 请求；relay/response_size_limit、1048577 饱和字节、HTTP 200；unknown 完整预留 19384 microyuan | 一容器 exit 137 强制停止后删除，精确 operation label 为空 |

大 SSE 验收脚本末行展示误把 padding 写为 88000，实际 payload 为 23 字节 ping × 4000 = **92000**。原脚本/日志保留，另用 AST 独立核对 yield 常量及循环次数并保存 padding-verification.json；该展示笔误未改变输入、执行、合同或结算结果。首帧仍含 300000 字节合成报告填充。

## 真实状态与后续

本轮 **0 新增真实付费请求**。只读核对原 canonical 账本逻辑摘要、714 operations / 1163 events 和 accounting 与上一回执一致：210 attempts / 202 known / 8 unknown / 0 pending；known 1791431、unknown 预留 16114944、保守余额 **2093625 microyuan（2.093625 元）**。global live=false，历史 unknown 未释放，没有旧槽重发、main 合并或部署。

这证明新的传输实现通过离线与合成 Linux 验收，不能反推上次真实 ValueError 的具体原因。真实 provider usage、账单、合同及 45 项语义质量仍未验收。下一步可按现有余额形成新的单槽只读清单并先做只读 check；本轮不启动付费执行，前次两请求 cap 4.032768 元不可沿用。
