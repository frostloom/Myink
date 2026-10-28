# Pi 审计只读合同 v1

此接口供 main 后续管理员 API 消费。数据标记 authority=audit_only，不授予模型调用、费用、文件读取、审批、发布或回退权限。本分支只提供数据与 reader，尚未接入管理员页面。

## 发布与读取

可信主机调用 AuditStore(private_db).append(record_key,record)，随后 export(private_directory)。库父目录0700、数据库0600，与原 manager/费用库分离，SQLite user_version=1001。稳定键相同输入幂等，不同输入拒绝；清洗前输入摘要只留在私有库，管理员导出只含清洗后事件。

目录结构为 manifest.json 与 pages/<sha256>.json。每页最多100个事件、1MiB；manifest最多8MiB、10000页，包含 schema_version、authority、generated_at、watermark、pages、runs、days、snapshot_sha256。哈希均为排序键、ASCII转义、无空白、禁NaN的UTF-8 JSON SHA256；页名为实际页字节摘要。清单最后原子替换并fsync；旧页保留，失败不覆盖最后可用清单。哈希检测损坏，不能证明恶意主机写入者的诚实，也不是签名或外部时间戳。

main 使用 src/myink/pi_audit.py 中的 AuditReader(root)，仅依赖标准库，不加载 Pi 或费用执行代码，不连接数据库或模型。构造时验证完整链、所有页和索引。读取已绑定快照；新清单发布后新建 reader。调用失败应显示“审计不可用”，不得转换为空列表或通过状态。

- runs(limit=25,offset=0,day=None)：运行索引。
- events(run_id,limit=25,offset=0,kind=None)：按序号返回该运行的事件，包含工具流转、分析、修复、测试与失败。
- enhancements(limit=25,offset=0)：按 details.reference 返回最新增强条目。
- daily(day)：上海日期的版本、变更、发布状态、计数和次日测试关联。

events流式扫描，只保留请求窗口；无kind过滤时使用已验证索引总数并在取得窗口后停止。daily聚合正文上限8MiB，超出显式报错并要求按run/events分页读取，不截成虚假的完整日报。

分页结果为 items,total,limit,offset；limit为1至100的整数，offset为非负整数，bool拒绝。未知运行抛 LookupError，非法/未知schema/重复JSON键/哈希错误/缺页/链接文件抛 ValueError 或 OSError。page路径仅由校验后的摘要派生。文件路径和源码路径不是读取主机文件的授权。

## 事件与证据

固定字段：schema_version=1、authority=audit_only、sequence、record_key、event_sha256、previous_sha256、recorded_at、occurred_at、day、time_basis、run_id、kind、status、mode、evidence_domain、summary、details、version、changes、evidence、followups、redacted、truncated。最大32KiB，未知字段拒绝。

kind包括 observation、analysis、plan、review、tool、development、test、deployment、rollback、followup、version、enhancement、memory。status包括 planned、running、passed、failed、blocked、uncertain、skipped、no_change、insufficient_evidence、candidate_ready、no_release、rolled_back。

mode为ACTUAL/SIMULATED/UNKNOWN，证据域为online_business/real_provider_fixed_input/offline/synthetic/unknown。真实模型固定输入实验不等于线上业务改进。online_business要求ACTUAL，但仍应检查具体收据，不能仅相信模型文字。

summary最多2000字符，details是闭合白名单，文本最多1000字符；不接收任意原始JSON。计数为非负整数或null，bool不作计数。duration_ms有限非负，range_complete为bool。known_cost_microyuan等每轮计数是该run的累计快照，不累加重复观察；费用权威始终是原账本。零与未知null严格区分。未知历史occurred_at保留null，day依据recorded_at并标time_basis，不能冒充原事件发生日期。

version固定包含source_commit、base_commit、candidate_sha256、controller_sha256、policy_sha256、sdk_version、model_id、deployment_id、generation、owner、image_ids。未知为null，image_ids未知为空映射。相同源码的不同deployment_id/generation分别展示。

changes是相对冻结基线的累计diff：path、category(production/test/docs/config)、added、deleted；增删未知为null。daily按candidate摘要及path保留最后一次快照，不把同候选重复报告累加；无候选摘要的记录不能推断相同。路径必须是无上跳的相对POSIX路径，仅作文本展示。

evidence每项仅kind、sha256、verified、evidence_domain；不导出宿主路径、密钥、完整会话或正文。原材料留私有证据区。summary/details清洗常见密钥、Bearer及带密码URL并标记redacted/truncated；这不是对任意文本保密的保证，生产者必须先做白名单投影，禁止把原始请求全文直接放入摘要。

## 每日与次日输出

daily包含day/timezone、event_count、unknown_occurrence_count、runs、versions、change_scope、next_tests、release_state、release_runs、known_cost_microyuan、observed_samples。release_runs保留各run的发布状态、事件摘要、发生时间依据和部署身份；其他run的no_release不能抹掉真实发布/回退。真实操作优先于未发布结论，已知occurred_at按发生时间排序，迟到导入不覆盖更新事实；仅当无已知发生时间时才以追加顺序展示记录状态，仍标记其time_basis，不能视为真实部署时间证明。一天无记录返回event_count=0、release_state=unknown；不虚构版本或成功发布。开发通过不等于发布。真实明确no_release才显示no_release；只有ACTUAL线上发布passed/回退rolled_back事件改变为deployed/rolled_back。模拟发布不改变真实发布状态。

followups每项固定test_id、scheduled_for(UTC)、target_run_id、target_version_sha256、criterion、kind(regression/metrics/quality/restore)、status(planned/blocked/insufficient_evidence)。计划永远保留原状态；执行结果另存test事件，在details.test_id关联。daily只关联计划之后追加、ACTUAL、运行与候选摘要匹配且已知occurred_at不早于到期时间的结果。晚到、跨日结果可以显示；缺时间/错版本/模拟不冒充次日测试。result为空就是尚无合格执行证据，非通过。

## 管理员接入边界

后续main API必须复用真实Bearer管理员身份逐次检查、no-store和访问留痕，以只读挂载读取导出目录。不要公开静态托管、把模型文字当HTML、自动打开源码路径或执行建议。权限与页面在codex/admin-control-plane维护。此合同不授权main合并或产品发布。
