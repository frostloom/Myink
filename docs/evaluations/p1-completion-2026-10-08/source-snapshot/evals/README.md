# 评测运行与维护

这是 P1 评测维护入口。先读 [设计](../docs/EVALUATION-DESIGN.md) 和 [覆盖清单](catalog.json)。审核数据现有 20 例，首轮真实审核仍是原 15 例；新增难例没有追加模型审核。召回、生成对照和浏览器有独立运行器，范围与结果见 [剩余 P1 验收](../docs/evaluations/p1-completion-verification.md)。

## 环境和目录

- 根目录执行；Python >=3.11，安装项目依赖，测试需 dev 依赖。Windows 终端建议 `PYTHONIOENCODING=utf-8`。
- `cases/audit/`：20 个固定文本案例，10 个阳性、10 个阴性。每文件一个案例，稳定 id；新五例来源见 [ADDED-CASES.md](ADDED-CASES.md)。
- `catalog.json`：40 例规范到测试函数的映射。coverage 表示对应机制覆盖，不是本次模型成功状态。
- `configs/audit.json`：固定模型及参数，默认最多 20 次请求、估算上限 5 元、600 秒总调度期限。配置文件不是执行授权；真实调用需要 `--live`。
- `.local/evaluation-runs/`：默认完整产物目录，Git 忽略。
- 每次 run 新建目录，不覆盖。分数保存到 `scores/<新评分编号>/`，原始 cases/results/manifest 保留。

## 1. 校验和预览（不调用模型）

```text
python scripts/evaluate.py validate
python scripts/evaluate.py plan --split development
```

validate 检查案例格式、文本指针和章号、来源案例名称、配对 split、规范/测试映射。plan 展示所选案例与资源限制；不会发请求或读取作品库。

迁移脚本 `scripts/migrate-evaluation-cases.py` 使用 AST 读取旧脚本的合成常量，**不执行旧脚本**。只用于首次迁移/对账，拒绝覆盖语义已编辑的数据。日常维护直接 review JSON 案例；不要为强行重建而删除已维护的文件。

## 2. 运行真实审核

```text
python scripts/evaluate.py run --suite audit --split development --live
```

目前仅支持 DeepSeek v4 Flash/Pro，读取根目录 `.env` 或进程中的 `DEEPSEEK_API_KEY`，不把密钥放进命令。生产调用的 audit prompt 和请求形状被复用；评测专用 SDK 客户端关闭所有自动重试，一次调度对应最多一次实际请求。没有 `--live` 会报错，且不新建运行目录。

本轮用户授权的完整 15 例使用 `--split all`（默认值）；开发迭代通常只跑 development。holdout 是已公开的本地保留组，不是独立外部基准，不因看过结果再调提示词还继续宣称其独立性。

费用采用仓库空闲单价乘 2 的保守估算，忽略缓存折扣，不是供应商账单。调用前用带余量的 UTF-8 字节估计与输出上限预留费用，未知用量保留预留额；未知单价拒绝执行。该估计不是 tokenizer 精确计数，也不能保证供应商未来调价后的实际账单。达到调用/估算费用/期限时停止调度；在途请求可能已产生费用。

CLI 的 `--max-calls`、`--max-cost-yuan`、`--deadline-seconds` 可显式覆盖配置。付费实验的范围需在运行前明确；不要将示例默认值当作无限期授权。

## 3. 看结果和离线重新评分

```text
python scripts/evaluate.py score --run-dir .local/evaluation-runs/<run-id>
python scripts/evaluate.py report --run-dir .local/evaluation-runs/<run-id>
```

以上不调用模型，均保存一个新的评分版本。查看打印出的 `report.html`。每个案例可展开输入/预期、实际模型输出和证据检查，失败不会被隐藏。

产物：

| 文件 | 维护口径 |
|---|---|
| manifest.json | 原始配置、案例/源代码/prompt 哈希、实际请求计数、估算费用和运行状态 |
| cases.json | 本次案例快照，不能事后改期望提高分数 |
| results.jsonl | 每次调度的真实结果；保存请求失败和预算中止 |
| artifacts/<case>/messages.json | 实际送入审核的完整消息 |
| artifacts/<case>/result.json | 逐案例结果，支持中断后的核对 |
| scores/<id>/scored.json | 本次判分结果，含证据检查和复核状态 |
| scores/<id>/scoring-manifest.json | 结果/案例/评分器哈希，绑定此评分版本 |
| scores/<id>/review-template.json | 待填写的人类复核模板 |
| scores/<id>/summary.json、report.html | 可重建的汇总和展示 |

