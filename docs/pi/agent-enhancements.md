# 从裸 Pi 到 Myink 受控维护执行器

更新：2026-10-29。此清单区分代码能力、服务器已部署能力和仍待接通的线上闭环，不把执行器在线称为管理者完成。

## 模型与主机的职责

裸 Pi 通常可直接使用文件和shell工具。Myink由可信主机控制器固定Node24.22/Pi1.1运行时，以RPC接入；实际服务器runtime005是封闭哈希运行时，独立审计audit004和只读采集observer003已另外部署。模型不持有原上游密钥、Docker socket、生产写凭据或Git/发布权限。

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
