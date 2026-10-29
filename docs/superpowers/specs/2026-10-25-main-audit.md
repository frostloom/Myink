# Myink main 全仓审查 — 2026-10-25

审查基线：本地 main `19f21b61f2ca39cccb0e40c3851ad0b2d268fbcb`，包含当前尚未提交的题材发布修复。
本轮没有修改仓库、提交、推送、部署或启动业务服务，未连接默认/生产数据库或调用真实模型。

## 范围与证据边界

覆盖 Python API/认证/权限/RLS/章节与记忆，worker/队列/预算/检查点/providers/工具，React 建书/工作台/编辑/资源与后台，以及配置/发布/迁移/部署脚本。
仓库当前没有 gateway 目录；第三方写作素材不作为应用逻辑逐篇评审。
审查采用源码调用链、SQLite 内存库、模型/消息队列替身、真实 LangGraph InMemorySaver 和 jsdom。不是对生产基础设施的渗透或容量验收，不保证不存在其他缺陷。
此前的 1867 项后端全量通过是上一轮修复的验证结果，本轮没有再次运行全量；下列补充场景未被此前绿灯覆盖。

确认 11 项：3 项 P1，8 项 P2；最后一项仅特定路由复用时触发。切书的两个异步入口合并为一项，同类表单即时归一化合并为一项。

## P1 — 优先处理

### 1. 删除章节误删建书人物设定

位置：`src/myink/memory/invalidation.py:189–190`；真实调用 `api/routes_chapters.py:174`；建书创建人物 `api/routes_book.py:551–562`。

人物清理仅按状态、关系和事件引用的最早出现章判断，不能区分作者建书设定的人物和模型在正文新增的人物。建书主角第一次在第 1 章出场后删除第 1 章，角色及其种族、境界上限、性格和基础属性会一起硬删除。删除正文不应清除作者的角色基底。

SQLite 复现 `/private/tmp/myink_audit_registry.py`：`characters_deleted=1`，`after-delete=None`。

### 2. 人工修订再次审核后，确认续跑清掉刚批准的记忆

位置：`src/myink/workflow/nodes.py:1365–1369`、`:1439–1444`；入口 `workflow/review.py:39–40`。

作者拒绝设定后修订设置 `rewrite=True, review_revision=True`。修订稿再次待审核，用户确认新事实后继续：finalize 把候选缩减为 plotline；persist 因 review_revision 跳过确认池重放，却仍失效整章记忆。结果章节正常确认，但新批准的事实失效、事件被删。

调用实际 finalize/node_persist，数据库与写入使用记录替身：`invalidate(['The new approved fact']) → persist_candidates([])`，最终记忆为空。脚本 `/private/tmp/myink-audit-review-memory-repro.py`。

### 3. 队列重投先 ACK，发布失败时任务消息丢失

位置：`src/myink/worker/consumer.py:103–118`。

retry/defer 都先 ACK 原消息，再向延迟队列发布。若 publish 失败或进程在两步之间退出，原消息已经消失，新消息不存在；没有 outbox 或补偿重新投递。任务不能自动接力，可能滞留 running/queued。

消息队列替身复现：retry、defer 两条路径均为 `[('ACK',1), ('PUBLISH_FAILED',)]`，没有 NACK。脚本 `/private/tmp/myink-audit-workflow-repro.py`。

## P2 — 功能一致性与恢复

### 4. 已删除记忆无法随正文恢复

位置：`src/myink/memory/correction.py:152–162,175–177`。

确认事实 A → 编辑移除 A 并确认记忆删除 → 正文恢复 A → 再校正。池去重包含任意历史状态，将旧 confirmed 候选视为重复，既不恢复活性事实，也不生成新的待确认项。硬约束同样受影响。

SQLite 输出：`changeset.add=1`、`add_to_pool=0`、`duplicates_skipped=1`、活性事实和 pending 候选均为 0。脚本 `/private/tmp/myink_audit_memory.py`。

### 5. 同一候选并发确认会重复落库

位置：`src/myink/workflow/nodes.py:1721–1733`。

普通 get 读取 pending，没有行锁或 CAS。两个请求均先读到 pending 后，可分别写事实/事件并都提交；confirm/reject 交错还可能让候选最终显示 rejected，但记忆已生效。

两个 SQLite Session 先读取 pending，再交错提交，单候选产生两条事实。PostgreSQL 真实并发尚未运行；证据是明确可达的无锁事务交错及无相应唯一约束。脚本同上。

### 6. 删除关系变更章后没有恢复前章关系

位置：`src/myink/memory/invalidation.py:55–60`；查询 `memory/repository.py:154–158`。

