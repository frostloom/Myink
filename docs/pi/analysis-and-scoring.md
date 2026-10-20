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

`ops/pi/writing_evidence.py` 接受固定采集器导出的 schema 1 JSON，表在根对象中，运行和快照的选择字段位于 `trace`。它不连接数据库，也不改变 metadata reader 的授权。可信控制程序调用 `load_writing_bundle(path, expected_sha256)`；默认私有根是 `/Users/a1/项目/Myink/myink-pi`。仅主机配置和测试可指定 `trusted_root`，不能接受 Engine 提交的路径根。加载器拒绝符号链接、非普通文件、越界路径、超过 8MiB、哈希不符、未知表、重复 JSON 字段、重复或无效主键、超出固定行上限及无效 UTC 冻结窗口。

`analyze_writing_bundle` 输出正文之外的私有清单：原始文件 SHA256、dataset_id、每行 canonical JSON fingerprint、来源主键/版本/更新时间、表上限和任务包。UUID 与经过项目、章节范围验证的 `UUID:chN` 才能关联运行；快照章节与请求矛盾时保留为未关联。账户级 short_creation 运行没有 session 外键，不能凭时间把它连接到会话消息。批次别名可能出现在多个任务包内，类型级统计先去重运行 ID，不把快照再次计费。

长篇 recall 同时检查 recall 和后续 plan_cast 的实际 context，保留每条上下文的节点、来源和人物/事件/情节/事实组；初始空人物组不能证明后续漏召。当前章节、设置、记忆、候选审阅和验证状态都标为 observed_now，只提供项目背景，不补历史召回。short_generate 的 recall/extract 为 not_applicable。缺 trace 是 unknown；保留了片段只表示 retained，不能说明完整、正确或有改善。采集达到行上限时，缺独立总量证明便标为 possibly_truncated。

质量目录分别列出召回的相关性、覆盖、漏召、未来泄漏、矛盾，抽取的支持性、遗漏、身份/时间/旧值、冲突、落库，写作的约束、连续性、人设、节奏、收尾/文风，以及审核、修订、工具和作者负担。每项有 rubric 和所需证据；缺独立标注与评审时 value=None/availability=unknown。正文摘录可作为后续评审输入，不自动成为 gold；数量、token、confirmed/done 或候选审阅状态都不是语义质量及人工接受的测量。

操作统计按 task_type 给出完整分母、stored status 分布、失败/未知、重试和留存工具信号。success 只是存储任务状态的成功比例，存在非终态则整体 value=None。created-to-updated 为 lifecycle_proxy_ms，包含排队和人工等待；少于 100 样本不报告 p95。run 的 duration/token/cost 是留存记录的求和，缺项保持 unknown，不等同完整任务总耗时或费用。非零估计费用属于 reported；measured 需要显式 model measurement、有效价格 fingerprint 及完整匹配的来源身份，零费用还需要 zero_cost=True。未验证零不填入费用平均；混杂或缺完整身份不接受跨版本因果结论。

`make_analysis_view(bundle, report, max_bytes=48000)` 在 UTF-8 紧凑 JSON 序列化后限制总量；本次 Pi 输入另用 36000 字节上限给 RPC/提示留余量。它按类别轮转，抽取优先同一运行的原始输出和最后输入，短审核优先保留原始与归一化结果。每份摘录含 table/id/fingerprint/path、分开的前后 byte range、clipped/redacted、源 _capture 和时间范围。中间省略不能拼成原文引语；redacted_field_bytes 的位置只适用于脱敏表示，原源字节间隙未知。视图声明候选/纳入/省略数量、各类覆盖、任务省略、源截断及表上限；过小预算无法保留这些说明时拒绝生成。正文始终是不可信输入，不能赋予权限。

已知凭据字段在对象编码前递归过滤，邮件、手机、已识别的 token/URL 凭据形态在裁剪前脱敏；_capture 只投影有限标记和数值上限。这不是任意秘密检测器。真实正文、会话和来源 ID 继续保存在私有 E 盘产物中，公开交付只提供计数、hash、覆盖与限制。该模块不代替 C15 工具隔离、C16 配对质量评测或 C17 开发/发布闭环。

