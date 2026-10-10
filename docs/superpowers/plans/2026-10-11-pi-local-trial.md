# Pi C：集成与有界本机实测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 安装固定版本 Pi，在已验证隔离和恢复的本机环境完成一次小步优化及次日归因演练。

**Architecture:** RPC 阶段执行器调用 Pi，官方扩展桥接受控工具，模型仅连接预算代理。开发输出为计划、补丁与证据，控制程序核验后执行本地候选流转；跨日继续由账本而非一条无限会话维持。

**Tech Stack:** Pi v1.1.0 `@earendil-works/pi-coding-agent`、Node >=22.19、TypeScript 扩展、Python RPC/评测/账本、B 阶段独立 Linux 实验服务。

**Spec:** [总体设计](../specs/2026-10-10-pi-autonomy-design.md)；[总计划](2026-10-11-pi-autonomy.md)；前提为 [A](2026-10-11-pi-control-foundation.md) 和 [B](2026-10-11-pi-maintenance-lab.md) 的 required 回执通过。

## Global Constraints

固定 Pi v1.1.0 与安装锁/完整性，不静默升级 latest。新运行时/缓存/会话/证据在 E 盘；首次实测累计最多 100 HTTP 请求、估算 10 元，含压缩、重试、评审和生成。平台 Anthropic/`deepseek-v4.1-flash` 的真实凭据仅预算入口持有。价格、隔离、资源或恢复检查不通过时不做付费闭环。规则严重错误不能被文风平均分抵消；至少 5 组配对，缺样本不发布。Git/邮件/云告警本轮仍是本地模拟，不部署线上。

## Review Focus

- Pi 返回 accepted/agent_end/exit 0，但随后重试或 assistant error：不能当阶段成功。C14。
- 恢复会话、异常工具和压缩触发额外请求：预算代理统一计量，工具不越权。C14/C15。
- Pi 计划阈值随结果改变、候选提示词未真正生效：废止比较，实际运行路径必须有哈希。C16/C17。
- 人工版本改变或次日未达标：重建基线、自主归因，不对旧证据反复发布。C17。
- 缺设施、超预算或模拟云服务：明确 blocked/partial/simulated，不声称完整上线。C18。

## Task 14: C14 固定安装、RPC 生命周期和模型兼容

**Files:** Create `ops/pi/lab/install-pi.sh`、`ops/pi/pi_rpc.py`、`ops/pi/pi_config.py`、`ops/pi/tests/test_pi_rpc.py`、`ops/pi/tests/test_pi_config.py`、`ops/pi/tests/integration/test_pi_compatibility.py`、`docs/pi/pi-version-upgrade.md`；Extend ops control/local-lab 文档。

