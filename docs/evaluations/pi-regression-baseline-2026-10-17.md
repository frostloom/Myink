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
| test_flow.py::test_batch_pause_halt_and_resume | 总写作调用 4 次，预期 3 次；需区分已持久化节点与暂停后的未提交结果 |
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

基线诊断阶段尚未完成修复、未运行全量 CI；以下续记记录实际修复与验收，保留 runtime032 历史结论。原工作区四个 ops/pi 文件的既有修改不纳入提交。
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
## 小目标 4：离线分析测试的主机路径隔离（2026-10-18）

业务全量实测为 1612 passed、1 skipped、159 deselected、5 xfailed（495.44s），无 failed/error。离线 ops 首次全量出现额外一项失败：1421 passed、1 failed、2 skipped、19 deselected（485.73s）。该测试依赖固定 macOS 私有目录存在，在 Windows 上先被根目录校验拒绝，未到预期的缺失目录分支。在不含四个既有未提交修改的冻结快照中单项复现相同失败（1 failed，1.35s）。

仅修正 `ops/pi/tests/test_writing_analysis.py`：用含中文路径的真实临时可信目录，仍调用实际权限和路径校验，要求缺失子运行目录返回原精确错误；测试改名说明实际覆盖范围。完整文件 41 passed、1 skipped（20.33s），跳过项因本机不能创建 symlink。独立审查无 Critical/Important/Minor。没有修改生产可信根或绕过安全校验；最终离线全量重验另记。

## 最终验收：源版本与已完成检查（2026-10-18）

业务全量针对 `1e60cad` 测试源码运行；随后 `c4af844` 仅增加 ops 测试修正和记录，未改变业务测试或产品代码。前端、契约和镜像所用产品源码与 `c4af844` 一致，已通过 `git diff --exit-code e210aac..c4af844 -- src web Dockerfile caddy pyproject.toml docker/constraints.txt` 核验。原工作区四个 ops 文件 SHA256 与开始时逐项一致，未进入提交。

| 门禁 | 实测结果 |
| --- | --- |
| 业务全量 `pytest tests/ -q -m 'not pi_lab and not pi_live'` | 1612 passed、1 skipped、159 deselected、5 xfailed；495.44s，退出码 0 |
| 前端 `npm ci`、`npm run lint` | 成功；保留已有 React refresh/effect 警告 |
| 前端 `npm test` | 58 files、457 passed；162.81s，退出码 0 |
| 前端 `npm run build` | tsc/Vite 成功；保留 bundle 大小警告 |
| `compileall -q src tests ops/pi` | 成功 |
| `scripts/evaluate.py validate` | audit 20、catalog 40、retrieval 8、comparison 2 案例校验成功，无模型请求 |
| OpenAPI 导出与 `git diff --exit-code -- spec/api-openapi.json` | 成功，无契约漂移 |
| API、Caddy 镜像构建 | 均成功；使用仓库支持的基础镜像代理参数 |

业务普通 skip 是 `test_evaluation_comparison_integration.py::test_direct_full_and_ablation_preserve_all_outputs_and_persisted_body`：需要显式认可的 localhost:15432 数据库身份；本轮隔离库为 25432，不绕过安全校验。五项 xfail 为既有冲突样例 05–09，仍是未实现/已知缺口，不是通过。159 项按 CI 标记排除的 pi_lab/pi_live 未执行。业务警告包括 Starlette/AnyIO 弃用与负向 HS512 用例的短密钥提示。Windows 进程行为已实测，POSIX SIGKILL 分支未在 Linux 实测，不能声称 Ubuntu Actions 等价验证。

镜像从 `e210aac` 的 `git archive` 构建，避免把私有 venv、日志或四项既有修改加入构建上下文；之后提交仅改测试和文档。首次官方 Python 基础源因 auth.docker.io 连接失败退出 1，失败日志保留；改用项目现有 `PYTHON_IMAGE/NODE_IMAGE/CADDY_IMAGE` 代理参数后退出码均为 0。镜像 revision 标签为 `e210aac`，不是对后续提交标签的伪装。未部署镜像。