C15a 审查修复：批次快照的 `:chN` 必须逐行与其 chapter_seq=N 一致，子任务的父线程别名须位于父请求声明的章节范围。测量身份采用非空字符串、非负整数 generation（排除 bool）及非空的字符串 image_ids 映射，且实际 model_id 匹配；非法身份使零费用保持 unknown、正费用保持 reported。短篇摘录保留已验证的 session_id、user/assistant 说话者及 exact/unavailable 状态，视图包含全部留存会话的消息主键清单；缺会话、非法角色和没有 session 外键的账户运行不推断关联。


## C16 冻结配对与统一评审

`ops/pi/evaluate.py` 保留原目录的 45 个稳定 metric ID：四类 recall 的相关/覆盖/遗漏/未来泄漏/矛盾，extract、write、audit、repair、tools、experience；operations 单独保留完整任务成功率、耗时和费用，所以不会把它们平均成写作分数。`unified_rubric()` 的语义锚点为 0、0.5、1；自动语义判断始终 `actor_kind=model`、`assessment_kind=automatic_judge`、`availability=provisional`、`label_confirmed=false`。证据缺失为 null/unknown。short_* 的 recall/extract 为 N/A，冻结 applicability 可声明其他不适用项。作者接受必须有明确 author_event，而不是 done、audit pass 或 candidate confirmed。

控制器先调用 `freeze_pairing(baseline,candidate,cases,plan, changed_factor='source'|'prompt', rubric=..., judge=..., directions=...)`；plan 接受已有 `ops.pi.plans.Plan`，其精确 plan_hash 和通用 metric/guard_metrics/thresholds/sample_floor 保留在冻结记录里。然后 `run_paired(baseline,candidate,cases,frozen,executor)`。baseline/candidate 各为 `{id,source_hash,prompt,config}`；config 冻结完整模型、协议、价格 fingerprint、canonical scope、采样、上限和代理地址，以及所有实际生效的其他配置。只有声明的源码或提示词因素和准确版本 ID 可以不同，其他因素必须相同。输出前冻结完整 cases/input、两个版本、config、prompt、rubric、scorer 源码、judge、seed 和阈值；后续改动拒绝继续执行。

executor 收到 `{version,source_hash,config,messages,case}`，case 仅含实际输入、消息和任务范围，不含 expected/required/severe 标签和 holdout 源产物。它必须返回实际 `executed_messages_sha256`、`executed_config_sha256`；SHA256 使用模块 `digest` 的 UTF-8、sort_keys、紧凑 JSON。候选提示词实际送入 executor，不能仅重评旧输出。源码因素也可以用固定单模块 checker 对同一个完整响应进行 baseline/candidate 字节比较，不要求额外模型调用。所有失败、超时、预算中止仍占原计划槽，不允许只选成功输出。

自定义机械目标从输出 `mechanism_measurements[plan.metric 或 guard_metric]` 读取：`value` 是有限数值，`availability=measured`、`assessment_kind=deterministic` 和 `evidence_sha256` 必须齐全；哈希绑定由可信 checker/controller 验证，不把 child 的 passed:true 当证明。`mechanism` 的 per_group/deltas/status 只表明该目标与护栏的配对结果。至少五组不同 development 任务和一组独立冻结的 holdout、所有目标/护栏可观测才比较；任一护栏退化或 holdout 目标退化阻断。字节保留完整度改善不会填入抽取或写作语义分数。机械结果本身不是生产发布授权，run_paired 的 release_allowed 始终 false；完整 CI、隔离、审查和发布回执仍由控制器另外验证。

`blind_review(bundle,call,rubric)` 每组保留一个计划 judge 槽，一次匿名 A/B 请求中分别评分，再确定性计算差值。固定 seed 随机化顺序；模型看不到版本、分支、commit、config、费用或延迟字段，文档 ID/path 也匿名化。原标签映射留在单独 blind_key；引用恢复后针对原文验证。缺失/格式错误/超额评审保留槽和 unknown。故事和工具结果是不可信证据，不能替换 rubric/policy。可信 call 对实际平台响应保留完整 raw_output/usage/model/accounting 记录；自动模型声明本身不会创造 human confirmation。

