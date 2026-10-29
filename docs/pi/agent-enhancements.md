# 从裸 Pi 到 Myink 受控维护执行器

更新：2026-10-29。此清单区分代码能力、服务器已部署能力和仍待接通的线上闭环，不把执行器在线称为管理者完成。

## 本轮最新状态（2026-10-29）

服务器已启用独立审查版本8d1802af的有限自动源协调、封闭管理器和外部审核队列；六个定时器正常，日间真实窗口拒绝/空闲/冷重入均0模型调用。源码许可到2026-10-30 08:47+08，仍等待真正夜间新任务验收；不能据此称完整管理者完成。原累计50元、9预留、所有历史与原次日18/18保持不变。实际部署包含67个Pi控制器/配置文件+4659/-129，管理员只读导出已验证；详见docs/evaluations/pi-autonomy-finite-2026-10-29.md。


本轮新增完成阶段在审查修复前3879项离线测试通过，36项环境测试未运行；8d1802af、ec08ca72及2ae019d7各自四项远程CI全部通过，e8daa02c四项远程CI也全部通过；当前新增完成阶段已经完成一次源码独立审查及作者修复，最终回归、精确提交CI、原生验证和部署另行记录。服务器新匹配控制器/SDK的两次模拟协议会话、两次ACTUAL空闲管理器冷启动通过，均0真实模型请求、原费用账本未变。新自动协调服务现已有限启用，原采集/诊断/次日服务继续运行，管理器已切换到经过核验的封闭入口。原生证据及一次前置条件失败保留于docs/evaluations/pi-autonomy-native-2026-10-29.md。

候选完成后审查正在补齐：只读编译器绑定完整候选、实际diff、固定gold与最终绿色检查副本，拒绝越界/旧测试/未知费用/未清理结果；审查资料没有审批或发布权。独立SDK候选审核和停机会话/RPC/已知费用认证已接入源码；停机开发/原工具账本/已知费用前缀也已源码验证；原管理器完成来源绑定、自动触发、逐工具审计和原固定次日注册表追加均已接入源码，待本计划独立审查、匹配部署和真实新任务验收。此前预开发审查不替代这一步。

管理员读取入口和数据语义以docs/pi/administrator-audit-handoff.md及docs/contracts/pi-audit-v1.md为准：保留检查分析、阶段与工具流转、失败调整、每日组件版本和变更范围、次日计划与独立实际结果。以下分阶段记录保留历史状态；“未到期”叙述已由Oct29实际18/18收据更新，不能拿旧段落判断当前验收。

## 模型与主机的职责

裸 Pi 通常可直接使用文件和shell工具。Myink由可信主机控制器固定Node24.22/Pi1.1运行时，以RPC接入；原runtime005保留；现采用a66c01a5封闭控制器和3cff5eb6匹配SDK源码，Node/Pi依赖9b6d4479不变。独立审计和observer004继续运行。模型不持有原上游密钥、Docker socket、生产写凭据或Git/发布权限。

ops/pi/pi_config.py生成私有HOME/XDG/TMP/agent/cache目录；仅允许127.0.0.1费用代理和短期scope token。关闭遥测、分析、缓存预热、自动压缩和自动重试；只选固定模型。禁用内置工具、MCP、自动扩展、skills、prompt templates、themes及上下文文件加载；仅显式装载固定摘要的受控扩展。PI_OFFLINE关闭SDK发现等网络功能，真实授权模型请求仍通过费用代理完成。

## 新增工具与流转

工具权威在ops/pi/tools.py，schema在ops/pi/extensions/tool-schemas.json。六项固定工具：

| 工具 | 用途 | 模型边界 |
|---|---|---|
| observe_metrics | 读取主机冻结的指标 | 不提供任意SQL或数据库凭据 |
| read_source | 查看允许的冻结源码 | 不读取宿主任意路径或密钥 |
| propose_plan | 提议范围明确的计划 | 提议不构成审核许可 |
| apply_patch | 修改私有候选允许文件 | 计划、冻结基线、文件清单与diff上限校验 |
| run_check | 调用固定检查器 | 不执行模型提供的任意shell；结果绑定候选摘要 |
| candidate_status | 查看当前候选身份和状态 | 不授予发布或回退能力 |

analysis/diagnose仅开放observe_metrics、read_source、candidate_status；plan另可propose_plan；develop仅read_source、apply_patch、run_check、candidate_status。主机的session/candidate/base/owner/generation/phase能力决定权限，模型文本不能创造授权。工具有持久intent和结果；崩溃后的未决操作不得自动重放。

