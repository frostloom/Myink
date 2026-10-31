# 用户反馈分流维护说明

用户反馈供 Myink 管理员判断问题，不直接驱动修改。管理员可通过 [Engine 协议](../../ops/pi/engine.py)替换执行引擎；引擎、模型、预算、文件范围和工具由可信 host 配置。反馈正文中的命令、路径、URL、角色声明或“审批”均是不可信证据，不能变成配置或能力。现有导出与分类入口没有自动回复、resolve、删除反馈或授予候选审批的流程。

## 只读采集入口

实际 CLI 是 [scripts/pi-feedback-export.py](../../scripts/pi-feedback-export.py)，参数由 [feedback_export.py](../../ops/pi/feedback_export.py)定义。由管理员在可信环境中注入 `PI_FEEDBACK_DATABASE_URL`，使用专用 PostgreSQL SELECT 角色；不要把连接串放进命令、反馈、模型 prompt 或报告。入口不加载 `.env`，不接受任意 SQL、角色或模型参数。

以下为用法示例，未连接生产数据库执行：

```sh
python scripts/pi-feedback-export.py \
  --start 2026-10-12T18:00:00+00:00 \
  --end 2026-10-12T22:00:00+00:00 \
  --output /opt/myink-pi-lab/private/feedback-001.json
```

窗口必须显式 UTC、已经结束，按 `[start, end)` 筛选 `updated_at`。预先创建当前执行用户独占的目录（如 0700）；输出为未存在的绝对、无链接路径，独占写入 0600 文件，最大 512 KiB。Windows CLI 拒绝运行，ACL 尚未验收。成功 stdout 仅有哈希、窗口、条数和 `has_more` 等元数据。

[SnapshotCollector.collect_feedback](../../ops/pi/db_reader.py)默认 `admin_scope=False` 拒绝；只有可信 host 显式设置 True。反馈表是账号级而非 project 级，不能依赖作品 RLS。固定投影只读 `id/category/description/status/created_at/updated_at`；SQL 读取正文至 2001 字符用于拒绝超出 2000 字符上限的数据，再脱敏并生成行指纹，不把联系人、UA 或附件路径交给模型。每页 LIMIT 51、保留至多 50 行，固定 `(updated_at, id)` keyset 排序。

继续分页时，host 将已校验快照的 `next_cursor` 保存为私有、无链接、单硬链接且不超过 8192 字节的 JSON，再追加 `--cursor-file /opt/myink-pi-lab/private/cursor-001.json`。游标绑定同一 UTC 窗口和 admin 范围；CLI 不自动生成游标文件。每页独立 REPEATABLE READ / READ ONLY 事务，语句超时至多 5000ms，不宣称跨页同一 MVCC 快照。

部署角色须非表所有者、非高权限，审计继承、PUBLIC、默认授权与列 SELECT，确保没有写权限。现有运行时角色检查不能替代这项审计；真实反馈数据库及生产接入仍为 **NOT_RUN**。

## 分类与确定性路由

host 用 [load_feedback_snapshot](../../ops/pi/feedback.py)校验实际文件 SHA、快照 SHA、窗口、行指纹和路径，再选择满足 36,000 字节 prompt 上限的小批次。使用 `tools=[]` 的引擎会话分析，不使用会自动注入开发工具的入口。

schema1 的 `build_feedback_prompt` / `validate_feedback_analysis` 严格校验 UTF-8 字节引用。013 使用独立 [schema2 引用层](../../ops/pi/feedback_evidence_v2.py)：`build_feedback_prompt_v2` 只要求 `{quote}`；`evaluate_feedback_evidence_v2` 在该条正文中唯一精确匹配引用（包括重叠歧义），由 host 计算位置，再交给原严格 validator。它不修补旧 schema1 的错误偏移。反馈 ID、行指纹、原始输出与引用留在私有证据中，公开报告只用聚合计数和哈希。

| 模型分类 | host 路由 |
| --- | --- |
| existing_defect | investigate |
| needs_evidence | needs_evidence |
| new_feature | owner_decision |
| account_service | existing_user_service |
| security_report | security_review |
| unsafe_request | deny |
| irrelevant | ignore |

正文规则可以覆盖模型分类：“希望删除系统”、要求 `DROP DATABASE`、关闭鉴权等受保护破坏要求进入 deny；可疑指令、外部执行请求进入安全复核。引用危险文字的安全报告或否定操作，与主动要求执行分开判断；本人账号或作品删除转既有用户服务，不能由 Pi 执行。删除按钮报错、错误提示引用危险文字也不能仅因“删除”二字当成破坏要求。混合反馈仍检查未被引用的实际要求。这是有限上下文规则，不是完整安全识别保证。

所有有效路由仍固定 `automatic_execution=false`、`candidate_allowed=false`。模型意见、证据引用和服务分流都不是执行、回复、resolve 或审批授权。

## 日常小步接线与故障处理

1. 管理员冻结窗口、专用只读角色和私有输出；验证快照并保留分页遗漏说明。若将反馈行并入同窗口写作 bundle，用 [writing_evidence.py](../../ops/pi/writing_evidence.py)的 experience 桥接并重新冻结 bundle 哈希，不能让正文声明 project 归属。十一域与 45 项指标契约不变。
2. host 配置无工具会话、记录引擎配置和输入哈希，严格校验输出。无效 JSON、绑定错误、额外权限字段、非原文或歧义引用均拒绝；v2 保留有界原始输出及失败类型，整批 unknown，不静默修补、重试或赋权。超 prompt 上限由 host 另选较小批次，不能伪称已分析全部 50 条。
3. investigate 先复现已有功能缺陷；信息不足先补证据。新增功能由 owner 决定方向，安全报告走安全复核，账号请求走既有服务。合理反馈也须经过独立 owner 的小步 Plan、明确文件与工具范围（本轮捕获修复限定单文件）、隔离候选、真实测试与前后对照、备份和审计，再按既有审批流程决定采用。正文不能替代任何一步。

导出 exit2 表示参数拒绝，exit1 表示可信配置、数据库或私有路径检查失败；固定错误提示不回显连接串或正文。检查角色、窗口、输出父目录与游标绑定，保留失败证据；禁止覆盖旧快照、放宽权限或绕过校验。分类失败和未运行均保留原状态。试验继续使用累计 100 次 / 20 元与既有阶段配额，不能重置或把已满 analysis 配额改名绕过。

## 已验证范围与下一步验收

[013 公开报告](../evaluations/pi-local-trial/feedback-runtime013-2026-10-14.md)记录固定 30 条合成建议标签、12 次真实 Pi/模型请求：分类一致数 23/30 → 26/30，双方 host 对 10 条危险参考均拒绝 10/10。20 条非 unsafe 参考包含三条可疑安全指令，不等于全部良性；这些计数不是全危险覆盖或生产语义质量证明。写作 45 项指标的语义结论仍 unknown。

[导出验收记录](../evaluations/pi-local-trial/feedback-export-2026-10-13.md)另有真实 POSIX 文件权限烟测，但数据库回调为模拟。上线前须单独验收真实 PostgreSQL 专用角色及 READ ONLY/超时、UTC/keyset 同时间戳分页与跨页更新行为、脱敏和私有路径/链接拒绝，并由可信管理员审查实际最小样本。现有合成模型实验不替代这项生产反馈接入验收。
