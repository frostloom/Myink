# Myink 评测体系设计与维护约定

日期：2026-10-08。状态：**固定文本审核主路径已实现，15 例首轮基线已运行；正式语义指标待人类复核**。

可用命令、实际文件布局和维护方式以 [evals/README.md](../evals/README.md) 为准；结果见 [P1 验收记录](evaluations/p1-verification.md)。下文保留原设计蓝图，标为“拟议”的扩展模式不代表已经实现。

本文面向实现和维护评测的开发者。目标是复用现有案例，建立可重复运行、可追溯、能解释失败的评测体系。审核 validate/plan/run/score/report 与既有恢复证据的 check-recovery 已实现；生成对照和恢复重新执行的统一适配仍是后续阶段。不改变生产工作流，也不要求先实现新的冲突机制。CI 新增的是不调用模型的数据校验。

## 1. 先读这几条

1. 程序机制测试、真实模型判断、完整工作流结果分别报告，不能合并成一个“系统准确率”。
2. 一条冲突必须识别到目标问题并提供有效证据；仅返回 `rewrite` 不算正确发现。
3. 正常对照必须经过适用的检测入口；入口没有实现或根本没运行，不算“正确放行”。
4. 保存失败、超时和预算中止。禁止只保留成功结果，禁止用重试后的成功覆盖第一次失败。
5. 先整理现有资产和离线判分，再做小批量真实模型评测，最后才依据失败改进系统。

阅读顺序：现有资产 → 数据格式 → 判分 → 运行与报告 → 维护与实施。新增案例通常只需要修改案例文件和清单；新增评测模式才需要修改运行器。

## 2. 现有资产及证据边界

| 资产 | 当前入口 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| 40 个冲突/正常案例 | [spec/conflict-samples.md](../spec/conflict-samples.md) | 场景定义、前提、目标问题和误报边界 | 文本描述本身不代表实现或运行通过 |
| 40 例机制套件 | [tests/test_conflict_sample_suite.py](../tests/test_conflict_sample_suite.py) | 实际检测/守卫处理逻辑；模型判定用替身，embedding 用确定性替身 | 真实模型检出率、真实向量召回效果 |
| 10 个逻辑正反例 | [scripts/eval-logic.py](../scripts/eval-logic.py)、[历史结果](evaluations/logic-smoke.json) | 5 组配对场景的真实审核模型历史输出 | 当前版本稳定性、全工作流效果；现有匹配主要检查 verdict |
| 5 个接续案例 | [scripts/eval-continuity.py](../scripts/eval-continuity.py)、[历史结果](evaluations/continuity-smoke.json) | 真实审核及一次生成/可能修订的历史记录 | 大样本长篇质量改善 |
| 人工拒绝后的恢复案例 | [scripts/eval-workflow-recovery.py](../scripts/eval-workflow-recovery.py)、[本轮完整结果](evaluations/workflow-recovery-2026-10-08-live.json) | 合成故事的真实生成、注入错误、人工拒绝、修订、保存 | 自然错误发生率、跨章长期一致性；该次 embedding 关闭 |
| 展示与导出 | [scripts/render-live-demo.py](../scripts/render-live-demo.py)、[案例说明](interview/README.md) | 已留存产物的可视化、正文与落库核对 | 展示页面本身不产生新评测证据 |

### 已知需要纠正的口径

- 40 例套件定义 26 个阳性、14 个阴性。文档中的 21/26 与 0/14 是机制套件历史口径，不是新的真实模型实验结果。
- 样例 5/6/7/8/9 当前标记 `xfail(strict=False)`；机制缺口与模型是否能够语义判断是两件事。例如逻辑 smoke 使用审核模型判断了这类问题，不等于 L1 机制已经补齐。
- 样例 28/29/30 的测试明确标注“真空通过”。新报告应列为对应入口的覆盖缺口，不纳入有效正常放行统计。
- 样例 4 的机制检出类型与规范期望有差异，应报告“发现相关问题”和“类型正确”两个结果。
- `test_sample_38_style_drift` 实际注入的是卷规划偏移判断，并断言 `conflict_type=volume`；不能据函数名称宣称已经测到文风漂移。样例清单应标注该错配，后续分别修正测试语义与文风评测。
- 套件末尾的常量断言仅检查固定基线数字没有变，不是动态统计。新指标须从每条实际结果计算。
- 本节来自代码检查；本次设计没有重跑上述测试，也没有新增真实模型评测。