实际开发顺序为冻结输入与独立审核→选择/分析→受控开发→检查失败反馈→候选复查→独立验收。owner002真实执行已完成1次选择、12次开发模型请求、14次受认证工具调用，18个固定案例由7失败到全通过；候选尚未合入main或作为产品发布，不代表线上指标改善。

## 预算、隔离与停止条件

服务器原manager/费用账本为唯一权威，旧本地账本冻结归档。最新授权累计50元，不跨日重置；保留9笔历史未知费用预留，不因导出或迁移释放。模型代理先预留后结算；未知费用、协议不一致、清理/归属不确定停止付费执行，绝不以重试掩盖。审计库使用不同schema，无法代替费用库。

候选和gold检查只在固定Docker镜像中运行，低权限、无外网、无主机凭据和socket；主机控制器及docker组仍属高信任边界。独立FileReview不由候选模型自批。软范围3个生产文件/150行，硬范围8个tracked文件/300生产行，按冻结基线累计；身份、预算、认证、计费、schema及发布政策变更另受保护。

## 记忆现状

已存在：私有模型会话、原始费用/manager/tool intent与收据、冻结输入/基线/候选/检查结果、失败和独立审核。新增：追加式审计链、运行/日期索引、版本与次日测试计划，可作为跨日实验记忆来源；本文件不声称它已自动注入每轮Pi提示词。

本机Codex的Hindsight约定是127.0.0.1:8888、仅myink bank；不可用时跳过。Pi服务器运行时尚无Hindsight适配器，不能把Codex可读写记忆称为Pi已接通记忆。未来记忆必须带来源、基线/候选、时间、证据域与失效条件；历史记忆不能升级为审批或未知费用解除。

## 回退、审计与未完成的接线

已验证的是Pi自身状态保全、原账本迁移/冻结、原计数最新检查点恢复、两次冷启动不重放、不新增费用及资源归属清理；这不等于产品业务版本已自动回退。全部失败试验和旧运行时保留，重试使用新身份或仅继续从未dispatch的任务，不能重演已计费意图。

产品发布/回退设计要求共享发布锁、main/镜像/deployment_id/generation/owner/维护epoch核对、人工发布优先、PRE/POST备份与真实恢复验证，只回退仍由自身持有的候选。旧Pi基线不能覆盖后来的人工版本。02:00–06:00上海维护窗口、05:30停止新候选，缺授权/归属/暂停/备份条件就阻断。

尚待接通并实际验证：线上异常与可重现证据→新任务独立审核→真实模型修复→授权产品发布观察/归属安全回退。独立次日固定回归已实际执行，见下文；它不替代产品发布后的验证。当前已上线的是受审核队列执行器。main合并和产品发布仍遵守用户明确授权边界。

审计合同见docs/contracts/pi-audit-v1.md：分析与检查结果、工具流转、开发/测试/失败、回退、每日源码/控制器/SDK/模型/策略/候选/部署版本、变更范围及次日测试均保留结构化输出；缺证据显示unknown，未执行显示planned。管理员面板后续只读消费，不获得执行器权限。

## 新增只读观测器（2026-10-28已启用）

固定PostgreSQL适配器是可信主机能力，没有扩展模型的六项工具权限。它使用独立NOLOGIN角色和两个security-barrier元数据视图，校验Docker来源、实际视图定义/列类型、只读事务、角色权限与查询超时；参数保持数据绑定，凭据形态和编码正文标识被置为null。模型不能提交SQL或获得数据库凭据。

采集器按固定窗口冻结结果，保留未知身份、空结果、混杂和未完成任务；同一窗口不重复查询，故障不覆盖旧证据。每轮追加检查/版本/能力到auditv1；只读采集不产生产品发布结论，缺少发布证据时保持unknown，main读取器可直接消费。代码树及配置摘要由受控入口校验，生产原状态只读，模型请求数为0。滚动窗口保留各自样本数，日报不将重叠窗口累加为独立样本。主机Docker组仍是高信任边界。

独立PostgreSQL权限/超时/注入/冲突回滚14项测试通过，另有3199项离线回归；它不替代原19项私有实验室验收。服务器已完成两个不同真实窗口，第二次由15分钟定时器自动运行；各1个样本均标证据不足，新增模型请求0，原费用/manager历史保全。实际证据见docs/evaluations/pi-live-observer-2026-10-28.md。次日执行仍须另附真正到期后的收据，不能把采集上线写成完整管理者闭环。

## 独立次日回归（03:02实际通过，以下保留预到期部署过程）

