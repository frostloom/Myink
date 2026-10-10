# Pi 离线控制基础

本阶段是离线工程验证，不能作为云端或生产就绪验收。禁止真实邮件、短信和模型请求。
A4 活库 SELECT reader、真实查询超时、collector SQL 待 B7；业务 tests/test_run_provenance、admin_observability、run_ownership 待后续验证。C16 raw usage presence pending。A5 Windows 和 Linux Git 验证完成不代表整个 A 阶段跨平台验收完成。

## 启动与目录

从仓库根运行 `python -m ops.pi.control ledger-check --state-dir E:/tools/myink-pi/state`。
WSL 对应 `/mnt/e/tools/myink-pi/state`；本轮状态、私有证据、依赖、缓存均在 E 盘隔离目录，保护主工作区。
`ops/pi/policy.example.json` 是配置起点；默认 live disabled。费用可信来源、价格、输入上界校准未具备时禁止真实请求。
凭据仅由受信宿主加载 PLATFORM_MODEL_API_KEY/BASE_URL/NAME/PROTOCOL；模型 HTTP 接口不提供通知、Git、凭据或任意工具权限。不要将凭据写入报告、通知记录或版本库。

## 报告

`python -m ops.pi.control report --state-dir E:/tools/myink-pi/state --output E:/tools/myink-pi/daily.md`
输出 UTF-8 Markdown 与同名 `.json` 索引，目录须预先存在。CLI 返回下一动作、事件数、快照数与未验收项。
账本追加 `snapshot` 事件携带 collect_snapshot 的安全汇总；报告只投影事件类型、操作 ID、状态及成本/配置/价格索引，保留每次失败，不以晚到成功覆盖。
空账本示例：

```text
No release
Reason: no verified release receipt in this ledger.
Next action: review blockers and gather the pending acceptance evidence.
Cost: unknown; no measured snapshots.
A4 live database ... pending until B7
```

日报是 `daily_report`，不是事故告警。fault event 单独保留；云故障信号替身仍不能证明云告警交付。

## 捕获通知与恢复

宿主调用 `send_daily(ledger, report, transport)`，report 必含 date（ISO 日期）、run_id、content_version，可选 recipient。
唯一键含日期/run/类型/内容版本，稳定 Message-ID 防止正常重启重复捕获。报告正文及凭据不进入通知账本，捕获 envelope 仅提供身份字段和收件目标。
无 transport 或收件人：pending，attempts=0，不声称发送；返回的是排队观察回执，不是账本完成回执，Ledger.finish 仍拒绝 pending。收件人与 transport 以后具备时可继续同一 pending 意图。
捕获 transport 返回 `{'status': 'captured'}`，回执 done/delivery_status=captured；它仅说明本地捕获。
明确证明未发送的 `{'status': 'not_sent'}` 最多尝试三次。异常、无回执、不识别的响应，以及发送标记后崩溃：uncertain，保留 unknown，不自动重发。SMTP 成功后回执丢失也不能证明未发送。
本阶段不实现真实提供方；以后只有支持幂等键查询核对的提供方才可自动核对后重发。uncertain 需要人工/提供方证据协调，不可删账本逃避去重。

## 账本维护与阻塞排查

SQLite schema_version/user_version 当前均为 1；意图身份与终态不可改，事件 append-only，WAL/FULL 保证持久意图。
未知版本、损坏、身份冲突或存储失败必须 blocked；不自动降级、不重建删除历史。升级前停控制器、备份 SQLite（含活动 WAL 的一致性备份），在副本验证显式迁移后再恢复。尚无自动迁移器。
blocked 时检查绝对 E 盘路径、磁盘权限与余量、schema/integrity、可信配置；日志不打印凭据。pending/uncertain 先核对意图与回执，不能当作成功。

## 离线验证

`python -m pytest ops/pi/tests/ -q -m 'not pi_lab and not pi_live'`
`python -m compileall -q ops/pi`
CI 独立 offline-ops job 不启动业务服务；后续设施与付费验证用显式 pi_lab/pi_live marker 单独运行。已有业务 CI job 和 contents:read 权限保持原样。未运行、SKIP、阻塞不记为通过。
用户授权逐项本地提交、审查验收后批次 push 功能分支；不合并 main、不部署生产 Pi。