语义行需要 source 和对应 stage 文档的引用；repair 需要 before/after，落库另需 commit_ledger/stored_row；完整性与角色范围是独立门槛。每条引用为 `{id,path,project_id,chapter,as_of_chapter,fingerprint,representation,start_byte,end_byte,quote}`，fingerprint 为冻结字段 UTF-8 文本 SHA256，字节范围为半开区间；只接受一个连续留存区间中的逐字引语和正确 UTF-8 边界。错误项目/章节/as-of、错 fingerprint、裁剪中间空隙均拒绝。位置适用于声明的脱敏/留存表示，不能冒充原文相等。clipped/observed_now 不证明遗漏或没有违例。recall required 与 relevant optional 集合分开，覆盖按唯一 proposition ID，保留各节点/未来/外项目观察；extract 一对一匹配身份、时间、旧值和 mutation，confirmed 字样不能证明落库。辅助 deterministic_label 比较仍为 proposed，进入统一报告前必须保留 item 的真实 source/output 引用和独立标签。

严重错误使用冻结 severe_rule_ids，必须有有效 source+draft 引用；有效严重发现独立 veto，优秀文风、速度或费用不能抵消。无完整严重规则检查集、目标或护栏证据为 insufficient_evidence。模型 judge 的执行身份也必须冻结：`judge={model,config_sha256,prompt_sha256}`；call 的完整返回记录必须有相同 model/config、`judge_prompt_sha256`、canonical reconciled 会计和 known estimated cost，才可能通过有限自动配对门槛。未知会计、未绑定 judge、无引用仍保留自动意见而不准 release。自动/同供应商偏差和样本局限随报告保存；五组合成配对不满足 >=20 同型完整实际任务，少于100完整真实尾部样本不生成 p95。

`operational_metrics` 的成功率要求每项 `task_terminal_verified` 和 `terminal_outcome`；latency 要求带时区的 full task start/end，不采用 node sum 或 created-to-updated；cost 要求每项全部 generation/judge/tool/retry/compaction 的 `cost_coverage_complete`、reconciled canonical receipt 和一致已知 pricing_id。缺项保留完整分母与 execution_distribution，数值 null；未知费用不作零或退款。

`evals/pi-local-trial/cases.json` 固定五个 development source family（旧表、伤势、承诺、重访、未解威胁）和已公开仪器供能 family 的 local_public_holdout。原 fixture 的来源文件 SHA256、字段 fingerprint、input/dataset hash 和 proposed 标签保留；作者来源 unknown，未创建人工 gold。派生、改名、正反例和重复内容必须同 split。已用于调参的 holdout 改归 development 并替换/版本化；这个公开 holdout 不是外部未见样本。现有私有27任务/298运行的发现数据不补历史缺失正文，也不变成语义 gold。capture completeness 是未来可验证目标，C16 不改 capture 源码。

## 平台调用与 legacy 入口

`src/myink/evaluation/platform_call.py` 只做一次明确 Anthropic HTTP 到固定 `http://127.0.0.1:PORT/v1/messages` 预算代理，scope 是 local-trial-1。`platform_config` 只选四个 PLATFORM_MODEL_* 字段；它们必须是 scoped gateway token/loopback URL/准确模型/anthropic，不能输入上游 key 或 URL，不混用 DEEPSEEK_API_KEY。transport 禁用重试、重定向和环境 HTTP 代理，thinking.type=disabled；保留实际 model、content/thinking/tool blocks、stop_reason、原 usage 和 raw/projection，缺 model/usage 不填 requested model 或零。

价格须显式可信64位 pricing_id 和四维 Decimal-string rates `{input,output,cache_read,cache_write}`，cache rate null 不代表免费。适配器不推导官方价格、不建立第二 Budget；只有可信 `_accounting_resolver(identity)` 逐项匹配 scope、request body SHA256、provider_request_id、actual model、pricing_id、usage SHA256，且独立账本事件 verified、done、usage_known、attempt_id、charged_microyuan 才设 cost_status=estimated。缺 resolver 或计费未知时 cost_est=null/accounting_status=unreconciled；旧未知预扣仍保留。总预算仍是全角色累计100实际 HTTP/10CNY；当前4次/6072790microyuan不是新额度。

