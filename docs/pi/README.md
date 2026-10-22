# Myink 管理员与 Pi 引擎

## 标准层级兼容与宿主诊断（2026-10-22）

SSE usage 兼容 null/standard service_tier；非标准层级及无效用量仍保留 unknown。启动器新增有限阶段/原因码和饱和字节数，清理失败保留首因；没有扩大 64 KiB 正文等边界。最终 Pi 离线 2071 passed、0 skipped、19 deselected，审查发现的首因覆盖已修复并复审；修复后实际 Linux Pi 合成标准两槽完成，超限场景单槽安全停止、容器全部删除。0 新增付费请求，原账本逻辑摘要未变、保守余额仍 2.093625 元、global live=false；上次真实 ValueError 根因仍未证实。见[本轮验收](../evaluations/pi-stage-tier-2026-10-22.md)。下一步先离线设计有界 SSE 传递，不补发旧槽或释放历史 unknown。

## 修复后真实诊断（2026-10-22）

用户明确批准向DeepSeek发送本次私有输入/报告后，以新run、最多2请求/cap4.032768元/240秒执行。实际1请求200 SSE、编码absent，已解析message_start，未再UnicodeDecodeError；用量起始被service_tier额外字段拒绝，另有宿主ValueError具体触发点未确定，未取得结果帧/有效session。0 DONE/1 UNCERTAIN/29 NOT_RUN，第二槽未运行、不重试；容器exit137强制清理删除。新unknown完整预留2.016384元，累计210次/202 known/8 unknown/0 pending，保守余额2.093625元，全局live=false。账户可见余额少0.25元不是本请求核定账单。见[真实诊断](../evaluations/pi-live-encoding-2026-10-22.md)；下一步先离线定位宿主拒绝分支与metadata兼容，不再直接付费尝试。

## 响应编码修复（2026-10-22）

生产入口显式要求未压缩响应；网关在读取正文前拒绝压缩或未知编码，固定502、保留unknown、不重试，并在私有诊断中记录有限编码类别。上次真实失败根因仍未证实。完整Pi离线2042 passed、0 skipped、19项未选入；独立审查无缺陷。真实Linux Pi合成identity两槽完成；忽略协商的gzip场景安全停止、第二槽未运行，三容器均exit0删除。修复及合成阶段0付费请求，canonical状态未改。见[编码修复验收](../evaluations/pi-response-encoding-2026-10-22.md)。 修复已推送078060c。审批拦截后的明确授权与真实执行结果见上方最新诊断；之前只读check和209次/余额4.110009元是执行前快照。

## 最新真实诊断（2026-10-22）

已实际发起1次deepseek-flash模型HTTP请求，上游200后因UnicodeDecodeError停止，第二槽未运行、不重试。首槽UNCERTAIN并保留2.016384元完整预留，原累计账本保守剩余4.110009元；该预留不是已核定消费。容器强制停止/退出137后删除，精确标签无残留；用量诊断未捕获SSE事件，合同/真实usage/账单均未通过。仅本轮独立冻结策略live=true，原全局策略仍false；清单过期不可重放。gzip原始流可在本地复现同类错误，但真实响应编码未留存、根因尚未确认；下一步先离线处理编码边界与安全元数据，不补发旧槽。见[真实诊断记录](../evaluations/pi-live-diagnostic-2026-10-22.md)及[机器回执](../evaluations/pi-live-diagnostic-2026-10-22.json)。

## 最新配置准备（2026-10-22，真实五组输入）

025完整五组view/原报告、当前源码闭包、官方价格/容量证据、原scope/policy身份已绑定为完整私有清单，默认入口checked，live=false且结果根未创建。修复真实报告约300KB导致初始帧超过旧上限的问题：仅可信首条输入改为512KiB，后续relay仍192KiB、HTTP64KiB，保留完整证据及请求身份。新闭包以大报告合成输入通过实际Linux两槽及清理；真实账本保守余额仍6.126393元，4.10元/240秒方案未付费执行，历史unknown不释放。已生成check清单有短期deadline，不能原样重放。见[绑定与修复验收](../evaluations/pi-real-input-binding-2026-10-22.md)。

## 最新运行核验（2026-10-22，usage诊断）

已将当前生产代码重新冻结为独立Linux快照，在实际Pi1.1.0/Node24.22.0无网络隔离容器中通过两槽MockTransport验收：两个新会话、合同/结算有效，两个0600私有诊断各1468字节，费用仅合成账本各834微元；两个容器退出0且按精确operation标签查无残留。首次验收脚本遗漏既有结算字段导致断言失败，证据保留；修正脚本后新目录复验通过，未改生产代码。0真实付费请求，真实usage/账单与生产验收仍未完成，诊断仍不保证交付。见[Linux验收记录](../evaluations/pi-usage-linux-2026-10-22.md)及[机器回执](../evaluations/pi-usage-linux-2026-10-22.json)。

