# Pi 切换 CC-Switch DeepSeek（2026-10-22）

已按用户要求，使用CC-Switch中唯一Pi/DeepSeek配置的字面量密钥，后续默认模型为`deepseek-flash`。实际比较确认Pi与Claude的DeepSeek条目原先使用同一密钥；导入选择Pi条目，不修改CC-Switch的当前provider或数据库。宿主继续使用既有Anthropic预算网关，通过`https://api.deepseek.com/anthropic`调用；不增加OpenAI协议转换层，也不把上游密钥交给Pi容器。

## 实际私有配置

原私有根`/Users/a1/项目/Myink/myink-pi`中，`state/credentials/platform-model.json`已原子替换为CC-Switch密钥及新的模型/端点/协议四字段。凭据目录0700、文件0600，旧文件备份仅保存在相同私有凭据目录，未进入Git、日志或记忆。复读比较密钥相等，只保存布尔值，未输出密钥或其摘要。

新增当前策略为`state/policy.json`，与凭据字段匹配；历史冻结`evidence/c20/.../source/policy.json`保持原样。宿主启动/后续预检必须显式选择新策略，旧试验与旧策略不能偷偷改模型。新policy保持fee-only累计20元、max_attempts=null、单次max_tokens2048和max_body_bytes65536，`live_enabled=false`。这是已准备好的宿主配置，未启动付费gateway。原daemon、Node/Pi固定依赖未升级。

`ops.pi.provider_config`提供只读CC-Switch提取与统一凭据绑定校验；只读预检新增可选`--credential-file`，在网络前核对完整四字段、字面量key及model/baseURL/protocol。不提供时`credentials_checked=false`。该字段只表示本地身份/格式核对，并非在线密钥可用或余额证明；回执仍`paid_admission=false`。

新分析注册/默认容器模型为`deepseek-flash`。原`deepseek-v4.1-flash`仅保留显式历史冻结兼容；模型进入冻结hash，改同一槽的模型仍拒绝。两种模型/两套provider的试验结果不能混成同一个只改提示词的对照。公开policy.example已同步新端点/模型和保守价格，默认live仍关闭，输入校准仍未启用。

## 当日公开来源

原始HTML/文本与manifest保存在私有`evidence/deepseek-profile-2026-10-22/official/`，不含任何密钥：

- DeepSeek中文价格/上下文页：`https://api-docs.deepseek.com/zh-cn/quick_start/pricing/`，SHA256 `556097caba8adfeeed6455714bffd731c7f60db520fcee06a922eba5840663a3`。
- 官方Anthropic兼容页：`https://api-docs.deepseek.com/guides/anthropic_api`，SHA256 `19b5e723f1c65f609c010999cdf3cc1929327c4369c54b0151e8ea82dc3dd033`。
- 官方缓存说明：`https://api-docs.deepseek.com/zh-cn/guides/kv_cache`，SHA256 `4c300649c617f75d8c4c2c23e88c9f0e310912c999da6671464622a609a328c0`。

核对资料列有`deepseek-flash`及1M上下文；策略冻结峰值人民币/百万tokens：输入2、输出8、缓存命中0.04。cache_write使用全价输入2的保守上界，不能解释为提供方单列的cache-write实测价格。输入采用提供方上下文容量1M的保守上界，并保留text-only/64KiB正文限制；不是实测tokenizer校准。策略flag表示宿主选定的保守容量界，不代表真实usage/计费已通过。原单次最大输出保守预留仍2.016384元；余额不是provider账户余额。未来真实发送前仍需核对价格是否变化。

当前只读预检已核对新policy/凭据，规范化policy SHA256 `c090c2f849813e68b234d9f272d45e65108467cfa6230754fa76ac11e4fcb799`。原账本逻辑SHA保持`17389afd9f04bda966b85b8ffd8ec1e8dacb25d6ab42fa37a363ec79da78d968`；DB/WAL字节未变，仍208次、202已知/6未知/0pending，保守余额6.126393元。六项历史未知预留未释放。

## 验证

新增23项合成密钥/temp SQLite测试先RED后GREEN。定向405 passed；完整Pi离线1947 passed、0 skipped、19项pi_lab/pi_live未选入（80.15秒），compileall与diff-check通过。初次编辑误匹配造成的预检语法错误已在定向检查中定位并修正，未用于实际私有配置写入。

新闭包源码及既有Linux依赖运行真实隔离Pi，actual001操作`4ef34cf1-3aea-45ee-a9cf-c500421096f6`：两臂各一个新会话，固定模型`deepseek-flash`，原合同及宿主重评分有效，Pi退出0。每槽HTTP状态`403/403/200/403`对应错token/请求漂移/唯一允许请求/重放。仅MockTransport提供合成答复，30槽为2 DONE/28 NOT_RUN；两个容器均退出0并删除，额外精确label的ps为空。闭包hash及无正文结果见同名JSON。

独立审查待完成。本轮未调用真实DeepSeek模型、未在线验证密钥或provider账单；`billing_verified=false`、`production_ready=false`、`automatic_execution=false`。未运行业务Python/Go/web或设施CI。45项语义质量仍unknown；真实提供方usage字段适配不能用缺字段自动补0。

下一阶段接入已固定的新provider/policy身份、本轮明确费用上限/绝对期限与原账本原子预留、可信容器生命周期。当前预检、配置切换与合成容器验收均不能作为付费启动授权。原main未合并或部署。
