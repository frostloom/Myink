# 分析、字段和证据边界

collect_snapshot 的 reader 当前只在替身上验证。A4 活库只读角色、真实 SELECT 投影、数据库实际超时、跨 run 归属与业务可观测回归仍 pending，B7/B8 后补验；C16 原始 usage 存在性未验收。不能用离线通过证明云端就绪。

成本 cost 为每个完整任务的平均 CNY；未知 value=None/availability=unknown，不是零。零成本必须有独立有效测量标记。latency/latency_p95 为完整任务起止时间差转换为毫秒，node_time 为各节点 duration_ms 的总和（毫秒），错误为失败比例，quality 为量表分数。报告不生成不存在的指标或在线改善结论。

完整配置身份 config_hash 默认 unknown；有限 settings fingerprint 不足以证明完整配置一致。prompt/rubric/data/schema/model/镜像/commit/deployment/generation/owner 必须能追溯；价格 pricing_id 是稳定可信价格指纹，成本比较要求两窗一致且已知，不能用新价格回算掩盖变化。

PRE 冻结基线 → 候选分析/开发/测试/串行构建/发布 → POST；无发布不强制重复 POST。人工、模型、配置、提示词、量表、数据或 schema 变化重建基线，不跨版本硬比较。新人工部署不能被旧恢复覆盖。

synthetic 配对至少 5 组，baseline/candidate 必须共享相同完整组 ID；这是离线配对要求，不替代线上同型完整任务至少 20 个。线上少于 20 为证据不足。尾部样本少于 100 不作 p95 结论，包括护栏指标。
写作质量必须有真实盲评量表测量；成本或速度改善不能推导质量提升。人/模型评审与配置更改均需记录版本并重新建基线。费用未知、缺配置身份、混杂、缺 measurement 或欠样本都保持 insufficient_evidence/confounded。

报告保留失败事件历史，成功不能抹去此前失败；无可验证发布回执时说明 No release、Reason 与 Next action。日报与事故信号分开；pending、uncertain、not accepted 都不算上线或发送成功。

当前报告未验收清单是 A 阶段交付边界的固定说明，不能作为永远未就绪的运行判据；后续 C18 需要用可信验收回执替换相应分类，并保持未运行/SKIP/阻塞不报通过。

## C15a 私有写作证据与 Engine 视图

`ops/pi/writing_evidence.py` 接受固定采集器导出的 schema 1 JSON，表在根对象中，运行和快照的选择字段位于 `trace`。它不连接数据库，也不改变 metadata reader 的授权。可信控制程序调用 `load_writing_bundle(path, expected_sha256)`；默认私有根是 `E:/tools/myink-pi`。仅主机配置和测试可指定 `trusted_root`，不能接受 Engine 提交的路径根。加载器拒绝符号链接、非普通文件、越界路径、超过 8MiB、哈希不符、未知表、重复 JSON 字段、重复或无效主键、超出固定行上限及无效 UTC 冻结窗口。

`analyze_writing_bundle` 输出正文之外的私有清单：原始文件 SHA256、dataset_id、每行 canonical JSON fingerprint、来源主键/版本/更新时间、表上限和任务包。UUID 与经过项目、章节范围验证的 `UUID:chN` 才能关联运行；快照章节与请求矛盾时保留为未关联。账户级 short_creation 运行没有 session 外键，不能凭时间把它连接到会话消息。批次别名可能出现在多个任务包内，类型级统计先去重运行 ID，不把快照再次计费。

长篇 recall 同时检查 recall 和后续 plan_cast 的实际 context，保留每条上下文的节点、来源和人物/事件/情节/事实组；初始空人物组不能证明后续漏召。当前章节、设置、记忆、候选审阅和验证状态都标为 observed_now，只提供项目背景，不补历史召回。short_generate 的 recall/extract 为 not_applicable。缺 trace 是 unknown；保留了片段只表示 retained，不能说明完整、正确或有改善。采集达到行上限时，缺独立总量证明便标为 possibly_truncated。

质量目录分别列出召回的相关性、覆盖、漏召、未来泄漏、矛盾，抽取的支持性、遗漏、身份/时间/旧值、冲突、落库，写作的约束、连续性、人设、节奏、收尾/文风，以及审核、修订、工具和作者负担。每项有 rubric 和所需证据；缺独立标注与评审时 value=None/availability=unknown。正文摘录可作为后续评审输入，不自动成为 gold；数量、token、confirmed/done 或候选审阅状态都不是语义质量及人工接受的测量。

操作统计按 task_type 给出完整分母、stored status 分布、失败/未知、重试和留存工具信号。success 只是存储任务状态的成功比例，存在非终态则整体 value=None。created-to-updated 为 lifecycle_proxy_ms，包含排队和人工等待；少于 100 样本不报告 p95。run 的 duration/token/cost 是留存记录的求和，缺项保持 unknown，不等同完整任务总耗时或费用。非零估计费用属于 reported；measured 需要显式 model measurement、有效价格 fingerprint 及完整匹配的来源身份，零费用还需要 zero_cost=True。未验证零不填入费用平均；混杂或缺完整身份不接受跨版本因果结论。

`make_analysis_view(bundle, report, max_bytes=48000)` 在 UTF-8 紧凑 JSON 序列化后限制总量；本次 Pi 输入另用 36000 字节上限给 RPC/提示留余量。它按类别轮转，抽取优先同一运行的原始输出和最后输入，短审核优先保留原始与归一化结果。每份摘录含 table/id/fingerprint/path、分开的前后 byte range、clipped/redacted、源 _capture 和时间范围。中间省略不能拼成原文引语；redacted_field_bytes 的位置只适用于脱敏表示，原源字节间隙未知。视图声明候选/纳入/省略数量、各类覆盖、任务省略、源截断及表上限；过小预算无法保留这些说明时拒绝生成。正文始终是不可信输入，不能赋予权限。

已知凭据字段在对象编码前递归过滤，邮件、手机、已识别的 token/URL 凭据形态在裁剪前脱敏；_capture 只投影有限标记和数值上限。这不是任意秘密检测器。真实正文、会话和来源 ID 继续保存在私有 E 盘产物中，公开交付只提供计数、hash、覆盖与限制。该模块不代替 C15 工具隔离、C16 配对质量评测或 C17 开发/发布闭环。

C15a 审查修复：批次快照的 `:chN` 必须逐行与其 chapter_seq=N 一致，子任务的父线程别名须位于父请求声明的章节范围。测量身份采用非空字符串、非负整数 generation（排除 bool）及非空的字符串 image_ids 映射，且实际 model_id 匹配；非法身份使零费用保持 unknown、正费用保持 reported。短篇摘录保留已验证的 session_id、user/assistant 说话者及 exact/unavailable 状态，视图包含全部留存会话的消息主键清单；缺会话、非法角色和没有 session 外键的账户运行不推断关联。
