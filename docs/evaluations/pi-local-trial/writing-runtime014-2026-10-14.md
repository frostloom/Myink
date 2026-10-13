# 本机 Pi 写作014：十阶段已完成，语义质量仍未知（2026-10-14）

014十个独立模型阶段、writing-finalize及精确keeper清理全部完成。每阶段一次真实HTTP200、一条usage记录和所属进程树清理通过；十stage140文件与finalize4文件共144个物理导出文件的长度/raw SHA已核对。模型tools和自动执行权限为零。

前八阶段（事件、情节、人物、抽取各两arm）均schema_failed，逐响应11unknown/0已接受refs；09/10任务运营分析有效，各两条连续字面引用、十个非目标域unknown。有效只说明严格格式/引用合同通过，运营观察及模型意见仍provisional，不是语义质量改善。

| 原五组配对结果 | baseline | candidate |
|---|---:|---:|
| planned / observed / NOT_RUN | 5 / 5 / 0 | 5 / 5 / 0 |
| 有效分析 | 1/5 | 1/5 |
| schema_failed，保持unknown | 4/5 | 4/5 |
| 连续字面引用接受数 | 2 | 2 |

双方共同有效组仅1个（operations），其余4组均未知。没有质量提升差值、有效率优势或独立semantic gold；45个原语义metric全部unknown。十阶段没有修复或重试原输出，HTTP200不把schema_failed升级为valid。全部聚合和逐stage hashes见[机器可读报告](writing-runtime014-2026-10-14.json)；[013反馈实验](feedback-runtime013-2026-10-14.md)是不同合同的历史对照，不混算写作质量。

## 统一留存：11域能说什么

冻结30天窗口2026-09-12T00:45:16Z至2026-10-12T00:45:16Z；27任务=19正文+8短篇，13项目。298条run中274条关联这些任务（正文252、短篇22），24条未关联，不能强配任务。真实只读导出留存不是作者真实性证明；human versus historical fixture未认证。当前memory/settings/chapters是observed_now，不冒充历史召回，snapshot也可能选择性留存/覆盖。

| 固定域 | 实际可观察口径 | 未解决限制 |
|---|---|---|
| 事件recall.events | 有限返回context与事件章节字段；当前events36 | 相关性/覆盖/矛盾/未来泄露/遗漏5项unknown；无当时eligible gold，有限未见未来事件不等于零泄露率 |
| 情节recall.plot | 留存context中plot_threads为空，当前表3条；foreshadows27 | 不同项目/时点不能直接相减作漏召回；同5项unknown |
| 人物recall.characters | 当前characters22/states42；初始recall和后续plan_cast分别统计 | 初始空快照不能判断人物召回坏；后续6组有4/3/5/4/5/3快照；同5项unknown |
| 事实recall.facts | 当前facts21及有限context | 当前事实集合不是历史gold；同5项unknown |
| 抽取extract | 9条保留raw响应全部truncated，关联留存6任务 | 支持/遗漏/冲突/身份/时间/旧值/持久化7项unknown，不能解析成完整JSON或从当前75候选反推原结果 |
| 正文write | 14任务有留存write stage但capture均截断；当前chapters12 | 文风/人物/节奏/连续性/约束/闭合6项unknown，缺完整历史版本和同输入双输出盲评 |
| 审核audit | 23任务有留存stage；至少14个有截断，其余仍有capture未知 | 检出/误报/严重度3项unknown；模型审查意见不是独立正确性证明 |
| 修订repair | 8任务有留存stage且均截断；可描述patch/audit循环 | 解决/新错/遵循3项unknown；重复调用或相同token数不能证明修复成功或no-op |
| 工具tools | 正文21条run有选择性tool trace，短篇工具证据unknown | 相关性/无支持结果/失败恢复3项unknown；不是完整调用分母或成功率 |
| 任务运营operations | status、run记录耗时/token/cost/retry和created→updated代理 | reported/proxy不升级为measured；不新增语义评分 |
| 体验experience（含短篇） | 8短篇任务、6 sessions/32 messages、8条review、6 revised=true | 接受/人工负担/重生成3项unknown，缺真实作者反馈、完整编辑史与修后复审 |

合计45质量项=4×5+7+6+3+3+3+3，全部availability=unknown/value=null；不是“45项失败”或“质量0分”。短篇场景保留在体验/运营等原域，不增造第12域。chapters12/cap12与sessions6/cap6均possibly_truncated；chapter_versions/validation_reports/findings各0只表示本批留存为空，不能推断零修改、零缺陷或无需审核。

## 成功、时间、费用必须保留分母

| 冻结源记录口径 | 正文 | 短篇 |
|---|---:|---:|
| task done/failed/unknown | 14/5/0，分母19 | 8/0/0，分母8 |
| stored-status成功率 | 14/19=73.68% | 8/8=100% |
| reported run时长之和 | 979537ms，252条有值 | 543799ms，22条有值 |
| created→updated生命周期proxy值 | 4717801.1588421045ms，19样本 | 68063.701375ms，8样本 |
| reported cost_est已知部分之和 | 0.6164502，仅124/252有值；完整cost仍unknown | 0.46727594，22/22有值；仍为reported估算 |
| reported input/output tokens | 683878/161280 | 139738/102917 |

