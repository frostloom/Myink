# 分析、字段和证据边界

collect_snapshot 的 reader 当前只在替身上验证。A4 活库只读角色、真实 SELECT 投影、数据库实际超时、跨 run 归属与业务可观测回归仍 pending，B7/B8 后补验；C16 原始 usage 存在性未验收。不能用离线通过证明云端就绪。

成本 cost 为每个完整任务的平均 CNY；未知 value=None/availability=unknown，不是零。零成本必须有独立有效测量标记。latency/latency_p95 为完整任务起止时间差转换为毫秒，node_time 为各节点 duration_ms 的总和（毫秒），错误为失败比例，quality 为量表分数。报告不生成不存在的指标或在线改善结论。

完整配置身份 config_hash 默认 unknown；有限 settings fingerprint 不足以证明完整配置一致。prompt/rubric/data/schema/model/镜像/commit/deployment/generation/owner 必须能追溯；价格 pricing_id 是稳定可信价格指纹，成本比较要求两窗一致且已知，不能用新价格回算掩盖变化。

PRE 冻结基线 → 候选分析/开发/测试/串行构建/发布 → POST；无发布不强制重复 POST。人工、模型、配置、提示词、量表、数据或 schema 变化重建基线，不跨版本硬比较。新人工部署不能被旧恢复覆盖。

synthetic 配对至少 5 组，baseline/candidate 必须共享相同完整组 ID；这是离线配对要求，不替代线上同型完整任务至少 20 个。线上少于 20 为证据不足。尾部样本少于 100 不作 p95 结论，包括护栏指标。
写作质量必须有真实盲评量表测量；成本或速度改善不能推导质量提升。人/模型评审与配置更改均需记录版本并重新建基线。费用未知、缺配置身份、混杂、缺 measurement 或欠样本都保持 insufficient_evidence/confounded。

报告保留失败事件历史，成功不能抹去此前失败；无可验证发布回执时说明 No release、Reason 与 Next action。日报与事故信号分开；pending、uncertain、not accepted 都不算上线或发送成功。

当前报告未验收清单是 A 阶段交付边界的固定说明，不能作为永远未就绪的运行判据；后续 C18 需要用可信验收回执替换相应分类，并保持未运行/SKIP/阻塞不报通过。
