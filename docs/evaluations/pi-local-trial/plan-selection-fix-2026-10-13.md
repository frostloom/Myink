# Pi 当前会话计划交接修复（2026-10-13）

本轮完成 **008 跨轮次计划选择缺陷的离线修复与回归**。源码提交 `baee005571edd8ad52955ac461ca9141de142b04`，位于 `codex/pi-autonomy-design`。最终离线 ops 套件 **998 passed、2 skipped、19 deselected，275.73 秒，退出码 0**。没有新增模型请求，没有启动 009，也没有部署或启用服务器 Pi。真实模型下的完整开发、质量对照与发布闭环仍未验收。

## 问题与修复

[008 实测](runtime008-2026-10-13.md)中，当前会话已经产生有效且通过 reconciliation 的计划；宿主却查询全账本的 `tool:paid-plan:` 前缀，把保留的 007 计划一起选入，导致“恰好一条”检查失败。历史计划本应保留，不能靠删除历史、换标签或绕过审批解决。

`ops/pi/trial_runtime.py` 的 `verify_stopped_phase(...)` 先沿用既有 `broker.lookup` 认证当前 stopped session 的所有 toolCall/toolResult，再要求当前恰好一个 `propose_plan`。从认证后的参数重建真实 `Plan`，验证工具与规则回执均成功、规则 verified 为 true、计算哈希与回执哈希相符、实际计划内容一致，才返回：

```python
result['proposed_plan'] == {
    'operation_id': current_operation_id,
    'plan': authenticated_plan,
    'plan_hash': computed_plan_hash,
}
```

该字段只交接计划，不授予独立审批、开发或发布权限。两个当前提案、无当前提案、规则阻断、外来绑定、调用 ID 或回执/内容/哈希篡改继续拒绝。已有开发阶段“最后一次补丁之后必须执行候选检查”的规则不变。

私有宿主的实际消费段在新的离线副本中改为读取这个字段，不再查询全账本。见 [consumer 差异](plan-selection-consumer.patch)：仅用于从冻结 008 宿主制作新的副本，不能覆盖旧证据。宿主先要求 reconciliation verified，再检查该字段的三个精确键，写入当前 proposed-plan 证明。补丁上下文中的 ACTUAL 字样是既有宿主代码；本轮验证使用明确的合成 stopped-session 元数据，**不能据此认定本轮进行了真实 native 或模型执行**。

## 验证记录

证据目录：`E:/tools/myink-pi/evidence/c19/plan-selection-fix/`。各子目录保留 execution.json、stdout、stderr；RED、失败的首次整套回归及后续 GREEN 均保留。以下测试集有重叠，不相加。

| 记录 | 实际结果 | 验证范围 |
|---|---|---|
| red-001 | 1 failed，预期 RED | 真实 ControlledTools/SQLite 保留历史计划；旧实现没有 proposed_plan |
| green-001 | 138 passed，16.42s | runtime/tools/plans/budget；14 个新增边界案例 |
| host-selector-red-001 | 1 failed，预期 RED | AST 提取旧宿主实际消费段，同标签历史与当前提案导致拒绝 |
| host-selector-green-001 | 1 passed，0.66s | 新宿主实际消费段只选择当前提案，历史操作与事件不变 |
| full-offline-001 | **2 failed、994 passed、2 skipped、19 deselected**，321.64s | 失败记录保留，不作为验收通过 |
| fixture-isolation-red-001 | 1 failed，预期 RED | 已加载的真实 Settings 与新夹具环境不一致 |
| fixture-isolation-green-001 | 15 passed，0.39s | 夹具刷新已加载 Settings；刷新后人为漂移仍被生产校验拒绝 |
| spawn-runner-green-001 | 1 passed，1.13s | Windows multiprocessing 验证入口增加 main guard，生产账本与其测试不改 |
| full-offline-002 | **998 passed、2 skipped、19 deselected**，275.73s | 干净 a79bf12 源码归档 + 仅三个已审查覆盖文件，最终离线验收 |

首次整套回归的两项失败分别是：`test_owned_active_operation_accepts_only_exact_fixture_urls` 的夹具缓存 Settings 漂移，以及 `test_two_processes_share_one_identity` 的 Windows spawn 重入 ROOT 临时 pytest 入口。前者仅修改 `test_lab_gates.py`，用 monkeypatch 刷新已加载的真实 Settings，测试后恢复；不主动导入未加载模块，不放宽生产校验。后者修复私有验证入口的 `if __name__ == '__main__'`，不修改生产账本或账本测试。

最终回归的两项 SKIP：