followup004和5分钟定时器已部署，真实预到期结果ACTUAL/planned/零请求/无认领；Oct29 03:00原候选18案例仍result=null。root固定登记是执行权，审计计划仅用于按target_run/test/candidate/due关联；调度运行可预留其他目标运行的任务。共享maintenance.lock与原manager串行，02:00–05:30准入、06:00前结束；固定Docker检查与清理、原账本保全及追加式结果不授予发布能力。父目录和意图先持久同步，不确定/失败不重放，写目标与冻结输入和原状态隔离。代码25fb6b06的14文件+752/-7另存控制器版本事件，原产品候选不变。验证见docs/evaluations/pi-followup-2026-10-28.md；真正次日验收仍待实际到期收据。

次日检查已更新到followup004（008de641），使用纯标准库fixed_checker.py；SDK开发器以兼容包装复用。3种真实Docker场景在-I-S子进程通过，服务器也验证无模型启动器依赖；004已恢复定时器，003暂停/恢复审计保留。完整离线3248通过，控制器累计16文件+914/-91单独存为版本事件。真正Oct29 03:00仍待实际验收，不提前报成功。

## Live diagnosis and bounded memory (actual acceptance completed2026-10-29)

The new no-tool diagnosis uses verified observation receipts and cohort-bound, expiring audit memory (at most8 facts/8192bytes). Model hypotheses do not become permission or independent samples. A finite root-approved host queue admits one original-ledger model request per evidence fingerprint; refreshed windows/audit/memory cannot create a second charge. New evidence without a fixed permit creates investigation only. Pending claims, new unknown fees or unverified cleanup freeze further paid diagnosis. The paid-host runtime explicitly freezes HTTP dependencies, versions and licenses; pure supervisor imports remain standard-library-only.

This phase completed one actual no-tool diagnosis with one source-bound memoryfact (4952microyuan), two zero-charge actualhost reentries, closedpolicy/credential/history/cleanup checks and an exact latestfee checkpoint. The finite root-approved15minute queue is active; new unapproved evidence remains investigation-only. It is not a complete automatic development manager. Actual report: docs/evaluations/pi-live-diagnosis-2026-10-29.md. Hindsight is still not a server adapter. Admin view/flow/cost/version/change-scope expectations are documented in docs/pi/administrator-audit-handoff.md, using the existing audit-only reader and no new admin authority.

## Shared maintenance lock scheduling (actual2026-10-29)

The original manager service now uses its existing idle0 single-scan mode with the60second timer. Two real automatic empty ticks measured485.888ms and502.689ms; externalmaintenance.lock was obtainable twice, with0modelrequests/fees and original005code/env/history preserved. Existing600second process completednaturally. This improves idle scheduling availability; contention and genuineexecution can still delay admission. Configrevision7970f31a, liveunit45ed3ba9...,1file+1/-1, zero productchanges. Evidence: docs/evaluations/pi-manager-scheduling-2026-10-29.md.


2026-10-29 03:02:39+08原定时器实际运行了owner002次日回归，原18案例全部通过、0错误/跳过、新增模型请求0；拥有的容器独立查询确认已清理，原费用fe7c37ea…与策略未变。main独立读取器已将昨天计划关联到今天实际passed事件，保留原计划状态和独立结果。此项已完成，不代表完整自主管理或产品发布已完成。

## 独立审查准入（代码实现中，尚未部署）

新增code_regression证据域要求实际固定案例断言失败、0错误/跳过、完整案例清单及source/gold/report绑定；不能从单测案例制造线上样本。review_dossier编译完整允许源码和测试供审查，受24000ASCII字节上限、密钥形态及来源检查约束。

sdk_review_launcher通过全新无工具SDK会话给出approve/reject/needs_evidence建议，沿用原费用代理、单请求/120秒限制、固定运行时及独立root许可。它不写FileReview，不启动开发；批准建议也不构成执行许可。宿主核验SDK/RPC、用量、费用前缀、清理、策略恢复、凭据和输入不变后，才记录可信状态；完整模型评语留私有区，管理员导出只保留白名单决定/原因、次数、费用与证据摘要。已计费但评语不合格仍留失败，不重放。

宿主准入器现已在代码中实现：独立审查后创建无选择费用ID的租约，自动签发精确选择审核；重验原网关实际选择UUID、已知结算、会话/RPC和选中任务后，生成不可覆写的派生租约，再发布精确开发FileReview。原FrozenDevelopmentAdapter/FileReview并发接线已通过SIMULATED测试；原候选根、范围、费用前缀和只减不增的时限保持绑定。新问题调查/提案、自动协调器、真实新任务验收、产品观察与归属安全回退尚未完成，服务器未启用新路径。实现与验证状态见autonomous-admission.md，避免将未部署代码写成服务器能力。


