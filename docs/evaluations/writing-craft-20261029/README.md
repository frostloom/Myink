# 写作指导深入改进：实测与发布门槛

2026-10-29。用户要求改进章节衔接和文风、删除四套旧示例文风，继续寻找与实际测试，达到效果再推送上线。

**当前状态：尚未提交、推送、发布。用户已授权继续改进，达到稳定性门槛后上线；当前仍在隔离评测。** 生产仍为上一轮后端 d25d8275、前端 a8a4361e；本轮临时容器只读配置与公开资源，不创建作品、任务或 AgentRun，不消费队列。

## 来源与候选

详细来源见 [写作来源说明](../../WRITING-QUALITY-SOURCES.md)。深入参考 jwynia 的场景衔接、Chinese Novel Writing Skills 的正文与人物声线指南、xin-yi33 的正反例教学。只原创改写方法，没有导入上游工作流或示例正文。

候选1：前章后果/人物状态 → 反应与选择 → 下场目标；原创表达示范、三种更丰富通用文风。
候选2：候选1加本章结果核对，避免把要求当场发生的事推到明天。
候选3：候选2加动机/用途保真、数值证据与动作空间复核。

本轮不以来源日期、规则数量、禁词数或同模型自评证明质量。测试范围是三个合成场景；未使用任何用户小说原文。

## 实际模型与方法

- 生产当前普通/VIP writer、audit 均解析为 `deepseek-v4.1-flash`；管理员当前有两条启用的 Flash 连接，没有已配置的更强模型。
- 生成温度0.7，模型盲评0.2，输出上限2400 tokens，目标650字。未启用思考。
- 使用真实 `prompts.write_messages`、资源绑定、已发布题材/精调和角色模板；不只测试字符串拼接。输入固定，顺序轮换，盲评随机映射。
- 第一轮：已发布基线 / 仅衔接 / 衔接＋表达示范＋题材匹配通用文风。
- 第二轮：已发布基线 / 候选1 / 候选2。
- 第三轮：已发布基线 / 候选2 / 候选3。
- 每轮9篇对比、3次模型相对盲评，再生成其临时排名赢家的3篇复测稿。第二轮候选1/2并列，脚本按固定顺序选择候选1复测，不是候选2已证明胜出。
- 独立审查者只读匿名原稿和事实要求；不读身份映射或模型排名。主代理揭盲后核对。每轮12篇，不只保留最好一篇。
- 这是小样本、有限题材及固定连接的探索实验，不是统计显著性研究，不代表所有小说/模型。

## 结果

| 轮次 | 模型盲评临时排名 | 独立检查与决定 |
| --- | --- | --- |
| 1 | 组合候选胜出两类，衔接候选胜一类 | 组合候选悬疑/修仙的对白、空间与选择较好，现实基线更好；复测仍有用途、绳路、自相矛盾问题，未通过发布门槛 |
| 2 | 两候选并列 | 没有候选原样满足全部验收；现实用途/关门/共同核账失守，悬疑有无依据的校时发现，修仙仍有空间跳跃 |
| 3 | 候选3胜两类 | 12篇仅U04（候选3修仙复测）完整通过本轮严格事实/逻辑/结果门槛；另一次同配置未通过，不能证明稳定 |

独立审查区分：改写给定事实、样本自身逻辑矛盾、遗漏本章结果、一般风格偏好。合理新增道具/后续发展不直接判事实错误；关门可以先于核账，无须在最后一句重演。各报告列出具体证据，仍存在编辑判断的主观性。

额外用系统实际 `audit_messages` 消息构造（相同固定Flash连接、关闭思考）检查候选1与候选3的各三篇首稿，共6次；audit 全部判 pass，所以没有触发 `revise_messages`。脚本没有强制改稿来美化结果。它漏过了独立检查定位的用途、数字方向与动作问题，因此也不能用“现有审核会修好”作为发布理由。这不是6次“审稿修订均通过”，而是**6次审核均放行、未执行修订**。此次调用没有执行数据库台账L1/L2、工具查询循环或其他节点，不能当作生产整章端到端回放，也不能据此断言所有线上审核均会漏报。

## 请求与成本限制

| 实验 | 实际HTTP请求（含重试） | 返回input tokens | 返回output tokens |
| --- | ---: | ---: | ---: |
| 第一轮 | 15 | 29474 | 12410 |
| 第二轮 | 15 | 13325 | 11982 |
| 第三轮 | 15 | 13903 | 12125 |
| 审核链路 | 6（上限12） | 20441 | 3816 |
| 合计 | 51 | 77143 | 40333 |

