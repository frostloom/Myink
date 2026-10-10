# Pi A：离线控制与分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 不调用模型、不连接生产，建立可重启、可对账的控制与分析原语。

**Architecture:** `ops/pi/` 使用类型化配置和本地 SQLite；外部副作用通过记录意图、执行、核对回执的协议注入。确定性规则负责时间、预算和范围，Pi 后续只消费证据与提出计划。

**Tech Stack:** Python >=3.11、SQLite、Pydantic、httpx、pytest、临时 Git bare remote；复用现有依赖。

**Spec:** [总体设计](../specs/2026-10-10-pi-autonomy-design.md)；[总计划](2026-10-11-pi-autonomy.md)。本文件执行前必须同时阅读两者。

## Global Constraints

完整继承总计划：E 盘私有状态；首轮累计 100 次/10 元不跨日重置；未确认价格禁止真实调用；维护 02:00–06:00、15 分钟收尾、05:30 停新候选；小步 1 假设/1 行为、3 文件/150 行软目标、8 文件/300 行兜底；本阶段模型、GitHub 和通知上游全部替身。

## Review Focus

- SQLite 并发、损坏或旧版本账本：不重新创建空账本放大额度，不能把未确认操作重做。A1/A2。
- 非法费用、午夜与流式中断：拒绝 bool/NaN/负值，跨日首轮额度不变，未知费用不退款。A2。
- 用户提出新增功能、拆提交绕过范围：进入决策或跨日计划，不自动批准。A3/A5。
- 样本缺失、零值和人工版本混杂：分别标记，不算改善。A4。
- 通知和 Git 操作在成功后丢回执：可核对则补回执，否则留 uncertain，不重复外部写。A5/A6。

## Task 1: A1 账本、身份和操作回执

**Files:** Create `ops/__init__.py`、`ops/pi/__init__.py`、`ops/pi/contracts.py`、`ops/pi/ledger.py`、`ops/pi/control.py`、`ops/pi/tests/test_ledger.py`。`__init__` 不导入业务 DB。

**Interfaces:** `contracts.py` 定义 `Record = dict[str, Any]`，`Identity(deployment_id: str, generation: int, owner: str, image_ids: dict[str,str], commit_sha: str | None = None, schema_id: str | None = None, config_hash: str | None = None)`，`Receipt(operation_id: str, status: Literal['done','failed','uncertain','blocked'], evidence: Record)`。所有记录有 `schema_version=1`。`Ledger(path: Path)` 提供 `transaction() -> ContextManager[sqlite3.Connection]`、`intent(operation_id: str, kind: str, payload: Record) -> Record`、`finish(receipt: Receipt) -> None`、`get(operation_id: str) -> Record | None`、`append_event(kind: str, payload: Record) -> int`。`control.main(argv: list[str] | None = None) -> int` 作为后续统一 CLI；先支持 `ledger-check --state-dir PATH`。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
def test_intent_survives_restart(tmp_path):
    path = tmp_path / "ledger.sqlite"
    Ledger(path).intent("build-1", "build", {"sha": "abc"})
    assert Ledger(path).get("build-1")["status"] == "pending"
```

- [ ] 写 `test_intent_survives_restart`：intent 后重开 Ledger，状态仍为 pending、payload 与版本一致；`test_done_is_immutable`：相同 done 回执幂等，不同结果禁止覆盖；`test_disk_error_blocks_mutation`：失败后不执行注入副作用。
- [ ] 运行 `python -m pytest ops/pi/tests/test_ledger.py -q`，确认 FAIL 且原因为新模块/接口缺失。
- [ ] 实现唯一 operation_id、事务、WAL、完整同步、只追加审计；启动做 integrity/schema 检查，版本不支持或损坏返回 blocked。intent 之后查现实状态并由专用工具核对；pending 不自动等同“未执行”。只创建显式 E 盘状态目录。
- [ ] 重跑同一文件并增加两进程竞争同一 ID 测试；预期 PASS，无活库和网络。运行 `python -m ops.pi.control ledger-check --state-dir E:/tools/myink-pi/state/lab` 返回状态 JSON，禁止显示环境或凭据。
- [ ] 审查与授权保存点：仅保存本任务文件；如本轮获得提交授权，提交 `feat: add durable Pi operation ledger`，否则保留未提交。

## Task 2: A2 请求预算和模型代理

**Files:** Create `ops/pi/policy.py`、`ops/pi/budget.py`、`ops/pi/model_gateway.py`、`ops/pi/policy.example.json`、`ops/pi/tests/test_budget.py`、`ops/pi/tests/test_model_gateway.py`；Extend `ops/pi/control.py`。

**Interfaces:** `load_policy(path: Path) -> Policy` 解析固定 schema；`BudgetPermit` 含 attempt_id、scope_id、reserved_microyuan、deadline。`reserve(ledger: Ledger, scope_id: str, request: Record, policy: Policy) -> BudgetPermit` 和 `settle(ledger: Ledger, permit: BudgetPermit, usage: Record | None) -> None`；费用整数微元，价格输入 Decimal 字符串。`GatewayResponse(status_code: int, headers: dict[str,str], body: bytes | Iterator[bytes], attempt_id: str)` 与 `forward_messages(body: Record, scope_id: str, *, ledger: Ledger, policy: Policy, transport: Callable) -> GatewayResponse` 定义于 model_gateway；流终止时再写 Receipt，避免缓冲整段回复后假装流式。CLI `model-gateway --state-dir PATH --policy PATH --credential-file PATH` 只在信任侧运行，HTTP `/v1/messages` 与流式均经此入口。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_101st_http_attempt_denied / test_unknown_usage_retains_reservation
assert forwarded_count == 100
assert denied_response.status_code == 429
assert ledger_reserved_microyuan == reserved_before_disconnect
assert total_reserved_microyuan <= 10_000_000
```