## 3. 范围与第一批案例

保留 40 例规范和 pytest 测试，建立稳定编号的覆盖清单。第一批真实模型数据复用现有 10 个逻辑案例、5 个接续案例，共 15 个；另保留 1 个恢复工作流场景。这里是 **15 个固定文本审核任务 + 1 个恢复场景**，不是 40 个已经可以端到端运行的任务。

逻辑案例属于规范的现实题材改编，必须标注 `adapted_from`，不能声称与原玄幻样例逐字一致。接续案例有自己的编号。恢复场景包含脚本注入和人工反馈，必须与自然生成失败分开。

| 测试层 | 输入与目的 | 第一阶段执行方式 |
|---|---|---|
| mechanism | 已有数据库前提、候选、正文；验证确定性逻辑和模型结果守卫 | 保留 pytest；导出测试状态和覆盖说明 |
| audit | 固定历史上下文、固定正文、计划和约束；验证审核判断 | 真实模型或已保存响应的离线判分 |
| recovery | 固定合成任务 + 明确故障注入 + 作者反馈；验证修订与保存 | 隔离数据库的完整工作流 |
| generation_compare | 相同任务，比较直接生成与完整工作流最终正文 | 后续阶段；独立盲评，不复用系统自己的 pass 当真值 |

后续只补已经发现的覆盖缺口：别名指向同一人物、无关历史干扰、合法治疗/结盟、失效记忆、跨章必要事实遗漏。每项需要正反对照与明确前提，不以扩大条目数为目标。

数据划分建议按配对组/故事族拆为 development 和 holdout，防止同一正反对照分别进入两边。15 个案例样本量很小，holdout 仍是本地可见的回归保留集，不宣称独立外部基准。新变体先指定分组，再调整提示词；查看保留集失败后若据此优化，该批改为 development，并另建保留组。

## 4. 文件布局与职责（拟议）

```text
evals/
  README.md                     操作入口、环境与维护约定
  cases/audit/*.json            每个文件一个固定文本案例
  cases/recovery/*.json         恢复案例，含独立的故障注入/反馈
  catalog.json                  40 例规范与各层入口的映射，不存指标
  configs/*.json                非密钥模型参数、模式、限制
scripts/evaluate.py             薄 CLI，参数校验和调度
src/myink/evaluation/
  cases.py                     版本化格式、加载、校验
  adapters.py                  调用既有审核/工作流入口
  scoring.py                   证据、目标问题和状态判分；不调用模型
  reporting.py                 从逐条结果计算汇总和 HTML
tests/test_evaluation_*.py      格式、判分和报告的离线回归
.local/evaluation-runs/<id>/    默认完整运行结果，忽略目录
docs/evaluations/<id>/          人工选定的合成运行快照
```

不引入独立评测服务、数据库模型、插件框架或多 Agent 调度。现有 prompts/schema/graph 是被测代码，适配器复用它们，不复制一套生产逻辑。先实现 audit，再根据恢复模式的真实需要拆文件，不创建空模块占位。

历史 JSON 保留原格式和原文件。需要重评分时写新 run，标注来源文件及其哈希；没有记录的历史配置填 `unknown`，不能反推为当时实际配置。对合成产物进行检查后再复制到公开文档目录，密钥、用户作品、账号环境不得进入产物。

## 5. 案例格式 v1（拟议）

使用 UTF-8 JSON，每个文件一个案例，便于 review 和单独运行。Python 验证层使用现有 Pydantic 依赖；拒绝未知字段、重复编号、找不到的来源定位和不合法期望。以下示例可作为第一次迁移的形状，但不是已落地 API。

