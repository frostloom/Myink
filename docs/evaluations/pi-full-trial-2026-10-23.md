# Pi 完整对照模式（离线开发）

本轮获准开发，不包含真实模型运行、自动发布或预算扩容。使用现有Python3.12项目依赖，新增 `ops/pi/analysis_trial_result.py`，并在原 launcher 中以独立清单 schema 选择模式。

## 使用及边界

沿用 `python -m ops.pi.analysis_launcher --config <私有清单>` 默认只读检查；只有显式 `--execute` 才进入既有执行门禁。完整模式清单使用 `schema=pi-analysis-trial-v1`，在原基础字段上必须额外包含且仅包含 `failure_policy=continue_known_contract_failure`；不接收selected_slots，固定五组×两臂×三重复，共30槽。清单仍绑定明确run_id、cap_microyuan、deadline和来源/策略/输入/证据哈希。旧pilot v1/v2与一/两槽限制、严格停止语义保留。

宿主先核验完整引擎证据、固定运行时和原始session，再从唯一完整assistant文本重新解析、执行原基础validator和目标scorer。worker结果和宿主结论不一致直接停止。输出JSON/schema错误公开分类output_invalid（worker旧分类engine_or_output_invalid保持不变），目标域错误为target_scope_invalid。两类均保留原始frame/session，不修复或覆写结果。只有HTTP负控/实际/重放、唯一已知结算、session唯一性和精确容器清理全部成功且期限仍有效，才把槽记为FAILED后继续。其他错误保持UNCERTAIN/blocked，后续NOT_RUN，无自动恢复或重试。

summary从全部30个durable snapshot状态统计，含DONE/FAILED/UNCERTAIN/BLOCKED/NOT_RUN及按两臂/五组分组；不从cases的输出判定推断终态。completed只表示试验所有槽有确定结果；FAILED不是合同通过，NOT_RUN不当作模型失败。语义质量、production_ready、automatic_execution、billing_verified仍无通过声明。

历史真实运行记录、冻结输入、费用和unknown预留不改。修改生产源码意味着旧冻结source闭包会被既有门禁拒绝；任何未来真实试验须重新审阅并冻结当前源码与预算/期限，不能直接复用历史清单或重新发送旧run。

## 验证记录

- 首批宿主验证20项：先确认缺少新verifier时失败，再实现后20 passed。
- 首批模式集成13项：实现前7 failed/6 passed（负向清单和原pilot检查已满足）；补齐后合并验证33 passed。
- 随后追加故障组合、清理期间过期和原始会话完整性覆盖。新增定向测试最终 **44 passed**。
- 初轮Pi全量离线回归2145 passed/19 deselected（未包含后续追加用例），0 skipped；最终修复后完整复跑 **2156 passed、19 deselected、0 skipped**，耗时151.74秒。排除的是pi_lab/pi_live，不代表这些集成或付费验收通过。
- 独立复核发现1项Important、0 Critical、0 Minor：原始session缺少结尾换行、assistant处于非message记录、errorMessage非空或文本空白时，不能相信worker的session_valid标记。已与PiAdapter会话规则核对，4项单元复现修复前均失败，端到端复现修复前错误跑完30槽；补强后这5项及全部新增用例通过。没有放宽JSON/schema/目标评分。
- 复核只读，不再次访问历史私有数据或执行真实provider；修复由主执行完成，完整离线回归已通过；保留未提交改动交付。
- 集成使用真实SQLite、loopback HTTP及stdio子进程，模拟Docker及外部provider；合成费用不是真实消费。未加载真实凭据/正文/账本，不运行Docker或付费请求。未验证真实Linux容器及真实模型效果。根产品数据库集成要求隔离PostgreSQL/Redis/RabbitMQ，本轮不创建或操作这些服务。

## 后续补验

同日后续用户要求继续后，已补真实Linux容器合成验收：完整30槽27 DONE/3 FAILED，以及unknown/空输出/旧pilot停止场景均通过。该阶段未改生产代码，仍无真实模型消费。详见[真实容器验收](pi-full-trial-linux-2026-10-23.md)。
