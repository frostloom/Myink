# Pi B：维护恢复与本机基础设施 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在独立服务中证明维护暂停、可靠交接、备份恢复、资源限制和人工部署优先。

**Architecture:** E 盘专用 Linux 环境承载独立 Docker daemon。可信控制程序持有固定工具权限，候选代码和 Pi 的执行环境不挂载 Docker socket 或秘密；业务维护状态存 PostgreSQL，发布与维护身份存外部持久账本。

**Tech Stack:** 独立 WSL2/systemd/cgroup、Docker/Buildx、现有 PG16+pgvector/Redis/RabbitMQ、Python pytest；不使用真实模型上游。

**Spec:** [总体设计](../specs/2026-10-10-pi-autonomy-design.md)；[总计划](2026-10-11-pi-autonomy.md)；依赖 [A1–A6](2026-10-11-pi-control-foundation.md)。

## Global Constraints

继承总计划。独立发行版磁盘和所有新运行数据在 E 盘；不改全局 WSL 配置或默认 context。Pi 384MiB/0.5 核，整组测试或 BuildKit 1536MiB/2 核、swap 额外 <=256MiB；连续 10 秒可用内存 <512MiB 停止重任务；阶段期限不超过 06:00。备份保留 >=14 自然日、最近 5 次 PRE/POST 对和稳定点；维护不停止 PG/Redis/RabbitMQ/入口。禁止对生产使用 down -v，本轮所有操作限定实验标签和 daemon。

## Review Focus

- 有限额参数但容器不在受限 cgroup：环境 blocked，不执行真实 Pi。B7/B12。
- 维护期间 Worker 重启或任务暂停原因变化：屏障仍生效，人工等待/预算暂停不自动恢复。B8/B9。
- ACK、publish confirm、DB 回执之间中断：允许重复投递但效果不重复，消息不会凭空消失。B10。
- dump 可解压但恢复失败、缺角色/附件/加密材料：不能称可恢复；POST 欠账不阻止健康开放。B11。
- 旧候选、迁移超时、人工同 SHA 部署：核对真实身份和事务结果后交接，不回滚新版本。B13。

## Task 7: B7 E 盘隔离环境与资源执行器

**Files:** Create `ops/pi/lab/preflight.ps1`、`ops/pi/lab/install.ps1`、`ops/pi/lab/compose.yaml`、`ops/pi/lab/provision.sh`、`ops/pi/lab/cgroup-setup.sh`、`ops/pi/resources.py`、`ops/pi/executor.py`、`ops/pi/tests/conftest.py`、`ops/pi/tests/test_executor.py`、`ops/pi/tests/test_resources.py`、`ops/pi/tests/integration/test_isolation.py`、`docs/pi/local-lab.md`；Extend `ops/pi/control.py`、`pyproject.toml` 的 pytest marker 注册。

