# 可信宿主的用户反馈导出入口

此前只有 `SnapshotCollector.collect_feedback()` 方法，实际 CLI/宿主入口不会调用它。本次新增 `ops/pi/feedback_export.py` 和 `scripts/pi-feedback-export.py`：宿主明确调用可信管理员范围的采集器，生成可交给 Pi 分析的脱敏反馈快照。导出器本身不启动 Pi、不调用模型，也不自动优化或发布。

## 使用与数据流

运行环境必须是 POSIX。由管理员通过现有秘密管理方式设置唯一连接来源 `PI_FEEDBACK_DATABASE_URL`，使用专用 PostgreSQL 只读角色；脚本不读取 `.env`，不接受命令行密钥、SQL、角色或模型选项。预先准备当前执行用户拥有、其他用户无访问权限的输出目录（例如 0700）。下列只是使用示例，未连接实际数据库执行：

```sh
python scripts/pi-feedback-export.py \
  --start 2026-10-12T18:00:00+00:00 \
  --end 2026-10-12T22:00:00+00:00 \
  --output /opt/myink-pi-lab/private/feedback-001.json
```

窗口必须已经结束，start/end 必须显式为 UTC。输出必须是绝对路径、未存在、没有符号链接及链接祖先；目录不会自动创建或修改权限。脚本独占创建不超过 512 KiB 的 0600 文件，调用已有快照校验和加载器验证实际字节。失败时只清理本次创建且身份仍一致的文件。数据库 engine 在采集成功或失败后都 dispose。

成功时 stdout 只输出文件 SHA、快照内部 SHA、窗口、条数、has_more 等元数据，不输出正文、反馈 ID、连接地址或密钥。错误仅输出固定提示，不输出异常 repr 或输入参数值。Windows 实际入口直接拒绝运行：没有验收过 ACL 的实现，不能把 chmod(0600) 当成 Windows 私有权限。

采集器固定读取 `id/category/description/status/created_at/updated_at` 六列，脱敏正文并保留指纹。联系人、账号标识、页面、UA、附件不进入分析。每批 SELECT LIMIT 51，仅保留最多 50 行；`has_more` 明确披露未读完。需要继续时，管理员把快照中的 `next_cursor` 保存在当前用户私有、绝对路径、无链接、单硬链接且不超过 8192 字节的 JSON 文件中，使用 `--cursor-file`；它必须绑定同一窗口和 admin 范围。每页是独立只读事务，不宣称跨页同一 MVCC 快照。

Pi 的消费者使用已有 `load_feedback_snapshot(path, file_sha256, trusted_root=...)` 和 `build_feedback_prompt(snapshot)`；以 tools=[] 运行分类后用 `validate_feedback_analysis` 校验。它们不会给予自动执行或候选审批权限。反馈快照若超过 prompt 的 36,000 字节限制，消费者必须先由可信宿主选择较小的批次；导出成功不代表模型请求已经提交。把已验证的 rows 加入同窗口写作 bundle 时，必须重新冻结 bundle 哈希，不能由反馈正文声明 project 归属或配置。

## 权限与验收边界

反馈是账号级表，没有 project_id，不能依赖作品 RLS。部署必须使用非表所有者、非高权限、无继承/PUBLIC/default 写授权的专用读取角色；列 SELECT 授权和实际事务只读验收仍需单独完成。现有角色检查和客户端 READ ONLY/REPEATABLE READ、最多 5000ms 语句超时不能替代数据库权限审计。本次没有修改权限审计方法、创建角色或连接数据库。

源码测试证据位于 `/Users/a1/项目/Myink/myink-pi/evidence/c20/feedback-export/`：

- `red/`：初次运行器 JUnit 路径转义错误，保留但不作为有效 RED 验收。
- `red-002/`：实现前缺少导出入口，1 项预期失败。
- `green-001/`：21 通过、6 失败；暴露 Windows 二进制写入的换行问题，以及无法创建真实符号链接的测试环境限制。
- `green-002/`：142 通过、1 失败、1 跳过；剩余失败是新测试 fake 数据列表引用未清空，已修正并保留日志。
- `green-003/`：143 通过、1 跳过，rc0。新增导出器 27 项全部通过；跳过的是原有 writing_evidence 的真实符号链接测试，原因是 Windows 无创建权限。
- `entry-smoke/`：真实脚本拒绝未支持的密钥参数，exit2，不回显参数值。

最终通过数量来自一次联跑，不能把多轮结果叠加计算。测试使用实际采集器的 SQL 构造、脱敏与严格快照契约，数据库边界为 fake engine；POSIX 权限和链接元数据在 Windows 上明确模拟。真实 PostgreSQL 角色/隔离、真实 POSIX 权限、用户反馈读取、模型反馈分析、线上 Pi、完整项目验证均 **NOT_RUN**。这批源码不改变冻结的 009/010 runtime，不复用其原生授权或验收。

参见 [反馈采集与分类契约](feedback-intake-2026-10-13.md)。


## ROOT 后续独立验证

在干净 Git 基线叠加本批明确文件后，独立针对性验证为296项通过、2项现有Windows符号链接权限跳过（14.57秒）；未包含既有B12改动。证据：`/Users/a1/项目/Myink/myink-pi/evidence/c20/focused-export-001`。

随后在真实隔离Linux文件系统运行7项合成烟测：0600私有输出、固定采集请求、脱敏快照/哈希回读、engine释放、禁止覆盖、真实软链接拒绝、公共可读父目录拒绝均通过。文件权限与路径检查是 ACTUAL_POSIX，数据库读取回调是明确模拟，零真实数据库/模型调用；该结果不替代PostgreSQL角色和SQL事务验收。证据：`/Users/a1/项目/Myink/myink-pi/evidence/c20/feedback-export-posix-smoke.json`。前面的未运行说明是源码冻结时的历史状态。