```json
{
  "schema_version": 1,
  "id": "logic.destroyed_item",
  "group_id": "logic.item_replacement",
  "split": "development",
  "mode": "audit",
  "category": "item_state",
  "polarity": "positive",
  "source": {
    "path": "scripts/eval-logic.py",
    "case_name": "destroyed_item",
    "adapted_from": ["conflict-samples:06"]
  },
  "input": {
    "chapter_seq": 2,
    "context": {
      "short_context": [{
        "kind": "prev_chapter_tail",
        "chapter": 1,
        "tail": "林川唯一的万用表已烧成无法修复的残骸，他尚未获取替代品。"
      }],
      "long_term_facts": []
    },
    "plan": {},
    "draft": "林川拿起那只完好无损的旧万用表，接上探针，顺利测出了电压。"
  },
  "expected": {
    "allowed_verdicts": ["rewrite"],
    "required_issues": [{
      "id": "destroyed_item_reappears",
      "description": "已毁且无替代的旧万用表被直接作为完好仪器使用",
      "allowed_conflict_types": ["item_rule"],
      "allowed_severities": ["major", "critical"],
      "evidence_sources": [
        {"chapter": 1, "pointer": "/input/context/short_context/0/tail"},
        {"chapter": 2, "pointer": "/input/draft"}
      ]
    }],
    "forbidden_issues": []
  },
  "label": {
    "status": "proposed",
    "review_note": "由既有案例迁移，执行正式指标前需要复核标签"
  }
}
```

- `id` 永久稳定；改写文字不换 id，语义目标改变则建新 id。运行 manifest 保存文件哈希。
- `group_id` 把错误与合法变化绑定；迁移脚本检查分组不能跨 split。
- `polarity` 是是否存在目标冲突，不是“文字好不好”。阴性案例 `required_issues=[]`，用 `forbidden_issues` 描述不得误报的合法变化。
- 标签 `proposed/reviewed/disputed`：只有 reviewed 进入正式质量汇总；其他仍可运行，但单列结果。不虚构复核人或复核时间。
- 证据源指针使用 JSON Pointer；必须定位到实际文本，章号与源相符。审核输出的 `conflict_key` 可变，不能把固定模型措辞当匹配标准。
- category 是评测业务分类，和生产 `conflict_type` 分开。合法的类型别名需按案例审查并显式登记，不能运行时临时放宽来提高分数。
- recovery 使用单独格式：`setup` 为合成初始数据，`instruction` 为任务，`fault_injection` 为注入操作，`feedback` 为拒绝理由，`expected` 包含正文、审核状态、版本/候选/记忆有效期的可验证断言。不把自然生成错误与注入错误混淆。

## 6. 判分：目标问题、证据、决策分开

判分函数接收案例与真实输出，不调用模型、不修改输出。每条结果分别保存以下字段：

| 字段 | 规则 |
|---|---|
| output_valid | AuditVerdict 解析和结构校验是否通过；非法 JSON 算模型输出失败，不隐藏 |
| evidence_valid | 引用逐字存在于声明的案例文本中，章号正确；仅规范 CRLF/LF，不删除标点或模糊匹配 |
| issue_match | 是否对应标注的目标问题；类型正确不等于语义正确 |
| verdict_match | 是否符合 allowed_verdicts；不能替代 issue_match |
| severity_match | 在案例允许的严重度中；与问题检出分开报告 |
| case_pass | 输出有效、所有必需问题已确认匹配且证据合格、没有确认误报、决策符合期望 |

自动检查先给出候选匹配：类型、严重度、证据来源合格后，才能进入匹配候选。评测人员复核具体语义并标记 `confirmed/rejected/disputed`。第一次 15 例规模小，全部复核；后续至少复核新增、失败、异常和抽样成功记录。待复核记录只能报告暂定自动结果，不能写成正式 precision/recall。