任务状态不是作者接受率或线上SLA；失败5个保留在分母，既有有限分析归为4认证问题、1事件schema约束，不据此判模型能力。生命周期包含排队/人工等待/更新，不是模型延迟；节点时长相加也不是任务墙钟。p95均样本不足/null。cost measured_samples均0，缺价格和完整身份，正文128条费用未知，不能填零、重复加snapshot费用或称真实账单。reported task/run retries与degraded均0只代表留存字段；run_errors正文2/短篇0与task失败5是不同单位。014本轮十条usage_known收据的已知估算合计0.189278元；这与原留存数据的reported cost_est口径分开。累计预算尝试66次，已知估算0.575877元，历史未知预留10.065792元，总保守占用10.641669元，不是供应商账单。

## 具体留存缺陷与最小改进方向

recall17条run仅6条具非截断capture记录，即6/17可用性，不是6/17召回成功；另11条缺完整capture证据，不能判成语义遗漏。关联6任务有初始recall和plan_cast context，这又是不同分母。“未标截断”也不保证原历史上下文完整。

extract24条run只留存9条raw响应，9/9全部truncated，其他15条无可用完整raw证据。9条响应都是2912字符且带截断标记；JSON字符串编码只有5887–11458字节，低于响应预留18000字节，体现固定每字符最坏六字节估算提前截断的可避免空间损失。历史尾部不能恢复；不能拼接多个head/tail、补JSON尾巴后算precision/recall/持久化成功率。

合理的最小候选修复是现有capture字符串prefix按真实JSON编码字节选取，连同保守credential boundary scrub；保留scrub-before-clip、ensure_ascii、max_text16000、marker/各区reserve、depth/items、最终encoded-row cap和输入不可变。目标是原预算下的采集保真与秘密过滤边界，不能宣称改进模型语义质量、扩大遥测范围或历史补全。015 owner Plan和独立源码审查只是后续开发前提；Pi必须在独立授权/自己的实际gates中产生真实patch和final check，本文不授权自动运行或生产发布。

## stage01已定位的schema根因

输出是合法strict JSON，11个域名和所有字段结构正确。events和hypothesis的231字符quote在指定excerpt内精确匹配；operations的38字符quote却不在其evidence_index=0/excerpt_index=0所指6394字符excerpt中，首先触发“quote outside one contiguous retained excerpt”。operations可以在observation解释body-free report而不提供ref，但提供的ref仍须真实连续匹配；不能用汇总或推论冒充excerpt原文。

独立第二项违反：本组仅recall.events可为非unknown，原operations却标trace_observation。首项已经使原解析退出，第二项是明确合同违反，不通过修改原JSON伪造第二次执行。整条响应原子拒绝后保持11unknown/0已接受refs；两处可诊断的字面匹配不把整条升级为valid，更不证明意见受独立支持。02–08只记录实际schema_failed，不套用未经独立诊断的首阶段具体原因。

## 冻结与公开边界

源码manifestd02e17833f7ac451b3ab554d165e67aa319a35086772f10dd6e889b7e4599d10；原bundle0f0184fc728d615718f03e2da433fa881b6b20f389a2b7091ed044aed9ded79a；源report0a58a5e69680379c93edfeec6bfe4bd629db32724811648efc67debf91ed65f6。配对manifest raw847beab65e99c49d3fa288ce0a384d2d35ca26d17eb4f8e6998d56052e409a97/content213c9cd8a16d0c647f343026d425c29376f5a5973b57c5545bb179afc99ef535。逐阶段聚合及raw hashes见同名JSON；不发布raw输出/body/UUID/usernames/ledger/grant。

配置模型qianwen-anthropic/deepseek-v4.1-flash/configured-deepseek-v4.1-flash-2026-10-13只证明配置，不是供应商权重证明。工具及自动执行权限为零；RPC analysis、实际计费phase experiment分开，原累计100次/20元、15/45/30/10配额和历史未知占用不重置/退款/重分类。十阶段和finalize均实际完成；完整快照185 operations/303 events，相比013新增21/32，原164/271历史完整保留。model-attempt和phase-admission pending均0，model-scope/phase-fence/preview-fence各一条原合法pending intent保留。analysis原始计数16含旧blocked1，有效transport15；develop13、experiment29/30、reserve8，原配额没有增加。keeper按精确PID745/start871524、同一环境epoch停止，无固定UID残留，old_pid_signalled=false；此结果不验收生产服务。

最终result raw SHA256：`cdc4d5bc603690c32cc5f9384c93fcbff07a88f7e21a1b5b2e1f96e460a732b4`；finalizer supervision：`a2d007a14e88b939b872e2861968c5c4f5f676693fd3736edd23d7d742cf13d0`；终态checkpoint：`dfe50095f01ad50d16f79099e5311e1060bf68f1802250b14847b0d80302184b`；keeper cleanup：`e802311dc53c1d20a00e5778fabbd6581de072e103cdc445a4644e3a38235f95`。私有完整快照和SQLite仅核对raw SHA，没有将账本或grant公开。

原失败/未知未被重试或schema修补覆盖。真实Pi开发015仍待独立实际授权/新SOURCE、whole after014绑定、fresh gates和真实patch/check，不自动运行；013反馈分类的局部观察也不当作014写作改善。生产/main/server/B12验收状态未提升。本次只整理事实，不触发模型/015/提交推送，report历史正文和其他已有修改保留。
