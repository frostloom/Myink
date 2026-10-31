# Pi 线上闭环与管理员审计输出

目标是最初的指标观察→原因分析→受控迭代→独立验证→发布观察→失败调整/业务版本回退，并持续留下次日测试、每日版本及变更范围。2026-10-28 已部署的是受审核队列执行器；不得把它或影子演练当成完整线上闭环。

用户已要求连续执行、不逐阶段确认；本方案沿用Python/SQLite/固定Node24.22/Pi1.1，分阶段原生实现、测试先行、每个独立计划一次新上下文终审。审计是正式数据接口，不依靠最后人工补写聊天总结。

## 不变边界与来源优先级

- 在现有 codex/pi-autonomy-design worktree 开发并按既有授权提交推送，不新建小分支。main 与管理员后台仍按项目规则分工；本轮提供管理员只读消费契约和数据模块，不修改管理员页面/认证或擅自合并main。
- 唯一原费用/manager在服务器 /home/ubuntu/myink-pi-managed/state，旧本地源冻结归档。当前761次=752已知+9原未知，保守占用22816453/50000000微元，未知预留18115200保留。新增审计库不得兼容费用账本schema，不能成为第二个付费scope。
- 旧设计的每日重置、100次/10元和分支创建策略已被较新指令覆盖；累计50元不跨日重置。未知费用/协议/清理异常停止付费，观察和报告仍运行。
- 主机控制器、数据库/发布适配器持有受控权限；模型只拿固定工具、冻结输入和短期阶段能力，不拿Docker socket、生产写凭据、任意shell、Git/发布权限或费用政策写权限。
- 原设计的02:00–06:00上海维护窗口、05:30停止新候选、人工部署优先、预/后备份和真实部署身份仍适用。缺乏实际暂停/恢复、备份、准确版本归属或发布授权时，记录阻断，不执行生产切换。
- 原始正文/会话/密钥仍私有。管理员输出为白名单结构化事实、经清洗有界总结和证据哈希；不是执行/审批授权。没有收件人授权只保留日报输出，不发送邮件。

## 分阶段交付（完整目标保持不变）

1. **审计与记忆基础**：追加不可改的审计事件、脱敏版本化分页导出、可直接由main后续导入的纯只读reader、每日版本/变更与次日测试计划、裸Pi增强清单；先导入已完成真实owner002产生实际数据。
2. **真实采集与自动触发**：复用metrics/observations/db_reader，以独立SELECT视图/非特权角色读取生产允许字段，真正启用轻量采集定时器。身份缺失、样本少、混杂、跨版本都明确标记；不把collector身份补成历史运行身份。异常需要可复现证据才生成新任务；无可信重现时形成调查/补样本任务。
3. **无人逐步确认的审核/开发接线**：复用固定Pi SDK、原费用代理、manager和独立审核机制。模型提出假设但不批准自己；独立审核角色/进程验证冻结source/gold/ledger和边界后放行。失败分类产生关联的新修正计划，不重放旧收费意图；同一基线/假设没有新证据时不重复改动。
4. **生产发布观察/回退与跨日复核**：固定执行器在共享发布锁内核对main/镜像/deployment generation/owner/maintenance epoch，PRE→串行构建→健康与业务探针→POST→开放。仅回退仍由自己持有的候选，人工新版本使旧回退失效。产品合入/发布按现有明确授权边界启用；任何尚未实际启用的环节不称闭环完成。
5. **持续实际验证与接入交付**：故障演练、真实运行/业务版本回退、24–48小时观察、次日测试实际执行与新旧指标比较；精确HEAD四CI、失败/空结果保留、公开脱敏指标。main管理员接入只消费已定版契约和私有只读挂载，不加载Pi执行器权限。

每阶段独立可验证并保留证据。后续计划在前一阶段接口稳定后细化；根目标只在全部所需实际接线成立时完成。

## 审计数据合同 v1

使用专用SQLite追加日志，只有events表/独立user_version，不具备费用operations/events schema。事件以稳定record_key幂等；相同key相同内容返回旧事件，不同内容拒绝。事务中分配序号和前驱哈希，禁止UPDATE/DELETE，导出前验证完整链；不能把哈希链称为抵抗恶意root。