- `test_writing_analysis.py::test_symlink_intake_is_denied`：host cannot create symlink。
- `test_writing_evidence.py::test_load_rejects_symlink_even_when_target_is_inside_root`：host cannot create symlink without OS privilege。

19 项由 `not pi_lab and not pi_live` 排除，未运行真实 lab/live 检查。最初的 138 项与两个宿主选择段 RED/GREEN 各有一个 asyncio_mode 配置警告：隔离入口禁用自动插件加载且未显式加载异步插件。后续夹具、spawn 与最终整套入口显式加载 pytest_asyncio，没有该警告。

最终入口使用 Python 3.12.4、`-I -B`，禁用 dotenv 和自动插件加载，固定源码路径，显式加载 pytest_asyncio，E 盘独立临时目录；pytest 参数为：

```text
ops/pi/tests -q -m "not pi_lab and not pi_live"
-p pytest_asyncio.plugin -p no:cacheprovider
--basetemp <独立临时目录> --junitxml <结果文件>
```

这是 ops 离线套件，不是根目录业务 Python、Go、前端、Docker 或完整 PostgreSQL/Redis/RabbitMQ 验收。全套从 a79bf12 的干净 Git 归档运行，避免把工作区既有 B12 修改当成已验证源码。聚焦夹具 15 项使用当时工作区 verify.py，因此它也不构成 B12 验收；最终回归另在干净基线上验证。

## 源码和证据身份

以下 SHA-256 均经文件读取核对；原始日志与独立审查保留在本机私有证据目录，不提交凭据、账本原始行或用户正文。

| 文件或回执 | SHA-256 |
|---|---|
| ops/pi/trial_runtime.py | 3bc30e4d7b47e6959f76ff0b4130d13a1ebe8f403b327794328d435faf3a20a1 |
| ops/pi/tests/test_trial_runtime.py | a343fe25476fb2420768cd577211c65bcc439fc1eff6af9831ff4037a5597499 |
| ops/pi/tests/test_lab_gates.py | cf1719bddfba9d404f21726a121cb7149a9e37b12c71b9151e493f184a7fe52e |
| full-offline-002/execution.json | e5963d6415f5887dda41d34cf1a53bfe57183df62ea69f95b9de5acf0b573b51 |
| full-offline-002/stdout.txt | ce531e1d5cde2ee3ae9f02c00a6f345d1eae7808dbc345442ee79f7c940fdaaf |
| full-offline-002/stderr.txt（空） | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| clean-a79bf12.tar | 3216b80e2b93e2d9874ae56b0735a897a96f20ff9769696049076f4c24958a25 |
| c19-plan-selection-fix-review.md | 11e78a51d7a3e87d1554fd9a0a07bd8292b8da0317b5ee2fa9b4c7adfa571cb1 |
| c19-plan-selection-fixture-review.md | f522857ba5eb9a48f9c42f4c7f036eadd5b1db25e7be4535056cff9cfe5a2d41 |

两份独立源码审查均 Approved，无 Critical/Important；审查冻结时最终整套尚在运行，所以最终 GREEN 是 ROOT 随后核验的结果，不写成审查者已经看过整套 GREEN。审查文件位于隔离工作区 `.superpowers/sdd/2026-10-11-pi-local-trial/`。

## 预算、隔离与后续边界

本轮新增模型请求 **0**。canonical 完整 operations/events 的只读快照哈希仍为 `010c773c6f292b21c865cea319c1204517732ae39f99693aede8edeeb181d32c`（各行序列化为 list，按 operation_id/id 排序，JSON sort_keys/indent=2，尾部换行）。累计仍为 32 次尝试 / 10254974 microyuan，含已知估算 189182 和历史未知保守预留 10065792；尝试数不等于 HTTP 数，预留不等于实际账单。100 次 / 20 元本机累计上限、阶段配额和未来服务器每日 10 元默认值保持。

主工作区与 18 个既有 B12 文件保持；旧 008 冻结源码、进程停止证明、失败记录保持。GitHub 交付仅在功能分支，不合并 main，不部署服务器。写作语义质量仍 unknown / 未验收，合成案例不能作为 gold 质量验收，完整服务与自动发布仍 NOT_RUN。本轮修复不追认 008 成功，也不自动启动下一轮付费实验。

维护时应沿用当前会话认证返回值；若 reconciliation、唯一提案、规则或哈希检查失败，应保存失败证据并终止该阶段，不能从旧账本挑选“可用”计划。新的真实实测需要新的隔离身份和证据；恢复时继续累计既有预算与历史记录。
