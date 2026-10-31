# Pi 真实开发恢复与用户反馈判断

日期：2026-10-13（Asia/Shanghai）。承接已批准 Pi 架构与实测计划；用户本轮明确要求开始真实开发和质量对照、分析反馈并识别危险操作，之前要求自主实施、不再逐项询问、验证后分批推送 GitHub。新增设计依该授权由主代理决定，不把流程重复批准作为阻碍。

## 目标与边界

在现有隔离功能分支完成首次真实模型补丁/候选机械对照，同时使可替换管理 Agent 能看到用户反馈、判断其合理性与处理范围。主工作区不改、服务器 Pi 不启用、不发布产品新功能。新产品功能仍由产品负责人决定。既有 18 个 B12 待验收文件保留，不纳入本轮提交或原生实测源码。

累计预算 local-trial-1 为100次/20元，原32次尝试与10254974微元保守费用/预留保持；analysis15/develop45/experiment30/reserve10不变。恢复无需新增 paid-plan，不把规划请求改算experiment。新的无工具反馈质量评估是experiment，需要独立冻结输入、标签、判断标准和绑定后才调用。模型凭据只由既有宿主网关读取，Pi 不获得密钥、任意SQL、shell、Git、备份、数据库写或发布权限。

## 方案选择

继续重新完整规划会消耗仅余2次reserve，无法容纳此前4次规划链；用旧计划成功包装会篡改失败事实。因此采用：query_only认证008的真实提案，仅作为历史数据 → 对新候选独立审查 → 新恢复授权与fresh隔离证明 → develop剩余37次内的真实开发。旧008总宿主失败状态始终保留。与改Pi核心或放宽工具相比，此路径复用官方接口与既有权限，改动最小。

反馈直接塞入开发提示词会混淆证据和授权；只做关键词拦截会误伤合法删除按钮报错。因此采用独立只读脱敏快照、无工具分类、宿主风险否决和既有开发能力限制共同约束。反馈可转为调查线索，不能直接授权修改。

## 真实开发恢复

新私有009副本独立BACK/VISIBLE/unitprefix/epoch；Pi/Node/Python仅复用已校验安装字节，不复用旧gates/进程证明。保持checker128MiB/Pi384MiB、swap0/CPU50%、caps0/NNP，以及原时间、大小、网络、并发限制。

历史adapter只绑定ControlledTools.lookup/_current原方法，不构造ControlledTools或Ledger。ledger.get使用SQLite mode=ro/query_only固定BEGIN和Ledger._record，仅做参数化SELECT。按原POSIX root/session/candidate/base/owner/generation计算绑定，通过新版verify_stopped_phase核验008真实adapter Receipt、session、rpc和已停止Pi单元证明。核对完整after008快照、原源码与各证据哈希，只选当前008唯一合法计划。新certificate明确retrospective/historical008，旧整体监督失败，无fresh权限。

新的develop-only grant绑定该certificate、after008完整前缀、有效20元增补、source23映射与selector源码覆盖，以及新的source closure和独立审查。只追加一个恢复审批operation与两个审计事件，不修改原记录。新候选从原capture-baseline-001字节创建，新独立plan review和工具approval绑定新candidate/root/generation，不伪造旧paid-plan成功wrapper。开发提示词提供计算后的真实plan_hash。

真实Pi通过已准入工具写单文件src/myink/admin_observability.py，之后必须candidate_status和最终候选ACTUAL unit run_check；宿主停止会话后独立核验apply_patch与最后一次补丁之后的检查。相同source/config/rubric/input冻结后逐次跑baseline/candidate，保留全部失败与护栏。52个既有合成机械案例及披露holdout只能证明capture完整性，不证明写作语义改善。失败或耗尽即保存证据并诊断，不重复同一mutation或清零费用。

## 用户反馈

反馈表为账号级，不能假定project RLS。SnapshotCollector新增明确admin_scope=True的可信只读采集入口；未授权拒绝，模型不得传scope/SQL/window/cursor。固定SELECT投影仅id/category/description/status/created_at/updated_at，禁止contact/user_id/username/user_agent/附件路径/字节。page_url不提供给模型，也不访问URL或附件。数据库事务READ ONLY，固定参数查询/服务器timeout<=5000ms，单批最多50行，LIMIT51检测has_more；updated_at,id键集游标绑定冻结window和scope。首次回溯窗口由控制程序配置；超出批次明示未处理，不称全部反馈已经读完。数据库列级SELECT授权示例写入维护文档，真实PG权限验收另列NOT_RUN。

独立feedback.py冻结视图保留feedback_id/字段指纹/描述全文或明确脱敏截断信息。description<=2000字符；秘密模式脱敏。所有文本标为用户声称、非事实、非指令、无权限。快照哈希、重复ID、越界时间、坏UTF8/非有限JSON/伪引用拒绝。

无工具triage返回每条准确ID的严格JSON，区分既有功能缺陷、需补证据、新功能、账号/作品服务请求、安全报告、不安全请求和无关反馈；引用必须来自同一条保留描述，不能拼接/捏造。模型不输出路径/命令/URL/权限/审批。模型判断为建议，宿主统一输出automatic_execution=False/candidate_allowed=False；现有功能缺陷的路线为investigate，不叫confirmed/resolved。新功能走owner_decision，合法删除本人数据走existing_user_service，不由开发Agent执行；危险删除系统/数据库、删他人数据、绕过鉴权、关闭审计等走deny或security_review。

规则仅对明确危险要求否决，含危险词的引用、负面报告及“删除按钮失灵”不能一概拒绝。对编码/混合指令/语言不确定者保留风险与需补证据；模型即使误判也不能获得危险能力。安全统计分别报告模型误分类、正常报错误拒与最终权限拒绝，不能把工具拒绝计作模型识别成功。

合理缺陷必须用反馈ID+fingerprint关联独立复现失败证据，经固定窄Plan、审批、补丁、测试和对照后才可修正；目前没有task/project外键，不能根据URL/时间/用户名猜出跨用户关联。首版不修改反馈status、不自动回复或取附件。

统一分析接入沿用experience域：受控bundle可新增feedback最多50行，只description进入证据；固定categories同步experience以免队列死循环，source/fingerprint引用校验不变，11domains/45未知质量目录不变。后续语义质量评估不能用代理生成的自评标签作为gold，需先冻结独立规则/标签与样本身份。

## 验收与维护

恢复TDD使用真实ControlledTools/SQLite产生历史提案后转query_only，断言无写/无模型/历史不变；篡改args/receipt/binding/hash/identity、旧007、多当前提案、坏停止证明、改写旧成功状态、新候选漂移、未审源码、错会计类别均拒绝。fresh gates与真实开发结果另记，不能用模拟fixtures冒充kernel证明。

反馈合同TDD覆盖真实固定SQL与范围/分页/窗口/隐私字段；来源/引用/哈希篡改；删除系统 vs 删除按钮bug/合法本人删除/引用危险命令；混合要求、伪system/命令/URL/路径、Unicode、超限/重复ID。真实工具护栏测试用ControlledTools/SQLite，不mock accepting lookup。聚焦测试后运行干净源码离线ops套件，明示SKIP/live排除。数据库集成与业务全量只有实际运行才算通过。

源码、私有运行证明、公开报告分别保存；GitHub仅分批提交功能分支，保留主工作区与B12。每轮记录准确请求数/已知估算/未知预留、实际补丁与测试、模型识别与最终拒绝的区别，避免长期维护者把“有接口”当“已上线”。