每个事件包含固定schema_version、sequence、record_key、event_sha256/previous_sha256、recorded_at、可空occurred_at、time_basis和上海日期；run_id、kind、status、mode、evidence_domain；有界summary及清洗/截断标记；白名单details、version、changes、evidence、followups。
- kind：observation/analysis/plan/review/tool/development/test/deployment/rollback/followup/version/enhancement/memory。
- mode：ACTUAL/SIMULATED/UNKNOWN。evidence_domain：online_business/real_provider_fixed_input/offline/synthetic/unknown。真实模型固定案例不冒充线上改善。
- summary/details仅白名单、有限长度和类型；拒绝未知字段、重复JSON键、NaN、bool冒充计数、任意嵌套原始请求。密钥/密码/Bearer/带凭据URL不进入导出，明示清洗/截断。模型文本始终不可信，前端只按文本展示。
- version固定包含source/base commit、candidate/controller/policy哈希、SDK/model标识、deployment_id/generation/owner/image_ids；未知为null，不用零或当前版本补造历史。
- changes记录相对冻结基线的完整生产/测试/文档/配置路径与增删行；未知计数为null，不累加同一候选重复观察。文件名只是显示，不成为读取宿主文件的能力。
- evidence只有kind、哈希、验证状态和domain，不输出原始宿主路径、密钥文件、正文/会话blob；原始材料留在受权限约束的私有证据区。
- followups保留稳定test_id、UTC计划时间、目标版本/运行、验收条件和计划/阻断状态。实际测试结果另追加test事件；计划不冒充执行成功。
- 所有输出显式authority=audit_only，不能被当成FileReview、预算许可或发布指令。

导出为不可变、按内容哈希命名的JSON分页文件，每页最多100事件且不超过1MiB，最后原子替换有界manifest。run与day索引携带总数、页哈希与生成/源水位。分页缺失/摘要不符/schema未知必须报错，不能伪造空报告。旧manifest引用的内容页仍保留，导出失败不破坏上一份可读快照。

main侧新增纯标准库只读reader（src/myink/pi_audit.py），不导入ops执行器、不连接模型/费用库/生产DB。接口提供runs、events、daily、enhancements的分页/读取；后续/admin路由必须复用真实Bearer管理员逐次校验、no-store和访问留痕，不将导出目录公开静态托管。

每日版本输出必须区分观察到的部署、已验证发布、候选/Git更新与no_release；未知发布结果不能显示no_release。次日测试以真实版本/证据窗口和样本门槛执行，不以自然日自动判成功。少于20个同型完整任务标insufficient_evidence；p95少于100不宣称改善。

## 裸Pi增强台账与运行记忆

按事实分别标记implemented/deployed/active/planned和host/model边界：
- 官方Pi SDK/RPC与固定运行时；默认危险能力关闭，实际固定工具清单从项目schema及phase allowlist生成，不把注册但未开放工具算可用能力。
- 冻结源、受控read_source/apply_patch/run_check/candidate_status、计划提议、指标观察等，逐项列明参数/资源/文件/调用上限及拒绝证据。
- 原费用代理、原生单主绑定、独立FileReview、容器权限、版本/备份/发布和恢复域。
- 会话与跨日实验账本、可追溯记忆摘要、失败/假设与复核任务。Codex使用的本机Hindsight不冒充Pi运行时已接入；Hindsight仅myink bank、可用时受控读写、不可用不阻断。运行时记忆必须有来源/基线版本/过期条件，模型不能把记忆变为审批。
- 每日controller/SDK/prompt/policy/source/candidate/deployed版本，以及改动范围、费用/资源、测试结果和全部失败。

## 结束验收

必须看到实际线上采集自动运行、真实异常/证据到新任务的无人逐步确认流转、真实模型开发与独立验收、实际发布观察/归属安全回退和跨日测试证据；代码存在、模拟成功或执行器在线均不替代。审计输出必须可由独立main reader读取，包含失败/未知/无发布日和完整工具流转，且不泄漏秘密。未发生的业务发布/回退/次日测试保持未完成并继续推进。