选择阶段的新增边界：ACTUAL不接受模拟传输或无摘要配置，初始输入与运行模式明确留证。费用预留前再次核验人工策略、配置、源码、凭据、审核、目录与运行时；撤销先于计费。原网关UUID只能从已经认证的选择回执取得，不能预造；弃选不签开发租约，缺少完成收据的派生状态不发布授权、不自动重放。宿主选择审核、已验证选择费用、精确开发授权分别输出审计，主费用只计一次。当前验收是离线/SIMULATED，尚未增加真实服务器请求。

独立诊断、调查及审核会话均无模型工具；六项受控工具列表不代表这些会话可执行工具。新调查角色已在源码中复用原费用和SDK协议，Root许可只允许提案，永久research指纹认领阻止换运行名重付；模拟模式不能使用正式账本。它只输出待复现的测试建议，尚未部署，未创建开发授权或真实新候选。原字节摘要与规范数据摘要分开，输入类型不能将true冒充样本数1。后续必须经过宿主冻结、固定隔离基线和独立审核。

调查到开发的新增主机能力（源码验收，未启用）：认证调查提案后冻结gold，固定隔离检查器只把真实断言失败转成待审查输入；已知待采用候选按相关文件/符号去重，不重复付费发现。独立SDK审查、精确选择授权、实际选择UUID绑定、精确开发授权和原管理器交接分开留证。外部审查worker不占用管理器维护锁，缺收据保留不确定状态；模型弃权保留一次真实费用分析并终止开发。批准前配置另留私有快照，管理器启动后重入仅容许审核摘要写回，不重复执行或放宽范围。新增固定登记与5秒调度单元尚未部署。完整新任务协调、候选完成后的独立复查、真实发布观察及业务回退仍需继续完成，不能把这些代码写成已上线的完整管理者。

固定源策略和自动阶段许可已在源码中实现（尚未部署）：Root策略绑定源码/相关文件/待采用候选摘要、观察器、运行时、固定检查器及原累计预算；依次认证提案、复现和独立审核，生成不同权限的阶段配置。产物即使重算自身摘要，也不能改变候选目录或扩大调用上限。Root许可保持root-owned0640，模型/检查器阶段仅允许ubuntu运行；固定四阶段入口没有任意模块、命令或注入传输入口，停止信号传递到原清理流程，取消后不再向管理器准入新任务。有限父进程的降权分派与完整调度仍在接线，不能据此声称全自动管理已启用。

有限父协调器已完成源码接线：原维护锁下自动生成许可、降权执行固定阶段、登记外部审查任务，再释放锁给原管理器。重复认领不重付；待采用文件未变时不重复调查。实际服务器已单独验证setpriv直接执行后uid1000、gid1001、Docker补充组988、能力集全零及NoNewPrivileges，未调用模型。原管理器前新增完整协调/五阶段/交接摘要准入校验；私有收据缺失不会仅凭入队文件付费。撤回只处理尚未登记且身份完全匹配的自有文件，先保留原字节和意图；失败历史不删。管理员导出有完整指纹、阶段证据和独立控制器版本记录，汇总不重复计费。这批服务模板仍未在服务器启用；完整native/SDK及独立审查、候选完成后复查、发布观察和业务回退仍待完成。


## 本轮新增完成阶段输出（源码，尚未部署）

- 原始 manager 任务/dispatch/冻结模板与停机 SDK、工具账本、费用前缀共同认证，才能签发独立候选评审许可。单纯绿色测试、模型 approve 或历史许可均不够。
- 六项工具及阶段权限不变。新增的是主机固定 no-model 投影阶段：开发工具原顺序、失败反馈摘要、基线/最终检查、候选变更和 no_release；父任务关联与次日计划不重复统计模型费用。
- 原 root 源码许可摘要和到期时间进入候选评审的实时校验；新审核运行时可使用匹配的新代码，依赖摘要保持原值，完成开发配置和原证据不被改写。
- Root 在共享锁内向原固定次日 registry 追加精确候选/源码/gold/案例/审查摘要，并更新原 env 引用；最多32项，保留原条目。先保存双配置原文和 intent，配置对更新中断即留作不确定，不覆盖历史、不重付费。计划与真正到期结果分开输出。
- 停止、未决、取消与放弃开发另留父任务观察，尚未完成完整认证的费用和工具计数保持 null/range_complete=false；部分原始会话和工具反馈私有保留。不会冒充完整开发审计。

源码新增能力不是线上验收。当前服务器仍是有限8d1802af版本；main/产品发布和实际业务回退、24–48小时验证仍未完成。