- API image ID：`sha256:0b68ac2c50d7b4cbe08ea351d44a6f5f04d5faa636a0e419a8ce915b0d31b6df`
- Caddy image ID：`sha256:f6193f70ad6869a465cf78d8c97de1320a0a8a1a7d0e62b2c5e18b65a688a8ae`

完整迭代差异 `d85d01c..1e60cad` 已独立审查，无 Critical/Important/Minor；额外路径修正 `c4af844` 另行独立审查通过。离线首次全量包含工作区既有四项修改，因此最终离线验收另从 `c4af844` 干净归档运行，不能拿选集或旧工作区结果替代。

专属 Compose 项目 `myink-regression-20261017` 已 `down --volumes` 成功，按项目 label 查询容器为空；没有清理其他项目。原始日志和 JUnit 留存在本轮忽略的临时工作目录，不提交私有环境文件。GitHub 当前工作流仅 main push/PR 触发，功能分支推送不代表已运行远端 Actions。

后续计划见 `docs/superpowers/plans/2026-10-18-pi-analysis-stability.md`，已独立审查，仅完成规划，尚未执行。当前提示已有部分 025 修正，后续先补真实缺口，再提供新模型、样本、费用和停止条件的预注册供审阅。当前所有门禁都不能证明写作语义质量提升，历史 032 失败终态与 025 质量方案未采纳结论保留。

补充诊断：对照用的未修正 `e210aac` 干净归档全量为 1420 passed、2 failed、2 skipped、19 deselected（607.77s），除已知路径案例外，`test_pi_rpc.py::test_continuation_requires_started_ack_and_new_completion_events[queued]` 出现一次 0.6 秒启动/协议截止时间敏感失败。原 transcript 只有首个 prompt，随后进入 clear_queue/abort 清理时才收到首轮 started/message_end/settled；未发送预期第二个 prompt，不能把它算作续跑拒绝路径已测。该轮曾与其他离线检查重叠，日志保留；这不证明生产续跑缺陷，也不因后续成功而删除该次失败。最终快照结果另列。

最终 `c4af84418de93cb077b734731dee0b536f9503f0` 干净归档执行 `python -m pytest ops/pi/tests/ -q --tb=short -ra -m 'not pi_lab and not pi_live'`：**1422 passed、2 skipped、19 deselected（548.14s），退出码 0**。两项 skip 分别是 `test_writing_analysis.py::test_symlink_intake_is_denied` 与 `test_writing_evidence.py::test_load_rejects_symlink_even_when_target_is_inside_root`，均因本机符号链接权限。未选入的 19 项 pi_lab/pi_live 不能算通过。该次包含此前 RPC queued 用例且通过，但没有修复其 0.6 秒测试截止时间，稳定性风险仍保留。

验收结论：本轮十项历史回归测试修正及额外主机路径测试隔离已完成，当前选定 CI 标记范围的业务、离线 ops、前端与构建检查通过。这里的通过仅指已执行集合，没有把普通 skip、xfail、未选入设施测试、未运行 Linux 路径或付费质量实验计为通过。78 项锁匹配的继承 venv、Windows 主机、镜像代理和记录中的一次 RPC 时间敏感失败，使本轮不能标为完全等价 Ubuntu Actions 或无间歇失败。没有合并 main、部署或启用每日自治。

对时间敏感 RPC queued 用例，随后在同一 `c4af844` 冻结归档中单独串行重跑 3 次，均 1 passed（13.30s、0.74s、10.04s）。未修改该测试或生产实现；这三次通过只说明未再次复现，不消除旧归档那一次失败或证明它已修复。

关键本地证据 SHA256：业务 JUnit `b318046cb83f56e1947fe86d110b24f0278434aa32811d7134891b656035a9b7`；最终干净归档 ops JUnit `1cf54793c9ab971a5c008471245292a5035d5becbb1bf89c389ead0eb91d609e`。原始日志仍在忽略的工作目录。

已推送的小目标：`58276a7` 基线与计划、`e210aac` CLI/Windows 进程、`3cd1c3d` 批次恢复、`1e60cad` 持久准入和预算恢复、`c4af844` 主机路径测试隔离；最终验收记录另行提交。分支保持 `codex/pi-autonomy-design`，不修改 main。
