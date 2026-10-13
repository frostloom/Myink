# 本机 Pi 反馈对照 013：已完成配对实验（2026-10-14）

013 的十二个独立付费阶段、finalize 和精确 keeper 清理均完成。每阶段实际一次 HTTP200、五条严格 schema2 有效结果，所属进程树清理通过；双方各观察原计划 30 条合成案例，有效 30、unknown 0、NOT_RUN 0。十二阶段与 finalize 共 172 个导出文件的长度及 raw SHA256 已独立核对。模型没有 tools 或自动执行权限。

| 相对冻结建议标签的计数 | baseline | candidate |
| --- | ---: | ---: |
| 分类一致 | 23/30（76.67%） | 26/30（86.67%） |
| 10 条 unsafe_request 参考被模型识别 | 9/10 | 10/10 |
| 20 条非 unsafe_request 参考被模型标成 unsafe_request | 3/20 | 3/20 |
| host 对 unsafe_request 参考拒绝 | 10/10 | 10/10 |
| host 对非 unsafe_request 参考拒绝 | 0/20 | 0/20 |
| host route 与建议 route 一致 | 29/30 | 29/30 |

双方共同有效案例为 30，分类一致数增加 3，比例增加 10 个百分点。这是一次固定合成参考上的观察，不证明生产语义质量或安全泛化改善。30 条标签属于 proposed synthetic references，不是金标准；上表的 20 条分母严格指非 unsafe_request 参考子集，包含 `fake_system`、`url_command`、`encoded` 三条可疑安全指令，不等于全部无害反馈。模型分类与 host 拒绝路由分别计算；所有分类、风险建议和引用均不授予自动执行、回复、resolve 或候选审批。

双方使用同一 schema2、输入、模型和源码，仅受信前缀不同。配置身份为 `qianwen-anthropic / deepseek-v4.1-flash / configured-deepseek-v4.1-flash-2026-10-13`，不是供应商权重证明。012 的 schema1 无效输出仍为 unknown，没有修补或混入本轮，也不作跨 schema 的质量差值比较。009 开发目标仍 FAILED；010、011 付费阶段 HTTP0；012 保留七次 HTTP200 / 35 个 unknown 槽位及五阶段 NOT_RUN。

累计预算尝试由 44 增至 56，本轮十二次真实 usage_known 收据费用合计 **0.098172 元**。全部已知费用累计 **0.386599 元**，历史未知保留占用 **10.065792 元** 未变，总保守占用 **10.452391 元**；它不是供应商账单。完整快照为 164 operations / 271 events；原 139 operations / 233 events 完整保留，仅新增一次批准操作及两个批准事件，外加本轮原合同的 admission / model-attempt 记录。model-attempt pending 为 0，原 scope/fence 的合法 pending intent 保留。

100 次 / 20 元与阶段配额 15 / 45 / 30 / 10 均不变。按现有账本口径，analysis 计数 16 包括继承 4、完成 11、旧 blocked 1，有效 transport 15；不是上限增加。develop 13，experiment 19/30（旧012七次加013十二次，剩余11），reserve 8。未重置、退款或重分类。

最终只读 checkpoint 导出工具首版因多取一层 evidence 而 rc1；旧脚本及失败诊断保留，修正后从顶层 usage_known 重算，与独立账本算术一致。这是导出工具错误，不是付费阶段失败；没有为此增加模型调用或写 canonical。

keeper 清理收据记录本轮精确 PID729 / start275695、同一环境 epoch、stopped=true、无固定 UID 残留、old_pid_signalled=false。该结果只覆盖本机隔离实验；生产角色、真实反馈数据库接入、写作十一域质量、B12、服务器与 main 验收状态均未提升。不自动启动 014。

当前 source closure：`a48bea981b5114abbaebfa84a1491941938dd31b432b25e18eadb92fa234e378`。最终结果 raw SHA256：`c400b016141c8508dce4b595bf3634d07c9c1d2b5d14f1dfd1e74b21e53377ea`。完整快照 raw SHA256：`216fd8d4d1cbe3b598d526a24d22e861f55c1b80bbb6d55e40d5a56c9cd72295`。终态 checkpoint raw SHA256：`56d50f9cfbdec327ebf4c9893ec26725881ad80f9269bd1957c7eec351e90e52`。配对原始 manifest raw SHA256：`cadb0a4083448ffc7f9afd775a720693359a9f790eb306db47017f168ff11565`，labels SHA256：`8d571518411c1bdb9a8cfe5a962d99232080b8aa7d3917b5fc1bdd94f6656ca1`。

公开聚合 JSON 仅包含计数、合成 case ID、分类/路由标签及 raw hash，不包含凭据、用户正文、完整账本或模型原始 hex。建议总 report 标题下增加这段最新状态摘要，再保留历史003的10元记录，以免读者将历史限制误读为当前20元累计额度。
