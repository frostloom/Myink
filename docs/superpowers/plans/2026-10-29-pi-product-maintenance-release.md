# Pi 产品维护与发布接线计划

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans inline and test-driven-development. Existing Pi worktree, no implementer agents. One fresh final reviewer at Task3, one author fixpass, no rereview.

**Goal:** 当前产品从无维护协议的旧版本安全引导到经过明确授权的新版本，完成匹配的恢复、观察与归属安全回退。

**Architecture:** 可信主机持有共享锁、固定操作包和独立批准文件；持久控制记录在执行副作用前落盘，旧任务必须自然排空。模型不接触执行器，主机产生脱敏审计；源码准备、隔离演练与生产授权分别验收。

**Tech Stack:** Python3.12、现有SQLite Ledger、Linux固定Docker命令、PostgreSQL16/Redis/RabbitMQ、现有追加审计与stdlib reader。

**Spec:** docs/superpowers/specs/2026-10-28-pi-online-closed-loop-design.md。

关联规格：docs/superpowers/specs/2026-10-28-pi-online-closed-loop-design.md。
前置：2026-10-29-pi-product-source-integration 的单次源码审查、作者修复、全量回归和精确提交 CI。此文为后续执行计划，所有未勾选项均未验收。

## 目标与授权

把现有 maintenance、pause、backup 和发布锁接到实际产品运行环境，形成可审查的固定操作包；经用户明确授权后才合入 main、安装生产协议、切换产品镜像。先完成离线实现及隔离真实服务演练，不逐阶段询问。只在已有 Pi 分支工作；不修改管理员页面、认证和其他分支。禁止把 readonly product_preflight 改成审批器，禁止以 observed 或表存在视为发布许可。

保留原 manager/费用库、累计50元和9笔历史未知预留。此次产品接线不是模型请求授权扩展；原有限付费 profile 的到期时间保留，不通过日期、切换源码或重建账本续期。原始输入、备份、会话和生产配置留私有区，管理员只读脱敏事件与证据摘要。

## 接口与实施顺序

### Task 1: 冻结实际产品及首次引导兼容协议

**Files:** Create `ops/pi/product_bootstrap.py`; Test `ops/pi/tests/test_product_bootstrap.py`. Read `ops/pi/maintenance.py`, `ops/pi/backup.py`, `src/myink/db.py`, `src/myink/maintenance_pause.py`. No production schema execution in this task. 用户已授权中途推送；可推送标明WIP的阶段检查点，最终独立审查仍在Task3，不以检查点CI代替完整验收。

**Interface:** `prepare_bootstrap(ledger, plan, host, *, now=None)` receives a trusted host boundary (never model/HTTP input). Closed plan fields: schema, mode, operation_id, legacy, candidate, expires_at. Legacy freezes source commit/hash and complete container/image identity; candidate uses contracts.Identity fields. Host must acquire shared release lock and revalidate external authorization/current identity before each fixed action. Action order: close_ingress -> drain_legacy -> backup_pre -> install_schema -> bind_identity. A prepared receipt is admission-closed, workers-stopped, release_allowed=false; no activation or public reopen is included. ACTUAL will require the exact Linux adapter introduced in Task2; injected clocks/adapters cannot impersonate it.

**Failure semantics:** Persist parent and per-step intents before effect; a pre-existing unfinished intent is uncertain and cannot dispatch again. Definite blocked work remains blocked; exceptions/partial results become uncertain. Never open ingress as generic finally cleanup. Drain requires two normal worker exits and zero active tasks, ready/unacked messages, consumers, task/book locks and unknowns under the same ingress fence. PRE proof must match original release pair and actual restore. Historical provenance remains unchanged.

- [x] Write isolated SQLite/shared-lock regression tests for action ordering, active/unknown drain, before/after identity drift, expired/denied authority, crash-after-intent, duplicate/changed plans, schema uncertainty and no reopen/activation.
  Expected: missing protocol fails; after implementation the same tests pass without production services/provider calls.

- [x] 重新读取实际 Python/前端/数据库/Redis/Rabbit 镜像与物理源码清单；记录 source commit 与组件身份，不用镜像标签代替内容校验。检测人工部署漂移则使旧操作包失效。
- [x] 读清 src/myink/db.py、maintenance.py、maintenance_pause.py、ops/pi/maintenance.py、contracts.py 及共享发布锁实现，明确 application protocol 与 host canonical identity 的对应。
- [x] 对当前无 maintenance/provenance 的旧部署设计首次引导：人工发布锁优先；先用固定边界停止新入口并确认旧 worker 排空，再进行经批准的兼容性 schema 安装。旧 worker 没有协议时不能伪造 pause/checkpoint；无法排空则阻断。
- [x] 固定 deployment_id/generation/owner/epoch/各组件 image ID、旧新源码与兼容版本；历史 task/run 缺 provenance 仍保留 null，不能回填当前身份。主机固定命令无任意 shell/模型参数。所有人工发布入口也必须参与同一发布锁与递增身份协议；不能仅凭 Pi 自己持锁便断言人工发布已被隔离。
- [x] RED 覆盖身份漂移、缺旧协议、活跃旧任务、未确认暂停、锁抢占、重复执行、版本不兼容、迁移失败和部分写入；逐项修复后针对性回归。

