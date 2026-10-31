# Pi 真实单槽验收（2026-10-22）

用户对“向 DeepSeek Flash 发送真实输入、只运行首个 baseline 槽、cap 2.016384 元、失败停止不重试”的具体方案回复“做吧”，本次据此执行。**实际 1 次上游请求、HTTP 200，SSE 和完整 usage 解析通过；基础 JSON/引用校验通过，但冻结的目标领域合同未通过，整体仍 blocked。** 本次没有继续第二槽或重试。

## 执行边界

- 开始准备：`2026-10-22T10:43:51.101773+00:00`；新绝对 deadline：`2026-10-22T10:48:02.381487+00:00`，240 秒、cap 2016384 microyuan。原过期 check 未重放。
- v2 selected_slots=1，首槽 `r1:recall.events:baseline`；原五组输入/报告、原累计 20 元账本、scope、最终源码 `fac756b` 对应闭包及 Linux runtime/本地 daemon/image 重新核对。
- 三份官方价格/兼容/cache 原始资料重新无认证 GET，其字节 SHA 与上次审阅相同；沿用峰值费率作保守上界。原私有凭据与 CC-Switch Pi/DeepSeek 配置仅在内存中比较相等，无密钥或其摘要落盘。
- 原全局 policy 始终 live=false，仅本轮独立 policy 的 live_enabled=true，其他字段不变。未启动长期服务，未改 CC-Switch、原输入或全局配置。
- canonical tools lock 内先做一致 SQLite 备份与余额 GET，再冻结新清单；默认只读 check=checked/launch_ready=true、selected_slots=1、结果目录未创建，然后仅调用一次 production launcher execute。
- production provider 外层只观察并限制最多 1 次 HTTP initiation；无 MockTransport、自动重试、重定向、fallback 或历史请求重发。

## 通过与未通过的部分

本轮取得完整结果帧和新 Pi 会话，engine_status=done、进程 exit0；会话原始字节摘要、单条纯文本 assistant 的 stop 状态、输出与会话一致性，以及固定 Linux Node24.22.0/Pi1.1.0/非 root/无网络边界均离线复核通过。没有工具调用。

基础 `validate_writing_analysis`（11 领域、严格 JSON、引用与假设等规则）通过。目标 `recall.events` 的进一步规则要求其他领域全部 unknown 且无引用；实际 `recall.facts` 为 trace_observation/1 引用、`operations` 为 trace_observation/0 引用，故 `score_contract_output` 离线稳定抛出 `non-target domain must stay unknown`。worker 返回 contract_valid=false/failure=target_scope_invalid；宿主 `verify_result` 因该 flag 在首个联合检查抛 `invalid engine evidence`。本次已定位到 `result_verify`，不是传输或 usage 拒绝。

该槽是历史共享 prompt 的 baseline，对各领域作评价在旧 prompt 下有可能发生；这份结果保留为冻结目标规则下的不通过样本，不修改 prompt、评分规则或历史结果来使其通过，也不能据此推断尚未运行的 candidate 更好。此次原因不追认此前没有完整结果证据的历史 ValueError。

整体 status=blocked、1 UNCERTAIN/29 NOT_RUN。这里 UNCERTAIN 是分析槽未被完整接纳；该次 model-attempt 同时是 done/usage_known=true，二者处于不同层级。完整生产链路仍未验收，45 项语义质量和 baseline/candidate 对照尚未完成。

失败详情的 response_bytes=349/http_status=403 是最后一条宿主 relay 响应的进度字段，不是整段 SSE 字节数或上游请求状态；真实上游状态为 200。

## 用量与费用

完整 message_start/message_delta/message_stop 被解析，service_tier 已兼容：input=137、output=688、cache_read=6400、cache_creation=0。冻结峰值 input/output/cache-read/cache-write 费率按每百万 2/8/0.04/2 元保守核算：137×2 + 688×8 + 6400×0.04 + 0×2 = **6034 microyuan（0.006034 元）**，不是本次 cap 2.016384 元，也不是 provider 实际账单证明。

model-attempt 已知结算，无新 unknown。累计 **211 attempts / 203 known / 8 unknown / 0 pending**；known 1797465、历史 unknown 完整预留 16114944、保守已用 17912409、余额 **2087591 microyuan（2.087591 元）**。原 714 operations 逐字段不变，原 1163 events 为相同完整前缀；仅追加 36 operations / 39 events，历史 unknown 未释放。

前后官方只读余额 GET 均 200，可见 CNY 余额差 0.00 元。账户显示精度、入账延迟或并行用量均未排除，不能把该差额当成请求账单或“免费”；actual_spent_microyuan=null、billing_verified=false，四维 usage 的实际计费语义仍未独立核账。

## 清理、验证与后续

唯一所属容器 exit0 并删除，精确 operation 标签查询为空，无第二槽诊断。原 global policy、credential、原 manifest/report 字节不变。公开数字、来源与 25 份私有证据摘要见[机器记录](pi-live-single-slot-2026-10-22.json)，不公开写作正文、密钥、header 或私有 request/attempt 身份。

本轮未改生产代码，未重跑此前 2112 项离线回归；本轮实际运行的是只读预检、一次真实执行、离线会话/合同/用量复核及账本历史保持与清理核对。准备脚本曾在启动标记创建前误用 Path.open 的 opener 参数，修正为内建 open 并验证 0600 后才开始本轮；该准备错误没有模型请求或账本写入。

本次单槽授权已消耗，停止付费运行，不恢复/重发该槽。下一步先离线记录 baseline 违反目标约束的表现，核对 candidate 的目标约束设计和评分口径；如需真实 candidate 对照，须另行明确其选择、cap 和期限。未合并 main、部署或发布。

独立只读复审完成：0 Critical / 0 Important / 0 Minor。范围为四份公开文档、相关生产验证/结算逻辑，以及两份指定脱敏私有摘要及其摘要值；未独立检查其余私有证据、原会话或运行实况，未运行回归、网络或 Docker。