同一 finding 最多匹配一个目标问题，一个问题重复报警只算一次 TP；按 case_id + issue_id 去重，重复次数单列。额外 findings 必须核实：真实但未标注的问题进入标签复核，确认不存在的问题算 FP，争议项保留 disputed。不得默认所有额外 findings 都是误报，也不得忽略它们。

正常案例要求适用入口确实执行、输出有效、无确认误报且决策符合预期。文风提示等非目标问题也要单列，避免把模型因“篇幅短”要求重写算成冲突检出。

### recovery 的判分

最低条件：反馈应用、指定错误移除、关键现实约束保留、修订经过抽取/检查/审核、最终状态符合期望、落库正文与最终状态一致、旧版本留存、旧记忆/候选按既有规则失效或替代。

“错误句不再出现”仅是字面断言，不能证明换一种说法的超自然设定也消失；语义约束由人工复核。数据库行数不等于有效记忆数；逐项核对失效和确认状态。案例若没有触发某类记忆失效，记为 not_exercised，不宣称该分支已验证。

## 7. 运行状态和指标分母

覆盖状态与运行状态是两个轴：

- `coverage=implemented/gap/not_applicable`：对应入口是否适用且存在。现有 xfail 和真空阴性必须明确列 gap，不根据 pytest 颜色自动升级。
- `execution=completed/provider_error/environment_error/timeout/budget_stopped/not_run`：是否获得本次判分需要的输出。非法模型 JSON 仍是 completed，`output_valid=false`，计模型输出失败。provider 失败要保存错误，不伪装成未覆盖。
- `review=provisional/confirmed/disputed`：人工复核状态；模型自评 confidence 不等于标签可靠度。

每份报告先列总案例数、planned/attempted/completed、各失败状态、覆盖缺口和复核状态，再列质量指标。缺失数据不填 0；分母为 0 时显示 N/A。

| 指标 | 计算与限定 |
|---|---|
| 机制覆盖率 | 已实现且适用的案例 / 全部适用案例；不跨层合并 |
| 条件检出率 | completed 且已复核阳性中，检出必需问题的案例数 / 该组阳性总数 |
| 端到端成功比例 | 已确认达到完整成功条件的案例 / planned 中已实现且适用案例；未跑和运行失败留在分母 |
| 阴性误报率 | completed 且已复核正常案例中，至少有一条确认 FP 的案例 / 该组正常案例数 |
| 问题级 precision / recall | TP/(TP+FP)、TP/(TP+FN)，仅对已完成完整复核的问题集合；结构/输出失败产生的未检出需计 FN |
| 有效证据比例 | 完成输出中的合法证据引用数 / 所有输出引用数；同时报告无引用 finding 数 |
| 决策/严重度一致率 | 各自独立统计，不用决策一致率冒充冲突检出率 |
| 修订成功比例 | 满足全部恢复断言并复核的运行 / planned 恢复运行；失败、中止单列 |

重复运行按 `case_id × variant × repetition` 保存，不当作新增独立样本；报告每个案例成功 k/n，再给类别分布和最差案例。小样本用“5/5”而非泛称“准确率 100%”。机制历史基线另列，不能与真实模型结果求平均。

报告 usage、API 耗时、总墙钟时间、重试/降级与工具次数。成本字段包含 `estimated/unknown` 和单价来源；价格不明或应用返回 0 不等于免费。与供应商账单明确区分。预算中止不保证已经在途的请求无费用。

## 8. 配置、产物和可追溯性

每次生成新 run_id，目录不覆盖。建议 `<北京时间日期时间>-<随机短串>`。manifest 时间使用带时区 ISO 8601，展示可转北京时间。

```text
manifest.json             schema、源提交、工作区差异哈希、案例/配置/prompt 哈希
results.jsonl             每个 case × variant × repetition 一行状态和指标
artifacts/<case>/<rep>/   请求、实际响应、阶段状态、正文、数据库导出
review.jsonl              人工复核，独立保存，引用结果哈希
summary.json              动态聚合结果；可从 results/review 重建
report.html               可读报告，包含失败、缺口及完整产物入口
```