`scripts/evaluate.py` 和 `scripts/evaluate-comparison.py` 新增显式 `--transport platform`；audit 读 `--config` 的可信价格/上限，comparison 需 `--platform-config PATH`，仍要求批准的隔离数据库。两者默认 `legacy-deepseek` 以兼容现有调用，runner.py 的 legacy client 保留不动；平台路径不调用其 Budget/价格 fallback。平台 plan 是零网络，且不输出 scoped token。真实 generation/judge 只由 C17 共用预算调度；C16 的 mock HTTP、纯 executor 和局部离线回归不能宣称数据库/隔离/真实模型/完整CI通过。


C16 fix round 1：comparison 每输出费用仅在所有 receipt 都有有限非负数值时求和；缺项、null 或空 receipt 批次为 unknown/null，并继续留存全部计划槽位。配对 `real_model_calls` 仅汇总 executor 显式 `actual_http_attempts`；执行完成不证明零调用。控制器注入的确定性 executor 必须独立核实没有任何上游请求并显式返回 0，未提供或未知计数使总数为 null。

抽取量表的独立比较集保存在冻结 case 中：`expected_mutations_status=independently_reviewed`、完整 `expected_mutations`（唯一 id、entity、attribute、chapter、old_value、new_value 及有效 source citations），且 `label_gaps` 无缺项。本量表采用保守的全比较集检查：各语义判断须有每个 expected id 的 source+extract_output 引用，唯一 item 集及 denominator 均匹配冻结比较集，才保留自动 provisional 分值；缺标签或证据仍 unknown。经独立核实的空集将 omission/persistence 记为 N/A、denominator=0、value=null；未标注空数组与它有区别，不给满分。其他空集判断保持 unknown。交付的合成资产没有独立抽取标签，仍不生成抽取语义分数。

合成配对比较禁止目标和所有护栏中的 p95 指标：即使提供有限的确定性数值，六组合成数据也不能建立至少100个完整真实尾部任务的资格；比较返回 insufficient_evidence 且不公布 p95 delta。非 p95 机制目标继续按原冻结 Plan 检查。

## 分析合同执行接入（2026-10-20）

`ops/pi/analysis_execution.py` 的 `prepare_contract_slots(views, report, model=..., cwd=...)` 按现有5组、2臂、3次重复产生30个私有槽位。重复1/3为baseline→candidate，重复2反序；实际system包含共同cwd，提示/输入/报告/请求身份均冻结。`writing_analysis.build_analysis_request` 与原preflight共用请求构造，SDK及网关两种编码仍受65536字节限制。

宿主用 `verify_contract_request(actual_body, slot)` 在实际网关转发前核对真实SDK请求；`run_contract_slot(slot_index=宿主当前可信序号, ... engine, session, deadline ...)` 在启动前重算槽位，拒绝输入/提示/模型/cwd漂移、旧会话和超过90秒deadline。调用现有Engine一次、无工具、无自动重试，原始私有回执保留；适配器done之后还需原严格解析及目标域评分。

槽位和结果含正文，只能放私有目录；公开摘要只列ID、状态、数量和哈希。`contract_valid`仅表示该返回满足输出合同；不证明请求已付费记账、实际隔离或语义质量。`billing_verified=false`、45项语义unknown、`automatic_execution=false`、`release_allowed=false`保持。原宿主仍必须提供当前有效scope、原累计20元账本、每次预留、整轮deadline、严格隔离和进程树清理。不能将新接入层当作真实调用grant，不能重放旧040授权。

可信序号由宿主的持久游标提供，接入层据此从固定顺序重算槽位；跨调用重放、累计次数与游标推进仍由宿主负责，不能把模型传入的序号当授权。

### 实际网关的计费前校验（2026-10-20）