以上为API响应中已记录的用量字段。Anthropic兼容接口可能把缓存命中/创建输入另计，当前provider返回的ModelResponse未完整保留这些字段；**不能把表中input当全部计费输入，也不能把部分记录的cost_est_cny当实际账单**。已知价格表不代表完整费用已核算。精确费用以供应商账单为准，没有宣称免费或零成本。请求hook限制实际HTTP次数，避免隐藏重试超上限；所有运行均自然结束，无截断被当成功。

## 本地代码状态与保护

准备但未发布：

- 内置列表只留三种通用文风；四旧ID的新选择返回404，不再由seed创建当前平台条目。
- 缩小后的定向发布脚本只允许升级3项当前定义（continuity、writer/planner角色默认），新增1项现实/悬疑落笔规则、删除4项当前旧示例条目。先检验全部条目与审核过的旧定义完全一致，遇管理员草稿/自定义立即拒绝；单事务、CAS发布、可幂等重跑。
- 删除的是当前平台目录记录；保留历史revision/publication数据库行、私人副本、作者小说/章节及冻结快照。退役后旧四项管理历史API因无当前条目返回404，这是当前退役语义；历史数据仍可在备份/数据库审计中保留。
- 新版资源不会静默改写历史出版版本，旧作品不自动套用新文风。最终本地候选保留原有三种通用文风；没有把评审未胜出的更长档案替换进去。表达教学缩小到现实/悬疑题材，修仙不叠加该段。
- 独立代码审查发现旧冻结writer/planner默认模板会恢复旧强制章末规则；已加入精确历史片段兼容，仅在资源已配置时去掉默认可选片段。旧资源本身的冻结规则仍保留，未配置路径不变。回归先复现失败，再修复。

本地测试最终结果另见 `verification.md`。这些检查验证接入/发布安全，不抵消写作效果未达标的结论。

## 证据文件

- `cases.json`：三类场景事实和目标。
- `inputs-1/2/3.json`：各轮候选具体文本与配置。
- `round-1/2/3.jsonl`：原始生成、模型评语、复测与请求计数。
- `blind-review-1/2/3.md`：独立匿名审查。
- `labels-1/2/3.json`：审查结束后揭盲映射。
- `inputs-audit.json`、`audit-pipeline.jsonl`：额外现有审稿链路检查；未强制修订。
- `usage.json`：响应字段汇总，不是完整账单。

用户进一步选择只用现有模型继续改进。后续实验将“事实/计划履约”与“风格润色”分开验证，暂不增加或更换模型。当前没有足够证据将任一候选称为“最好的通用文笔”，不发布未通过候选。


## 后续实验与最终验收（全部未部署）

用户明确选择**继续只用现有模型**，没有增加或更换模型。后续对照也全部使用同一已有Flash连接。

- 加强审稿措辞、逐项要求、逐项举证：仍大量放行已知问题，没有作为新运行时审核机制接入。
- 将事实校对与风格评价分开：开始抓到用途改写，但也把正常后续状态变化误判成矛盾；加入时间/状态解释仍不可靠，没有接入运行时。
- 新增三题保留题，提前由独立审查确认口径。**第一轮保留题作废完整门槛结论**：脚本拆分expected_events时漏传完整must_end，评审却按完整题验收。原始记录为`holdout-incomplete-input-invalid.jsonl`；不是因为结果不好而改题。已补真实消息到mock provider的回归，先红后绿；每次付费生成前现都断言facts、goal、previous_tail、全部expected_events/must_end实际到达最终消息。
- 原题完整输入重测12篇：10篇完整通过，但文风并未显示更长方案稳定胜出。两次缺少共同坐桌的动作仍未通过；详见`blind-review-holdout-complete.md`。
- 结果提醒移到请求末尾后比较15篇（基线每题1篇、两候选各两篇）：9篇完整通过，原有自然文风并非稳定劣于新文风；修仙基线文风排名第一，现实/悬疑有单篇改善，但未证明整体稳定改善。见`blind-review-completion-layout.md`。
- 最后缩小真实候选：原有自然文风、简短连续性、末尾结果提醒、只在现实/悬疑叠加落笔教学。从实际新源码原生amd64镜像、真实builtin资源/角色模板/genre_rule路由生成每题两篇，共6篇。**仅P06完整通过（1/6）**。其余有管理员权限矛盾、未共同坐桌、药袋初态变化、返回路线未兑现。见`blind-review-candidate-native.md`。这是最终实际接入方案的效果门禁，未通过。
- 又试同一模型先产首尾段框架再写全文，6篇、12次请求。仅2/6逐字遵循框架，忽略换行后为3/6；独立完整验收仍仅B05通过（1/6）。框架还会先写错初态，故**没有实现/启用新的首尾框架运行时阶段**。见`blind-review-frame-experiment.md`。

