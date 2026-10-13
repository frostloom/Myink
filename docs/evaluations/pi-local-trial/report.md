# Pi 本机试验交付报告

最新本机快照（2026-10-14）：[014写作配对实验](writing-runtime014-2026-10-14.md)已完成十次真实HTTP200、finalize和精确清理；双方各5个响应，仅运营组各1份分析有效，其余4组schema_failed/unknown，共同有效组1。11域留存口径及45项语义指标完整保留，写作质量改善unknown；[013反馈配对](feedback-runtime013-2026-10-14.md)的23→26分类一致、9/10→10/10危险参考识别只是合成标签观察。009目标仍FAILED，015真实Pi开发仍待独立实际授权与验收，不自动运行。

当前累计上限100次/20元：66次尝试，已知估算0.575877元、历史未知预留10.065792元，总保守占用10.641669元，不是供应商账单；014新增已知估算0.189278元。model/admission pending为0，原历史rows/events及合法scope/fence pending保持。下文按轮次保留历史快照；003的10元及停止状态仅属于当时记录。[014聚合JSON](writing-runtime014-2026-10-14.json)和[013聚合JSON](feedback-runtime013-2026-10-14.json)分别给出合同、分母与hash。


状态：partial。本版为 `final-host003` 最终事实快照。主机 checker/Pi 隔离和真实 Pi 的模拟协议已通过；付费规划失败、完整业务服务与生产启用仍未验收，全部自有进程、keeper 和网关已停止。源码、真实进程协议替身、独立内核/checker、完整服务/镜像、生产启用分别验收。[机器可读索引](receipt-index.json)使用 passed/failed/blocked/not_run/simulated，引用私有证据 hash/path。

本次文档冻结前已提交并推送的源码为 `f4d905d311ba08eddcc4dc6e200f30816b74f1fc`，离线全量的冻结源码基线为 `f2516c4d8ecd63a1faaa5919e10c1c4a2a0c4a1f`，主工作区基线 `299672ca9b36e3cbc27bca5ae0aad0c640d2fcbf` 与既有修改由主代理保护。B12 过期 root/systemd/usernamespace/full-build packet03 被自动审批拒绝，未重试或换包装。完整业务构建、真实服务故障矩阵和旧 watchdog 验收仍有缺口。

| 阶段 | 目标与产物 | 证据边界 |
| --- | --- | --- |
| C14 | 固定 Pi 1.1.0 与预算化 RPC | 实际安装身份由私有回执记录，不默认 latest |
| C15 | 真实 Pi 的8次脚本传输/7个认证工具回执 | protocol mock；same UID authority SIMULATED、0 provider HTTP；mock001–003 的失败保留 |
| C15 写作发现 | 27任务/298运行，其中19长篇任务/252运行；12条字面引用、11域 | 30日有界采样可能截断；rollback 类型错误使完整 receipt pending_schema；发现不是质量改善 |
| C16 | 源码配对、冻结量表和计费身份，源码审查通过 | actual judge/pairing not_run，语义改善 unknown、release_allowed=false |
| C17 | 持久小步调度和恢复，源码审查通过；实际 `003` 捕获 | checker/Pi containment 实际通过；安装的 Pi 协议通过，3次模型传输 SIMULATED；paid plan 实际失败、develop not_run、build/release blocked |
| C18 | 13项离线故障案例、825项冻结源码离线验证、维护文档和索引 | 2个Windows符号链接SKIP、19个设施测试deselected；外部适配器 SIMULATED，实际服务矩阵未运行；最终事实文档仍由主代理独立复核 |

45个稳定语义 metric ID 全部保持 `value=null, availability=unknown`，11域保持完整。没有独立历史 gold，字节、数量、done、当前记忆和模型意见都不能填成语义分。当前记忆为 observed_now，人工/fixture 来源 unknown；19任务的252运行不能写成252任务。

