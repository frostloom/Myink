# Myink 管理员与 Pi 引擎

管理员是 Myink 的组成部分，负责既有产品的稳定性、成本、速度、写作质量与体验；新功能方向由项目所有者决定。`Engine` 接口把管理员职责与具体 Agent 解耦，目前接入固定版本 Pi。预算、权限、备份与发布验收由控制程序管理。

## 最新状态（2026-10-20）

当前Pi分支干净提交的离线控制模块回归为1687 passed、2个Windows符号链接权限SKIP、19个pi_lab/pi_live未选入；不是业务全量或生产验收。已核对025原输入/报告与累计预算，45项语义质量仍unknown。本轮未调用模型、未采纳候选、未部署。详见[基线与数据分析记录](../evaluations/pi-baseline-resume-2026-10-20.md)和[可核对回执](../evaluations/pi-retained-data-audit-2026-10-20.json)。下一步绑定当前真实Pi运行器做有限分析合同对照，完整自主迭代闭环尚未完成。

## 历史状态（2026-10-14）

本机试验改为累计 20 元费用上限、累计请求次数不限；保留历史未知预留与单轮时间、工具及资源边界。已补充 30 条合成反馈演示和 111 项相关通过测试。详见[预算与反馈记录](../evaluations/pi-local-trial/fee-only-budget-and-feedback-2026-10-14.md)。[022真实开发](../evaluations/pi-local-trial/development-runtime022-2026-10-14.md)已跨过旧100次限制，但17项产品回归仍有4项失败，候选未采用。实际进度保存在[交付报告](../evaluations/pi-local-trial/report.md)；尚无生产 Pi。

## 历史引入与阶段验收

当前已完成 E 盘实际安装、真实 Pi 进程的模拟接口验证和受预算限制的真实模型只读源码分析。见 [本轮引入记录](pi-introduction-2026-10-11.md) 和 [安装与版本升级规范](pi-version-upgrade.md)。最终主机试验 `003` 的 checker/Pi 隔离与真实 Pi 模拟协议已通过；付费规划执行2次HTTP和4次只读工具调用后因 cache-input 用量转换未通过现有严格解析器校验及剩余额度不足停止。累计6请求，未形成获批计划、业务补丁、实际质量对照或发布，全部自有进程、keeper 和网关已停止。完整本地迭代闭环仍未完成；当前没有生产 Pi。真实邮件、短信和线上自动迭代尚未启用。

以下保留离线控制基础的操作说明。离线测试本身不发送模型请求；真实预览必须使用已授权的独立策略与累计账本，不能把模拟回执当成线上验收。A5 Windows 和 Linux Git 检查通过，也不代表整个 A 阶段跨平台验收完成。

## 启动与目录

C18 分层状态与维护交接见[本机试验报告](../evaluations/pi-local-trial/report.md)、[证据索引](../evaluations/pi-local-trial/receipt-index.json)、[服务器启用清单](server-enablement.md)和[日报/事故通知](notifications.md)。当前为 partial：主机隔离与模拟协议已通过，合成基线机械检查实际失败，45项语义指标/11域仍 unknown。冻结源码离线825 passed、2个Windows符号链接SKIP、19个设施测试deselected；该结果早于 admission 修复，修复另有17项真实SQLite查询测试通过，PostgreSQL回归未运行。完整服务构建与生产启用仍未验收。报告中的旧 A 阶段固定 banner 是历史边界，不自动反映新主机事实。

从仓库根运行 `python -m ops.pi.control ledger-check --state-dir /Users/a1/项目/Myink/myink-pi/state`。
WSL 对应 `/Users/a1/项目/Myink/myink-pi/state`；本轮状态、私有证据、依赖、缓存均在 E 盘隔离目录，保护主工作区。
`ops/pi/policy.example.json` 是配置起点；默认 live disabled。费用可信来源、价格、输入上界校准未具备时禁止真实请求。
凭据仅由受信宿主加载 PLATFORM_MODEL_API_KEY/BASE_URL/NAME/PROTOCOL；模型 HTTP 接口不提供通知、Git、凭据或任意工具权限。不要将凭据写入报告、通知记录或版本库。

## 报告

`python -m ops.pi.control report --state-dir /Users/a1/项目/Myink/myink-pi/state --output /Users/a1/项目/Myink/myink-pi/daily.md`
输出 UTF-8 Markdown 与同名 `.json` 索引，目录须预先存在；`--output` 禁止使用 `.json` 扩展名（不区分大小写），避免报告与索引重名覆盖。CLI 返回下一动作、事件数、快照数与未验收项。
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