- [ ] 写 `test_101st_http_attempt_denied`：100 个实际替身请求后第 101 个不触 transport；`test_reservation_race_never_exceeds_ten_yuan`：并发预留总额 <=10_000_000 微元；`test_midnight_does_not_reset_local_trial`；`test_unknown_usage_retains_reservation`；`test_missing_confirmed_prices_blocks_live`。
- [ ] 运行 `python -m pytest ops/pi/tests/test_budget.py ops/pi/tests/test_model_gateway.py -q`，预期 FAIL。
- [ ] 实现可信 policy 与固定 `local-trial-1` scope，实验和进程共享同一额度；未来 server-daily scope 使用北京时间日期但默认禁用。单请求最长 120 秒；校验允许模型、协议、请求大小、输入上界、max_tokens 和所有计费维度，先原子预扣再出站。输入上界与价格来源作为可信配置必填，未校准时关闭真实调用；不得从 Pi 请求接受价格、上限或任意 base URL。
- [ ] 实现 Anthropic 流逐事件透传与有界 usage 采集，缓存读写/输入输出按配置费率处理；402、空响应、断连、未知 usage 保留尝试及未知预留。无隐含 SDK 自动重试，每次实际重试重新 reserve；供应商 request_id 供对账，不因客户端重复 ID 默认免费重发。拒绝请求重定向到任意站点；不打印 key/header/完整异常上下文。
- [ ] 重跑上述测试，补 `test_boolean_negative_nan_price_rejected`、`test_stream_disconnect_no_refund`、`test_proxy_restart_keeps_scope`、`test_client_cannot_change_model_or_prices`、`test_cache_usage_incomplete_is_unknown`，预期 PASS。本任务用 httpx MockTransport，不发真实模型请求；真正禁止绕行由 B7/C15 验收。
- [ ] 审查与授权保存点：`feat: enforce durable Pi model budgets`。

## Task 3: A3 阶段时间、小步计划和确定性门禁

**Files:** Create `ops/pi/schedule.py`、`ops/pi/plans.py`、`ops/pi/tests/test_schedule.py`、`ops/pi/tests/test_plans.py`；Extend `ops/pi/policy.py`、`ops/pi/control.py`。

