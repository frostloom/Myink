# Pi 基线修复与数据分析继续计划

> 使用 superpowers:executing-plans 当前会话执行；每个小目标验证后单独提交并推送。复用已有 Pi worktree，不合并 main，不部署。

**Goal:** 清理可复现的测试阻碍，重新建立当前分支的离线基线，并基于保留证据推进数据分析闭环。
**Architecture:** 复用现有 backup / writing_evidence / writing_analysis / analysis_trial 接口，不放宽发布门槛或严格校验器。冻结快照运行，保留失败、跳过和未知指标。
**Tech Stack:** Python、pytest、SQLite、Git、已有 E 盘私有实验材料。
**Spec:** docs/superpowers/specs/2026-10-10-pi-autonomy-design.md；docs/superpowers/plans/2026-10-18-pi-analysis-stability.md；用户本轮要求先定位失败再分析数据、小范围修复与前后对照。

## Global Constraints

- 保护四个原有未提交 ops/pi 文件和主工作区修改，不把它们带入提交或冻结源码。
- 新旧所有调用和未知预留共用原累计20元上限；离线工作不调用模型。付费执行必须核对可信策略、身份、输入范围、实际运行时及当前累计费用，不直接重放040。
- 不合并 main、不部署、不启用每日自治。每个小目标分别提交推送。
- 保留45项语义指标unknown，格式、协议或合成案例通过不代表真实质量提升。

## Review Focus

1. 固定夹具与现实时间混用；发布演练7天过期规则必须保留。
2. 文件链接/Bash沙箱失败不能冒充生产缺陷，也不能计为通过。
3. 冻结归档必须排除四项旧修改，测试路径指向该归档src。
4. 跨部署/模型/样本不可比的指标不得作前后收益比较。
5. 实测输出必须包含失败和未运行分母；数据不足时不能自动采纳或发布。

### Task 1: 修复备份测试的时钟漂移

**Files:** ops/pi/tests/test_backup_lab.py；docs/evaluations/pi-baseline-resume-2026-10-20.md。
**Interfaces:** 使用 test_backup.NOW 与 release_allowed/mark_released 的现有 now 参数。

- [x] 保留四个失败的精确nodeid；同一冻结快照排除沙箱后复现。Expected: 1 failed/3 passed。
- [x] 根因核对：qualified_restore写入2026-10-11，而未注入时钟的资格查询使用现实时间，7天后失效；生产过期逻辑不变。
- [x] 仅在该生命周期测试显式传入固定NOW，保留准备失败撤销资格、禁止发布及恢复可用断言。Expected: 原失败变通过。
- [x] 运行 test_backup.py、test_backup_lab.py 和其余三个失败用例，记录通过/跳过/环境限制，审查后单独提交推送。

### Task 2: 当前源码基线与保留数据分析

**Files:** docs/evaluations/pi-baseline-resume-2026-10-20.md；必要时仅按复现证据修改相关测试或分析实现。
**Interfaces:** Task1提交的干净git archive、writing_evidence.analyze_writing_bundle、make_analysis_view、analysis_trial.freeze_contract_trial；不导入未经认证的候选代码。

- [x] 从提交归档运行完整 offline ops 测试，排除pi_lab/pi_live，保留JUnit和失败详情。Expected: 全部已选用例无失败；skip/deselected单列，环境失败先诊断。
- [x] 核对历史025冻结输入/报告哈希与当前累计账本，只读分析可用域、指标和缺失项。Expected: 不修改历史、不输出正文或凭据。
- [x] 对照现有预注册确认下一次真实分析所需的运行门禁和可执行性；若发现真实合同缺陷，先RED后最小修复，不放宽校验。
- 交付门槛：当前目标完成后记录证据、审查、单独提交推送；推送结果须以远程SHA核对，不由本计划复选框替代。缺少可比语义标签或合法运行门禁则明确剩余项，不以格式通过代替质量闭环。