| 分析范围 | 指标、单位与分母 | 必要证据 |
| --- | --- | --- |
| 事实/事件/人物/情节召回 | 各自 relevance、eligible coverage/omission、future leakage、contradiction；唯一命题ID分母 | 实际有序 recall/plan_cast context、章节时点可用集合、独立标签；当前快照不反推历史漏召 |
| 写后抽取 | supported/omitted mutations、identity/time/old_value/conflict；独立 mutation 集分母；validation/persistence 分列 | 源章节、raw extract、验证明细及实际 commit/stored-row；confirmed 不证明落库 |
| 规划和写作 | 执行约束、连续性、人设、节奏、收尾、文风；冻结 rubric 单位 | brief/plan、实际配置、draft/final及盲评引用；规划保留阶段证据，不另造测量分 |
| 审核/修订 | 检出、误报、严重性、解决/新增错误、指令遵循 | 独立违规集、before/after、完整审阅；自动评审仅 provisional |
| 工具/作者负担 | 相关/无依据/恢复、人工编辑/重生成/接受 | 完整有序工具结果、作者明确反馈；自动意见不等于人类接受 |
| 完整任务运行 | 终态成功分母=全部同型任务；完整起止ms；CNY/task；重试、timeout、budget pause、恢复结果 | 全任务起止和终态、生成/评审/工具/压缩/重试完整账本；node time和created-to-updated不替代总耗时，未知费用不作0 |
| 资源/部署 | CPU、内存bytes/MiB、队列深度、恢复seconds、冷/热窗、owner/generation/镜像/源码身份 | 仅真实留存采样；共享页cgroup MemoryPeak不等于冷RSS，限额不等于实耗 |

维护者扩充有界指标须固定 ID、定义、单位、适用任务类型、分子/分母、采样窗/行上限，以及 source/data/prompt/rubric/model/config/price/commit/image/deployment 身份。保留原45个ID，操作观察不改写语义定义。null/unknown 是缺证据；N/A 仅用于证明不适用或独立核实的空集，未标注空数组不能满分。自动标签保留 provenance/provisional，版本或人工变更重建基线。少于20同型完整真实任务为证据不足，尾部少于100不报p95；不生成总加权分抵消严重错误。一个候选可处理单个具体发现，但报告仍覆盖全45项和操作表现。详见[分析与评分](../../pi/analysis-and-scoring.md)。

最终累计6次请求、已扣或预留8095752 microyuan，其中不可变未知预留8049408、已知估算46344；实际账单金额未知，不能将8095752写成实际支出。累计上限100次/10000000 microyuan，跨日不重置。剩余1904248小于下一次最坏预扣2016384，禁止下一次请求。

实际 `003` 的付费 plan 发送2次HTTP，执行4次只读工具（observe_metrics、candidate_status、read_source两次）。cache-input 用量转换未通过现有严格解析器校验使阶段失败；随后请求因预算不足被本地网关阻断。未形成获批计划，未 apply_patch、develop、judge、构建或发布，candidate 未改变。合成基线机械检查为实际失败，只证明该受控检查结果，不证明语义改善。45个语义ID和11域继续 unknown。原生导出45个文件及manifest的私有路径/SHA256见索引，保留原生回执、失败和supervisor结果，不重建或替换。

离线矩阵覆盖PRE禁止候选、POST欠账/损坏撤销、402/空响应/缺usage跨午夜和重开账本、候选写前/写后崩溃不重放、人工同SHA接管、05:30/06:00调度选择、ACTUAL缺验收无副作用、中断后源ID/45项unknown保留。传输与外部执行器固定替身，不发API；移除内存owner防护产生预期失败，源文件未变。实际队列屏障/ACK/checkpoint/旧watchdog/主客机低内存故障矩阵未覆盖，不添加假watchdog替代。`003` 自有进程树清空、固定UID进程消失、root keeper按精确身份停止及网关关闭另有真实清理证据；该清理不能验收业务服务故障矩阵。