## 宿主计量诊断接线（2026-10-22）

`AnalysisRun.gateway_handler`新增可选可信宿主usage_observer，launcher固定为每槽在0700结果目录预建0600私有`slot-{index}-usage-private.jsonl`，每文件最多一条、8192字节，记录slot_index、attempt_id及既有网关已脱敏的计量字段存在性/数值；不保存请求、响应正文或token。初始化失败在当槽请求/容器创建前停止；回调错误不改变费用或终态。路径不能是符号链接，追加前核对原inode、普通文件、单硬链接及权限；原句柄保持到回调决定或观察器销毁，防止inode编号复用。

诊断沿用既有单daemon、六条队列的异步观察器，可能因存储阻塞、队列满或进程退出而丢失；不等待、不重试、不将记录写入账本或公开receipt。公开usage_diagnostics=best_effort_private只说明采集模式，不能证明已有记录落盘，更不证明usage语义或账单正确。接线检查点仅完成离线合成测试；后续Linux容器合成复验见上节，真实provider仍未验收。原source-reviewed与私有草稿绑定旧代码；本次新建source-usage-reviewed用于合成验收，真实执行前仍须绑定当次配置。见[接线验收](../evaluations/pi-usage-launcher-2026-10-22.md)。

## 最新核验（2026-10-22，DeepSeek计量准备）

官方价格/兼容/缓存资料已重新获取并固定摘要；原累计账本只读复核未变，保守剩余6.126393元。现有计量、缓存、预检及入口相关245项测试通过。准备了两槽4.10元、240秒的不可执行配置草稿；真实五组输入、审阅证据及绝对deadline尚未绑定。公开资料未明确Anthropic四维usage语义，不能补零或称真实计费已验收。保持live=false、0付费请求；安全usage诊断已接入并通过上节Linux合成复验；下一步准备有界真实响应与账单证据。见[计量准备核验](../evaluations/pi-provider-readiness-2026-10-22.md)和[机器回执](../evaluations/pi-provider-readiness-2026-10-22.json)。

管理员是 Myink 的组成部分，负责既有产品的稳定性、成本、速度、写作质量与体验；新功能方向由项目所有者决定。`Engine` 接口把管理员职责与具体 Agent 解耦，目前接入固定版本 Pi。预算、权限、备份与发布验收由控制程序管理。

## 可信宿主分析入口（2026-10-22）

`python -m ops.pi.analysis_launcher --config /absolute/private/manifest.json` 默认只检查，不创建账本/目录，不联系Docker或provider。宿主清单固定所有原状态路径和scope/policy/input/evidence/code/runtime指纹、run_id、正整数cap_microyuan、未来600秒内绝对deadline，以及本地daemon/不可变image。路径须为绝对非符号链接路径，Docker CLI也使用解析后的真实路径；credentials保持0600/父目录0700。

清单schema为`pi-analysis-launch-v1`，完整字段见`ops/pi/analysis_launcher.py`的`_FIELDS`。输入文件仅含五组`views`及`report`；证据记录schema为`pi-provider-evidence-v1`，固定policy_sha256、review_reference、valid_until以及price/input_bound原始文件path与sha256。所有expected摘要为canonical JSON SHA256，原始来源文件为原始字节SHA256；code/runtime使用既有闭包fingerprint。证据须覆盖deadline，但只表示宿主审阅声明，不自动验证provider最新价格、密钥在线有效性、usage语义或账单。

只有显式`--execute`且live_ready、余额/单次预留/证据/身份检查都满足时，才在原账本注册30槽并绑定本轮费用与期限；入口仅选择第一对槽，不自动恢复/重试。原子预留仍核对同scope/policy/请求、本轮和累计预算及期限，历史unknown完整预留不释放。worker只收到当槽冻结输入、局部token和期限；上游key和原ledger不进容器。宿主合同/session、已知结算、精确所属容器清理全部成功才前进；任一unknown或清理失败停止。

新增44项先RED后GREEN（含审查修复）；修复前定向231 passed，修复后完整Pi离线1991 passed、0 skipped、19项设施/在线未选入，compileall/diff-check通过。实际私有policy仍live=false，未开启真实上游。修复后实际Linux Pi+MockTransport两槽通过、精确所属容器均清理；独立审查的一项session唯一性终态顺序问题已RED→GREEN修复。见[宿主入口验收](../evaluations/pi-analysis-launcher-2026-10-22.md)和[机器回执](../evaluations/pi-analysis-launcher-2026-10-22.json)，不把合成验收算成provider或生产验收。既有固定synthetic probe仍不接真实ledger/transport。