第 1 章盟友、第 2 章变敌对，后者已将前者 valid_to 关闭。删除第 2 章只关闭敌对行，不重开第 1 章关系。当前关系查询仅取 valid_to IS NULL，因此关系完全消失，影响之后召回与检查。

SQLite 输出：删除前 `['hostile']`，删除后 `[]`，第 1 章 ally 行仍为 valid_to=2。脚本 `/private/tmp/myink_audit_relation.py`。

### 7. 人工审核收尾时预算暂停，追加预算后仍卡待审核

位置：`src/myink/workflow/runner.py:164–168,143–144`；`worker/processor.py:267–271`。

finalize 先将章确认为 confirmed，再做摘要；摘要触发预算暂停时，图 checkpoint 仍是已结束、needs_review=True。恢复时因章已 confirmed 绕开 finalize，invoke(None) 返回旧待审核状态；摘要也不再执行，追加预算无法推进。

真实 LangGraph InMemorySaver 配合实际 dispatch/finalize/resume 的替身复现：首次章已 confirmed/request_limit；checkpoint next=(),needs_review=True；第二次 returned_needs_review=True，summary_calls=1。脚本 `/private/tmp/myink-audit-review-resume-repro.py`。

### 8. Provider 丢失截断原因，短篇半截稿不提示

位置：`src/myink/providers/deepseek.py:334–343`、`providers/anthropic.py:298–303`，及 Anthropic 非流式返回路径；消费者 `workflow/short_runner.py:203`。

OpenAI/DeepSeek 流式 finish_reason=length 没写入 ModelResponse；Anthropic stop_reason=max_tokens 也未映射。短篇截断检查仅识别 finish_reason=length，因此章标记齐全但末句截断的成稿可能按完成保存，无截断 warning。

向真实 Provider 注入受控 SDK/HTTP 响应，得到 `error=None, finish_reason=None, warning=None`。脚本 `/private/tmp/myink-audit-workflow-repro.py`。

### 9. 切书后的迟到生成结果污染当前工作台

位置：`web/src/pages/WorkspacePage.tsx:364–373` 和 `web/src/components/GenerationPanel.tsx:89–96,115–121,137–141`。

有两条独立入口：

- A 的章节物化请求等待时切到 B；B 已显示后 A 响应返回，await 后没有再次检查项目/代次，直接把 A 章节写入 B 列表。
- A 的入队请求未返回时切到 B；迟到响应继续调用旧 onTaskStart，向复用工作台写入 A 任务、占位章和成功通知，监听 A 的 SSE。

jsdom 已用真实 React Router 切换复现：B 章消失，显示 A 章；GenerationPanel 切换项目后旧回调仍执行。未证明后端跨租户越权，问题是前端状态串书。

### 10. 建书与手动计划的表单吞掉未完成输入

位置：`web/src/pages/NewProjectPage.tsx:795–798`；`components/ChapterPlanPanel.tsx:53–55,97–99`，同类列表字段也受影响。

世界观框每次按键立刻解析键值，未输入冒号的行会被删除：输入首字“魔”立即变回空。列表字段每次输入就 trim/filter，Enter 产生的末尾空行立即消失；再输入第二项目标，会与第一项合并。作者无法正常逐字填写世界观或逐行添加目标/伏笔/节拍，应在提交时才归一化。

jsdom 复现：首字消失；手动计划提交目标是 `['第一目标第二目标']`。

### 11. 特定历史导航下，旧设置覆盖另一本书并可被保存

位置：`web/src/pages/SettingsPage.tsx:32–45`。

设置页异步 load 没有代次/取消保护。直接跨两个不同 projectId 的设置路由时，A 迟到响应可覆盖 B 的目标字数；随后保存实际向 B 写入 A 的数值。测试中 B 原 6000，最终 updateProject('b',{target_words:1500})。

触发频率较低：通常作品栏会先到工作台，卸载设置页，能避免该竞态；浏览器历史直接跨两本设置页（跳过中间页面）仍可触发。jsdom 路由复用已复现，未做真实浏览器导航验证。

## 本轮验证与建议顺序

主代理独立重跑了上述六个后端复现脚本，得到同样结果；前端临时 jsdom 4 文件、5 测试通过，断言的是缺陷行为而非修复正确性。脚本均位于 /private/tmp；仓库内未新增测试或修改源码。

建议先修 1、2、3 的数据/消息丢失，再处理恢复与并发一致性，最后收口跨书响应保护和编辑输入状态。修复后需要将这些场景转成正式回归，并在独立 PostgreSQL/Redis/RabbitMQ 环境复验；不能用既有全量绿灯代替新场景验收。

未发现高置信的直接跨用户越权；未进行真实 PostgreSQL 并发锁、生产负载、真实供应商或浏览器可视布局测试。既有五项冲突检测 xfail 未计入这些新发现。
