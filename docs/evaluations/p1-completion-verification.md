# 剩余 P1 验收记录

日期：2026-10-08。承接 [首轮审核基线](p1-verification.md)，交付入口见 [归档说明](p1-completion-2026-10-08/README.md)。本轮不提交、推送或部署；保护开始时已有修改。

当前范围：用户在2026-10-08明确决定只整理现有内容，暂停新增自动语义评审、公平重跑、真实embedding与批次Reflexion实验，不要求用户人工逐条复核。本期工程及已运行实验按此收口；现有数据不变，尚未验证的质量结论作为局限保留。面试阅读顺序见 [成果与讲解](../interview/README.md)。

## 已实现与实际运行

- 审核数据由 15 扩至 20（10 阳性/10 阴性），新增 5 例来源、配对与 split 检查；新增案例未另跑真实模型。40 条 catalog 继续保留缺口，把测试 38 的实际行为名修正为 volume_drift，不将其当风格检测。
- 8 例召回基线运行真实生产上下文、SQL、pgvector 与 RLS；关键词必要事件从 4/7 到 6/7，修复当前项目人物 canonical/alias 双向术语扩展，ILIKE 字面量转义和跨项目约束保留。修复前后未来章/租户泄漏均 0；干扰名称挤出历史仍有 1 条缺失。vector_fixture 6/7、rrf_fixture 7/7 均为三元字词哈希替身，不代表 bge 语义效果；最终上下文 K 可变。
- 两合成任务 × 两重复 × direct/full/no_hybrid。首轮 60 请求、8 个 completed、4 个预算中止，估算 0.591484 元；用户随后批准最多40次/2元，仅补4条，实际39次、4 completed、估算0.426502元。合计99请求、估算1.017986元，保存12个最终输出及16个全部尝试。SDK自动重试为0，所有角色与修订共享预算；费用采用仓库单价×2且不是账单。
- full/no_hybrid 实际跑生产单章图、真实隔离数据库；逐阶段保存完整 states、请求/响应和落库一致性。awaiting_review 仍需作者处理，不能计为全流程完成。no_hybrid只关闭混合补充腿，仍保留近期上下文和硬事实。
- 工具增加“失败后继续有效读取”和“模型传项目id不能覆盖服务端id”检查，复用重复调用/预算终止测试。provider超时为SDK故障替身，未知usage保留费用预留；未人为让真实供应商超时。
- 真实两worker、RabbitMQ、Redis、PG复现：写作阶段杀掉持锁进程，另一worker在锁到期后处理重投，落库只有一次；再次投递相同消息不重复persist，任务和作品锁释放。该检查通过（聚焦13项65.39秒），不是 exactly-once 保证或负载测试。
- 实际Chromium访问真实前端构建，API/SSE为合成替身，10项检查通过：登录、计划确认、完成前增量正文、第二段增量、cursor重连、刷新后拒绝、续跑请求、刷新载入正文、409保留草稿且阻止覆盖、390px无页面横向溢出。不是连接部署后端的E2E。

## 审查与修复

按执行计划和 requesting-code-review 做一次独立只读审查，开发和付费运行没有委派。三个发现全部处理并复现/回归：

1. 原direct遗漏previous_tail和明确别名映射：未来入口补齐；原首轮/补跑输入不覆盖、不重跑成功组。**历史结果不能构成公平质量优劣结论**，合并报告显式标注。
2. embedding manifest原先固定写关闭：现在在碰数据库/SDK前拒绝实际启用的配置。真实运行时环境为EMBED_ENABLED=0。
3. 成功解析tool_calls的嵌套参数原先未脱敏：现在递归处理键和值，替换实际API密钥；加入回显密钥回归。

聚焦58项通过，另有合并补跑记录的6项回归通过。已观察到相关新检查修复前失败，不将环境失败算产品回归。补跑绑定原run/results哈希，只选budget_stopped；合并器保留全部尝试，拒绝替换成功项。原始消息里没有事后补填上下文。

最后离线评分/数据/对照回归57项通过（3.22秒），最后运行器集成2项通过（4.22秒）；格式校验20个audit、40个catalog、8个retrieval、2个comparison均通过，旧迁移15例/40映射重跑只对账。

## 验证入口与环境

完整结果与命令日志见归档 `checks/`。Python使用专用myink-test服务（PG15432、Redis16380、Rabbit15673）；业务角色myink_app非superuser/非BYPASSRLS，先核对数据库system_identifier。开发容器未使用。临时初始化脚本LF副本修复本机CRLF挂载问题，部署源未改。

完整Python回归实际 **1496 passed、5 xfailed、0 skipped，360.56秒，退出0**；5项xfail为既有经历/物品/伏笔/能力/归属机制缺口，不能计通过，catalog中的3项真空阴性同样不计有效机制覆盖。合并器后续变更单独跑6项聚焦回归，不能冒充已包含在这一轮完整suite中。

原生成manifest已包含workflow/memory/providers/validation/evaluation源码哈希与dirty提交信息，但没有运行器脚本自身的历史哈希；未来入口补存，历史缺失保持缺失。实际messages/state快照是本次输入证据，验收时source-snapshot不冒充两轮运行时的精确脚本版本。

资源清理核对两轮manifest的11个合成项目，项目和AgentRun残留均为0；首轮清理时遗漏的无FK运行记录已按这些明确id补清，未来runner已同步删除。测试结束移除myink-test容器/网络/测试卷，原有ai-gateway-redis、ai-gateway-mysql、new-api、postgres、redis仍在运行。清理凭据与确认见checks，未经修改的原模型产物保留。

```text
python -m pytest tests/ -q --tb=short -rA --basetemp=<全新忽略目录> --junitxml=<新结果文件>
python scripts/evaluate.py validate
python scripts/migrate-evaluation-cases.py
cd web
npm run lint
npm test
npm run build
```

前端57文件453测试通过；lint退出0、build退出0。lint限定src与vite.config.ts，避免把依赖和dist当源码检查；已有FastRefresh/hook依赖警告及大bundle警告仍保留。未跑Go、镜像构建、远程CI或部署验证。

Windows系统tmp写权限不适配，pytest使用全新工作区basetemp，npm使用绝对工作区TMP/TEMP；pyreadline3退出时句柄告警与pytest结果分开核对。浏览器前8次失败是SSE/计划字段/续跑接口/隐藏或未选中控件的替身和脚本预期不匹配，回执保留；最终引用browser-9的passed=true。

## 尚未完成的正式结论

人类语义复核、两个额外findings裁决、公平质量对照、真实embedding质量和适用批次Reflexion消融没有完成；按用户最新范围，本期不继续开展，也不作为用户必须处理的待办。所有质量状态pending，不伪造reviewer，不把系统自身audit pass当独立评分。P1已经交付可复现的工程入口与本轮授权证据，**不是所有原定质量验收已经通过**。