**Interfaces:** `make_pi_config(root: Path, gateway: Record, policy: Policy) -> Record`、`run_phase(phase: str, prompt: str, session_path: Path, deadline: datetime, tools: list[str]) -> Receipt`、`stop_phase(reason: str) -> Receipt`。RPC 命令用唯一 id；stdout 仅 JSONL，stderr 分开脱敏；session_path 由实验/run/stage 决定，不能默认 --continue。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_prompt_acceptance_not_completion / test_agent_end_before_retry_not_success
assert ledger.get(phase_operation_id)["status"] == "pending"
assert run_was_accepted is True
assert stage_complete_before_agent_settled is False
assert abort_command_order == ["clear_queue", "abort"]
```

- [ ] 写 fake 子进程的 `test_prompt_acceptance_not_completion`、`test_agent_end_before_retry_not_success`、`test_error_message_with_exit_zero_fails`、`test_handled_prompt_does_not_wait_forever`、`test_json_unicode_separator_is_not_record_boundary`、`test_clear_queue_before_abort`、`test_session_resume_does_not_repeat_tool_receipt`。
- [ ] 运行 `python -m pytest ops/pi/tests/test_pi_rpc.py ops/pi/tests/test_pi_config.py -q`，确认 FAIL。
- [ ] 安装脚本在 B7 新发行版的 E 盘 runtime 下建立私有 npm 项目，安装精确 `@earendil-works/pi-coding-agent@1.1.0 --ignore-scripts`，记录 registry/integrity/package-lock，后续 npm ci；不执行默认用户目录的一键安装器。Node 已有且满足最低版本则固定其版本/路径，否则下载经官方校验的 Node 到 E 盘；版本不可验证或接口不符则 blocked。
- [ ] 设置 HOME、XDG 缓存、npm cache、临时路径、`PI_CODING_AGENT_DIR`、显式 `--session-dir` 全在 E 盘。Pi models.json 使用预算代理 baseUrl、`anthropic-messages` 与限定模型；只含代理 scope token，不含上游密钥。实际费用依据 A2 账本，不依赖 Pi catalog 零价；关闭未声明的自动 catalog/资源下载与其他 provider 凭据。
- [ ] 实现 binary LF framing、持续读 stdout、stdin backpressure、先订阅后 prompt、agent_settled 与实际产物校验；handled prompt 单独处理。中止 clear_queue → abort → 有界退出，仍核对外部工具意图。新阶段使用短会话与证据摘要，恢复显式 session 文件；不启用模型驱动的自升级或任意项目扩展。
- [ ] 单测 PASS 后先对本地 Anthropic 替身验证 Pi 实际 RPC；再通过 `control trial preflight --state-dir PATH --policy PATH` 核对全部 A/B 回执、可信价格、额度和 E 盘路径后，进行最多 6 次真实兼容请求，计入实验阶段 30 次配额而非另加额度。覆盖文本、一次工具往返、thinking off、SSE 终止和完整 usage；压缩/重试边界先用替身，任何真实调用照常计账。关闭思考参数以现有 `providers/anthropic.py` 和服务实测为准，不仅看 Pi 文本设置。
- [ ] 运行 `python -m pytest ops/pi/tests/integration/test_pi_compatibility.py -q -m pi_live --pi-live --pi-lab`，记录预算前后、Pi/Node/服务身份与脱敏回执；402/空内容/unknown usage 不报通过。审查与授权保存点：`feat: run pinned Pi phases through budgeted RPC`。

## Task 15: C15 最少扩展、阶段 Skills 和受控开发工具

**Files:** Create `ops/pi/extensions/controlled-tools.ts`、`ops/pi/tools.py`、`ops/pi/prompts/analyze.md`、`ops/pi/prompts/plan.md`、`ops/pi/prompts/develop.md`、`ops/pi/prompts/diagnose.md`、`ops/pi/skills/myink-iteration/SKILL.md`、`ops/pi/tests/test_tools.py`、`ops/pi/tests/test_prompt_contracts.py`、`ops/pi/tests/integration/test_pi_tool_isolation.py`；Extend pi_config/executor/control。

**Interfaces:** `handle_tool(name: str, arguments: Record, capability: Record) -> Receipt`；仅提供 `observe_metrics`、`read_source`、`propose_plan`、`apply_patch`、`run_check`、`candidate_status`。Pi 提出动作，控制程序核对 plan_hash/candidate/base/capability 后执行。Git/发布/备份不暴露任意命令；`candidate_status` 返回回执，不允许 Pi 在文本中伪造已发布。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_patch_requires_approved_plan_hash / test_protected_policy_cannot_be_modified
assert patch_without_plan.status == "blocked"
assert protected_policy_patch.status == "blocked"
assert upstream_key_found_in_tool_response is False
```

