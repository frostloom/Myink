# 真实Pi分析与开发接力

用户已明确继续既有真实付费/私有数据外发/自主常规决策方向，无需再次确认。复用Pi分支，不提交推送合并部署，不启用服务器。技术选择由主代理决定：先从一个已复现的既有产品缺陷开始，用既有单轮协调API连接真实无工具Pi分析、宿主冻结与独立审查、真实Pi开发；不声称任意任务自主发现或发布能力。

## 组件

新增selection_launcher.py负责严格只读预检及有限分析执行：固定schema配置，冻结目录/source/runtime/原费用账本/关闭策略/凭据摘要/具体独立审查/owned Docker daemon和image。新私有root、费用锁及二次验证。只允许1次模型HTTP，最多120秒，受协调器共享取消和绝对期限约束。不建立新预算，复用原累计账本和PolicyLease，结果保留每次原账本快照、关闭恢复、旧历史保持及拥有容器清理；未知或缺少费用审计保持uncertain，不重放。

新增workers/selection.py，仅使用固定PiAdapter、纯文本no-tools配置及loopback模型中继，fresh analysis session。容器无外网/真实密钥/费用账本/Docker socket，不挂载候选源；模型只见有界目录。复用现有development_launcher._exchange，经固定worker枚举选择新worker，默认development.py行为不变。中继只允许认证模型端点，tools/verify路径一律拒绝，forward_messages tool_allowlist=()，1请求后拒绝任何续接，不自动重试/压缩。

宿主读取停止后session/RPC/receipt，核对源码冻结、fresh会话/cwd、准确prompt及context_hash、唯一纯文本assistant/stop、严格JSON proposal、无工具、会话摘要与RPC对应、prompt started和clear/abort确认、进程退出0及容器实测隔离/停止。不能仅信模型文字或worker自报verified。分析返回四字段proposal由maintenance_handoff._selection再次约束。

新增maintenance_adapters.py：SelectionAdapter固定分析配置与上下文目录/source身份一致后执行上述入口，只有完整认证/费用已知/策略关闭/清理完毕才返回绑定当前stage的ACTUAL Receipt；坏输出已知费用为blocked、未知为uncertain。FrozenDevelopmentAdapter只从宿主task_id→私有模板路径与摘要映射读取；模型不能控制路径。校验模板source/test/cases/files/baseline.reproduction，刷新仅原账本最新检查点与缩短的deadline_seconds；Plan和运行身份、范围、策略/凭据/来源不变。调用可信独立review适配器取得绑定新授权的review文件，更新review_sha256，重新完整development_inputs.prepare，返回config_path/file SHA。审查不能由模型自批。

真实交接演练中，review适配器在私有目录写出具体授权草案并有界等待外部独立审查记录；主代理可调度独立静态审查并按实际批准写记录，这不需要用户常规确认。等待协作响应cancel/deadline，缺少批准即停止，不用占位成功或旧批准。此入口不把审批文本写进原计费账本。

## 本轮真实任务与采纳

当前first_visit规则把完整句上的否定/条件词简单搜索，可能把明确人物/地点专名误判语气。先冻结真实SQLite/ValidationService测试与106项已有回归，隔离Docker确认RED；目录仅一个合格条目，实际选择证明有限目录交接，不证明开放式自主选题。主代理不改产品实现，真实Pi只能改l1.py；独立静态精确SHA审查后采纳，通过独立产品回归。不得宿主import未采纳候选；动态复现只用隔离checker。

分析1请求120秒；开发最多30模型96工具900秒；总协调期限不超过3600秒，实际首轮1800秒，审查等待有界。原无费用上限授权沿用、历史未知保留，异常不重放。代码变更后重新冻结完整runtime，旧source闭包和回执不可复用。先离线TDD/完整Pi/Node及真实Linux模拟传输演练，经具体配置独立审查后才执行真实链。模拟费用不得计入真实账本。

## 验证

严格配置/目录/来源/凭据/审查身份、无工具路由/请求上限、session/RPC篡改、未知计量/策略恢复/owned清理、防重放/并发、冻结模板错任务/原账本检查点刷新/审查拒绝/期限测试。只读预检不创建账本/锁/输出。保留全部失败、费用及清理证据；新入口不改变既有开发schema/权限/自动采纳边界。
