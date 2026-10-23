# Pi 完整对照的期限与受控中断

状态：用户已于本会话明确批准，离线实现、测试及独立代码审阅修复均已完成；不包含真实执行授权。2026-10-23，基于Pi分支4364b8fd及同日token校准记录。目标是让完整30槽试验有明确的执行窗口和停止语义；本方案不授权真实模型请求、不调整费用策略或额度。

## 现状与范围

`analysis_launcher._prepare` 对pilot和完整trial都要求绝对deadline在未来600秒内。worker每槽45秒，宿主exchange最多60秒，Docker操作多次各15秒；30×45秒已超过600秒。`analysis_budget.bind_run_budget`只要求首次绑定未来期限，绑定后不可延长，并不自带600秒限制。因此不能只改一个常量后声称完整30槽获得时长保证。

launcher捕获Exception，finally会尝试reconcile/cleanup及写receipt，但KeyboardInterrupt/SystemExit不经过普通失败归类。Gateway请求使用daemon线程，当前各Docker调用也没有共享的全局清理截止时刻。已知费用与已确认的slot outcome是不同概念：计费known不代表输出或清理已验证。

本轮只做宿主离线实现与测试，不改变模型、输入、max_tokens、单worker45秒、单exchange60秒、30槽次序、失败继续规则、历史unknown或20元累计门禁。保留所有未运行槽，不恢复、不重试、不重发。硬杀宿主、掉电及远端计费撤销不属于可保证范围。

## 方案选择

1. 原schema直接从600放宽：改动最少，但会静默扩大既有清单允许的权限窗口，且不解决清理及中断。拒绝。
2. 把30槽分成多个可恢复run：每个run仍短，但破坏现有单run顺序与不可重放语义，新增跨run状态和预算问题。拒绝。
3. 独立版本清单＋不可延长的执行截止时间＋有限清理窗口：采用。本轮先解决确定停止和记录，不承诺一定跑完。

以下数值和接口均为实现者建议，尚未作为用户授权：

- 新schema `pi-analysis-trial-v2`，全量30槽、固定 `failure_policy=continue_known_contract_failure`。
- 沿用既有deadline绝对时间字段，新增且仅允许 `time_policy=bounded_trial_v1`，没有任意用户自定义超时字段。
- 首次check/execute校验 `0 < deadline-now <= 3600`。旧pilot v1/v2和trial v1仍最多600秒；不改历史清单。
- 3600秒是允许用户另行选择的执行窗口上限，不是自动设置的新期限，更不是运行保证。新manifest仍需与有效至deadline的价格/输入证据、源码闭包和新run_id一起重新冻结。
- 所有模型计费及run预算仍绑定同一个原始绝对deadline，永不延长。
- 首次execute同时捕获wall和monotonic剩余时间。后续剩余量取两者最小值；系统时钟倒退不能增加执行时长，前跳会提早停止。
- 停止流、等待gateway结束及容器清理共用执行停止后最多120秒的主动等待预算，且最迟不超过原执行deadline之后120秒。用本地monotonic界定，也受wall截止约束；清理窗口不得发送模型请求、开新slot或创建新容器。该预算不承诺整个launch在停止后120秒内返回，最终账本核查及receipt持久化见下文。
- 每次开始新slot前，要求执行剩余量严格大于120秒，否则以 `insufficient_slot_window` 停止。120秒是保守启动门槛，不宣称覆盖所有Docker最坏情况；各子步骤仍受执行截止约束。短窗口清单可以check，但execute会在首槽前明确停止，且不创建容器或消耗claim。

## 运行状态与结果

沿用现有 `status=checked/completed/blocked`，不中断旧消费者。v2在check和execute receipt新增生命周期字段：`time_policy`、`execution_deadline`、`cleanup_grace_seconds=120`、`stop_reason`、`cleanup_complete`；check使用null表示尚未执行的停止/清理结果。正常完成的stop_reason为null，提前停止只采用下列固定枚举，不包含私有正文或任意异常文本：

- `deadline_exceeded`：执行截止或剩余量耗尽。
- `insufficient_slot_window`：启动下一槽前不足120秒。
- `interrupted`：CLI第一次收到SIGINT或SIGTERM，或库调用中发生KeyboardInterrupt。
- `execution_failed`：协议、身份、未知计费、worker、预算或其他已有失败。
- `cleanup_failed`：执行无更早停止原因，但精确清理未确认或清理超时。

