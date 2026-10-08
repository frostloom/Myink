# 剩余 P1 实施计划

> 使用 superpowers:executing-plans 在当前会话实施，测试先行；最终一次独立只读审查。不提交、推送。

**Goal:** 为已批准 P1 路线补齐可维护的数据、生成对照、召回、工具、恢复与浏览器验证入口，并保存真实结果。
**Architecture:** 扩展现有 evaluation 包，复用生产图/提示/检索；独立临时 PG/Redis/RabbitMQ。现有测试的有效覆盖直接复用，不为凑数量复制。
**Tech Stack:** Python/Pydantic/pytest、现有 PostgreSQL/Redis/RabbitMQ、React/Vitest、浏览器自动化。
**Spec:** [原评测设计](../../EVALUATION-DESIGN.md) 与 [P1 路线](../../INTERVIEW-ROADMAP.md)。

## Global Constraints
- 保留已有工作区修改，原始运行不覆盖；本轮累计最多 60 次实际请求、估算费用 5 元，已有 DeepSeek 配置，无 SDK 自动重试。
- 新真实调用统一共享 Budget；业务逻辑重试和工具循环同样计请求，预算用尽停止并记录，未知用量保留预留额。
- 仅合成素材，隔离端口 15432/16380/15673；标记并核对隔离库身份，禁止访问开发/生产库；不输出密钥。
- 模型/Agent 语义分析不冒充人类校准；盲评模板保留 pending。embedding 替身只证明机制，真实 embedding 未运行须明示。
- 已有恢复/工具/SSE 测试先运行查缺口；P1-06 基于召回基线决定最小修复。无证据不加 reranker。

## Review Focus
- full/no_hybrid 必须实际运行生产工作流；相同素材/约束/目标篇幅，预算或人工等待不能算质量成功。
- 配对组不跨 split；输出抽样不可只选成功；blind key 与待复核正文分开。
- 向量腿替身不能标真实语义效果；召回指标以独立标注的必要事件计算，泄漏和未来章单列。
- 测试资源清理仅本轮创建的容器/合成项目，不接入正式队列；记录 skip/xfail。
- 浏览器场景验证真实组件与可控 API，不能将 jsdom 单测称浏览器 E2E。

## Tasks
- [x] 1. 数据与口径：补 5 个审核难例（别名/合法变化/干扰），总计 20；改 38 的名称映射为实际 volume；留下额外 finding 的 Agent 分析建议和待人类复核包。测试配对 split/新案例来源与校验。
- [x] 2. 召回基线：新增 `retrieval.py`、`scripts/evaluate-retrieval.py`、`evals/cases/retrieval.json`；函数 `retrieval_metrics(required_ids, returned_events, chapter_seq, project_id)` 返回 recall/irrelevant/leak/token 指标；隔离库运行真实 keyword 与 fake-vector/rrf，保存模式、输入、结果、耗时。基线证明别名失败后做最小别名术语扩展，保留前后。
- [x] 3. 工具与恢复：复用 `tests/test_tool_boundaries.py`、`test_worker.py`、`test_multiprocess.py`、`test_reflexion.py`；工具补跨项目参数、失败后恢复、重复预算检查，provider timeout/中断重投、确认取消续跑/锁释放记录真实结果。
- [x] 4. 生成对照：新增 `comparison.py`、`scripts/evaluate-comparison.py`、2 个任务数据；共享预算 provider `generate(...) -> ModelResponse` 记录每次完整请求/响应。direct/full/no_hybrid 两任务各重复两次；full 使用生产 chapter 图，no_hybrid 只关闭混合补充腿。批次 Reflexion 用已有适用测试验证，本轮不将单章做伪消融。盲评表/映射/原始结果分开，正式质量 pending。
- [x] 5. 浏览器：复用实际前端和合成 API 替身覆盖登录、计划确认、流式正文、拒绝、刷新恢复、409 和窄屏；保存运行入口/回执，跑 lint/test/build；不修改产品流加入评测细节。
- [x] 6. 验收：在隔离服务跑 Python 完整 suite，记录失败/跳过/xfail；校验数据/离线重建/安全归档，最后独立审查并修复重要问题，更新维护指南/路线状态/结果和资源清理。

## Verification path
每个新增功能先写失败测试再实现；按阶段执行相关 pytest（全新 `.local` basetemp）并记录命令/结果。最后完整 Python suite 与前端 lint/test/build；调用预算有离线拒绝/错误/参数测试，再执行授权真实对照。环境问题记录根因与替代，不伪报通过。

## Rulings and progress
- 2026-10-08：用户明确授权继续剩余 P1 与 60 请求/5 元；沿用原已批准设计，当前会话直接实施。
- 原工作区含未提交 P0/评测资产，直接在该目录继续，避免新 checkout 丢失被测实现；不改 Git 分支、不提交。
- 测试 Compose 首次因挂载脚本 CRLF shebang 失败；临时目录 LF 副本 + override 挂载，部署源保持原样。
- review 仅一次最终只读子代理，依据 executing-plans/requesting-code-review；开发和模型运行不委派。
- 首轮60请求/0.591484元：8 completed、4 budget_stopped。用户追加批准仅补4条、最多40请求/2元；实际39请求/0.426502元，4 completed。合计99请求/1.017986元，全部16尝试保留。
- 独立审查指出历史direct少前章尾文/明确别名：未来入口修正，历史不重跑或覆盖，不声称公平质量优胜。embedding实际开关守卫、工具嵌套参数脱敏均补回归。
- 1496 passed、5 xfailed、0 skipped，完整Python360.56秒；前端453 passed、lint/build退出0；browser-9的10项检查passed=true；后续离线57项/集成2项通过。
- 本轮工程入口与授权实验已交付；质量复核、公平生成质量对照、真实embedding和批次Reflexion正式验收待后续，不能将任务勾选解释成全部P1质量结论通过。