- [ ] 写 `test_patch_requires_approved_plan_hash`、`test_protected_policy_cannot_be_modified`、`test_read_source_excludes_env_and_backup`、`test_prompt_injection_cannot_grant_capability`、`test_stale_generation_tool_denied`、`test_nested_model_call_is_metered_or_denied`。
- [ ] 运行 `python -m pytest ops/pi/tests/test_tools.py ops/pi/tests/test_prompt_contracts.py -q`，确认 FAIL。
- [ ] 只加载 pinned 自有 extension；显式 `--no-builtin-tools --no-mcp` 并允许列明的 extension 工具，不继承机器其他 MCP/Skill/项目 .pi 配置。需要 read/edit/check 能力时分别走类型化工具，候选 shell 仅在 B7 沙箱运行。extension 不持生产/Docker/GitHub/上游 key；信任側服务同样验证请求，而非信任工具名。
- [ ] 阶段提示与 Skill 写清输入证据、固定输出 schema、优化范围、基线/假设/指标、失败分类、额度/期限和跨日策略。计划先于开发，规则与独立审查回执绑定 plan_hash；审查调用也走代理并计入分析/开发预算。使用 superpowers:writing-skills 审阅新增 Skill；提示词验证不代替权限测试。
- [ ] 运行单测及 `python -m pytest ops/pi/tests/integration/test_pi_tool_isolation.py -q -m pi_lab --pi-lab`；真实 Pi 对替身模型执行恶意工具输入/直接 HTTP/读取凭据/自改额度，必须被机器边界拒绝。回执覆盖扩展尝试访问模型、模型切换、嵌套进程和异常重试，预算或拒绝均可核对；普通源码读取与允许补丁成功。
- [ ] 审查与授权保存点：`feat: expose controlled Myink iteration tools to Pi`。

## Task 16: C16 统一评测模型配置、公平配对和自动质量评审

**Files:** Create `src/myink/evaluation/platform_call.py`、`ops/pi/evaluate.py`、`ops/pi/tests/test_pairing.py`、`tests/test_evaluation_platform_call.py`、`evals/pi-local-trial/cases.json`；Modify `scripts/evaluate.py`、`scripts/evaluate-comparison.py`、`src/myink/evaluation/comparison.py`；保留 `runner.py` 的显式 legacy DeepSeek 入口以兼容已有使用者；Extend analysis-and-scoring 文档。

**Interfaces:** `platform_call(messages: list[dict], config: Record) -> Record` 返回现有 evaluation raw_output/model_id/tool_calls/token/cost_status 字段；`run_paired(baseline: Record, candidate: Record, cases: list[Record], plan: Plan, executor: Callable) -> Record`；`blind_review(bundle: Record, call: Callable, rubric: Record) -> Record`。调用路径显式选择 platform 或 legacy，不把 Anthropic key 填进 OpenAI DeepSeek 客户端。Pi 实验的 platform URL 指预算代理；网站既有配置与用户自备模型不改变。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_platform_anthropic_without_deepseek_key / test_partial_comparison_cannot_release
assert actual_protocol == "anthropic"
assert legacy_deepseek_transport_call_count == 0
assert partial_pairing["release_allowed"] is False
assert severe_error_candidate["release_allowed"] is False
```

- [ ] 写 `test_platform_anthropic_without_deepseek_key`、`test_no_implicit_official_price`、`test_protocol_tool_thinking_usage_preserved`、`test_baseline_candidate_same_input_and_unaffected_factors`、`test_prompt_candidate_actually_executed`、`test_severe_rule_error_cannot_average_away`、`test_partial_comparison_cannot_release`。
- [ ] 运行 `python -m pytest ops/pi/tests/test_pairing.py tests/test_evaluation_platform_call.py -q`，确认 FAIL；业务文件在独立服务环境运行。
- [ ] 复用当前 provider 协议与评测输出结构，入口使用 PLATFORM_MODEL_*，价格由可信实验配置供给；重试、评审、生成一律经代理计账，不重复把 P2 网站额度当 Pi 额外授权。现有 .env 已支持这四项，核对字段即可；不提交真实密钥，不重写主工作区 .env。
- [ ] 固定至少 5 组合成案例和至少一个不用于开发的保留案例，复用现有冲突/伤势/仪器约束素材，记录来源、期望严重规则和数据哈希；对计划声明的变化因素外保持模型/config/prompt一致。快照两个准确版本，实际执行两条路径，不仅重打分旧报告；失败、未知与超额中止都占计划输出槽。
- [ ] 盲评以稳定 seed 随机化版本顺序，固定独立 rubric，输出证据位置和理由，不能看 branch 名称；报告标记自动评审、同供应商偏差和样本限制。改善/退化阈值由冻结计划提供，严重规则为独立门槛。预估完整调用数不够时缩小合法任务或保存 partial，不为达到 5 组扩大额度。
- [ ] 运行新增测试与 `tests/test_evaluation.py tests/test_evaluation_comparison.py tests/test_evaluation_comparison_integration.py tests/test_custom_providers.py`，预期 PASS；真实配对在 C17 统一预算调度中执行，不在此额外跑一轮。审查与授权保存点：`feat: evaluate Pi candidates with platform-backed paired evidence`。

## Task 17: C17 完整日循环、次日归因和有界自主开发

**Files:** Create `ops/pi/iteration.py`、`ops/pi/tests/test_iteration.py`、`ops/pi/tests/integration/test_autonomous_trial.py`、`ops/pi/lab/scenarios.json`；Extend control/reporting。

**Interfaces:** `run_iteration(ledger: Ledger, experiment_id: str, now: datetime, services: Record) -> Receipt`、`continue_experiment(ledger: Ledger, experiment_id: str, observations: Record) -> Receipt`。CLI `trial run --state-dir PATH --policy PATH --scenario ID`、`trial resume --state-dir PATH --experiment ID`；默认 simulate，真实模型需显式 `--live` 且满足 preflight。operation_id 使用实验/run/slice/阶段/输入哈希，不以重启生成新身份绕过。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# test_no_improvement_generates_diagnosis / test_budget_stop_preserves_state_and_recovery
assert plan_event_id < first_patch_event_id
assert diagnosis["parent_experiment_id"] == experiment_id
assert diagnosis["reason"] == "not_improved"
assert recovery_receipt.status == "done"
```

