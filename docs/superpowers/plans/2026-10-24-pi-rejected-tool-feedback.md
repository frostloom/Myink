# 受控补丁参数错误的认证反馈

问题已在首次来访真实001/002/003复现：Pi SDK在扩展execute之前用嵌套schema拒绝模型坏参数，生成本地字符串错误，没有宿主工具回执；下一模型请求的历史再次被gateway按schema拒绝，于是模型永远拿不到修正机会。三轮21次真实调用108352微元，无新增未知；003仅有效加入Character导入，均未采纳。停止新增付费任务，先完成本前置条件。

不改变模型可见严格schema，也不改变ControlledTools执行schema、来源哈希、范围、独立审批、费用/时间/调用上限或终态认证。不切换模型/提供方/endpoint，不重放旧会话。DeepSeek文档的strict Beta需要不同API格式及schema投影，当前Anthropic路径没有已验证的原生强制保证；不用未经验证的strict开关代替宿主校验。

最小调整：仅develop的apply_patch在Pi本地注册object外壳参数，使其嵌套坏参数也能送到宿主。before_provider_request仍从冻结完整tool-schemas.json恢复相同严格模型schema；wire guard只额外接受这一固定本地壳及SDK去掉additionalProperties的固定投影，不能接受任意schema。宿主ControlledTools维持原完整校验和拒绝，并持久记录绑定call ID/input_hash/session/base/Plan的blocked receipt；不修复、不删字段、不执行错误参数。

模型gateway默认仍严格拒绝畸形历史。仅development入口通过可信Python参数传broker.lookup；历史畸形apply_patch参数可继续的必要条件为：原始tool_use与单个is_error=true的tool_result完全配对；结果是严格JSON单text块或SDK等价展平的文本字符串（普通本地错误字符串无法解析/认证）、receipt完整schema_version=1/status=blocked；reason为宿主schema拒绝有限枚举；当前broker.lookup以同call ID/name/原始args/完整receipt查得当前会话真实记录。无lookup、错误/伪造/重复/成功/uncertain/其他原因/外会话/失配/坏JSON均拒绝。只允许作为未执行失败的历史，下一次实际工具调用仍完整校验。最终必须有真实成功补丁、unit PASS、status及退出认证。

验证：先新增RED。真实broker拒绝额外/遗漏/错误类型参数且源码不变；合法认证失败历史可发送下一模型请求，畸形/伪造/无lookup等不得计费；新JSON壳出站仍恢复完整严格schema。Node扩展执行模拟将坏args原样送host，不在SDK端吞回执；合成真正Linux Pi跑坏patch→宿主blocked反馈→正确patch→unit→status完整链，精确账本/退出/清理/关闭证据，不调用真实提供方。独立审查、相关及完整Pi离线回归后，才新建真实首次来访任务继续100测试。

- [x] 独立设计审查，确认无执行/历史认证降级。
- [x] Python/Node RED→最小实现→focused GREEN。
- [x] 全Pi离线及真实Linux合成协议验收；所有owned容器清理。
- [x] Fresh独立审查与冻结runtime；新真实任务不复用终止会话。

文档来源：[DeepSeek Tool Calls strict说明](https://api-docs.deepseek.com/guides/tool_calls/)。本机Pi1.1.0真实失败请求确认正常tool_result.content也是字符串，所以同时接受一段严格JSON文本及单text块；两者均必须完整严格receipt并通过当前lookup。SDK normalizeOptionalNulls/Value.Convert/coerceWithJsonSchema确实在execute前运行，必须在真Linux合成验证固定object壳不会转换嵌套坏参数。

实测：新Python反例63项通过；完整Pi离线2337通过/19未选，101.74秒。Node原有与新增边界脚本全通过。实际Linux合成13次mock、三类坏参数原样绑定host blocked且源码不变，随后5次实际补丁、10项unit PASS、status/退出认证verified；两个owned容器removed，假策略恢复关闭，独立假账本历史保留。模拟计量不加入真实费用。代码与新冻结runtime一致，fresh rejected_tool_feedback_review已只读核对实际工具账本、最终check/status与回执，前置条件完成；独立first_visit_scope_review另外批准全新004实际任务。