**Interfaces:** `probe_environment(root: Path) -> Receipt`、`execute(command_id: str, args: Record, deadline: datetime, ledger: Ledger) -> Receipt`、`sample_resources(target_id: str) -> Record`。command_id 为固定清单，分别注册测试、构建、数据读取、Git、备份和恢复，不接受 shell 字符串。`install.ps1 -Root E:\tools\myink-pi -Distribution MyinkPiLab` 只创建新环境；`control lab preflight --root PATH` 和 `control lab up --state-dir PATH` 输出资源与身份回执。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_missing_cgroup_proof_blocks_execution / 实际出站反例
assert execution_without_limits.status == "blocked"
assert direct_upstream_http_succeeded is False
assert upstream_key_found_in_sandbox is False
assert protected_policy_modified is False
```

- [ ] 写 `test_unknown_command_rejected`、`test_path_escape_and_symlink_rejected`、`test_secret_env_not_inherited`、`test_foreign_docker_target_rejected`、`test_low_memory_for_ten_seconds_stops_heavy_work`、`test_missing_cgroup_proof_blocks_execution`；运行 `python -m pytest ops/pi/tests/test_executor.py ops/pi/tests/test_resources.py -q`，确认 FAIL。
- [ ] 实现 PowerShell 只读 preflight：E 盘路径、现有 WSL/虚拟化、工具版本、磁盘、发行版重名、rootless/权限与 cgroup 条件；现有同名环境不覆盖。安装使用官方镜像和完整性清单，在新发行版安装私有 daemon，不复用系统 Docker context。失败留下回执，不触发主机重启或已有发行版 shutdown。
- [ ] 实现内部 Docker 网络、无秘密候选沙箱和受控出站代理；Pi/候选代码仅能到模型代理与类型化工具端口，不能到公网、生产 DB、宿主或元数据地址。gateway 单独持有上游凭据并且校验 token/scope；包下载与 Git 在白名单工具中执行。挂载只含候选源代码及 E 盘缓存，排除 .env、主工作区、私有账本、备份、凭据、宿主 socket；去 capability、非 root、只读政策域。直接工具子进程继承同一隔离，而非只靠 extension 拦截。
- [ ] 建立 lab UUID 标签、独立 PG/Redis/RabbitMQ/网络/卷及动态 loopback 端口；生成 `lab-env.json`，不使用生产 URL。测试环境导出自己的 DATABASE_URL/ADMIN_DATABASE_URL/REDIS_URL/AMQP_URL/QUEUE_PREFIX，业务 fixtures 的默认地址必须被替换。默认 `.env` 自动加载也不能读到真实凭据。清理核对 daemon/项目/标签/绝对路径，只清本轮资源。
- [ ] 注册 `pi_lab` 与 `pi_live` markers；conftest 注册 `--pi-lab`、`--pi-live`。选中设施/付费测试却未显式选项或 preflight 失败时报 UsageError/blocked，不静默跳过；普通 CI 明确 `-m 'not pi_lab and not pi_live'`。所有 live fixtures 自动检查价格、累计 scope 和 B 阶段回执，不能通过直接 pytest 绕过 CLI 门禁。
- [ ] 运行前述单测预期 PASS；再运行 `python -m pytest ops/pi/tests/integration/test_isolation.py -q -m pi_lab --pi-lab`。断言子进程与全部测试容器位于整组 cgroup，限制实际生效；直接 HTTP、嵌套 curl/Python、读取 credential、修改 policy、访问主目录全部被拒，模型替身能经代理成功。依赖缺失不得用 SKIP 当验收。
- [ ] 记录发行版/docker/cgroup/网络/路径身份、资源峰值和剩余容量，写 local-lab 文档；审查与授权保存点：`feat: isolate Pi lab tools and resources`。

## Task 8: B8 持久维护屏障与独立维护页

**Files:** Create `src/myink/models/maintenance.py`、`src/myink/maintenance.py`、`ops/pi/maintenance.py`、`ops/pi/lab/maintenance.Caddyfile`、`ops/pi/lab/maintenance.html`、`tests/test_maintenance_admission.py`、`tests/test_maintenance_worker_barrier.py`；Modify `src/myink/models/__init__.py`、`src/myink/db.py`、`src/myink/cli.py`、`src/myink/worker/enqueue.py`、`src/myink/worker/consumer.py`、`src/myink/api/routes_tasks.py`、`src/myink/task_budget.py` 的续跑入口；Extend lab compose、ops control。

**Interfaces:** DB `MaintenanceControl` 单例保存 epoch/generation/owner/deadline/admission_closed/consumer_blocked；变更只由可信入口发起。`maintenance_view(db) -> Record`、`require_admission_open(db) -> None`、`may_consume(db) -> bool`；不可读维护状态时拒绝新增/消费。`enter_maintenance(ledger: Ledger, expected: Identity, now: datetime) -> Receipt` 同时记外部 epoch 和数据库屏障。API 返回 503、machine code `maintenance` 和北京时间 reopen_at，不暴露控制端点。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_generate_and_resume_denied_during_maintenance
assert response.status_code == 503
assert response.json()["code"] == "maintenance"
assert production_messages_executed_after_worker_restart == 0
```