**共140次实际HTTP请求（包含重试），记录到174855 input tokens、100659 output tokens。** 所有原始用量见`usage.json`，缓存字段/实际费用限制同前，不能当完整账单。后续实验/作废轮次也全部计入，没有删除不利样本或仅展示最佳篇。该阶段结束时暂停模型调用；用户随后授权继续，新增逐项检查与修补实验见下。现有证据不支持宣称文笔已稳定提升。

工程最终全量为**2233 passed、1 skipped、5既有xfailed、2 subtests passed**，267.18秒；针对性135项通过。发布前所需文学效果门禁未通过，因此没有提交、推送、构建正式revision发布镜像或执行目录删除/发布事务。只生成了独立的`myink-api:craft-evaluation`测试镜像，没有改`myink-api:local`或现有运行容器。

最终只读核对线上身份仍为：API/两Worker `d25d82752d4821ae701f3ed7ebbffea01b4b63f7`，Caddy `a8a4361ec1a9d3b5b8aa82ffa081f006d542ed82`。旧四平台当前记录仍在生产；只在本地目录与种子候选中移除。测试服务`myink-test`已安排清理，评估临时容器均使用`--rm`。


## 后续：来源校对与有界修补原型

用户明确要求仅用现有模型继续到稳定后上线。后续将事件拆分、观察、服务端判断期望极性、局部补丁、再次观察分开。新资料在[proof-loop](proof-loop/review.md)；未接入写作运行时。单条事实的平衡校准12/12正确，但含联合动作/否定句的泛化校准暴露误判。人改的正反控制只校准检查器，不算自动创作成功。

已记录的后续实验：20次校准、两次各1请求的初始编译诊断（在服务器）、24次逐条观察、3次批量补丁拒绝、5次整稿回退、5次现有另一Flash对照、4次正反例修补，以及6案例首轮16次请求。合计新增79次，连同前阶段140次为**219次实际HTTP请求**。用量中本地已收集77次，详见`proof-loop/usage-local.json`，两次服务器编译诊断的完整原始用量尚需收集；缓存/费用限制同前，不把这些数当完整账单。

首轮六例仅现实两例完成修补并通过模型复查，其余四例在来源覆盖环节被挡住；这是2/6完成，不能按2/2通过报告。独立审查认为两篇坐下补丁合理，但仍有自然动机误判、语义保真、结束状态和泛化不足，见独立审查记录。没有因单例成功而发布。

本地新增来源/批量证据/时态区分等测试，针对性25 passed；此前2233全量结果属于新helper之前，不能视为已验证新集成。该组纠错评测曾因自动审批超时暂停；用户后续明确批准，实际结果见下。生产版本与四套旧资源的实际状态仍未改变。


## 明确批准后的连续验证：仍未达到发布条件

用户批准继续隔离测试后完成纠错16次、v1语义保真19次、v2限定/证据复核35次、v3重点验证22次、语义正反校准6次，合计98次请求尝试。连同此前记录，累计**317次HTTP请求尝试**（含重试，非成功数或账单数）；全部后续177次已收齐，精确文件校验与已报告用量见[usage-all.json](proof-loop/usage-all.json)。失败/截断响应可能缺少用量，缓存/费用仍不完整，不估算最终账单。

| 实验 | 结果与真实限制 |
| --- | --- |
| 一次来源纠错，六例 | 仅P03走到模型pass；其余来源丢失、引文不精确或超出条目上限。不能自动放行 |
| v1，六例 | 仅P02模型pass。语义核对把拆分本身误当语义改变；其余还有引文协议失败 |
| v2，六例 | 模型报告五例pass，P04协议失败。**人工复读发现P01口令矛盾、P05自己来路遗漏都未修，属于两个错误放行，不能报5/6成功** |
| v3，三例重点验证 | P01前提证据编号非法，未进入修补；P05完成修补/复查但final仍false且改错重点；正确P06被过严证据复核误修，随后协议调用失败/截断。没有建立稳定闭环 |
| 最小语义校准，六例 | 5/6与预先标签一致。**联合动作遗漏乙坐下的负例仍被判faithful**，这个最小反例足以否决自动语义门禁 |

本地来源、作用范围、严格布尔/编号、原文证据引用、全来源语义结果与私人文风等针对性检查**40 passed**，`git diff --check`通过。没有把这些工程测试当作文笔验收或新全量回归。未启用任何新运行时阶段；原型明确未接入线上。

服务器只读核验：API/两Worker仍为`d25d82752d4821ae701f3ed7ebbffea01b4b63f7`，Caddy仍为`a8a4361ec1a9d3b5b8aa82ffa081f006d542ed82`。评测临时容器使用`--rm`，无生产任务、作品、队列投递、模型路由或资源发布事务变更。尚未提交/推送/部署；旧四套资源仍未在生产退休。