## 最新状态（2026-10-22，DeepSeek切换）

按用户要求，宿主Pi私有凭据已改为CC-Switch Pi/DeepSeek的同一密钥，模型`deepseek-flash`，通过DeepSeek官方Anthropic兼容端点继续使用预算网关。密钥只在原私有state/credentials，目录0700/文件0600，未进入容器、Git或记忆；CC-Switch当前provider不变。当前策略为私有`state/policy.json`，历史冻结策略不改；后续入口必须显式选新策略。默认新分析注册已切新模型，原模型仅保留显式历史冻结兼容。

只读预检新增可选credential-file并验证身份绑定；原账本208次/保守余额6.126393元不变。官方价格/上下文与兼容资料已在私有证据中固定SHA，仍需真实usage/计费验收及本轮cap/deadline。当前live_enabled、paid_admission、production_ready、automatic_execution均false，付费请求0。见[DeepSeek切换验收](../evaluations/pi-deepseek-profile-2026-10-22.md)及[机器回执](../evaluations/pi-deepseek-profile-2026-10-22.json)。

定向405通过，完整Pi离线1947 passed、0 skipped、19项设施/付费未选入。新闭包在固定Linux Node/Pi无网络容器中通过deepseek-flash本地合成两槽：合同有效、新会话、无工具、退出0，两容器均删除；不代表真实DeepSeek调用或计费通过，45项语义质量仍unknown。

## 前一检查点（2026-10-22，只读预检）

可信宿主入口的只读预检已补齐：单一SQLite只读事务核对完整账本schema/记录、原累计20元审批链、固定scope/policy身份及保守费用，输出无正文逻辑快照指纹；不创建scope或预留。真实账本当前208次、202次已知/6次未知、0 pending；已知费用1.791431元、未知完整预留12.082176元，保守余额6.126393元。两次只读观察相同，数据库及WAL字节未变。见[只读预检记录](../evaluations/pi-analysis-preflight-2026-10-22.md)及[机器回执](../evaluations/pi-analysis-preflight-2026-10-22.json)。

新增32项预检测试通过；审查修复后完整Pi离线1924 passed、0 skipped、19项设施/付费测试未选入。独立审查的一项私有路径错误泄漏已RED→GREEN修复。历史策略所声明的价格/input bound仅供诊断，本次未独立复核成当前可信证据；paid_admission、production_ready、automatic_execution仍为false。下一阶段复核价格和输入上界、冻结源码/配置/容器来源与本轮费用/绝对期限，再连接原子预算预留及容器生命周期。本轮0付费请求，未运行新容器，45项语义质量仍unknown。

## 前一状态（2026-10-21）

Mac Python3.12环境已恢复；持久化30槽身份、原子认领、防重放、逐槽独立令牌已接入原累计账本、本轮显式费用上限与绝对期限。预留事务同时限制本轮和累计费用，重启不续期，本轮未知计费阻止继续；请求及policy私有快照保证计价与实际转发一致。见[本轮预算与期限验收](../evaluations/pi-run-budget-2026-10-21.md)。

当前Mac Docker容器底座已通过隔离、实际资源限制、超时及输出溢出的整个PID命名空间清理。随后在相同边界内启动固定Linux ARM64 Node24.22.0/Pi1.1.0，通过有界stdio反向loopback接入宿主AnalysisRun预算网关；baseline/candidate两槽各一个请求由MockTransport接纳并已知结算，合同有效、新会话、无工具、退出0，两个容器均删除。30槽分母为2 DONE、28 NOT_RUN。见[容器底座](../evaluations/pi-container-containment-2026-10-21.md)、[真实Pi本地合成验收](../evaluations/pi-container-runtime-2026-10-21.md)及[机器回执](../evaluations/pi-container-runtime-2026-10-21.json)。

当前完整Pi离线1892 passed、0 skipped、19个pi_lab/pi_live未选入；容器相关83项定向通过，语法检查通过。独立审查发现的两项来源闭包缺口已分别RED→GREEN修复，再跑最终真实验收和全量回归。`pi_runtime_verified=true`仅限固定本地合成协议，真实provider/计费、生产容量/checker隔离和45项语义质量仍未验收；production_ready、automatic_execution为false。本轮未调用外部模型或修改真实账本。

下一目标是把容器执行纳入真实试验的可信宿主入口，核对原累计20元账本、冻结源/配置、价格和输入上界，再评估有限真实只读分析对照；本合成probe不接收真实provider或账本参数，不能充当付费launcher。