- [ ] 写 `test_generate_and_resume_denied_during_maintenance`、`test_no_quota_charge_before_admission`、`test_worker_restart_does_not_consume`、`test_db_unavailable_fails_closed`、`test_maintenance_page_survives_candidate_failure`；运行 `python -m pytest tests/test_maintenance_admission.py tests/test_maintenance_worker_barrier.py -q`，确认 FAIL。
- [ ] 按现有 `ensure_task_budget_schema` 模式新增维护表和幂等初始化，使用精确授权的控制角色；API/Worker 仅读控制表，租户不能改状态。不加生产管理员路由；数据库或屏障不可确认时 fail closed。关闭 admission 的行锁与新任务登记形成顺序边界；已经接收的任务保留队列身份。
- [ ] 消费循环创建或恢复订阅前查屏障，屏障开启时只保持心跳；在 _on_message/任务认领再检查，消除进入维护与取消息的竞态；不得用重投忙循环消耗资源。续跑、计划确认及预算追加入口也遵守维护拒绝，不把任务状态强改 done/failed。
- [ ] 维护入口使用独立稳定 Caddy 配置/静态文件，重任务不重建或停止它；检查 390px 展示和开放时间、HTTP 状态/Retry-After，实验端口绑定 loopback。生产 Caddy TLS/卷本轮不变，后续部署计划才接管入口。
- [ ] 运行新增两文件及 `tests/test_enqueue_gates.py tests/test_task_budget_routes.py tests/test_manual_plan.py`，预期 PASS；运行实验 HTTP 探针确认只停止 API/Worker、PG/Redis/Rabbit/维护页仍健康。A4 的活库验证在此后完成。
- [ ] 审查与授权保存点：`feat: persist maintenance admission and consumption barriers`。

## Task 9: B9 节点暂停、父子状态和恢复兼容

**Files:** Create `src/myink/maintenance_pause.py`、`tests/test_maintenance_pause.py`、`tests/test_maintenance_compatibility.py`；Extend maintenance model；Modify `src/myink/task_budget.py` 的节点/效果守卫、`src/myink/workflow/runner.py`、`src/myink/workflow/short_runner.py`、`src/myink/workflow/batch_graph.py`、`src/myink/worker/processor.py`。

**Interfaces:** `MaintenancePaused` 独立于 TaskBudgetPaused；`request_pause(db, epoch: str, task_id: str, generation: int) -> None`、`guard_maintenance(stage: str) -> None`、`confirm_pause(db, task_id: str, checkpoint: Record, message: Record) -> Record`、`resume_maintenance_tasks(db, epoch: str, expected_generation: int) -> list[Record]`。暂停回执包含 task/thread/parent、epoch、generation、completed/next_node、checkpoint_id、事务结果、消息与锁、原等待原因。只恢复相符维护暂停；不自动追加模型额度。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_resume_does_not_repeat_completed_effect / test_user_budget_and_review_wait_not_resumed
assert persisted_chapter_count == 1
assert persisted_memory_effect_count == 1
assert resumed_task_ids.isdisjoint(user_and_budget_paused_ids)
```

- [ ] 写单章、短篇、批次父子、工具往返的 `test_resume_does_not_repeat_completed_effect`；分别断言正文/记忆落库只一次、下一节点准确、批次已完章节不重跑。另写 `test_user_budget_and_review_wait_not_resumed`、`test_unconfirmed_interruption_blocks_candidate`。
- [ ] 运行 `python -m pytest tests/test_maintenance_pause.py tests/test_maintenance_compatibility.py -q`，确认 FAIL。
- [ ] 在已有 budget_node 入口与效果事务中加入维护 generation 守卫，节点中途只请求暂停，不把未完成写事务标为安全；执行结束并持久 checkpoint/short progress 后确认。冻结旧 owner 的后续副作用；失联在途模型保留 unknown 与预算预留。15 分钟无法确认时取消候选，保留 interruption_unconfirmed，由稳定版核对；不能使用强杀作为无损暂停证明。
- [ ] 长篇/批次使用现有 checkpointer 与显式 thread 恢复；短篇用已有 `_Progress` 和任务进度；runner 单独捕获 MaintenancePaused 并传回 pause decision，保留计划/审核 interrupt。不替换 P2 预算账本、不混用维护和预算暂停原因。
- [ ] 本任务用两个隔离 Python 进程及明确版本状态集合检查旧状态到候选续跑、候选状态到稳定版恢复；覆盖单章、短篇、批次、plan/review 等待和工具响应。首个可回退“稳定版”须已支持基础维护协议，不能把未改造的线上 `c1f7a84` 当无条件兼容版本。兼容证明绑定两版本和 schema；新增不兼容候选必须被拒。B12 建立镜像构建后，B13 再用两个真实镜像执行同一矩阵，不倒置任务依赖。
- [ ] 运行新增测试和 `tests/test_task_budget_recovery.py tests/test_short_runner.py tests/test_worker.py tests/test_manual_plan.py`，预期 PASS，报告节点矩阵与实际恢复镜像。审查与授权保存点：`feat: pause and resume tasks at verified maintenance points`。

## Task 10: B10 消息交接、恢复对账和不丢任务

**Files:** Create `src/myink/worker/handoff.py`、`tests/test_queue_handoff.py`、`tests/test_maintenance_reconciliation.py`；Extend maintenance model；Modify `src/myink/worker/consumer.py`、`src/myink/worker/amqp.py`、`src/myink/worker/enqueue.py`、`src/myink/worker/processor.py`；Extend ops maintenance。

**Interfaces:** DB `QueueHandoff` 保存 message_id/task_id/operation_id/body_hash/destination/state 与受控重建 payload；`record_handoff(db, body: Record, destination: str, operation_id: str) -> Record`、`publish_handoff(operation_id: str) -> Receipt`、`reconcile_queue(db, epoch: str) -> Receipt`。message_id 和 operation_id 持久，不使用 channel delivery_tag 作为跨重连身份。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_ack_then_publish_failure_has_outbox / test_confirm_then_receipt_failure_deduplicates_effect
assert handoff_record_exists_after_restart is True
assert orphan_task_ids == set()
assert persisted_chapter_count == 1
```