manifest 必须记录：模型请求名称/实际响应名称、协议、温度、token 上限、thinking 设置、重试设置、embedding 开关和模型、评测模式、选定案例、重复次数、预算、开始结束时间、源提交、工作区是否 dirty、源文件内容哈希、渲染后 prompt 哈希与依赖版本。服务可能更新模型，固定名称不保证完全复现；随机种子只有 provider 支持且确实传入才记录为生效。

密钥仅从现有配置/账号连接获取，禁止写入 CLI、manifest、响应日志和公开快照。不导出整份 `users.environment`。合成案例关键正文完整保存，遥测截断不影响专门的评测产物；若实际响应或输入未完整取得，显式标缺失，不编造内容。

复核/标签更新后生成新的评分版本，保留旧报告。重新聚合不重新调用模型；prompt、模型、输入变更则必须新建真实运行，不能混用旧响应声称新结果。

## 9. 运行接口与隔离（拟议）

以下命令在入口实现后才能执行，当前不是可用命令：

```text
python scripts/evaluate.py validate --cases evals/cases
python scripts/evaluate.py plan --suite audit --split development --config evals/configs/audit.json
python scripts/evaluate.py run --suite audit --split development --config evals/configs/audit.json --live --max-calls 20 --max-cost-yuan 5 --deadline-seconds 600
python scripts/evaluate.py score --run-dir .local/evaluation-runs/<run-id>
python scripts/evaluate.py report --run-dir .local/evaluation-runs/<run-id>
```

上面的 20 次/5 元/600 秒是接口示例，不是已经批准的实验额度。未带 `--live` 不发出模型请求；`plan` 只校验配置并输出调用上限估计、案例清单和资源需求。未知单价不能假装成本预算有效，应拒绝仅依赖金额上限的实验；先配置价格或使用明确调用/token/deadline 限制。重试也算调用，deadline 到达停止调度，在途请求使用有限超时并记录结果。

audit 固定文本评测不需要业务数据库；recovery 必须使用独立临时 PostgreSQL/Redis 和合成账号、作品，不接开发/生产库。任务书锁不代替实验资源隔离。固定测试端口 15432/16380 下只能串行运行，并记录占用检查、Compose 项目名和清理结果。

第一版保留现有恢复脚本的 15432 端口保护，并增加库身份/临时环境校验，不能认为“端口正确”就必然安全。未来需要并行时再实现独立端口/库名映射；不要为了使用自定义端口直接删除现有保护。

输出 error 或输出无效不会丢弃后续案例；运行器尽量继续并保存每条状态。schema/config/隔离前置失败则不开始运行。score/report 是离线过程。退出码拟定：0=执行和验收均满足，1=质量/执行验收未满足，2=配置或数据不合法；summary 中提供具体原因。

## 10. 对照实验如何避免自评偏差

先完成固定文本 audit 基线，再建立 generation_compare。audit 的问题是“给定这一段，能否发现指定冲突”；生成对照的问题是“给定任务，最终正文包含多少错误”，二者分母不同。

生成对照两组使用相同素材、任务和初始事实，记录各自实际提示和参数：

- direct：只生成，不经过本项目记忆检索/审核修订；需要明确它仍拿到了哪些基础约束。
- full：完整生产工作流，包括实际启用的召回、校验、审核与修订。

这是整套系统效果与开销比较，不能由此归因到某一个模块。所有最终正文打乱组别后由同一独立标准复核；不得把 full 自己的审核 pass 当作优于 direct 的评分。再根据瓶颈做同工作流的单模块消融，例如召回关闭；Reflexion 只在适用的批次场景比较，不能拿未使用它的单章场景作消融。

## 11. 新增与维护流程