聚焦命令：`python -m pytest ops/pi/tests/integration/test_fault_matrix.py -q --noconftest -p no:cacheprovider`。进程级PYTHONDONTWRITEBYTECODE/PYTHONUTF8/PYTHON_DOTENV_DISABLED，TEMP/TMP和唯一basetemp在E盘。首次沙箱不能建目录：11 setup errors，非RED；授权E盘后初版2夹具错误/9通过，修正后13通过。最终owner/pending内存变异3预期失败、10 deselected（2.46s），还原进程后13通过（4.62s），无SKIP。主代理已完成冻结源码离线全量：825 passed、2 skipped、19 deselected，255.71s；两个SKIP为Windows无法创建符号链接，19项为pi_lab设施测试。执行采用 `not pi_lab and not pi_live`，源码为 `f2516c4d8ecd63a1faaa5919e10c1c4a2a0c4a1f` 加9个pre-host C18文件，排除dirty B12。先前180s timeout回执保留，后一次通过不删除该失败。该全量结果早于最终admission修复，不能当作修复后全量通过。业务Python全量、服务集成、前端、Go、契约、镜像本轮未运行。

一次整分支源码/架构审查发现Important：rejected admission会遮蔽同操作的published retry。最小修复已在 `f4d905d311ba08eddcc4dc6e200f30816b74f1fc` 提交并推送，单次有限复审为Approved，原Important已在源码层关闭。修复独立验证为17 passed（1.76s），使用真实映射表、SQLite和正常SQLAlchemy查询；PostgreSQL路由/owner回归NOT_RUN，真实broker/consumer/服务门槛仍未通过。它与825项离线结果分别绑定执行回执，不合成一次修复后全量验收。

管理员的可替换 Engine 接口和 Pi 实现已完成，已有 Pi 会话归属保护；第二个实际引擎的运行时替换未运行，也没有两个假引擎的合同测试。此缺口留给后续具体适配器，不用两个自定义假引擎的自证断言宣称运行时兼容。

C18审查修正：上述历史运行的stdout未物理留存，故仅补录一次相同范围的GREEN与既有变异RED，未重建历史日志。新结果为13 passed（4.03s，exit0）及3 failed/10 deselected（2.00s，预期exit1）。[索引](receipt-index.json)的两个passed检查现已绑定 `E:/tools/myink-pi/evidence/c18-delivery-fixround1-001/` 下的execution.json及SHA256；回执进一步绑定实际stdout/stderr、精确命令、进程环境覆盖、E盘临时目录、执行源码哈希和RED变异脚本。变异只在内存，运行前后源码一致；这仍是SIMULATED外部适配器的离线证据，不改变任何主机/服务验收状态。

冷RSS/冷热峰值未测量。Pi384MiB、checker128MiB、50%CPU、swap0为配置上限；runtime binding仅观察。AF_INET/AF_INET6-only 的真实Pi协议及付费只读调用兼容已通过；localhost允许范围仍超过一个代理端口，不声称内核逐端口隔离。

生产 `enabled=false`；主代理功能分支actual push与Pi自主GitHub模拟流程分列，没有main merge。日报/事故信号未真实发送。`reporting.py`旧A阶段固定banner保留，仅代表历史交付边界；空账本或模型事件不授予新验收。后续见[服务器清单](../../pi/server-enablement.md)、[通知](../../pi/notifications.md)、[升级](../../pi/pi-version-upgrade.md)。公共文件不含正文、账号、密钥或dump。

## C19 本机累计额度更新

2026-10-12用户授权后，既有local-trial-1已追加可信20元增补，仍累计最多100次请求；原6次请求与8095752微元估算费用/预留全部保持不变。本文上述003运行及10元额度为历史快照。当前增补实施、318项合并测试及证据参见[预算增补记录](budget-amendment-2026-10-12.md)。该更新没有宣称004实际开发、质量评估或部署完成，也不改变未来服务器每日10元默认值。

## C19 005 真实规划与读取工具修复

上述预算增补为落地时的6次请求快照。后续005已真实运行：9次HTTP用量解析通过，但文件末尾读取反馈不足耗尽analysis15，没有提出计划或修改候选；另一次本地拒绝的预留保留，累计16次/10143409微元估算扣费或预留，实际账单未知。EOF最小修复经57项测试和独立审查后已推送。006恢复尚未运行，完整服务与生产仍未验收。详见[005实际结果与核查路径](runtime005-2026-10-12.md)。


