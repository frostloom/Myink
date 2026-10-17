# Pi 写作分析稳定性与对照准备实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for preserved inline execution. Steps use checkbox syntax for tracking.

**Goal:** 验证当前写作分析提示与严格合同的一致性，准备可审查的新实验预注册；本计划不执行付费请求。

**Architecture:** 复用 `writing_analysis.py` 的提示、严格校验及 `analysis_trial.py` 的目标域评分与冻结机制。先补实际覆盖缺口，再冻结共同输入和实验条件，不修补模型输出、不改写历史失败。

**Tech Stack:** Python 3.12、pytest、合成 JSON 证据；离线阶段不需要数据库、模型或私有正文。

**Spec:** `docs/evaluations/pi-local-trial/quality-runtime025-2026-10-15.md` 的后续方向；`docs/evaluations/pi-regression-baseline-2026-10-17.md` 的已修复回归基线。

## Global Constraints

- 当前 `build_writing_prompt` 已有目标域唯一约束、字面引用说明、rollback 字符串示例及显式索引，不重复实现这些修正。
- 保留 `validate_writing_analysis` 严格合同及 `score_contract_output` 的非目标域 unknown 限制；合同有效不代表语义正确。
- 45 项语义质量值保持 unknown/null；不把缺失、截断、失败或未运行的数据计零或计通过。
- 合成数据不得冒充历史原始响应。025 的 1/10、原始失败及费用口径不改写，不用新实验覆盖。
- 不合并 main、部署、开启每日自治或调用付费模型。每个已完成小目标验证、独立审查后单独提交推送。
- 本文是后续计划，尚未执行；沿用当前 inline 开发方式，具体新实验模型和费用仍须形成可审查方案后确认。

## Review Focus

1. 非目标 operations 获得 trace_observation 或 refs：必须被目标域评分拒绝；operations 目标的例外不能泄漏到其他域。
2. 字面反斜线、换行、中文及头尾分段：引用必须落在单个保留 excerpt 内，不拼接、不反转义或改写正文。
3. schema 类型错误、数组 rollback、空 observation、重复 JSON key：继续拒绝，原始证据不被“修好”。
4. 两臂输入或模型配置漂移、重复择优：预注册绑定同一输入/版本与完整分母，失败也保留。
5. 格式有效率与语义质量混用：主要指标只评价合同，采纳/发布与独立语义审查分开。

### Task 1: 离线合同覆盖核查与补缺

**Files:** `ops/pi/tests/test_writing_analysis.py`、`ops/pi/tests/test_analysis_trial.py`；仅证明实现缺陷后修改 `ops/pi/writing_analysis.py` 或 `ops/pi/analysis_trial.py`。不读取私有正文。

**Interfaces:** 使用现有 `fixture()`、`plan()` 合成输入、`build_writing_prompt(view, report, target_domain=...)`、`parse_writing_analysis(text, view)` 和 `score_contract_output(result, view, target_domain)`；输出全部 11 域的正反合同覆盖表。

- [x] 对照已有测试建立覆盖表，已有覆盖不重复添加；记录未覆盖的具体输入与预期。
- [x] 缺口优先用参数化 `test_target_scope_accepts_only_selected_domain` 覆盖 11 个目标：目标合法引用可接受；每个非目标变为 trace_observation（携带有效引用，确保到达目标域 scorer）或 unknown 但持有 refs 都必须拒绝；operations 的空 refs 例外仅在其自身目标可接受。
- [x] 用 `test_literal_excerpt_roundtrip_preserves_escaping` 覆盖字面 `\\n`、真实换行、引号及中文的 JSON 编解码，真实单段 quote 接受，解转义或跨 excerpt 拼接拒绝，原 view 不变。结合现有数组 rollback、空 observation、重复 key 用例记录结果。
- [x] 对当前已满足的行为如实记录为契约补测，不伪造 RED；若发现真实缺陷，先保存失败，再最小修复，禁止放宽校验器。
- [x] 运行 `python -m pytest ops/pi/tests/test_writing_analysis.py ops/pi/tests/test_analysis_trial.py ops/pi/tests/test_prompt_contracts.py -q -ra`，独立审查并提交推送此目标。

### Task 2: 新实验预注册与执行边界

**Files:** 新建 `docs/evaluations/pi-analysis-contract-preregistration-2026-10-18.md`；复用 `ops/pi/analysis_trial.py::freeze_contract_trial(view, report)`，不改历史报告或账本。

**Interfaces:** 输入 Task 1 的覆盖表与当前冻结函数输出；输出人工可审查的预注册，真实输入仍存私有目录，公开文档仅列哈希与口径。冻结函数不能执行模型请求。

- [ ] 固定五组 `recall.events/recall.plot/recall.characters/extract/operations`、baseline/candidate 两臂、输入和提示哈希、源码版本、共同严格 validator 与目标域 scorer；明确当前函数的模型字段是历史固定值，不能当作新实验已确认配置。
- [ ] 明确新模型的精确标识、共同参数、每格重复次数及运行顺序、每次/累计请求和费用上限、价格依据、超时/重试、停止及所属进程清理规则。未确认值必须标待定，不发起请求，不复用旧轮额度作为新授权。
- [ ] 主指标为合同有效数/全部预注册输出；按组列失败、未运行及首错分类，同时保留一条输出多重违反的可能性。保留固定采纳规则 `candidate_valid_count > baseline_valid_count` 的有限用途，不将其解释为质量提升或发布许可。
- [ ] 预先规定语义主张的独立盲审、可比配对和未知项；固定数据不足时仅能得出合同结论。不得因结果差而换题、删失败或自动修复后计原始成功。
- [ ] 自查冻结可重复、改输入会改变摘要、`automatic_execution=false`、`release_allowed=false`；独立审查，提交推送文档，交用户审阅新实验模型和费用范围。

## 当前状态

2026-10-18：用户已确认执行。Task 1 完成：新增 255 个合同案例，相关三文件 304 passed/1 skipped，干净归档离线全量 1677 passed/2 skipped/19 deselected；独立审查通过，无生产代码改动。Task 2 正准备预注册草案，真实输入、模型价格和执行门禁待核验，不发起付费请求。