- [ ] 写 `test_plan_before_any_patch`、`test_new_main_rebases_and_retests`、`test_no_improvement_generates_diagnosis`、`test_insufficient_evidence_extends_observation`、`test_manual_change_confounds_not_blames_pi`、`test_same_hypothesis_without_new_evidence_not_repeated`、`test_budget_stop_preserves_state_and_recovery`。
- [ ] 运行 `python -m pytest ops/pi/tests/test_iteration.py -q`，确认 FAIL。
- [ ] 按 A3 编排观察→基线→分析→计划/审查→开发→验证→本地分支/PR→构建→候选发布/PRE-POST→开放→次日比较→归因。副作用调用 A/B 原语，每步先核对现实身份和账本。阶段请求初值 15 分析/45 开发/30 实验/10 储备，总计 100；兼容探测和评审从这同一分配扣，不另加额度。
- [ ] 定义可重放场景：一个隔离评测/运营样例的可复现小缺陷（fixture 注入，不修改线上制造故障），具有现成失败断言和可计算目标；Pi 在候选副本形成小计划、修复、测试、本地提交/候选发布与 >=5 组配对报告。此为有界演练，不宣称提升整体写作质量，也不自动把注入问题提交到项目 main。
- [ ] 次日场景分别注入未改善、明显退化、样本不足、人为新版本和配置变化；Pi 自主生成关联诊断与修正/补证据计划，控制程序按旧版归属恢复。模拟跨日不重置首轮额度；真实模型不足时保存未完成槽和下一动作，剩余确定性演练继续。
- [ ] 运行单测及 `python -m pytest ops/pi/tests/integration/test_autonomous_trial.py -q -m pi_lab --pi-lab`，先使用替身跑完每个故障；安全和价格门禁满足后执行一轮 `trial run --live`，所有真实调用从 C14 之后累计。报告动作实际回执、资源峰值、调用数/已结算/未知预留，不以 Pi 自述替代证据。
- [ ] 审查与授权保存点：`feat: continue Pi experiments through measured diagnosis`。