## C19 006（2026-10-13）：付费前的就绪竞态

[006 运行快照](runtime006-2026-10-13.md)保存新源码 60 项纯测试、独立源码审查与真实隔离失败。checker 通过；Pi 的 overflow 负例在 ready.json 完整关闭前读取而 JSONDecodeError，因此整个 gate2 失败，未进入已安装 Pi 的模拟工具协议或付费规划。3 个 gate2 进程树和精确 keeper 已清理，失败未重跑、旧证明未复用。

20 元累计上限已生效，100 次请求和原阶段配额不变；本轮新增真实请求 0，canonical 仍 16/10143409，完整快照与 after005 相同。10.143409 元为估算扣费或预留，不能写成实际账单。启动握手修复尚在设计，未获修复后的运行验收；语义质量、业务服务和生产闭环仍未完成。


## C19-007 真实规划与开发终止快照（2026-10-13）

后续独立 007 已完成握手修复的 71 项纯测试及组合源码的 75 项纯测试，均无跳过（两套有重叠）；新 gate1/gate2 通过。gate2 的 3 次传输仍为 SIMULATED/MOCK，真实规划随后另有 4 次 HTTP 成功并提出经过审查的计划；开发的 8 次 HTTP 成功没有转化为补丁。计算属性 plan_hash 未交接到开发提示词，apply_patch 错用源码哈希，被已存在的审批门禁正确拒绝；开发终止，无成功补丁、实际 checker 或候选对照结果。

累计为 28 次尝试 / 10221679 microyuan，其中已知估算 155887、未知保守预留 10065792，非确认账单。100 次 / 20 元仍是本机累计额度，服务器每日 10 元未改。源码 23 个生产输入保持；精确保活已停止，之后只读检查唤醒的新 guest 不能续用旧 epoch。语义 45 项仍 unknown，52 个合成案例非 gold；完整服务 B12 NOT_RUN、production_enabled=false。007 失败历史保留，008 仅设计方向、未运行，也不自动重试。详见[007 实测与失败诊断](runtime007-2026-10-13.md)；上述 005/006 段落继续作为各自历史快照。


## C19-008 真实计划与跨轮次汇总失败（2026-10-13）

计划哈希交接修复经 79 项纯测试与独立审查后，008 使用新 epoch 完成 gate1/gate2；gate2 的 3 次传输仍为 SIMULATED。随后真实规划的 4 次 HTTP200、完整用量、真实 propose_plan 和 ROOT reconciliation 均成功，但宿主按共享 paid-plan 标签从整个账本汇总计划，混入保留的 007 记录，最终恰好一条检查失败。没有计划成功 wrapper、开发、补丁、开发阶段候选 checker / run_check 或候选对照；规划基线 checker 已实际运行。该跨轮次选择缺陷尚未修复。

累计 32 次尝试 / 10254974 microyuan，含已知估算 189182 和历史未知预留 10065792，非确认账单。100 次 / 20 元累计上限及阶段配额保持，reserve 已用 8/10；未来服务器每日 10 元未改。只读快照已保留，自有进程树清空，keeper 精确停止。语义质量 unknown，完整服务与生产未验收；不自动启动 009。详见[008 实测、预算与诊断](runtime008-2026-10-13.md)。之前的 007“008 未运行”描述为历史快照，以此后续记录为准。


## C19 当前会话计划选择离线修复（2026-10-13）

008 发现的跨轮次汇总缺陷已在新的离线副本修复：runtime 交接当前会话中已认证的唯一提案，宿主消费该返回值，历史计划和独立审批保留。源码与测试提交 baee005；新增 14 个计划边界案例与 2 个夹具案例，独立源码审查通过。最终干净归档离线 ops 回归为 **998 passed、2 skipped、19 deselected**；两项 SKIP 为 Windows 符号链接权限不足，lab/live 19 项未运行。首次整套两项失败及修复过程均保留，不累计重叠测试数量。

