# Pi 标准层级兼容与有界失败诊断（2026-10-22）

本轮仅离线开发和合成验收，0 真实付费请求。SSE usage 的 `service_tier` 现在接受 `null` 或精确字符串 `standard`，其余数字计费维度仍严格验证；priority、batch、错误类型、未知字段、缺失或截断用量仍保留完整 unknown 预留，不套用标准价。非流式结算未变。

官方 Anthropic Python SDK 的 usage schema 将 service_tier 定义为可空的 standard/priority/batch；本实现只接纳当前冻结价格所覆盖的标准层级。参考：https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/main/src/anthropic/types/usage.py 。这不证明 DeepSeek 真实 usage 或账单语义已验收。

启动器新增有限 `failure_detail`：slot_index、stage、reason、response_bytes、http_status；可区分 relay 超限、无效 UTF-8、合同验证及未知用量。字节数饱和于 65537，`failure_detail` 不保存响应正文、异常消息或 traceback；既有私有证据文件保持原来的边界。response_bytes/http_status 指最后一次 relay 响应；后续合同/结算阶段失败时可能对应 replay 的 403，不能一律当成模型的 200。清理/reconcile 失败继续阻止执行，且不会覆盖首个异常及诊断；清理结果仍单独记录。

HTTP 正文 64 KiB、后续帧 192 KiB、可信首帧 512 KiB、期限与预算边界保持原值，不重试、不释放历史 unknown。合成的多个小 SSE ping 可触发正文聚合上限；这只证明一种离线机制，**上次真实 ValueError 的具体原因仍未知**。历史真实记录保持原样，见 [真实诊断](pi-live-encoding-2026-10-22.md)。

## 验证

- 初始 TDD：10 failed / 13 passed；首轮定向回归 172 passed。完整回归随后暴露两项旧测试仍把 null tier 视为无效，已更新为 priority，保留拒绝非标准层级的覆盖。
- 独立审查发现 1 项 Important：清理故障覆盖首因。overflow/UTF-8 × remove/reconcile/slot 的组合测试先 6 failed / 2 passed，修复后 8 passed。首次修复回归另有两项测试错误要求故意注入 stop 失败后仍删除容器，已校正为明确保留 removed=false；生产停止与计费行为不变。复审无未解决 Critical/Important。
- 最终定向 185 passed；完整 Pi 离线 **2071 passed、0 skipped、19 deselected**。19 项属于未选入的 pi_lab/pi_live，不能当作通过。compileall、git diff --check 通过。
- 修复后独立源码闭包运行固定 Linux ARM64 Node 24.22.0/Pi 1.1.0，生产 provider 函数仅外部 HTTP wire 换为 MockTransport；合成输入/临时账本，不读取真实凭据或私有写作。首帧含 300000 字节合成报告填充。

| 场景 | 结果 | 计费（仅合成） | 清理 |
| --- | --- | --- | --- |
| start null / delta standard | 2 DONE / 28 NOT_RUN；两个新 session，各 403/403/200/403，合同有效 | 两笔已知，共 1668 microyuan | 两容器 exit 0、删除、精确标签为空 |
| 4000 个小 SSE ping 聚合超限 | 1 UNCERTAIN / 29 NOT_RUN；1 请求，relay/response_size_limit，65537 字节、HTTP 200 | 完整保留 19384 microyuan | 一容器 exit 137 强制停止、删除、精确标签为空 |

合成验收的生产代码闭包为 `69e0e884938cb90300a8dad03d6fac83e3d0079402e386fba214994d40b31e49`。运行身份、容器清理及私有回执 SHA 见 [机器记录](pi-stage-tier-2026-10-22.json)；运行时依赖与历史验收证据未覆盖改写。

## 真实账务边界

只读核对与上一真实回执的完整逻辑账本摘要和 accounting 一致：210 attempts / 202 known / 8 unknown / 0 pending，known 1791431、unknown 完整预留 16114944、保守余额 **2093625 microyuan（2.093625 元）**。714 operations、1163 events 未变；全局 live=false。没有释放历史预留、重新发送旧槽、开启新真实清单、合并 main 或部署。真实合同/usage/账单及 45 项语义质量仍未验收。

下一步继续离线设计和验证 SSE 的有界传递方式，避免把协议事件开销与有效模型文本混作同一容量假设；形成具体方案和针对性测试后再开发。任何新的真实运行仍需独立冻结输入、价格证据、预算和绝对期限，当前剩余额度不足以沿用前次 4.032768 元的两请求清单。
