# Pi 显式单槽与真实输入只读预检（2026-10-22）

已补齐显式单槽入口，并以原真实输入、原禁用策略和原账本通过默认只读 check；**本轮 0 真实模型请求、0 费用预留，没有 execute 或开启 live**。这是准备记录，不是实际 provider、usage、账单或写作质量验收。

## 清单与预算

旧 `pi-analysis-launch-v1` 的封闭字段和两槽行为不变。新 `pi-analysis-launch-v2` 必须增加 `selected_slots`，只接受精确整数 1 或 2（排除 bool/float/string/null）；额外字段和 v1 偷带该字段均拒绝。首帧校验、check 所报告选择数及执行循环共用同一选择函数，只运行既有冻结序列的前 N 槽；完整 config hash 绑定 schema/选择。仍注册 30 槽，不新增恢复、重试或跳过前槽能力。

本次选择首槽 baseline，只用于传输/usage 诊断，不构成 baseline/candidate 质量对照。拟定 cap 为 **2016384 microyuan（2.016384 元）**，等于当前冻结策略的单次完整预留；保守余额 2093625 microyuan 足够覆盖，整笔变为 unknown 后仍会保留 **77241 microyuan（0.077241 元）**。没有降低 input bound、缩减原输入、释放历史 unknown 或用预算不足来伪装单槽选择。

## 默认 check 的实际结果

- 检查完成时间：`2026-10-22T10:30:18.593607+00:00`（北京时间 2026-10-22 18:30:18）。
- 当次绝对 deadline：`2026-10-22T10:34:14.562232+00:00`（北京时间 2026-10-22 18:34:14）；清单期限为 240 秒，原清单过期后不可重放。
- schema=v2、planned_slots=30、selected_slots=1、首槽 `r1:recall.events:baseline`；status=checked、launch_ready=false。
- 绑定完整五组 view/原报告，私有输入文件 496153 字节，选中首帧 354925 字节；源文件身份、冻结 slot/system/request 指纹均校验，未上传写作内容。
- 绑定已验收源码闭包 `295e2affc415c29a488128442a206611929613bdf3e0d47f4288b02b015766a7`、固定 Linux runtime、原 scope/policy 及公开来源证据；凭据只在宿主本地加载，不输出、不记录其摘要。
- 默认 check 中禁止构造 Ledger writer、调用 provider 或 create 容器的探针未触发，cases/cleanup 为空，结果根目录未创建。另行只读核对了本地 daemon 和缓存 image 身份，共两条 Docker 查询，真实输入容器数 0。
- 前后 audit 完整相同，原 DB/WAL、policy、credential、原 manifest/report 字节不变；私有配置草稿和 executable=false recipe 单独保留。

这份检查会随 deadline 到期而失效；不能据此声称之后任意时刻已就绪或获准支出。真实执行前须重新核对账本、价格/输入/来源、明确执行授权并生成新绝对期限；全局策略在本轮始终 live=false。

## 公开价格复核

重新无认证获取官方 pricing、Anthropic compatibility、cache 三页，保留有界原始字节、获取时间和 SHA；没有向其发送凭据或私有正文。价格页本次列出的 Flash 版本为 DeepSeek-V4.1-Flash-1017、上下文 1M，并有峰谷费率：峰值每百万 input/output/cache-read 为 2 / 8 / 0.04 元，空闲时段为 1 / 4 / 0.02 元。现有 policy 保留峰值作为保守预算上界，不按当前空闲时段重写 policy 或减少预留；cache-creation 的 2 元仍为原策略保守声明，不是新获证实的 provider 计量语义。

原兼容页本次仍不足以独立证明四维 usage 和实际账单语义。冻结数字可支持预算检查，不是实际扣费证明。来源地址、抓取摘要、独立价格复核和清单证据见 [机器记录](pi-single-slot-2026-10-22.json)。

## 实现验证

17 项新增测试先 RED：6 failed / 11 passed；实现后所有 launcher **72 passed**。完整 Pi 离线 **2112 passed、0 skipped、19 deselected**，未选入的 pi_lab/pi_live 不算通过。独立审查无 Critical/Important，独立运行 launcher 72 passed；一项 Minor CLI 仍称 two-slot，已更正文案。全量后仅改该 docstring；新完整源码闭包随后再跑实际 Linux 单槽、检查 CLI help、compileall 和 diff-check。

测试明确证明：单槽成功即使还有合成预算也不尝试第二槽；unknown 保留完整预留且 29 槽未运行；v2 非法/缺失选择在 writer 前拒绝；禁用策略不执行；选择改变 config hash。旧 v1 两槽回归继续通过，原已知结算与清理首因逻辑不改。

固定 Linux ARM64 Node24.22.0/Pi1.1.0、新源码快照、生产 provider 函数、仅外部 HTTP MockTransport：合成大报告首帧加 92000 字节 SSE ping 开销后，只有 1 请求、1 容器、1 DONE/29 NOT_RUN，HTTP 403/403/200/403、合同和 session 有效，known 合成 834 microyuan；容器 exit0 删除、精确标签为空，无第二槽诊断文件。修正文案前的合成验收证据保留，未覆盖。

## 未改变的真实状态

210 attempts / 202 known / 8 unknown / 0 pending；known 1791431、unknown 完整预留 16114944、保守余额 **2093625 microyuan**。714 operations / 1163 events 的完整逻辑摘要未变。没有真实预留或费用、旧槽重发、unknown 释放、main 合并或部署。上次真实 ValueError 的具体原因仍未知；真实 provider 合同/usage/账单及 45 项语义质量仍未验收。