- [ ] 写 `test_crash_before_ack_preserves_original`、`test_ack_then_publish_failure_has_outbox`、`test_confirm_then_receipt_failure_deduplicates_effect`、`test_unmaterialized_and_delayed_tasks_accounted`、`test_redis_loss_does_not_lose_pause_receipt`。
- [ ] 运行 `python -m pytest tests/test_queue_handoff.py tests/test_maintenance_reconciliation.py -q`，确认 FAIL。
- [ ] 用小型事务 outbox 修复当前 consumer ACK 后 retry/defer publish 的窗口：先保存可重建交接记录，再确认消息；独立重放器 publisher confirm 成功后结算。重复发送允许出现，任务物化、认领和副作用按持久身份去重。未知 confirm 不删 outbox，不按“没发”重新制造新的 task_id。保留 priority、退避与 retry_count。
- [ ] 给 admission 接收但未物化的任务留下 durable intent，以便计算 planned 分母和重建消息；更新 owner 验证不凭未知消息恢复用户暂停。维护恢复对账核对 DB/任务/checkpoint/queue/main-delay-DLQ/outbox/锁，未知或冲突不解除屏障。受控 payload 不进入 public 报告。
- [ ] 独立 RabbitMQ 中在每个 DB/ACK/confirm 边界终止并重启消费者，再检查最后无孤儿任务、章节和记忆效果只一次；运行上述两文件及 `tests/test_worker.py tests/test_enqueue_gates.py tests/test_multiprocess.py`，预期 PASS，不把替身证明当真实交接验证。
- [ ] 审查与授权保存点：`fix: retain task handoffs across queue interruptions`。

## Task 11: B11 PRE/POST 备份、留存和完整恢复

**Files:** Create `ops/pi/backup.py`、`ops/pi/tests/test_backup.py`、`ops/pi/tests/integration/test_restore.py`、`docs/pi/backup-and-recovery.md`；Extend ops control。只复用 `scripts/backup.sh` 中已核验 dump/压缩方法；不把现有按份数轮转直接用于新的配对策略。