运行状态 running 时允许对已保存前缀评分，剩余案例列 not_run；已有请求意图但无结果列 interrupted_unknown，不能假定没有费用。manifest 原子替换；最终 JSONL 尾部写裂时只允许基于一致的前缀/逐案例产物恢复派生报告，原日志不修改。其他损坏或已完成记录哈希不一致直接报错，不静默忽略。

初版真实基线保存的是经过服务端文本处理和脱敏的 `raw_output`；原始 HTTP 内容未保存。后续适配器另外保存 `raw_response_content` 与投影/脱敏标记，仍不保存响应头或密钥。历史缺失字段保持缺失，不能补造。

## 4. 人类复核

自动检查只确认类型、严重度、来源引文和 verdict；语义对应关系与额外问题需要复核。case label 默认 proposed，正式指标为空，不将模型 confidence 当真值。

1. 复制最新评分目录的 `review-template.json` 到新文件。
2. 阅读 cases 快照、模型输出和证据；填写真实 reviewer。确认期望标签后填写 `label_confirmed: true`，不修改原案例快照。
3. 每个 finding（编号为输出数组位置 `0`、`1` 等）选择：
   - `match`：确实发现指定问题，必须填 `issue_id`，且证据/类型满足规则。
   - `duplicate`：同一问题的重复报警，指定已有 match 的 issue_id；不重复计算 TP。
   - `false_positive`：经过复核确实不存在该问题。
   - `label_gap`：发现合理但未标注的额外问题，进入标签完善，不计作模型误报。
   - `disputed`：尚有争议，不计正式已确认结果。
4. 无 findings 的正常输出也需要 reviewer/label_confirmed 与空 decisions，才能确认放行。非法 JSON 可用空 decisions 确認为输出失败，不允许编造 finding。
5. 保存并离线评分：

```text
python scripts/evaluate.py score --run-dir .local/evaluation-runs/<run-id> --review <review-file.json>
```

模板示意（哈希须使用实际模板值）：

```json
{
  "results_sha256": "实际结果哈希",
  "cases_sha256": "实际案例哈希",
  "actor_kind": "human",
  "cases": {
    "logic.destroyed_item": {
      "reviewer": "实际复核人",
      "label_confirmed": true,
      "decisions": {"0": {"kind": "match", "issue_id": "destroyed_item"}}
    }
  }
}
```

不要把 Agent 生成的建议填写成“人类已复核”。未填写、部分填写或争议记录保持 provisional/disputed。review 同时绑定案例与结果哈希，不能拿旧确认套新标签。正式分母由已确认标签/输出决定；整体成功比例另外保留 planned 分母。报告始终列运行失败、未执行和待复核数量。

退出码：validate/plan/报告成功为 0；run/无 review 的 score 以暂定自动验收为依据，未满足返回 1；带 review 的 score 要全量确认且成功才返回 0，未完成复核或确认失败返回 1；配置/数据错误为 2。返回 1 不等于请求失败，先看 execution 状态。

## 5. 恢复证据检查

```text
python scripts/evaluate.py check-recovery --source docs/evaluations/workflow-recovery-2026-10-08-live.json
```

这是对已保存真实恢复案例的 11 条确定性断言重查，不是再次调用模型。完整修订稿、落库一致性、旧版本和反馈应用可检查；语义约束、失效记忆有效期需要复核；provider 超时、worker 中断和消息重投未由此覆盖。

## 6. 日常维护与验证

新增失败复现时优先写最小合成正反对照，稳定 id/group_id，标明必要历史事实及证据源；同一配对不跨 development/holdout。标签保持 proposed，确认后留下实际复核说明。额外合理问题通过新标签版本修复，旧运行仍按原标签保存，重新评分要保留版本。

```text
python scripts/evaluate.py validate
python -m pytest tests/test_evaluation.py -q
```

Windows 若系统临时目录不可写，选择仓库忽略目录中一个**全新的** `--basetemp`，不要指向已有资料目录（pytest 会清理它）。CI 仅校验数据及跑离线测试，不自动调用付费模型。

首轮结果与范围见 [P1 验收记录](../docs/evaluations/p1-verification.md)。新增入口如下，费用示例不是继续付费授权。

## 7. 召回实验（不调用真实模型）

```text
python scripts/evaluate-retrieval.py --output .local/evaluation-runs/<new-retrieval-run>
```

`cases/retrieval.json` 的 8 例使用严格 schema，事件 id 不重复，required 必须是第 30 章之前的已有事件。必要事件标签独立于检索排名；无必要事件的阴性 recall 为 null。每例新建本项目及其他项目，真实生产 `build_context` 与 SQL/RLS 运行后删除；业务连接必须启用 RLS。

