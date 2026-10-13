# 本机 Pi 真实开发 020：超时未完成，未知请求已保守结清（2026-10-14）

020 确实运行了安装版 Pi 和真实模型：4 次请求收到 HTTP200 响应头，只有3条完整 usage。Pi 自己读取源码并生成一处隔离补丁，但在105秒 worker deadline 内未完成任务。最终 status、run_check 和冻结的配对检查均 NOT_RUN；候选未采用、未发布。HTTP200 响应头不等于完整模型响应或成功开发。

本轮任务仍是修复观测内容的字节前缀保留和 Bearer 凭据边界。候选只修改了 Bearer 正则，capture 字节计算未变。独立静态审查还发现新增的窄分隔符 lookahead 可能让部分原可遮蔽的 token 前缀不再匹配；该风险未经候选执行验证，不报告为已测失败。补丁不能因生成成功而获准采用。

adapter 已停止，session_valid=false、deadline_or_protocol_failure；宿主 unit 没有硬超时、OOM 或输出溢出，所属进程树已清空。会话输出间隔不能直接归因于供应商延迟，具体生成、传输或调度耗时原因 unknown。控制器正确拒绝未完成的认证会话。

初始只读终态真实为 PENDING_RECONCILIATION：第四次请求已经发送，却未留下完整 usage，并有1条 pending model-attempt。ROOT在独立审查和原有临时 SQLite 测试后，仅调用既有 settle(原 permit, None) 一次，转为 uncertain，保留2016384微元全额预留。原 pending 快照与备份原样保留；262条操作中只有这条 pending 的状态/证据改变，原435条事件保留并新增1条回执，未结算 model/admission 均归零。恢复后的状态仍 FAILED_OR_INCOMPLETE，绝不变成开发成功。

停止 keeper 后 WSL 重启，首次ROOT恢复检查额外要求新旧 epoch 相等，在写账本之前拒绝操作。只读核对原快照未变后，独立审查确认按原STOP证据、当前无活动进程、完整账本和固定源码核验恢复；记录新旧 epoch，不复用旧运行授权。冻结 runtime 的 gate/epoch 守卫未修改。

累计87/100次、20元上限：已知估算0.698292元，未知预留12.082176元，保守占用12.780468元，不是供应商账单。本轮新增已知估算0.018392元、未知预留2.016384元；旧未知10.065792元未退回或重分类。原阶段配额15/45/30/10保留；analysis聚合16含继承4及raw12中的blocked1，有效transport15；develop34、experiment29、reserve8。

本轮源码专项57PASS、helpers68PASS、终态脚本11PASS；这些验证范围重叠，不能相加为产品验收。原有预算结算临时SQLite专项3PASS/23DESELECTED（未运行）。新gate1和gate2独立审查通过；gate2运行真实Pi工具协议、3次模拟模型响应、0次canonical请求。它们不证明真实代码修复或写作语义质量。

[013反馈对照](feedback-runtime013-2026-10-14.md)已完成30条固定合成参考的真实模型配对；危险要求由host拒绝，反馈只授予分析线索，不能直接执行、回复或关闭工单。实际生产反馈只读角色与数据库接入仍NOT_RUN。[014写作分析](writing-runtime014-2026-10-14.md)中的人物、事件、情节、抽取等11域45指标仍unknown，旧截断内容无法恢复。所有候选、本轮失败和历史失败保留；没有main合并、生产部署或完整服务验收。

[聚合JSON与证据哈希](development-runtime020-2026-10-14.json)不含用户正文、凭据、完整账本或模型原始会话。最终独立FACTS审查已通过，仅认可这些失败、恢复与预算事实，不授权采用候选或复用旧运行权限。