**Interfaces:** `create_backup(ledger: Ledger, phase: Literal['PRE','POST'], identity: Identity, executor: Callable, root: Path) -> Receipt`、`restore_check(manifest: Record, target: Record, executor: Callable) -> Receipt`、`retention_candidates(manifests: list[Record], now: datetime) -> list[str]`。manifest 含 artifact hashes、角色、配置/附件/证书/解密材料引用、外部账本快照、完整性、离机回执与 restore_status；秘密内容在私有集合，不在 manifest 明文。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_stable_point_and_last_five_pairs_retained / test_missing_roles_or_crypto_material_not_restorable
assert stable_backup_id not in deletable_ids
assert all(pair_id not in deletable_ids for pair_id in last_five_pair_ids)
assert restore_with_missing_crypto_material.status != "done"
```

- [ ] 写 `test_pre_failure_blocks_candidate_not_recovery`、`test_post_pending_blocks_next_release`、`test_stable_point_and_last_five_pairs_retained`、`test_failed_artifact_not_counted_as_good`、`test_duplicate_backup_trigger_has_one_owner`、`test_missing_roles_or_crypto_material_not_restorable`。
- [ ] 运行 `python -m pytest ops/pi/tests/test_backup.py -q`，确认 FAIL。
- [ ] 用唯一锁、part → 原子 manifest 发布、dump exit/stderr/非空/gzip/hash 验证；备份和临时目录在 E 盘工作区外。保留 14 自然日、5 发布配对、稳定点；删除前复核允许名单和新峰值容量。单机副本同步到独立本地私有目的地，真实离机未配置则 offsite_status=not_configured。
- [ ] 恢复到干净 PG16+pgvector，导入必要角色和 schema，`psql ON_ERROR_STOP=1`；验 RLS、章节/关系/checkpoint、附件哈希、MODEL_CREDENTIAL_KEY 可解密与控制账本一致。首次/迁移/工具变化及虚拟每周触发演练，失败阻止新的候选；不把 gzip -t 当完整恢复。
- [ ] 运行单测和 `python -m pytest ops/pi/tests/integration/test_restore.py -q -m pi_lab --pi-lab`，预期 PASS；记录 PRE/POST 顺序、600 秒 deadline、磁盘新增峰值和恢复校验。应用回滚不还原 PRE 覆盖新数据；数据库事故保存现场并退出自动数据丢失路径。
- [ ] 审查与授权保存点：`feat: verify paired Pi backups and restores`。

## Task 12: B12 限额测试和串行镜像构建

**Files:** Create `ops/pi/build.py`、`ops/pi/checks.py`、`ops/pi/lab/buildkitd.toml`、`ops/pi/tests/test_build.py`、`ops/pi/tests/test_checks.py`、`ops/pi/tests/integration/test_build_limits.py`；Modify `scripts/ci-local.sh`、`docker-compose.test.yml`，把项目名/URL/端口改为可覆盖且原默认不变；Extend ops control/lab compose。

**Interfaces:** `run_checks(candidate_sha: str, lab: Record, executor: Callable) -> list[Receipt]`、`build_images(candidate_sha: str, lab: Record, ledger: Ledger) -> Receipt`。检查回执含 required/status/pass/fail/skip/command/version/junit/artifact_hash，不能只解析一个“passed”字符串；镜像回执为精确 revision + image IDs/digests，加载与 build 分开。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_python_build_precedes_caddy / 实际资源回执
assert build_order == ["python", "caddy"]
assert worker_image_ids == [api_image_id, api_image_id]
assert build_memory_max_bytes == 1536 * 1024 * 1024
assert build_memory_plus_swap_bytes == 1792 * 1024 * 1024
```

- [ ] 写 `test_only_one_heavy_action_runs`、`test_python_build_precedes_caddy`、`test_workers_reuse_python_image`、`test_skip_or_missing_required_check_blocks`、`test_disk_new_peak_plus_five_gib_required`、`test_loading_cost_is_in_deadline`。
- [ ] 运行 `python -m pytest ops/pi/tests/test_build.py ops/pi/tests/test_checks.py -q`，确认 FAIL。
- [ ] 显式创建专用 docker-container builder，1536MiB RAM、RAM+swap 总计 1792MiB、2 核、max-parallelism=1；inspect/cgroup 实测生效。Python Dockerfile 与 caddy/Dockerfile 依次 build/load，CLI/daemon/load 开销纳入宿主门槛。固定稳定镜像和最近两个已验证集合；失败候选清理不得删除唯一稳定集合。
- [ ] 测试 runner/PG/Redis/Rabbit 同属受限父 cgroup，1536MiB 总额；无 xdist，前端 worker=1。现有 ci-local.sh 的 `myink-test` 与端口作为默认保留，Pi 调用必须注入自己的 UUID 项目/环境。contracts export 在专用候选副本执行，不能覆盖主工作区或其他会话产物；runner 本身不读取真实 .env。
- [ ] 单测 PASS 后运行 `python -m pytest ops/pi/tests/integration/test_build_limits.py -q -m pi_lab --pi-lab`，实际冷/热缓存与人工压力/OOM 注入，检查不超范围、PG/维护入口保持健康，阶段最长 45 分钟。运行完整 Python/前端/案例/契约和两镜像验证，逐项列真实 PASS、SKIP 或 blocked；Go 仅实际适用时执行。
- [ ] 审查与授权保存点：`feat: bound Pi regression and serial image builds`。