**Interfaces:** `window_at(now: datetime) -> Record` 计算带时区维护窗口；`next_action(ledger: Ledger, now: datetime, observations: Record, policy: Policy) -> Record` 返回单个类型化动作与 deadline，不执行 shell。`Plan` 固定 hypothesis、metric、minimum_improvement、severe_regression、sample_floor、guard_metrics、baseline、scope、files、slice_ids、compatibility、rollback、call_estimate、time_estimate；`validate_plan(plan: Plan, baseline: Record, policy: Policy) -> Receipt`、`check_diff(plan: Plan, diff: Record, policy: Policy) -> Receipt`。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_0530_refuses_new_candidate / test_threshold_change_invalidates_comparison
assert window_at(datetime.fromisoformat("2026-10-11T05:30:00+08:00"))["allow_new_candidate"] is False
assert diff_receipt.status == "blocked"  # 累计生产增删 301 行
assert evidence_plan_hash != modified_plan_hash
assert old_comparison_valid is False
```

- [ ] 写 `test_0530_refuses_new_candidate`、`test_0600_requires_verified_open_receipt`、`test_backup_before_heavy_work`、`test_pre_failure_still_allows_recovery`；在虚拟北京时间下断言 deadline 与动作顺序，不使用真实 sleep。
- [ ] 写 `test_new_feature_enters_user_decision`、`test_plan_soft_target_requires_smaller_slice_or_reason`、`test_cumulative_diff_cannot_split_commits`、`test_threshold_change_invalidates_comparison`。期望目标在候选结果前冻结；越兜底范围 blocked，软目标偏离需结构化说明和独立审查，不能模型自报通过。
- [ ] 运行 `python -m pytest ops/pi/tests/test_schedule.py ops/pi/tests/test_plans.py -q`，预期 FAIL。
- [ ] 实现每阶段行动意图与剩余时间检查；只有收尾/开放/恢复可以越过“新候选停止”状态。POST 超时登记 backup_pending 后恢复开放，下次普通发布先补缺口；每天最多一次普通发布，事故恢复单列。受保护政策路径和高风险类型进入政策决策，不由行数放行；开发前必须有规则回执和独立审查回执，两者绑定 plan_hash。
- [ ] 同文件重跑，补重复调度、跨日工作保存、预算耗尽继续恢复/报告、未达标继续诊断、计划无新证据避免反复修改；预期 PASS。CLI `schedule --clock ISO_TIME --simulate` 输出动作计划，不连接真实服务。
- [ ] 审查与授权保存点：`feat: gate Pi plans and maintenance phases`。

## Task 4: A4 版本化数据、基线与比较口径

**Files:** Create `ops/pi/metrics.py`、`ops/pi/compare.py`、`ops/pi/telemetry.py`、`ops/pi/tests/test_metrics.py`、`ops/pi/tests/test_compare.py`、`ops/pi/tests/test_telemetry.py`、`src/myink/observability.py`；Modify `src/myink/workflow/nodes.py` 的 `record_run`（当前约 92 行）及 `src/myink/config.py`；Create `tests/test_run_provenance.py`。

**Interfaces:** `collect_snapshot(reader: Callable, window: Record, identity: Identity) -> Record`，`compare_windows(baseline: Record, candidate: Record, plan: Plan) -> Record`，`public_status(observations: Record, now: datetime) -> Record`。快照字段包括部署/schema/model/config/prompt/rubric/data_hash，planned/completed/failed/paused 数、测量值与 availability 标记、版本区间与混杂因素；结果固定为 improved/not_improved/regressed/insufficient_evidence/confounded。`run_provenance(settings) -> dict[str, Any]` 放 `src/myink/observability.py`，record_run 只附加部署/观测元数据到 detail，不重写历史成本或状态。业务镜像不依赖未打包的 ops 模块。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_nineteen_tasks_insufficient / test_manual_or_model_change_confounds_window
assert result_for_19_tasks["status"] == "insufficient_evidence"
assert result_for_99_tail_samples["p95_conclusion"] is None
assert result_with_manual_change["status"] == "confounded"
assert missing_cost["availability"] == "unknown"
```

- [ ] 写 `test_failed_planned_tasks_remain_in_denominator`、`test_zero_and_missing_are_distinct`、`test_nineteen_tasks_insufficient`、`test_p95_requires_one_hundred`、`test_manual_or_model_change_confounds_window`、`test_quality_is_not_inferred_from_cost`。planned 事件来自任务/入队意图，不能只从成功 agent_runs 生成分母。
- [ ] 写 `test_maintenance_page_up_pg_down_is_incident`、`test_stale_heartbeat_is_incident`、`test_expected_worker_stop_is_not_incident`。维护状态只能豁免预期业务停止，不能豁免 PG、备份和 06:00 后业务探针。
- [ ] 运行 `python -m pytest ops/pi/tests/test_metrics.py ops/pi/tests/test_compare.py ops/pi/tests/test_telemetry.py -q`，预期 FAIL。
- [ ] 实现允许的 SQL 投影、时间窗、分页和查询期限；生产读取角色仅 SELECT，正文按选定样本读取，不返回账号环境/密钥。任务记录按 task/thread 与父批次归并，区分排队、人工等待和节点耗时。历史记录缺少部署或测量标记则 unknown，不能用今天配置回填；当前采集配置来自信任侧、对日志只存哈希与标识。
- [ ] 运行上述离线测试，预期 PASS；B7 独立服务建立后运行 `python -m pytest tests/test_run_provenance.py tests/test_admin_observability.py tests/test_run_ownership.py -q`。验证 record_run 保留已有 detail、归属与账费，新增测量与版本可回读。数据库测试未执行前该子回执保持 pending。
- [ ] 审查与授权保存点：`feat: compare Pi metrics by deployed baseline`。

## Task 5: A5 Git 分支、候选冻结和人工版本失效

**Files:** Create `ops/pi/git_flow.py`、`ops/pi/tests/test_git_flow.py`；Extend `ops/pi/control.py`。