`make_gateway_handler(..., request_guard=...)` 和 `serve_gateway(..., request_guard=...)` 接受可信宿主提供的校验函数；配置此函数时必须配置非空 `scope_token`。此接口不从 HTTP 参数装载函数，也不把通用 CLI 自动升级为实验授权。

网关先认证，再检查请求封装并严格解析 JSON；仅 messages 两条现有路由调用 `request_guard(body)`，且只有返回字面布尔 `True` 才进入原 `forward_messages` 的预算预留/转发/结算。False、None、其他真值或异常统一返回无异常详情的403，拒绝请求不占用模型预算。工具和证明路由仍走原 broker；未配置函数的旧入口保持原行为。

宿主应由冻结输入构建当前可信槽位，在函数中调用 `verify_contract_request(body, slot)` 并明确返回 True；随后仍由原账本执行每次预留，不能用校验函数代替计费。HTTP 服务使用线程并发，函数对共享槽位游标的校验和消费必须自行提供原子性及持久化；此接口不会阻止重复请求、自动推进游标或恢复进度。整轮次数/费用/时间上限、当前隔离证明、会话与进程树清理仍需宿主绑定。校验函数执行也受原 HTTP 总期限约束，但函数本身是可信宿主代码，不是可强制终止任意 Python 函数的沙箱。


### 持久化槽位与 HTTP 防重放（2026-10-21）

`ops/pi/analysis_run.py` 的 `AnalysisRun.create(ledger, run_id, slots, source_sha256=..., config_sha256=...)` 原子登记一轮身份和全部30槽。`slots` 来自 `prepare_contract_slots`；冻结全部请求及顺序，账本只保存身份和哈希，不保存提示或正文。`AnalysisRun.open(...)` 只能打开完全相同的持久记录，不能重建缺失槽位、覆盖原运行或改变源码/配置。复用现有 Ledger 的 WAL/FULL、BEGIN IMMEDIATE 和不可变回执，schema 不变。

可信宿主用 `run.gateway_handler(slot_index, policy, transport, scope_token=...)` 构造已有 HTTP 网关，并为该槽位的新 Pi 会话配置同一个私有随机令牌。令牌应由宿主使用 `secrets.token_urlsafe(32)` 等方式产生，长度32–4096、可打印ASCII；只落盘令牌SHA256。每个槽位使用不同令牌，同一账本内禁止跨槽位或跨运行复用。部分 baseline 请求字节完全相同，所以仅有正文哈希无法辨别旧 HTTP 包；宿主必须在结束旧会话、确认退出并记录结果后，为下一槽建立新的处理器和会话，不能在保留旧令牌的服务中切换游标。

`run.guard(slot_index)` 是底层正文校验原语。HTTP 路径优先使用上面的 `gateway_handler`，由既有认证先拒绝旧令牌，再在预算预留前原子校验、持久认领一次。线程/进程竞争只能有一个请求获准；相同请求重发、旧guard、漂移请求和乱序请求均拒绝。认领事务与后续模型预算预留是不同事务：即使认领后没有成功预留、没有发出请求或宿主崩溃，该槽位也已消耗准入机会，不能自动重试。

宿主核对实际结果后调用 `run.finish(slot_index, status='done'|'failed'|'uncertain'|'blocked')`；done/failed 表示本槽已得到明确终态，允许下一槽，不能理解为合同有效或计费认证。uncertain/blocked 阻止后续槽位；终态不可改写。不填写终态的已认领槽位在 `snapshot()` 中保持 UNCERTAIN，不能因重启变成 NOT_RUN。恢复程序可以依据外部证据为尚未写入终态的认领记录结果，但此模块不执行自动核对或释放。`snapshot()` 返回完整30槽，包括 NOT_RUN，不含正文或令牌。

该模块接通持久准入能力，不启动 Pi、不循环执行30槽，不授予新预算。当前有效的整轮预算/期限、原累计账本、准确运行时与实际文件身份、无工具分析、资源隔离和进程清理仍由可信宿主接入验收；不能将本地HTTP模拟视作付费实验许可或语义质量改善。
