# 用户反馈采集与判断（C20）

## 已实现的边界

管理员控制器调用 `SnapshotCollector.collect_feedback(window, admin_scope=True, cursor=...)`，读取账号级反馈。`admin_scope` 必须来自可信宿主，不能暴露给浏览器或模型作为可选权限。窗口为 UTC 的 start/end，按 updated_at/id 键集分页，每页最多50条，用第51条判断 has_more；next_cursor 绑定窗口与范围。分页是多次独立只读事务，不声称跨页同一 MVCC 快照。

固定投影只有 id/category/description/status/created_at/updated_at。不采集联系方式、用户ID、访问地址、浏览器信息或附件，不推断反馈关联哪个写作任务。现有用户反馈 API 保持原行为。

`feedback.make_feedback_snapshot` 固定来源、快照哈希和脱敏披露；`build_feedback_prompt` 只生成无工具分析输入；`validate_feedback_analysis` 验证全量ID、来源哈希和逐字 UTF-8 引用。模型输出不能包含权限、执行或配置字段。原文里的命令、路径和网址可以作为引用证据，不能执行。

| 分类 | 宿主建议 | 后续条件 |
| --- | --- | --- |
| 已有功能缺陷 | investigate | 独立复现与指标证据，才能进入计划/审查/补丁/测试 |
| 缺少证据 | needs_evidence | 保留未知，收集日志或复现材料 |
| 新功能建议 | owner_decision | 产品方向由所有者决定 |
| 本人账号/作品删除申请 | existing_user_service | 使用既有用户服务流程，Pi不执行 |
| 安全事件报告 | security_review | 区分引用、否定和实际操作要求 |
| 破坏性或越权要求 | deny | 不授予执行权限 |
| 无关内容 | ignore | 保留来源，不进入开发计划 |

所有分类都固定 `automatic_execution=False`、`candidate_allowed=False`。宿主规则是有界语境辅助判断，不是通用语义安全识别；真正边界是反馈无工具权限。明确删除系统/数据库、关闭鉴权等要求被拒绝；正常删除按钮报错、引号中的错误提示不会被简单关键词误伤，混合反馈里额外的真实危险要求仍被拒绝。

`writing_evidence` 只将已校验的反馈描述纳入 experience 类，与原11个分析域一起处理。人物、事件、情节召回、抽取等质量没有标签时仍为 unknown，不因新增反馈填充虚构指标。不自动回复用户、关闭反馈、下载附件、修改数据库或创建新功能。

## 维护与权限

生产接入必须使用专用非所有者、无高权限的只读数据库角色。最低反馈列授权示例：

```sql
GRANT SELECT (id, category, description, status, created_at, updated_at)
ON public.feedback TO myink_pi_reader;
```

这只是权限示例，未在服务器执行。角色成员继承、表所有权和其他授权也必须验收；客户端事务设置与现有角色检查不能替代数据库实际权限审计。收集器使用 READ ONLY repeatable-read 和最多5000ms服务端语句超时。

添加分类时同时修改严格输出合同、宿主路由与测试；添加证据队列时同步 round-robin 类别列表，避免队列无法消耗。任何分析输入超过36000字节必须由宿主声明缩小批次，不允许悄悄截断覆盖范围。真实模型实验需独立固定输入/预期标签/提示词/模型，按 experiment 计入既有累计额度。

## 验证与限制

- 初始完整干净 ops 离线回归：1064 passed、2 skipped、19 lab/live deselected，283.68s；这是误判修复前的冻结版本。
- 最终修复后的独立相关回归：249 passed、2 skipped，13.55s，覆盖反馈读取/分析、写作证据/分析、真实SQLite受控工具与计划。
- 两个 SKIP 均为既有 Windows 符号链接权限限制；不是通过。
- 独立审查先发现两条 UI 引用误判，真实 RED 复现后修复；旧失败和旧源码快照保留。
- 30条合成案例包含七类反馈、故意低估危险的模拟分类、引用/否定/混合请求。预期标签为可审阅的工程判断，不声称独立语义金标或真实模型准确率。
- 真实 PostgreSQL 角色/服务集成与真实模型反馈质量评估在本记录生成时 NOT_RUN。未启用线上 Pi。

原始测试和审查证据保留在 /Users/a1/项目/Myink/myink-pi/evidence/c20/feedback、focused-final-001、full-offline-001；私有审查报告在隔离工作区 .superpowers/sdd/2026-10-11-pi-local-trial。原始用户内容、凭据、账本和私有运行时不进入GitHub。