## 前一检查点（2026-10-20）

以下保留当日进度；持久槽位的后续更新以上节为准。


跨电脑继续开发先读[最新迁移交接](../HANDOFF-2026-10-20.md)：分支检查点、各文档用途、私有证据/运行时/账本清单及恢复顺序均在其中。最新功能`0d02318`已把可信宿主`request_guard`接到实际网关，在模型预算预留前校验请求；相关171项测试通过、无跳过，见[网关验收](../evaluations/pi-gateway-admission-2026-10-20.md)。持久槽位、防重放、整轮预算/期限及本轮严格隔离仍需接入。

分析合同逐槽接入已完成：实际Pi1.1.0进程通过两臂本地合成网关验证，实际请求匹配、同system/cwd、新会话并退出0。相关回归402 passed、1个Windows符号链接SKIP；正式付费30槽对照尚未启动。见[运行接入记录](../evaluations/pi-analysis-runtime-2026-10-20.md)及[公开回执](../evaluations/pi-analysis-runtime-2026-10-20.json)。

最近完整离线控制模块基线来自提交4083b69：1687 passed、2个Windows符号链接权限SKIP、19个pi_lab/pi_live未选入；早于本轮接入改动，不是当前全量或生产验收。已核对025输入/报告与累计账本；45项语义质量仍unknown，本轮无外部模型调用、无候选采纳、无部署。见[基线与数据分析记录](../evaluations/pi-baseline-resume-2026-10-20.md)。下一步接入当前宿主scope/预算/隔离验收后做有限真实分析对照，完整自主迭代闭环尚未完成。

## 历史状态（2026-10-14）

本机试验改为累计 20 元费用上限、累计请求次数不限；保留历史未知预留与单轮时间、工具及资源边界。已补充 30 条合成反馈演示和 111 项相关通过测试。详见[预算与反馈记录](../evaluations/pi-local-trial/fee-only-budget-and-feedback-2026-10-14.md)。[022真实开发](../evaluations/pi-local-trial/development-runtime022-2026-10-14.md)已跨过旧100次限制，但17项产品回归仍有4项失败，候选未采用。实际进度保存在[交付报告](../evaluations/pi-local-trial/report.md)；尚无生产 Pi。

## 历史引入与阶段验收

当前已完成 E 盘实际安装、真实 Pi 进程的模拟接口验证和受预算限制的真实模型只读源码分析。见 [本轮引入记录](pi-introduction-2026-10-11.md) 和 [安装与版本升级规范](pi-version-upgrade.md)。最终主机试验 `003` 的 checker/Pi 隔离与真实 Pi 模拟协议已通过；付费规划执行2次HTTP和4次只读工具调用后因 cache-input 用量转换未通过现有严格解析器校验及剩余额度不足停止。累计6请求，未形成获批计划、业务补丁、实际质量对照或发布，全部自有进程、keeper 和网关已停止。完整本地迭代闭环仍未完成；当前没有生产 Pi。真实邮件、短信和线上自动迭代尚未启用。

以下保留离线控制基础的操作说明。离线测试本身不发送模型请求；真实预览必须使用已授权的独立策略与累计账本，不能把模拟回执当成线上验收。A5 Windows 和 Linux Git 检查通过，也不代表整个 A 阶段跨平台验收完成。

## 启动与目录

C18 分层状态与维护交接见[本机试验报告](../evaluations/pi-local-trial/report.md)、[证据索引](../evaluations/pi-local-trial/receipt-index.json)、[服务器启用清单](server-enablement.md)和[日报/事故通知](notifications.md)。当前为 partial：主机隔离与模拟协议已通过，合成基线机械检查实际失败，45项语义指标/11域仍 unknown。冻结源码离线825 passed、2个Windows符号链接SKIP、19个设施测试deselected；该结果早于 admission 修复，修复另有17项真实SQLite查询测试通过，PostgreSQL回归未运行。完整服务构建与生产启用仍未验收。报告中的旧 A 阶段固定 banner 是历史边界，不自动反映新主机事实。

从仓库根运行 `python -m ops.pi.control ledger-check --state-dir /Users/a1/项目/Myink/myink-pi/state`。
以上命令是Mac私有根示例。原Windows私有根为`E:\tools\myink-pi`，WSL对应`/mnt/e/tools/myink-pi`，状态目录均为该根下的`state/`；Linux原生执行目录另在E盘WSL虚拟磁盘内，迁移映射见交接文档。本轮状态、私有证据、依赖、缓存均在E盘隔离环境，保护主工作区。
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
