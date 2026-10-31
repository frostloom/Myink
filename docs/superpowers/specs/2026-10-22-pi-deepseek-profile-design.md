# Pi DeepSeek 配置切换

用户明确要求复用CC-Switch中DeepSeek配置的密钥，后续Pi模型为deepseek-flash。继续原Pi worktree/分支，自主完成并提交推送，不确认问题。

宿主只读读取CC-Switch SQLite中唯一Pi/DeepSeek记录，验证官方端点、协议、deepseek-flash模型与字面量密钥；不执行CC-Switch配置命令，不更改其当前provider。密钥只进入原宿主私有credentials/platform-model.json，目录0700/文件0600、原子替换；原密钥备份也只在该私有目录，禁止日志、Git、Hindsight或Pi容器包含密钥。宿主网关复用同一严格凭据绑定校验，预检可显式提供credential-file只核对本地绑定，不请求provider。

新增本机state/policy.json使用deepseek-flash、官方Anthropic兼容端点，原fee-only20元预算不变；原冻结policy/源/ledger不改。已有分析执行允许原历史模型和新模型，默认新注册为deepseek-flash，逐槽仍冻结模型、拒绝漂移；历史模型仅供既有冻结工件及离线回归。

复核当日DeepSeek官方价格、Anthropic兼容及上下文缓存文档，保存原始来源及SHA。策略使用峰值CNY费率、1M输入保守上界和2048输出，cache_write按全价输入保守上界，不猜缺失usage为0。真实上游usage、付费容器入口和明确本轮cap/deadline仍需后续验收，当前live_enabled=false；配置切换不授予新的支出权限。

离线验证用合成密钥/temp SQLite覆盖错误/重复provider、命令/环境引用、官方端点漂移、header注入、只读DB、不输出密钥、credential/policy模型/端点/协议匹配、预检绝不启动HTTP。验证新的30槽配置与模型漂移拒绝；相关与完整Pi离线回归。真实操作只保存不含密钥的比较布尔值和无正文账本回执。可复用新源码快照运行真实容器内Pi+MockTransport，不接触真实provider或账本。