**Interfaces:** `prepare_slice(repo: Path, experiment_id: str, slice_id: str, base_sha: str) -> Record`、`freeze_candidate(repo: Path, branch: str, check_receipts: list[Receipt]) -> Record`、`merge_candidate(repo: Path, candidate: Record, remote: str) -> Receipt`。Git 参数使用 argv，禁止 shell 拼接；remote 允许列表来自信任配置。每次调用绑定 expected_head/expected_base，不默认部署 latest main。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_new_main_invalidates_checks / test_wip_push_does_not_change_ready_slice
assert merge_receipt.status == "blocked"
assert ready_ref_after_wip_push == frozen_ready_ref
assert required_skipped_check_does_not_authorize_merge is True
```

- [ ] 写临时 bare remote 的 `test_wip_push_does_not_change_ready_slice`、`test_new_main_invalidates_checks`、`test_new_candidate_commit_unfreezes`、`test_skipped_check_blocks_merge`、`test_unrelated_local_changes_untouched`。输入含空格/中文路径的 repo 仍工作；分支为 `codex/pi/<experiment>/<slice>`，父 WIP 分支为 `codex/pi/<experiment>`。
- [ ] 运行 `python -m pytest ops/pi/tests/test_git_flow.py -q`，预期 FAIL。
- [ ] 实现工作分支与独立步骤分支、draft/ready 模拟 PR、准确 SHA 合并和新 revert 分支；保存 push/PR/CI/merge 分别的意图与回执，操作失联用 Git ref/PR 身份核对，不 force push。protected paths/额度/发布政策不能由普通优化提交改变。与人工变更合并冲突保留分支、废止证据；不擅自覆盖用户历史。
- [ ] 重跑同文件并验证相同 SHA 的发布不被 Git 层当相同 deployment（B13 才决定部署归属）、模拟远端成功后丢回执能核对；预期 PASS。所有 Git 指向测试 bare remote，不用项目 origin。
- [ ] 审查与授权保存点：`feat: freeze and verify Pi candidate revisions`。

## Task 6: A6 可维护报告、捕获通知与控制测试 CI

**Files:** Create `ops/pi/reporting.py`、`ops/pi/notify.py`、`ops/pi/tests/test_reporting.py`、`ops/pi/tests/test_notify.py`、`docs/pi/README.md`、`docs/pi/analysis-and-scoring.md`；Extend `ops/pi/control.py`；Modify `.github/workflows/ci.yml`，新增不使用业务服务的 ops 测试 job。

**Interfaces:** `render_report(events: list[Record], snapshots: list[Record]) -> str`、`send_daily(ledger: Ledger, report: Record, transport: Callable | None) -> Receipt`。通知唯一键为日期/run_id/类型/内容版本；字段含发送状态、Message-ID、attempts、unknown，不含正文原始证据和凭据。CLI `report --state-dir PATH --output PATH` 输出 UTF-8 Markdown 与 JSON 索引。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_uncertain_send_not_automatically_duplicated
assert transport_call_count == 1
assert notification_receipt.status == "uncertain"
assert development_notification_kind == "daily_report"
```

- [ ] 写 `test_report_keeps_failure_after_success`、`test_no_release_has_reason_and_next_action`、`test_unknown_cost_not_zero`、`test_missing_recipient_queues_report`、`test_development_report_is_not_incident`、`test_uncertain_send_not_automatically_duplicated`。
- [ ] 运行 `python -m pytest ops/pi/tests/test_reporting.py ops/pi/tests/test_notify.py -q`，预期 FAIL。
- [ ] 实现账本生成日报、捕获 transport、有限重试与回执。SMTP 成功后丢回执无法证明未发送，保留 uncertain；能按幂等键查询的提供方才自动核对重发。fault event 与 daily report 分开；未配置真实发送服务保存 pending。本任务只使用内存或本地捕获服务。
- [ ] 文档说明启动配置、目录、账本升级、字段单位、版本窗、样本/盲评限制、阻塞排查和报告示例；CLI 显示下一动作与未验收项。CI 增加 `python -m pytest ops/pi/tests/ -q -m 'not pi_lab and not pi_live'`（后续设施测试使用显式 marker 单独运行，不默认触发 WSL/模型）。
- [ ] 运行 `python -m pytest ops/pi/tests/ -q -m 'not pi_lab and not pi_live'`、`python -m compileall -q ops/pi`，预期全 PASS；CI 使用相同 marker 排除显式设施/付费测试，不扩大 token 权限、不改已有 job。阶段 A 回执列出 A4 活库验证仍 pending。
- [ ] 审查与授权保存点：`feat: report Pi evidence and offline gates`。