## Task 13: B13 发布身份、迁移期限、人工接管和独立恢复

**Files:** Create `ops/pi/deploy.py`、`ops/pi/recover.py`、`ops/pi/tests/test_deploy.py`、`ops/pi/tests/test_recover.py`、`ops/pi/tests/integration/test_release_recovery.py`、`docs/pi/release-and-handoff.md`；Extend ops control/maintenance。

**Interfaces:** `deploy_candidate(ledger: Ledger, expected: Identity, candidate: Record, executor: Callable) -> Receipt`、`takeover_manual(ledger: Ledger, expected: Identity, requested: Record, executor: Callable) -> Receipt`、`recover_owned(ledger: Ledger, now: datetime, executor: Callable) -> Receipt`；共用主机锁，所有真实写入前核对 generation/owner/image_ids/epoch。CLI `release --candidate MANIFEST --expected IDENTITY`、`recover --state-dir PATH`、`manual-intent --manifest PATH`；恢复无需模型。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_manual_same_sha_invalidates_old_watchdog
assert before.commit_sha == after.commit_sha
assert before.deployment_id != after.deployment_id
assert old_recovery_receipt.status == "blocked"
assert actual_image_ids == manual_image_ids
```

- [ ] 写 `test_manual_same_sha_invalidates_old_watchdog`、`test_pre_candidate_crash_restores_original_services`、`test_manual_takeover_inherits_opening_responsibility`、`test_unrecorded_container_change_blocks_writes`、`test_lease_expiry_does_not_mean_docker_finished`。
- [ ] 写 `test_migration_lock_timeout_has_known_transaction_result`、`test_nontransactional_uncancellable_ddl_rejected`、`test_candidate_startup_keeps_queue_barrier`、`test_post_failure_reopens_with_backup_pending`、`test_0600_failure_is_alert_not_fake_open`。
- [ ] 运行 `python -m pytest ops/pi/tests/test_deploy.py ops/pi/tests/test_recover.py -q`，确认 FAIL。
- [ ] 实现持久 maintenance_epoch 在关闭服务前落盘；未发布恢复原稳定服务/撤销维护，已发布只回滚仍属于本 Pi 的候选。主机锁临界区仅生产步骤，不包围分析/构建；人工意图阻止新步骤，当前有界操作核验结果后交接。未知现场保存只读证据，不认领陌生镜像。
- [ ] 发布门禁绑定 exact merge SHA、required checks、PRE、状态兼容、schema/config 与资源回执。迁移设置 lock_timeout、statement_timeout、最晚开始时间和事务结果；非事务不可安全取消的操作 blocked。合成探针使用独立 DB/队列，候选生产 Worker 保持屏障；健康 + POST done/pending + 所有者对账后才解除/续跑。
- [ ] 实际演练两镜像切换、候选 OOM、Pi 失联、重复调度、人工抢占、同 SHA 重新发布、旧 watchdog、05:30/06:00 deadline 和迁移超时；重复 B9 状态兼容矩阵，运行 `python -m pytest ops/pi/tests/integration/test_release_recovery.py -q -m pi_lab --pi-lab`，预期 PASS。恢复耗时写入峰值报告，不能只用 stub executor 得出可恢复结论。
- [ ] 编写用户部署如何使用同一入口、绕过入口后 unknown 的处理和维护责任交接文档；审查与授权保存点：`feat: fence Pi releases and recover owned maintenance`。