下一步涉及产品取舍，已询问是否接受“新章先待审核，作者确认后再推进后续章”的流程；该取舍不是再次请求服务器测试权限，也不代表增加人工环节即可宣称文笔提升。若保持全自动，当前候选仍不具备上线证据。

## Latest full-automation research checkpoint

User rejected mandatory author confirmation; existing-model-only and fully automatic workflow remain the requirement. Current work is still unreleased. Protocol probes confirm both configured connections are Anthropic; unrelated OpenAI reasoning-as-final fallback was excluded from the active path. Explicit high thinking catches the supplied missing-person negative but paired calibration remains10/12complete-correct due to two output failures; low thinking achieves6/6on those hand-inventory controls. These narrow results do not establish prose quality. Broad actual audit still misses shared seating, and full-source thinking compilation repeatedly exhausts its token budget. Research now separates ordinary structural compilation from low-effort factual judgments with fixed request limits. No automatic runtime integration accepted.

Original P01 password case now has independent reviewer disagreement: character denial can be evasiveness rather than an author-world fact. Old label/results are preserved. Added P07 authoritative source/narration negative to retain a genuine hard contradiction test. Correct P06 remains a no-unnecessary-edit control. See action-matrix protocol, raw logs and README for labels and failures.

New output-integrity fix: finish_reason=length cannot pass _llm_checked even if a JSON prefix parses or prose is nonempty; existing corrective-retry bounds remain. Full regression2264passed/1skipped/5xfailed/2subtests, plus related45passed after two added stream/bound tests. This is engineering evidence only. Commit/push/catalog update/deployment remain pending the unmet quality gate.

## 2026-10-30：全自动研究续验，仍未发布

保留现有 Flash 连接、全自动目标。未启用强模型或作者必审。此次追加136次有上限HTTP尝试，累计767次；包含所有失败、截断和重试，响应字段用量见[逐实验记录](direct-source/confirmation-usage.json)，不等同供应商完整账单。

- 审稿意见复核与新对照分别10/10、12/12匹配预先标签，但解释仍有漏证和附加推断；不能称为全章语义准确率。只复核失败条目还会漏掉初次错误通过。
- 自动专项发现曾把明确原路要求判为none，后续完全相同输入又正确；成功回放未覆盖原失败。
- 补丁普通/低思考模式独立盲审各2/4成功，共4/8；没有切换全局模式。
- 顺序单审+复核、单补丁事务试验均触及32次上限，没有finalpass。阶段目标通过不等于全文验收。
- 双审对所有原始要求批处理、程序负责源ID归属后，单P05稿23次完成模型finalpass；独立匿名审查却仍判候选uncertain。本人来路已补好，风术托袋、收绳与越棱的动作歧义未解决，文笔没有明显提升。详见[匿名效果审查](direct-source/symmetric-P05-blind-review.md)。不能报稳定成功或发布。
- 新时间控制S03原uncertain标签经独立 reread 有争议（倾向实际violated）；保留原标签和判定变化，不把它计作明确模型共同误判或事后成功。无效源引用批次已单独标明；程序源ID修正仅补测该批1次，正确，不抹去原失败。

独立审查与无模型编排检查验证了对称覆盖、失败回滚、截断重试耗尽、预算异常、终验hold，以及诊断与候选稿对应；这些证明程序保护，不证明模型语义或文学效果。所有专项检查器仍未接入运行时。P06/P07下一组对照仅准备，未执行，因为P05尚未通过效果门禁。

另外实证复现并修复运行时输出完整性漏洞：node_patch绕过_llm_checked，曾应用length截断响应中的闭合首个补丁并发成功artifact；现在在解析/应用前拒绝截断，发失败artifact，不写入applied spans/成功正文。真实_llm的调用记录和原始响应快照仍保留供审计。provider error优先，无额外调用/重试，正常stop缺少advisory RESPONSES仍保持原兼容行为。新测试先红后绿，独立审查未见具体回归。

本次最新完整Python回归：**2275 passed、1 skipped、5 xfailed、2 subtests passed，2既有warnings，274.98秒**。日志[regression-patch-truncation-20261030.log](regression-patch-truncation-20261030.log)。此前2272/2264等数字仅为历史阶段。未改Go/前端，本轮未重跑其门禁；没有将其报告为通过。git diff --check通过。

未提交、推送、合并、目录发布或部署。线上只读核对API/两Worker仍d25d82752d4821ae701f3ed7ebbffea01b4b63f7，Caddy仍a8a4361ec1a9d3b5b8aa82ffa081f006d542ed82，均running。旧四资源生产退休仍待效果验收。本轮测试仅使用专用PG15432、Redis16380、RabbitMQ15673，回归后清理。