## Task 18: C18 完整验证、故障矩阵和维护交付

**Files:** Create `ops/pi/tests/integration/test_fault_matrix.py`、`docs/pi/notifications.md`、`docs/pi/server-enablement.md`、`docs/evaluations/pi-local-trial/report.md`、`docs/evaluations/pi-local-trial/receipt-index.json`；Update docs/pi/README.md、总计划任务状态与设计审查记录。

**Interfaces:** report/index 标记每项 passed/failed/blocked/not_run/simulated，引用证据 hash 和私有路径；公共报告无正文、账号/模型秘密或 dump。服务器检查清单有 enabled=false、本机与服务器证据分栏；不在本机生成“服务器已验收”回执。

关键断言示例（除 A1 完整示例外，变量由上述接口和本任务案例设置产生；不是已实现的测试）：

```python
# 公开验收索引，模拟外部渠道不能冒充已接通
assert receipt_index["server_enabled"] is False
assert receipt_index["github"]["status"] == "simulated"
assert receipt_index["notifications"]["status"] == "simulated"
assert receipt_index["model_attempts"] <= 100
```

- [ ] 写 `test_pre_and_post_failures_recover`、`test_model_402_empty_unknown_usage_preserves_budget`、`test_crash_before_and_after_candidate_recovers_owner`、`test_queue_barrier_checkpoint_and_old_watchdog_matrix`、`test_0530_cutoff_0600_opening`；关联每条总体设计故障要求，使用虚拟时间、实际服务/进程和可检验 side effect。
- [ ] 在替身执行器中临时移除消费屏障/归属防护，运行 `python -m pytest ops/pi/tests/integration/test_fault_matrix.py -q -m pi_lab --pi-lab`，确认 FAIL 证明场景能捕获危险效果；恢复防护后运行真实独立服务矩阵，预期 PASS。未覆盖故障先补断言，不通过删案例达成验收。模型错误用替身，不额外请求真实服务。
- [ ] 运行离线 ops 全量及业务 CI 等价验证（Python 全量、案例校验、契约 diff、前端 lint/test/build、两镜像）。使用已校准实验 daemon/资源和唯一项目名，不能直接同时启动固定 `myink-test`。按源码变动选择附加检查，无必要不反复重跑已通过重任务。
- [ ] 独立审查整分支的消息可靠性、事务、费用、越权、恢复和人工优先；修正发现后做针对验证。确认主工作区状态、真实远端 ref 和只读生产身份未被本轮改变，私有安装与凭据不在 git diff/build context。
- [ ] 生成报告：每阶段目标/产物、版本、命令和结果、所有故障、冷/热峰值、调用/费用与未知预留、样本与效果、SKIP/blocked、剩余事项；标明注入实验及模拟 GitHub/邮件/云通知。预算耗尽或设施不满足仍给可维护 partial 报告，不冒充完整验收。
- [ ] 文档写明用户手动部署/交接、Pi 版本升级、政策配置、备份/恢复演练、失联排查、报告字段与收件人配置。未来服务器 checklist 包含稳定协议 bootstrap、真实容量/冷缓存/恢复耗时、离机确认、旧 cron 单一执行者交接、GitHub App 权限与 CI、真实邮件和外部云告警（含 PG down、备份失败、心跳缺失），全部留作后续启用计划。
- [ ] 本机验收达到时提出服务器启用计划输入和真实配置缺口；本轮不安装服务器、不改 cron、不发邮件/短信、不自动推初始化成果。审查与授权保存点：`docs: deliver Pi local trial evidence and operations guide`。

## 版本接口依据

- [Pi v1.1.0 安装与 Node 要求](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/README.md)
- [RPC 完成语义与 framing](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/docs/rpc.md)
- [命令、会话与工具开关](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/docs/cli.md)
- [配置目录](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/docs/configuration.md)
- [模型与扩展](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/docs/models.md)

实施安装时再核验实际 --help/包完整性与接口；上述固定版本文档不替代服务兼容和隔离实测。
