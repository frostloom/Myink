# Pi DeepSeek 计量准备核验（2026-10-22）

本轮完成官方资料复核、现有严格计量回归、原账本只读核对和不可执行的两槽配置草稿。没有真实模型调用，没有运行容器，没有修改运行代码或实际策略。公开机器回执见同名 JSON；`billing_verified=false`、`production_ready=false`、`automatic_execution=false`。

## 来源与计费边界

重新从 DeepSeek 官方 HTTPS 获取三份原始资料，SHA256 与本日配置切换时的来源一致；原文及只读核验脚本保存在 worktree 忽略目录 `.local/pi-provider-readiness-20261022/`。URL、原始字节长度和摘要见机器回执的 `sources`。

- 中文模型价格页仍列 `deepseek-flash`、1M 上下文及人民币每百万 tokens 高峰上界：未命中输入 2、命中输入 0.04、输出 8。按高峰上界预留，不依赖当前时段或缓存命中优惠。
- 官方 Anthropic 兼容页确认端点与模型，但没有明确描述完整响应 usage 的字段及缓存拆分语义，不能仅凭“兼容”认定已通过本项目结算器。
- 缓存页使用 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` 描述输入命中与未命中。不能把这组字段直接当作 Anthropic 的四维计量，也不能断言 Anthropic `input_tokens` 是否已经包含命中输入。
- `cache_write=2` 仍只是宿主选择的全价输入保守上界，没有独立实测的 cache-write 单价。输入上界仍采用提供方上下文容量，非 tokenizer 实测。

当前网关严格要求输入、输出、缓存读取、缓存创建四个计量维度都有数值证据；缺失维度不补零，未知费用保留完整预留。已有 SSE 兼容逻辑只接受同事件数值一致的 `prompt_tokens_details.cached_tokens` 冗余说明；它不供应缺失维度。非流式额外缓存说明仍保守结算为未知。不得为了首轮可执行而放宽这条规则，也不能用合成 fixtures 证明真实 DeepSeek 响应形状。

价格页另列 Search/Fetch 按次收费及未来收费生效日期；本轮仍沿用文本、无工具、固定消息体的分析合同，没有新增这些接口权限。本文并未完成所有可选服务的计费认证。

## 原状态复核与草稿

使用新策略及实际凭据执行 `analysis_preflight.audit`：本地四字段绑定通过。`live_enabled=false`；验证密钥格式及身份不等于在线密钥、账户余额或账单验证。没有打印或持久化密钥及其摘要。

原账本逻辑 SHA 仍为 `17389afd9f04bda966b85b8ffd8ec1e8dacb25d6ab42fa37a363ec79da78d968`，208 次历史请求中 202 已知、6 未知、0 pending。已知估算费用 1.791431 元，未知完整预留 12.082176 元，累计 20 元范围内保守剩余 6.126393 元。这是宿主费用账本的剩余额度，不是提供方账户余额。核验前后 DB/WAL、策略和凭据文件字节相同；只读 SQLite 可能维护 SHM 读标记，不声称所有文件系统元数据不变。

准备的**提案**为首对 baseline/candidate 两槽、费用上限 4.10 元、总期限 240 秒。每次最坏预留 2.016384 元，两次共 4.032768 元，上限余量 0.067232 元。首槽未知时仍须停止，不能把剩余槽位自动补跑。此金额尚未绑定成实际运行，也不变更原累计 20 元范围。

私有 `manifest-draft-private.json` 采用不同于可执行入口的 `pi-analysis-launch-draft-v1` schema，明确 `executable=false`。已固定原账本/策略/凭据位置、scope/policy 身份和本轮复核的既有 Linux 运行闭包。它**不是通过 launcher 的完整 manifest**：真实五组输入和其摘要、审阅证据与其摘要以及绝对 deadline 留空；不把合成输入替换成真实输入，不提前开启 live。当前 source-reviewed 闭包核验不接触 Docker，也没有重新确认 daemon/image 的在线状态。

## 验证与下一执行条件

在当前源码运行以下现有测试：

```text
.venv/bin/python -m pytest ops/pi/tests/test_usage_diagnostics.py ops/pi/tests/test_cache_usage_compatibility.py ops/pi/tests/test_cumulative_usage.py ops/pi/tests/test_analysis_preflight.py ops/pi/tests/test_analysis_launcher.py -q
245 passed in 6.30s
```

没有新增行为，未重复完整离线、业务 Python/Go/web 或设施 CI。最初一次私有脚本因没有项目 PYTHONPATH 而导入失败，未读取真实状态；设置 `PYTHONPATH=.` 后完整核验成功。

下一实际阶段应先准备只采集数值 usage 形状的有界提供方诊断：重新确认当次价格、选定真实输入、费用范围和绝对期限，记录完整 EOF/最终 usage、结算与提供方账单的对应证据；未知就停，保留原始失败。价格资料不能替代响应及账单证据。真实调用前的配置必须重新核对并冻结，本文的草稿不是付费接纳或上线回执。既有宿主 launcher 尚未接入原有异步 usage observer，诊断接线需先离线验证，不能以旧 preview gateway 绕过原账本和新凭据入口。

独立只读审查核对公开文档/机器回执、私有核验脚本/草稿、计量及入口代码、保存的价格文本和245项测试日志：无Critical/Important/Minor问题。审查者未独立认证在线来源、凭据、原账本余额、Docker状态或真实账单，未运行私有核验脚本；这些声明仍以本轮实施方实际回执为依据。
