# Pi C20 开发恢复与反馈判断实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. 用户已要求自主执行、不要再逐项询问，并授权验证后分批推送。

**Goal:** 完成真实Pi补丁/固定前后对照并加入安全的用户反馈分析入口。
**Architecture:** 旧计划只读认证为数据，新隔离证明与独立审批后开发；反馈只读快照→无工具triage→调查或owner/安全路线，不直接赋权。
**Tech Stack:** Python/pytest/SQLite/PostgreSQL固定SELECT/官方Pi RPC与既有受控工具。
**Spec:** docs/superpowers/specs/2026-10-13-pi-development-feedback-design.md

## Global Constraints

隔离codex/pi-autonomy-design；主工作区与18个B12文件保护。local-trial-1累计100次/20元与15/45/30/10原配额、旧32次/10254974保守预留不变。不开服务器Pi，不改旧008证明，不伪造成功wrapper，不自动新功能/回复/关闭反馈。

## Review Focus

- 历史提案有效不等于旧整体阶段成功或新的运行权限；数据恢复与fresh证明分开。
- lookup适配器无constructor/写入；POSIX root精确绑定；相同标签旧007不得混入。
- 无工具反馈分类不能授予命令/SQL/文件/修改或发布权限；词匹配不能误伤正常删除报错。
- feedback为账号级：可信admin scope、列投影、冻结窗口与游标，不能沿用项目RLS假设。
- 别把机械capture对照或synthetic反馈测试当线上语义质量改善，别把最终拒绝当模型识别成功。

### Task 1：历史提案认证与fresh开发恢复

**Files:** 私有 .superpowers/sdd/2026-10-11-pi-local-trial/c20-host-runtime-009/，其中新增historical_plan.py与test_restore009.py；从008复制运行14个输入，修改budget_binding/phase_host/host_common和固定009标识，原008不写。公开源码仅使用df4470e已审core23（trial_runtime新SHA），不混入B12或并行feedback代码。
**Interfaces:** 历史只读认证函数返回 {historical_case,overall_host_failed,proposed_plan,source_sha256,evidence_hashes,protected_snapshot_sha256}；没有新execution权限。develop-only恢复证书由ROOT确认/独立审查后作为新grant输入；phase_host创建fresh候选并读取精确证书，不创建paid-plan成功wrapper。
- [ ] RED：真实SQLite历史提案query_only验证、args/绑定/回执/源/停止证明篡改、旧轮/重复拒绝；断言operations/events不变。
- [ ] GREEN：最小constructor-free adapter与独立新候选review；严格develop grant与原前缀/增补/配额校验，测试错误会计类型/源码/候选阻断。
- [ ] 独立源码审查，ROOT冻结新证书/grant/source闭包；fresh E/native绑定与进程身份，checker/Pi gates实际运行并审查。
- [ ] ROOT追加本次develop恢复审批，真实Pi开发后核验最后候选检查、停机清理和完整相同输入对照；记录成功或实际失败，不虚报。

### Task 2：只读反馈与安全triage

**Files:** Create ops/pi/feedback.py、ops/pi/tests/test_feedback_analysis.py、ops/pi/tests/test_feedback_reader.py；Modify ops/pi/db_reader.py；共享experience桥接只改ops/pi/writing_evidence.py及其测试、prompts/analyze.md、skills/myink-iteration/SKILL.md，原11域strictschema保持。
**Interfaces:** SnapshotCollector.collect_feedback(window, *, admin_scope=False, cursor=None)严格只读→快照；feedback.build_feedback_prompt(snapshot)/validate_feedback_analysis(result,snapshot)→建议及宿主固定deny/investigate/owner等路线，automatic_execution/candidate_allowed始终False。trusted window含start/end datetime，<=50行/LIMIT+1，cursor绑定window/scope并用updated_at/id键集；feedback正文不能选择任何配置。
- [ ] RED：固定SQL/只读范围/隐私投影/50+1/分页与伪cursor拒绝，strict模型结果/引用/ID/哈希/危险语境与合法删除报错，真实tools禁止越界。
- [ ] GREEN：最小snapshot合同、脱敏/来源、no-tool prompt与宿主约束；新功能owner、危险deny、安全报告review、合理缺陷investigate。
- [ ] experience桥接反馈描述，同步categories与row cap，引用和unknown质量不变；不写contact/附件，不猜任务外键。
- [ ] 聚焦测试与独立审查；冻结反馈评估标签/输入/模型/预算以experiment无工具阶段实测，模型失败计入报告，阶段额度不重分类。

### Task 3：验收、文档与分批GitHub交付

**Files:** docs/evaluations/pi-local-trial/新增c20开发/反馈验收与维护记录；原report.md追加，原历史段保留。
- [ ] 聚焦测试之后用干净已接受源码+本轮明确覆盖做ops离线回归，记录SKIP/未运行PG及业务服务。
- [ ] 独立结果事实审查；批次提交：反馈合同/测试与流程文档；真实Pi候选经相应测试/审查后单独提交；验收证据说明另批。
- [ ] 推送codex/pi-autonomy-design并核对远端SHA。未验收路径精确说明，不合并main/不上服务器。
