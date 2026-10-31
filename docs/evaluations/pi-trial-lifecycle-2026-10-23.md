# Pi 完整对照：期限与受控中断离线实现

2026-10-23。用户已明确批准[设计](../superpowers/specs/2026-10-23-pi-trial-lifecycle-design.md)并授权离线实现与测试；[实施计划](../superpowers/plans/2026-10-23-pi-trial-lifecycle.md)记录执行证据。基于Pi分支4364b8fd，所有改动仍在工作区，未提交、推送、合并或部署。

## 已实现行为

- 新清单 `pi-analysis-trial-v2` 必须携带 `time_policy=bounded_trial_v1` 和原固定失败策略，选择全部30槽；显式绝对deadline最多在未来3600秒，旧pilot与trial v1继续最多600秒。没有自动延长已有run，没有选槽/恢复/重试入口。
- 每次开始新槽前须剩余超过120秒，否则保留未claim的NOT_RUN并明确停止。worker45秒和exchange60秒上限不变；3600秒是清单能力上限，不代表本次已设置真实期限，也不保证跑完。
- 宿主持有wall与monotonic截止时间，剩余取最小；模型正文不能控制取消信号。可选取消通道贯通AnalysisRun/gateway/provider等待和stdio交换，默认参数保持旧行为。已发送请求无法撤回计费；unknown保留原预留，已知费用不能被取消改写。
- CLI显式execute v2时暂时安装并恢复SIGINT/SIGTERM处理器，处理器只记录无锁停止意图；库调用不安装信号处理器。KeyboardInterrupt转为blocked并尝试记录，SystemExit清理/记录后继续传播。第一停止原因不被后续清理错误覆盖。
- 容器身份检查和删除仍按原daemon/name/label/确切ID执行；Docker调用、attach与HTTP服务主动关闭等待共用剩余预算。终止后主动清理最多120秒，且不晚于执行deadline+120秒。最终账本核查/提交及文件持久化不提供整个调用的硬墙钟保证。
- 新run在首容器创建前写只含身份摘要的 `lifecycle-private.json`；最终receipt增加时间策略、execution_deadline、cleanup_grace_seconds、stop_reason和cleanup_complete。只有容器确证清空及所有已预留attempt结算已终结，才可cleanup_complete=true；terminal unknown可以结束清理，pending不可以。无法写最终回执不能报告成功。
- 已完成DONE/FAILED保持不变；事务内终态写入前后都检查停止意图与期限，避免锁等待跨过停止边界后仍提交确定结果。未finish的claim仍UNCERTAIN，summary保留全部30槽。

## 独立审阅及修复

独立审阅发现并修复四项重要问题，每项均有失败复现和通过验证：

1. 信号处理进入Event.set可能在Event条件锁上重入死锁；改为无锁记录意图，由正常路径处理停止。子进程持锁后发SIGTERM的测试先超时，修复后退出正常。
2. 清理finally内KeyboardInterrupt/SystemExit绕过Exception捕获而跳过receipt；现在清理中断仍尝试记录，KeyboardInterrupt返回blocked，SystemExit保存后重抛。
3. finish在事务锁等待前检查生命期，等待后仍可能写DONE；新增可选宿主check，在终态SQL前后检查，失败回滚，不改变旧调用默认行为。
4. 无更早执行错误的清理异常被归为execution_failed；按实际stage改为cleanup_failed，同时保留已有首原因。

同时把配置冻结前移至生命周期捕获之前，防止调用者并发修改导致期限与冻结清单不一致。HTTP服务shutdown/join的主动等待也补入共享预算，防止Docker之外的关闭路径超出已承诺的主动等待范围。最终定向用例还核实了终态SQL后停止会回滚，以及pending不能冒充已结算。

## 验证

最终代码完整Pi离线回归：**2190 passed /19 deselected /0 skipped**，耗时90.99秒；新用例34项。命令为 `.venv/bin/python -m pytest ops/pi/tests/ -q -m 'not pi_lab and not pi_live'`。修复后定向回归64项通过（12.59秒），语法及git diff --check通过。

[机器记录](pi-trial-lifecycle-2026-10-23.json)包含最终代码文件SHA和测试日志承诺；完整离线日志在当前worktree私有 `.local/pi-lifecycle-20261023/full-verified.log`。较早两轮2181/2189通过记录不作为最终代码验收，最终回归启动后未再修改生产代码。

验证使用隔离SQLite、真实loopback HTTP和stdio子进程，只有Docker/外部provider边界替身。覆盖30槽完成与普通失败继续、越过原600秒、窗口不足/时钟跳变、取消前后发送边界、清理失败/中断、唯一session与旧入口行为。没有执行真实Docker、真实模型/账单或主项目PostgreSQL/Redis/RabbitMQ集成验收；不能把本轮结果称为Linux容器或真实计费验收。

## 仍然存在的执行前条件

本轮0真实模型POST、0付费请求、0真实run/容器，不改真实policy、原20元累计scope或历史unknown预留，不读取真实凭据/账本。代码闭包已经变化，旧source/manifest不得重放，未来必须重新冻结全部证据及新绝对期限。

[离线token校准](pi-token-calibration-2026-10-23.md)尚未建立可替换1M策略的提供方输入上界；延长期限能力没有解决完整30槽的保守费用问题。完整付费对照仍未就绪，亦未获本轮执行授权。没有待搁置的重要审阅问题；未引入新依赖。

后续同日已追加[真实Linux容器合成验收](pi-trial-lifecycle-linux-2026-10-23.md)：8场景、37个容器全部移除；该后续阶段仍无真实模型调用，不能取代提供方计费验收。