### Task 2: 实际服务隔离演练与备份恢复

**Files:** Create `ops/pi/product_commands.py` for bounded binary native transport and `ops/pi/product_runtime.py` for canonical Linux adapter, `ops/pi/product_backup.py` for existing paired-backup bridge, `ops/pi/product_restore.py` for owned network-none PostgreSQL import and bounded private material restoration, `ops/pi/product_migration.py` for candidate-image additive schema/identity jobs, `ops/pi/product_cold_probe.py` for read-only application restoration checks in both frozen images, `ops/pi/product_activation.py` for fixed candidate/rollback cohort creation, source/runtime verification and natural process lifecycle; Test `ops/pi/tests/test_product_commands.py`, `ops/pi/tests/test_product_runtime.py`, `ops/pi/tests/test_product_backup.py`, plus owned real-service integration fixtures. Product activation/rollback is added here, not exposed as a model tool.

**Interface:** `LinuxProductHost` implements Task1 shared lock, independently issued exact authorization, fixed identity observation and fixed actions; ACTUAL forbids injected transport/time. Separate production/rehearsal roots and physically owned labels/IDs prevent rehearsal from targeting myink resources. Existing backup protocol supplies manifest/restore proof; control ledger must be disjoint from canonical billing/manager state. `activate` requires prepared receipt plus current PRE/restore, then fixed image switch, business probes, POST/restore and explicit reopen. `rollback` requires current exact candidate ownership and compatible verified recovery; no fee/manager rewind. No generic command/SQL/path argument comes from a model.

- [ ] 复用 ops/pi/backup.py 的 release pair、可信清单和 restore attestation；数据库/角色/加密材料/附件/配置/证书/原账本快照需成套。备份必须私有且可恢复；不把旧测试套件通过当作当前产品恢复证明。原费用/manager 快照只用于保全与核对，业务回退不能恢复旧费用账本、释放未知预留或重置已执行意图；维护控制 ledger 与原计费 ledger 类型必须分开。
- [ ] 为当前 Linux Docker 环境提供固定 executor；复用可信资源绑定，不把 WSL lab 的 /mnt/e 或固定容器名直接搬到生产。演练使用明确拥有的独立网络、卷、端口，生产 socket 由可信主机持有。
- [ ] 对同一冻结源码完成真实 PG/Redis/Rabbit 的 intake 阻断、long/short/batch checkpoint、VIP/普通/延迟队列盘点、恢复后续跑、原费用/guest quota 保持；未确认执行和未知发布保留阻断。
- [ ] PRE 从目标版本复制并在独立环境实际恢复，核对 PG 身份、业务完整性、加密/附件引用与资源归属；旧版本仍可用的回退兼容性单独证明。只清理本次拥有资源。
- [ ] 验证失败后重入不重复 schema/发布/收费；保存每个工具 intent/result 和失败证据。

Task2 发布控制接线：新增 `ops/pi/product_release.py` 及对应单测，使用独立封存的 control approval 绑定原 plan、运行模板、入口配置哈希和维护截止时间。顺序为停止态候选创建→安装标记→POST实际恢复→启动→就绪→开放PG及Caddy；每步持久意图，未知不重放，无 finally 自动开放。回退先关入口/准入、保留消费者排空，再阻消费/自然退出、新代次旧镜像启动及开放；只切代码、保留后续业务写入及原费用历史。运行中暂停/跨代接续、完整配置认证恢复和业务探针仍须各自验收，不能由原生开放收据替代。先按边界/顺序/失败写RED，再运行独占真实七服务演练；ACTUAL主机构造限制在完整能力齐备前保留。

Task2 运行配置恢复资格：新增 `product_runtime_snapshot.py`，备份v2必须绑定独立封存的原始运行模板，并把实际PRE/POST Config.Env、命令、资源/网络/卷作为私有配置材料入包；原生读取前后均重新核对。ACTUAL只接受v2和runtime资格；旧v1仅保留SIMULATED材料/应用读取范围。恢复目标仅本次拥有的无网络PG，重置只允许临时目标管理员；应用/报表角色密码从原运行材料读取，强制SCRAM（错误密码必须拒绝）、readonly和RLS验证，口令不进入argv、意图或公开审计。业务探针和最终POST阶段仍另验收，不把这一资格冒充完整业务发布。