已有主停止原因不可被后续清理错误覆盖；细节仍保留stage/reason和清理记录。正常走完30槽且所有清理已确认才completed；其他均blocked。`cleanup_complete`只在owned和pending均已确证清空、操作标签扫描确认不存在容器、且本run所有已预留model-attempt的canonical settlement已完成时为true（known或已终结的unknown均可，pending不可以）；存在无法确认的create或结算结果仍false，不伪称无残留。未发生reservation时结算条件自然满足。

不新增slot状态。未claim保持NOT_RUN；已有claim而尚未成功finish的槽保持/落UNCERTAIN。普通输出合同失败只有原身份、HTTP负控/唯一session、已知费用和精确清理全部通过、并仍在执行deadline内，才可FAILED继续。完成同样要求deadline内验证与finish，晚到的结果不追认DONE/FAILED。已完成DONE/FAILED不可改写。中断发生在槽完成之前则当前claim按UNCERTAIN处理，即使usage已知；若finish已原子提交，中断不追溯撤销已确定结果，后续停止。summary始终以30槽snapshot生成。

## 请求取消与信号边界

核心实现一个仅宿主持有的停止控制对象，包含固定deadline、monotonic剩余时间、首次停止原因和Event；不写进模型frame、不接受模型选择。stop_reason在执行过程中只能由未停止变成首次原因，不能清空。将其通过v2宿主路径传给slot、relay及provider包装器。

在准备下一slot、创建容器前、启动attach前、逐帧relay、provider实际POST前、结果验证和finish前检查。模型请求已跨越发送边界后不能承诺撤回费用；取消只终止本地等待/流和后续请求。必须尊重现有canonical settlement：已知结算不可覆盖；无法完整证明usage则unknown保留全额。停止后不以补发请求换取usage，不轮询模型，不自动重连。

CLI仅在主线程且显式execute v2时暂存并安装SIGINT/SIGTERM处理器。处理器只记录停止意图，不做Docker/SQLite/HTTP等阻塞操作，finally恢复原处理器。第二次信号也只保持首次停止意图，主动清理等待仍共用120秒预算；用户强制SIGKILL不承诺可清理。库调用不安装进程信号处理器；KeyboardInterrupt在v2执行区域转为interrupted，确保最终receipt后按blocked返回。SystemExit及任意BaseException不当成可忽略错误；finally尝试有限清理与receipt后保留原异常传播，除非新的存储故障使记录无法写入，此时明确报blocked且不得制造成功回执。

跨线程停止是协作取消：检查不能撤回已经进入transport的POST。测试精确界定该边界；停止意图被包装器观测后不得再进入底层transport，已进入者最多一次并沿用不可重发claim。Event并非提供方已取消/已结算的证据。

## 清理与落盘

执行终止后发出关闭当前relay/本地响应的意图，并将同一个只读宿主Event传递至gateway所属线程和_DeadlineUpstream等待路径，由所属线程观察取消并退出、执行既有流finally settlement；不跨线程直接close正在执行的生成器。以有界主动等待观察settlement，不把loopback断连当作结算证明；容器停止和移除不能被未返回的网关无限阻挡，主动清理各项共享预算。按原daemon、name、label和确切ID核实并停止/移除本次拥有的容器，最后核查snapshot/summary并写receipt。不得移除外来容器，不使用rm --force、宽泛标签清理或重建容器。

给v2专用的ProbeHost适配层传入操作剩余时间（每次subprocess timeout不超过原15秒及该阶段剩余量）。执行阶段使用执行剩余量，终止清理使用共享120秒清理剩余量；不是对每个清理步骤重置120秒。实现者可选可选timeout回调或小型子类，但不能改变旧ProbeHost调用者默认语义。清理期间clock到期即记录未移除/未确认对象并停止阻塞操作，不无限重试。

当前attach进程停止与本地句柄关闭使用有界等待；gateway线程不会无限join。若流在取消后无法于清理期限内完成canonical settlement，保留pending/unknown实际状态并报告cleanup_complete=false，不调用新的结算路径捏造费用。后续新run仍受原pending门禁阻止。

