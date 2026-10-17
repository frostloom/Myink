# Pi 回归基线修复记录（2026-10-17）

## 范围与环境

依据 runtime032 的五类十项历史失败，先建立当前 `codex/pi-autonomy-design` 的真实复现清单。本轮基础提交 `d85d01c`，未更改业务源码。用户已批准计划，并授权每个完成的小目标提交、推送功能分支；没有 main 合并、付费模型调用或生产发布。

Windows，Python 3.12，计划专属 venv，`docker/constraints.txt` 的 78 项已安装版本逐项匹配。venv 继承 aiink 的系统包，pip 提示与本项目无关的既有 Streamlit/Starlette 冲突，因此不声称完全纯净的 Python 环境。独立 Compose 项目 `myink-regression-20261017` 使用 PostgreSQL/pgvector、Redis、RabbitMQ，端口 25432/26380/25673。初始化脚本仅在忽略的临时目录规范为 LF，独立数据库已执行 `python -m myink.cli init --seed`；没有使用现有业务容器。

## 基线实测

```text
python -m pytest tests/test_cli_auth_safety.py tests/test_flow.py tests/test_task_budget_routes.py tests/test_user_isolation.py tests/test_multiprocess.py -q --tb=short -m "not pi_lab and not pi_live"
7 failed, 84 passed, 3 errors, 1 warning (93.64s)

python -m pytest tests/test_worker.py tests/test_task_budget_recovery.py -q --tb=short -m "not pi_lab and not pi_live"
2 failed, 49 passed (37.78s)
```

| 精确测试入口（均在 tests/） | 实际表现 |
| --- | --- |
| test_cli_auth_safety.py::test_init_does_not_run_legacy_schema_cleanup | 未模拟新增维护 schema 初始化，MagicMock 的权限查询被判为真，触发权限保护 |
| test_cli_auth_safety.py::test_init_default_runs_additive_setup_without_creating_demo_or_samples | 同上 |
| test_cli_auth_safety.py::test_init_seed_flag_creates_demo_account_and_samples | 同上 |
| test_flow.py::test_batch_review_resume_finalizes_chapter | 续跑审核阶段触发 `TaskBudgetPaused: manual_pause` |
| test_flow.py::test_batch_pause_halt_and_resume | 总写作调用 4 次，预期 3 次；已完成节点被重复执行 |
| test_task_budget_routes.py::test_old_delivery_cannot_advance_a_new_resume | 旧消息被持久准入身份校验拒绝，抛 QueueAuthorityUnknown；旧断言仍期待 waiting |
| test_task_budget_recovery.py::test_worker_budget_pause_is_terminal_without_retry | 手工消息与持久任务 payload 不一致，未到达目标预算分支即被拒绝 |
| test_task_budget_recovery.py::test_worker_cancellation_wins_budget_pause | 同上 |
| test_user_isolation.py::test_consumer_requeues_transient_ownership_database_failure[process] | 构造的消息无持久准入，被较早校验送到 DLQ，未到达模拟的瞬时故障 |

`test_multiprocess.py` 三项均在 fixture 就绪时出错，尚未执行历史 kill 断言，不能计为复现第十项失败。实际 worker 日志显示已消费，但 Windows venv 的 Popen PID 是启动器，Redis 心跳 PID 属于其子进程。独立真实子进程对照已证明：直接启动 base executable 并传入 `__PYVENV_LAUNCHER__` 能保留相同 venv 依赖且返回真实 worker PID。后续先修正测试启动方式，再执行 kill 案例及其余断言。

初次准备环境遇到 `pyotp` 缺失；依赖安装尚未结束时的一次 init 因 Pydantic/core 暂时不匹配失败。安装结束、78 项锁检查无漂移后初始化通过。以上环境失败不是业务红测，也未计为通过。

## 计划与边界

1. 修复 CLI 测试的初始化依赖隔离，以及 Windows 进程测试的启动器和终止断言。
2. 调查批次恢复，保持人工审核和暂停保护，禁止重复写已完成节点。
3. 更新过时消息 fixture/断言，使用真实持久准入，保留旧投递拒绝和瞬时错误重入队的安全要求。
4. 全量业务、离线 ops 及相关 CI 门禁，完整列出失败、跳过和环境限制。

本轮未完成修复，未运行全量 CI；保留 runtime032 历史结论。原工作区四个 ops/pi 文件的既有修改不纳入提交。
## 小目标 1：初始化隔离与 Windows worker（2026-10-18）

CLI 的三个初始化测试补齐 `ensure_maintenance_schema` mock，并断言默认初始化调用该迁移。真实角色权限检查未改。Windows venv 的多进程 fixture 直接启动 base executable，并用 `__PYVENV_LAUNCHER__` 保留依赖路径，确保测试持有实际 worker PID。kill 后分别要求 Windows 返回 1、POSIX 返回 -SIGKILL；checkpoint、owner、队列和重复副作用检查全部保留。

实测：两个完整文件共 7 passed（83.11s）。修正启动器后恢复旧负返回码断言，单项真实失败 `assert 1 < 0`（16.30s）；恢复新断言，完整 kill 场景 1 passed（57.81s）。独立只读审查未发现 Critical/Important/Minor。其余已知失败仍未修复，不能宣称业务全量通过。
## 小目标 2：批次暂停和人工审核续跑（2026-10-18）

实际调用链证明两项旧测试未跟上执行契约。人工审核测试直调 runner 前现在明确模拟 Worker 的 `running` 转换，不放宽 awaiting-review fence。手动暂停发生在第二次 provider 返回前，该结果尚未保存，恢复时需要重试；测试检查 ch3 已持久化、ch4 checkpoint 停在 write 且无 draft，再验证续跑后每章只有一条已记录的 write。总 provider 调用为 4，不把暂停后的未提交结果称为已完成节点。

原两项失败已在基线观察；修正后 `python -m pytest tests/test_flow.py -q --tb=short` 为 43 passed（40.72s）。独立审查无 Critical/Important/Minor；业务生产逻辑未改动，全量验收仍在进行。
## 小目标 3：预算恢复与队列权威测试（2026-10-18）

两项预算 worker 测试及瞬时归属查询故障测试注册真实持久准入，使消息通过初始权威检查后进入原定目标分支。旧投递测试保留 QueueAuthorityUnknown，进一步检查 consumer 不 ACK、送死信、不发 SSE、不 dispatch，预算上限和 queued 状态不变。没有 mock 掉持久消息身份或改变生产逻辑。

```text
python -m pytest tests/test_task_budget_routes.py tests/test_task_budget_recovery.py tests/test_user_isolation.py tests/test_queue_handoff.py -q --tb=short -m "not pi_lab and not pi_live"
60 passed, 39 deselected, 1 warning (22.80s)
```

39 项设施测试按 CI 标记被排除，不能算通过；存在既有 Starlette/AnyIO 弃用警告。原四项失败已在基线观察，独立审查无 Critical/Important/Minor。完整业务回归及 offline ops 门禁另行记录。