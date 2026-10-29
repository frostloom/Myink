# Pi 管理过程与管理员输出对照

本对照是 main 后续接入的交付索引，不是管理员页面已上线的证明。读入口：`src/myink/pi_audit.py`；字段、分页、完整性与次日关联规则：`docs/contracts/pi-audit-v1.md`；接入边界：`docs/pi/administrator-audit-handoff.md`。

## 原始 Pi 的增强

| 层 | Myink 增强 | 证据与边界 |
|---|---|---|
| 运行时 | 固定 Pi SDK/RPC、Node 和依赖摘要，私有 HOME/XDG/TMP | `ops/pi/pi_config.py`、`pi_rpc.py`；关闭自动扩展发现、隐藏重试及默认 shell；模型不持有生产凭据 |
| 工具 | observe_metrics/read_source/propose_plan/apply_patch/run_check/candidate_status 六项 | `ops/pi/tools.py`、`extensions/tool-schemas.json`；按阶段授权，固定源码、文件和检查器；无任意 shell/SQL/Git/部署工具 |
| 记忆 | 冻结指标、会话、原费用和工具收据、失败反馈、来源绑定的诊断摘要与审计历史 | `diagnostic_memory.py`、原 manager/费用库及独立 audit；记忆不授予审批；服务器未接 Hindsight，本机 Codex 的 myink bank 是另一条能力 |
| 任务与审核 | 真实问题复现、开发前独立审核、固定选择、隔离开发、完成后独立审核 | proposal/selection/development/candidate-review 各自绑定来源和摘要；模型 approve 文本不等于主机许可 |
| 隔离与费用 | 私有候选、冻结 gold、低权限无外网检查器、原账本先预留后结算 | 累计50元，9笔原未知预留不释放；未知费用/协议/清理异常停止付费；不跨日重置 |
| 维护与恢复 | 发布锁、事务准入、checkpoint、持久队列移交、PRE/POST 与兼容恢复协议 | `maintenance.py`、`maintenance_pause.py`、`worker/handoff.py`、`ops/pi/backup.py`；源码/演练与实际生产启用分开验收 |
| 审计与版本 | 追加链、内容寻址导出、标准库 reader、版本/变更分片、次日计划与实际结果 | `ops/pi/audit.py`、`audit_export.py`、`src/myink/pi_audit.py`；只读且不承担费用或执行权威 |

逐项详细设置及历史启用身份见 `agent-enhancements.md`。控制器源码、运行时部署、产品版本、Pi 模型产生的候选是四种不同身份；源码历史导入不能计作 Pi 模型自主改进。

## 每轮工具与开发流转

| 阶段 | 保留的管理员输出 | 成功/失败解释 |
|---|---|---|
| 检查 | observation：指标窗口、样本数、来源/组件身份、观测时间 | 重叠窗口不累加成独立日样本；缺信息显示 unknown |
| 分析 | analysis：有界检查总结、假设、决定、原因、下一步、主机计数和证据摘要 | 模型分析是不可信建议；完整私有会话不进入浏览器 |
| 复现与计划 | test/plan：固定复现结果、允许改动范围和检查标准 | 基线失败可代表复现成功，不能标为候选通过 |
| 独立审核 | review：来源绑定、结论、理由、证据和候选身份 | 开发前审核不代替完成后审核；审核建议不代替权限 |
| 工具 | tool：operation_id、工具名、请求投影、结果、阶段和证据摘要 | intent 无匹配结果是未决；不得以重试隐藏未知效果 |
| 开发 | development：基线/候选、实际文件增删、固定检查结果和失败 | 失败保留原事件，调整形成后续事件；不覆盖历史失败 |
| 接受或拒绝 | review/test：完整候选、固定 gold 和最终检查、独立接受 | 绿色候选仍是 candidate_ready，未发布保持 no_release |
| 采用与观察 | deployment/observation：批准关联、实际 owner/generation/epoch/image、业务探针 | 容器健康不是业务成功；当前镜像不回填旧 task/run 身份 |
| 回退 | rollback：触发原因、旧/新身份、备份恢复证明及实际业务恢复结果 | 只在仍拥有当前部署时执行；清理候选/重启控制器不算业务回退 |