120秒约束可控的容器/attach/relay清理及线程主动等待，不能改写canonical存储的持久性语义。现有Ledger.transaction每次有独立30秒竞争等待；最终snapshot、settlement提交和文件落盘不承诺整个调用的硬墙钟上界，也不将多个事务等待假定为只发生一次。主动等待到期后不再启动阻塞清理操作；仍需尝试最终账本核查与receipt，结算未终结则cleanup_complete=false。若存储阻塞或失败，不能输出成功；本轮不增加进程隔离、存储抢占或硬退出看门狗。

新run创建后、首个容器创建前，私有root写一份不可覆盖的 `lifecycle-private.json`，包括run/config/provenance摘要、operation_id、deadline和time_policy，不含凭据或正文。已有root/run冲突仍拒绝。它支持异常退出后的人工核查，不提供恢复执行入口。正常或受控停止后最终receipt含上述生命周期字段。无法写最终receipt是失败，不能向CLI输出completed；系统崩溃仅靠已有claim和初始标识保守判定，自动重启回收器留待独立工作。

## 代码边界与验证

预计改动 `analysis_launcher.py`，新增小型宿主生命周期模块及对应测试；ProbeHost通过受控可选扩展支持剩余量。取消Event通过AnalysisRun.gateway_handler、control.make_gateway_handler、model_gateway.forward_messages/_DeadlineUpstream的可选宿主参数传递，默认无Event时保持旧行为；具体签名交给实现者，不增加模型body字段。不重构Ledger或模型协议，不新增依赖，不改变AnalysisRun终态。trial v2的全部已有trial schema分支（选30、独立结果验证、清理后期限检查、summary）必须同步适配，不能误入pilot路径。

先写失败测试再实现；本轮只用隔离SQLite、loopback、stdio子进程，Docker/provider用外部边界替身，不读取真实凭据/账本或发送私有输入。必须覆盖：

1. v2未来3600内可check、超限/nonfinite/bool/多余字段拒绝；旧schema 601秒仍拒绝；新时间策略错误拒绝。证据valid_until不足拒绝。check不创建run/root/容器、不写账本、不安装signal handler。
2. 30槽跨越原600秒仍可在新期限内完成，保留普通合同FAILED继续；状态和summary与既有规则一致。无需实际等待600/3600秒，以注入时钟驱动。
3. 小窗口在创建容器与claim前停止；中途到期不执行下一slot；worker45秒/exchange60秒不被放宽。时钟回退无延期，前跳停止。
4. SIGINT/SIGTERM/KeyboardInterrupt在provider前、流中、清理中和slot间的确定结果；底层transport未进入时零POST，进入后最多一次。原信号处理器总恢复，库调用不装signal handler。SystemExit重抛并尝试清理。
5. 已知usage后中断不改known；不完整usage不释放预留；未claim NOT_RUN、未finish claim UNCERTAIN；已finish的DONE/FAILED不可改写。
6. cleanup预算全流程共享，Docker/attach卡住有界停止；pending create、daemon/ID/label漂移不越权删除；无法确认残留cleanup_complete=false；主停止原因不被cleanup覆盖。
7. 初始生命周期文件存在且无敏感正文；最终receipt写失败无成功；root/run冲突不可恢复。源/输入/策略漂移、重复session、低预算和未知费用仍停止。
8. 首先定向运行新测试及analysis_launcher/full_trial/run_budget/container_probe相关回归，之后运行全部Pi离线回归（明确排除真实live/lab）。记录真实运行数和跳过数，不把本轮离线验证称为Linux或真实计费验收。

实施完成后独立代码审阅及修复再交付；默认不提交、不推送、不合main或部署。3600秒能力即使离线验收通过，现有1M费用上界仍只保证原余额内的极少槽，不能据此声称完整付费试验就绪。

## 设计审阅

独立builder check已完成。明确了120秒仅约束主动清理等待，不承诺包括持久化在内的整个调用硬上界；统一cleanup_complete同时要求容器与canonical settlement确认，并补充网关所属线程的取消通道。上述为实现者在现有存储约束内的选择，无其他影响方案的未决问题。用户随后明确允许按此方案进入离线实现与测试；不包含付费执行授权。