本轮新增模型请求 0，canonical 仍 32 次尝试 / 10254974 microyuan（估算费用或预留，非实际账单），100 次 / 20 元累计上限不变。没有运行 009、完整服务、语义质量或生产发布。本段更新的是离线修复状态；前述“尚未修复”继续作为 008 当时的历史快照。详见[修复、测试和维护说明](plan-selection-fix-2026-10-13.md)。


## C20 真实开发与反馈分析（2026-10-13）

009已实际执行真实模型开发：5次HTTP响应成功，Pi应用了隔离候选补丁并查询最终状态、执行实际检查。但52项固定检查及配对门槛未通过，整体阶段失败，候选没有进入产品代码或发布。旧失败和完整预算前缀保留，三个本轮进程树已清理。累计为37次/10292937微元保守预算占用，确认用量估算227145微元、旧未知预留10065792微元，均非服务商结算账单。详见[真实开发失败与费用记录](real-development-2026-10-13.md)。

反馈只读采集、严格无工具分析合同和安全路由已实现并推送，反馈本身始终不能授予自动执行权限。正常删除按钮故障与破坏系统的要求有不同路由。配对评估固定30条合成参考、同输入/同模型/提示词单一变量，计划12次请求；本段不声称实际模型对照已完成。独立针对性验证269通过、2项现有Windows符号链接权限跳过；实际PostgreSQL读取仍未验收。详见[反馈接入](feedback-intake-2026-10-13.md)及[配对评估维护说明](feedback-comparison-2026-10-13.md)。

生产Pi仍未启用，没有合并main或部署服务器。正文、事件/情节/人物召回、抽取质量及全任务耗时的真实改善继续未知。上述各历史段保留为当时快照，当前实现与实际成功验收须分别判断。

## C20 反馈对照010启动失败（2026-10-13）

新的checker和安装版Pi模拟会话关卡通过，但首个正式反馈阶段在HTTP请求前因ROOT包装器继承umask077导致输入目录0700而退出。新增模型请求0；后续11阶段和质量汇总NOT_RUN。完整账本仍37/10292937，已有实验审批保留，当前快照d528a8f4a7776a1b88f3f3cd2acef820142733d916bbb889e78c52f02b5fe5e6。实际进程树清理通过，旧失败不重跑；新的运行身份准备中。详见[实际失败、复现与维护要求](feedback-runtime010-2026-10-13.md)。本段不宣称真实模型反馈对照完成。

## C20补充：反馈实验011实际关卡与发送前失败

011完成新的实际隔离/安装Pi协议关卡，首个反馈阶段收到本地400 request blocked并失败，模型HTTP0、usage0，后11个请求未运行；未获得分类或配对质量结果。自有进程树与精确keeper已清理，源码和累计37次/10.292937元保守计费不变（不是供应商账单）。完整历史快照现为124操作/210事件，包含新的1操作/2事件批准，旧记录均保留。

见 [反馈011失败记录](feedback-runtime011-2026-10-13.md)。载荷兼容原因正在复现；不把模拟协议或失败记录计作真实质量提升。原010失败及009真实开发未达标结果继续保留。


## C20 反馈012：7次真实响应、格式失败与中断

012完成7次真实HTTP200并清理所属进程树，七批schema1均无效；第8调用前epoch校验拒绝、0HTTP，8–12未运行。原始35个案例槽位均unknown，不能报告分类准确率或危险请求识别率。新增已知估算0.061282元，累计44预算尝试/10.354219元保守占用，包含历史未知预留10.065792元；不是服务商账单。原100次/20元及阶段配额保持，未重试或修补旧输出。详见[012终止部分记录](feedback-runtime012-2026-10-13.md)及[聚合JSON](feedback-runtime012-2026-10-13.json)。

新的独立schema2接口已通过96项针对性测试和代码审查并推送，仅由宿主从唯一原文引用计算字节位置；它不追认012成功。详见[引用校验维护说明](feedback-evidence-v2-2026-10-13.md)。013尚未实际调用，主项目与生产保持。