keyword 使用生产关键词腿；vector_fixture/rrf_fixture 使用确定性三元字词哈希向量和真实 pgvector 查询，只测召回机制，不测 bge 语义质量。输出是最终上下文（含最近 10 条），不是固定 K 搜索结果；每例保存 returned_unique、缺失事件、无关比例、未来/租户泄漏、估算 token 和耗时。不要只比较汇总 recall 而忽略这些成本与边界。

## 8. 生成对照与补跑

```text
python scripts/evaluate-comparison.py plan
python scripts/evaluate-comparison.py run --live --output .local/evaluation-runs/<new-run> --max-calls 60 --max-cost-yuan 5
python scripts/evaluate-comparison.py plan --supplement-source .local/evaluation-runs/<finished-run> --max-calls 40 --max-cost-yuan 2
python scripts/evaluate-comparison.py run --live --supplement-source .local/evaluation-runs/<finished-run> --output .local/evaluation-runs/<new-supplement> --max-calls 40 --max-cost-yuan 2
python scripts/assemble-comparison.py --primary .local/evaluation-runs/<finished-run> --supplement .local/evaluation-runs/<new-supplement> --output .local/evaluation-runs/<new-derived-report>
```

真实运行前须满足：专用 localhost:15432/myink、`APP_ENV=test`、`EMBED_ENABLED=0`、`MYINK_EVALUATION_SYSTEM_ID` 为维护者核对过的 PG system_identifier；连接角色为非 superuser/非 BYPASSRLS 的 myink_app。管理员连接也只能指向该专用库。核对 Docker 专用容器的 `SELECT system_identifier FROM pg_control_system()`，再设变量；不要让 runner 自动信任当前连接。服务启动/角色初始化见项目测试 Compose 和 [DEPLOY.md](../docs/DEPLOY.md)，Redis/Rabbit 使用 16380/15673，禁止与其他会话并发占用 `myink-test`。

两任务各重复两次，三个 variant：direct 仅生成；full 生产单章图；no_hybrid 与 full 相同，仅关闭关键词/向量补充腿，仍保留最近事件和硬事实。各角色、工具往返和修订共用同一个 Budget。所有请求保存完整消息、响应、实际模型、usage/耗时/估算成本；SDK 不重试。`states.json` 是生产状态快照，`outcome=awaiting_review` 仍需要作者处理。run 退出 0 表示运行器完成记录，不代表质量通过。

仅允许补 source 中的 budget_stopped 槽位，使用 source 的输入快照；新目录记录原 run/results 的 SHA-256，已完成槽位不能被替换。离线 assemble 校验绑定和请求数量，保留全部 attempts，另外生成 selected 和 16 个尝试的盲评包，原文件不变。blind key 只用于复核后解盲，不能声称真正保密随机实验；固定 seed 仅便于重建。

**本日历史 direct 输入缺前章尾文与明确别名映射**，因此归档不构成公平质量对照。入口已修正未来输入，但不能补造旧消息，也未获授权重跑成功组。首轮和补跑有不同代码哈希，详见各 manifest。真实 embedding、批次 Reflexion 消融仍待另行安排。

## 9. 浏览器与机制验证

```text
cd web
npm run lint
npm test
npm run build
cd ..
node scripts/evaluate-browser.cjs --output .local/evaluation-runs/<new-browser-run>
```

Node 可解析 `playwright` 且已安装 Chromium；非标准安装可设 `NODE_PATH` 与 `P1_CHROMIUM_EXECUTABLE`。脚本运行真实构建产物，启动本机随机端口，API/SSE 为明确的合成替身，未知接口失败；不连接部署后端、不调用模型。检查登录、计划确认、两段增量、重连 cursor、人工拒绝续跑、刷新载入正文、409 保留草稿与390px。回执含检查、接口和错误，失败也保存截图/文本。

Windows 临时目录权限不适配时，把 npm 的 TMP/TEMP 指向绝对路径的仓库忽略目录。完整 Python 用项目约定的隔离 PG/Redis/Rabbit；评测 runner 的集成测试另需明确的 system identity，否则会显式 skip，不能计通过。worker 杀进程测试等待锁过期，可能需要一分多钟。

维护时先改合成案例/schema并跑相关测试，再决定真实实验；模型费用、数据库身份和人类复核各自留记录。不可手改历史原始响应、自动填写 reviewer，或用当前代码配置填补历史缺失字段。