所有阶段以可信主机生成的 operation、run、source/candidate 摘要及 evidence 关联；摘要字段被清洗或截断必须保留标记。管理员可查看有界投影及完整分页历史，原始输入/私有源码/密钥/完整会话和备份留私有证据区。

## 每日和第二天输出

- 每日 `daily(day)`：运行列表、各组件版本历史、完整累计变更范围、发布状态、原账本费用投影和观测窗口。上海日期和未知发生时间显式区分。没有事件的日期显示 unknown，不能生成虚假版本更新。
- 大范围变更按每事件最多128路径分片，保留同一冻结 base/candidate、分片序号/总数和完整范围证据哈希；不得把单个分片声明为全范围。导入历史与本轮修复分别给出范围。
- 次日任务：稳定 test_id、UTC 到期时间、target_run_id、target_version_sha256、regression/metrics/quality/restore、验收标准及 planned/blocked 状态。
- 实际结果另追加 test 事件：只有真实到期、匹配运行和版本、发生时间明确的 ACTUAL 结果才关联。未执行是 null/pending；未满足环境或许可是 blocked，均不是通过。昨天计划到今天执行时，需要跨日期读取原计划。
- 保留每日失败、拒绝、未知费用、被人工发布抢占、回退及恢复结果；同一候选/路径重复观察不重复计数。原 owner002 的次日18/18只属于该固定候选，不替代新的次日或24–48h验收。

## 可用于简历的指标口径

记录固定问题的基线失败数、候选通过数、独立案例总数、实际模型/工具次数、原账本已知费用与未知预留、开发用时及明确证据域。当前已知历史 owner002：18个固定案例，7失败到0失败，1次选择与12次开发模型请求、14次认证工具调用；这些是固定输入实验结果，不是线上成功率提升。源码合并及本轮119项针对性回归属于人工控制器/产品集成，不能改写为 Pi 自主开发绩效。线上改善必须另有实际部署、独立样本、观察窗口和回退证据。

当前产品接线与尚待验收项见 `docs/superpowers/plans/2026-10-29-pi-product-maintenance-release.md`。管理员只读 API、权限和页面在 main/管理员分支另行接入；此文件不授权合并或发布。

## Linux 引导与恢复阶段（2026-10-30）

阶段源码b38d8a80，4028项离线通过/43未选入，7个合成数据真实服务案例另行通过；未发布。固定命令意图、成套材料、独占恢复、运行包源码核对、闭闸schema及首次归属绑定已实现。数据库/材料恢复不替代业务恢复。9条本地pi-audit-v1事件已由独立标准库reader读取，完整18路径范围和blocked次日计划保留；尚未追加服务器审计。阶段口径、失败及待完成项见[记录](../evaluations/pi-native-bootstrap-checkpoint-2026-10-30.md)与同名JSON，最终发布包仍按维护计划验收。

## 应用恢复与POST阶段（2026-10-30）

源码efd26876：4048项离线通过；显式真实服务验证为应用6项、PG/迁移6项、配对应用1项。冻结新旧镜像实际读取恢复数据，检查源码、HTTP启动、密钥/MFA、附件/TLS、所有租户（含空数据）、checkpoint/pending writes；POST绑定当前候选及持久身份，保留PRE之后新增数据。属于人工主机边界增强，不扩大Pi SDK六工具，不计为Pi自主开发绩效。新增9条本地审计，独立标准库reader验证本轮11路径与前轮9事件保留；未写服务器，次日blocked且无结果。生产activate/rollback仍未齐备，不称上线或业务回退。详见docs/evaluations/pi-application-recovery-2026-10-30.md/.json，仍按原累计50元及9笔未知预留边界推进。