1. 为实际失败写最小合成复现，标注来源；不复制用户小说。
2. 写出必要前提、目标问题、合法变化、有效证据源；明确被测层和入口。
3. 加入配对对照或说明不能配对的理由；指定 group_id、split，标签先 proposed。
4. 运行离线格式校验；由维护者复核标签，留下姓名/时间/说明的实际记录。
5. 运行相关机制测试或小批量模型实验；保存失败，不在 runner 中特判案例 id。
6. 更新 catalog 覆盖映射，并从结果重新生成报告；不手改指标常量伪装改善。

发现误报时先区分标签错误、上下文缺失、召回错误、模型判断错误、证据守卫、路由或保存错误，再决定改动位置。标签有争议时标 disputed；可先做失败分析，但不发布未完成复核的正式质量数字。

评测维护责任：开发者维护运行器/适配器及 schema 版本；案例维护者负责标签与对照；实验执行者负责资源/费用、manifest、产物和清理。个人项目可由同一人承担，但记录真实职责，不虚构独立盲审。重要变更应由他人复核。

格式向后不兼容时提升 schema_version，提供显式迁移并保留原始文件。历史记录缺少字段必须 unknown，不静默填当前配置。旧脚本在新入口覆盖相同场景并完成对账后才退役，不一次性重写所有测试。

## 12. 实施顺序与完成条件

| 阶段 | 交付 | 完成条件 |
|---|---|---|
| A：资产整理 | 40 例 catalog、迁移 15 个 audit 案例、记录 1 个 recovery 场景 | 编号和来源可追溯；5 个 xfail、3 个真空阴性、类型/名称错配明确标注；分组不跨 split |
| B：离线判分 | schema、score/report、离线回归 | 伪造引文、错误章号、无关 rewrite、重复 finding、额外误报、非法输出、运行失败、零分母均有针对性检查；原始结果不可覆盖 |
| C：模型运行入口 | audit 适配器、manifest、预算、逐条写入 | 无 live 不发请求；超时/重试/预算中止可追溯；关键输入输出完整、无密钥；不读业务库 |
| D：第一轮基线 | 15 例逐条结果、人工复核、分类报告 | 先 development 小批量，核对成本与判分；reviewed 案例才进正式指标；可离线重建报告 |
| E：恢复验收 | 当前恢复场景接入、保存/失效断言 | 独立资源，确认完整关键正文与版本/记忆语义；清理可验证；未触发分支明确列出 |
| F：效果对照 | direct/full 同任务输出与盲评结果 | 相同任务公平比较、保存所有重复运行和费用/耗时；结果不归因到单模块 |

第一轮做到 A–D 即可得到可维护的审核评测基线，不必等 F 才交付。真实调用的模型、费用与样本范围在实验开始前明确，不能把本文示例当作执行授权。

CI 默认只做案例格式、评分器和报告器的离线检查；机制测试沿用现有 [CI](../.github/workflows/ci.yml) 的隔离服务。付费模型评测手动触发，不把 API 波动变成每个 PR 的硬门禁。实施时优先相关测试；本设计文档不表示这些新增检查已经存在或通过。

## 13. 面试交付应展示什么

给出原始案例与预期、系统实际输出和证据、已确认失败/误报、分层指标、调用开销、修复前后同案例的变化。重点说明如何识别错误并改进；不要用角色数量、测试数量或挑选出来的成功页代替效果证明。

关联：[优化路线](INTERVIEW-ROADMAP.md) · [本轮完整案例](interview/agent-execution-live-2026-10-08.html)。

## 14. 2026-10-08 实施状态

审核20例、召回8例、生成2任务×2重复×3variant与只补预算中止的运行器已实现，详情及复现命令以 [维护说明](../evals/README.md) 和 [验收](evaluations/p1-completion-verification.md) 为准。20个审核任务仍proposed，真实审核是先前15例；工程脚本与机制测试通过不等于正式语义评测通过。

已保存的生成实验direct缺前章尾文与别名映射，不能完成阶段F的公平效果验收；未来入口修正不能追溯改变原实验。人类复核/正式指标、真实embedding、批次Reflexion仍未验收。保留失败与输入差异，后续在明确样本、费用和标签后再重跑，而非把原结果包装为效果提升。