Task2 业务读取与POST顺序：新增固定 `product_business_probe.py`，独立封存的只读案例绑定plan/context、真实用户/项目/章节及响应摘要；仅从候选API自身发固定loopback GET，临时令牌留容器内，验证本人内容、外租户和匿名拒绝及数据库逻辑不变。控制v2顺序为创建→验证启动→业务读取→验证停止→POST实际恢复→独立正式启动→开放；工厂批准v2新增正式启动/回退停止动作，旧六动作批准不得扩权，POST和原正常停止/业务收据缺失不能启动。该层不冒充long/short/batch生成或跨代接续，完整目标继续验收。

Task2 恢复主API进程：runtime资格额外在恢复PG的无网络命名空间启动真实`myink-api` PID1，使用封存实际API环境、原应用/报表凭据和资源，仅覆盖隔离端点/只读/反馈恢复位置并关闭外部模型及遥测。核对PID1环境、导入源码、附件内容、匿名空列表、已知用户作品读取及自然退出；恢复资格合同升为3，绑定15组件，旧认证读取收据不能复用。该层不伪称Redis/Rabbit/worker/Caddy已重建，完整服务及写作任务仍继续验收。

Task2 完整服务恢复接线：备份runtime资格同时封存原Redis/Rabbit/Caddy有效配置和原入口JSON，Redis以原值/绝对到期快照保存配额状态，前后只容许自然过期；旧心跳不冒充恢复worker。所属独占内部恢复网络内重建认证Redis/Rabbit、两真实worker和Caddy，验证错误口令拒绝、空队列、专属心跳、每个真实worker的应用只读DB/错误口令拒绝及Redis/Rabbit连接、API/经Caddy就绪、封存TLS证书指纹及worker自然退出；恢复合同4/17组件阻止弱资格复用。worker保留独立PID/hostname，目标PG只对本次私有网段开放原应用/报表SCRAM，逐次拒绝外来网络成员；不共享宿主PID。Caddy冻结二进制复制到本次私有执行tmpfs并逐字节cmp，保持cap-drop ALL/no-new-privileges和其余tmpfs noexec，不修改镜像。Redis与Caddy配置及证书只经私有材料写入本次tmpfs，不恢复原费用/manager，不成为模型工具。

### Task 3: 固定操作包与一次独立审查

- [ ] 冻结候选源码、CI、镜像、PRE/恢复证明、迁移计划、操作顺序、维护窗口、最大停机时间、观察阈值、回退触发和权限。全量范围区分历史导入、主机操作与 Pi 模型候选。
- [ ] 单次新独立最终审查，单次作者修复，按修复影响回归；不循环复审。
- [ ] 提交并推送 Pi；精确提交 CI。main 合入与生产安装/发布前，将完整可审查操作包提交用户做最后明确授权。未授权期间可完成所有独立准备。

### Task 4: 授权后产品采用、真实观察与回退

- [ ] 按明确授权范围合入 main、确认 main 精确 CI 和镜像身份，重查人工部署/锁/窗口，取得已批准 PRE 后执行；每一步写持久 intent/result，异常停止，不重放未知意图。
- [ ] POST 成套备份与独立实际恢复；实际业务探针和指标对照绑定新 deployment/generation，不以容器 healthy 代替业务成功。
- [ ] 仅当当前版本仍由本次 owner 持有、generation/epoch/image 匹配且兼容恢复证明有效，才执行批准的业务回退；人工版本抢占则停止并报告。恢复实际业务探针确认后才记录 rolled_back。
- [ ] 新真实付费候选独立审核、隔离开发与失败调整、最终审核和采用形成全链证据；原有限许可已过期或证据不匹配时记阻断，不自动扩展付费窗口。
- [ ] 登记并实际完成新候选次日与24–48小时观测；计划和结果为不同事件，旧18/18结果不能替代。持续时间不能用模拟时间压缩。

## 管理员交付与验收

现有 src/myink/pi_audit.py、docs/contracts/pi-audit-v1.md 和 docs/pi/administrator-audit-handoff.md 是 main 只读消费接口。每阶段投影 observation/analysis/plan/review/tool/development/test/deployment/rollback/version/followup，关联 operation、candidate、deployment 和证据哈希；每日版本及完整变更范围分片输出，不能截成虚假的完整范围。模型建议不成为权限。

验收必须区分 implemented、offline verified、isolated rehearsal、approved、deployed、observed、rolled_back；没有收据就是待完成。最后交付裸 Pi 增强清单、工具/记忆/边界、运行及失败流程、每日版本范围、次日计划与独立结果。源码集成和控制器在线均不能结束完整 Pi 上线目标。
