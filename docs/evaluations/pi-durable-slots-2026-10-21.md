# Pi 持久化槽位与防重放验收（2026-10-21）

## 本次交付

在 `codex/pi-autonomy-design` 新增 `ops/pi/analysis_run.py`，复用现有SQLite账本，不增加schema或预算授权。创建时原子登记run/source/config和30个冻结槽位；打开、认领、完成与快照都核对原持久身份。提示和正文不写入这些账本记录。

- 按可信宿主指定序号原子认领；并发线程/进程只有一个成功，拒绝乱序、重放和身份漂移。
- 已认领但未完成的槽位保持UNCERTAIN，重启不重发，不继续下一槽。明确done/failed才允许前进；uncertain/blocked及全部终态不可覆盖。
- 始终保留全部30槽，包括NOT_RUN；done只代表宿主记录的明确终态，不等同合同有效、计费成功或语义质量改善。
- `gateway_handler` 接入已有真实HTTP处理器，逐槽绑定私有随机令牌，仅存摘要；同一账本内跨槽/跨运行不能复用令牌。baseline正文可能相同，旧包先因旧令牌被拒绝，再由持久guard保障当前槽最多准入一次。
- 认领与模型预算预留分别提交：认领后即使未发HTTP或费用预留失败也不能自动重试，保守保留不确定状态。

API及宿主用法见 `docs/pi/analysis-and-scoring.md` 的持久化槽位章节。该模块不启动Pi、不驱动30槽循环；由可信宿主选择槽位、创建新会话/独立令牌并核对结果。

## 验证

- TDD第一轮：22 failed（模块缺失）→22 passed。
- 相同baseline包/独立令牌反例：8 failed（缺少gateway_handler）→合计30 passed，1.90秒。
- 新增测试覆盖真实SQLite、多线程、多进程spawn、子进程认领后`os._exit(23)`、重启拒绝、不可用存储、输入修改、终态、两次真实loopback服务启动和旧HTTP包拒绝；外部提供方由mock替代。
- 完整Pi离线：**1768 passed、0 skipped、19 deselected，39.90秒**。
- `python -m compileall -q ops/pi` 和 `git diff --check` exit0。
- 独立实现审查：Critical/Important/Minor均0；审查者运行28 passed，另2个loopback测试因其沙箱bind权限失败，未到断言，不记为独立通过。主执行者具备本地loopback权限的30项及最终1768项均已实际通过。
- Mac环境基线修复另见 `pi-mac-baseline-2026-10-21.md`，已单独提交推送 `8821831`。

最终命令：

```sh
.venv/bin/python -m pytest ops/pi/tests/ -q -m 'not pi_lab and not pi_live' --tb=short --junitxml=.local/pi-durable-slots/final-offline.xml
.venv/bin/python -m compileall -q ops/pi
git diff --check
```

原始日志/JUnit在当前worktree的 `.local/pi-durable-slots/`，不含真实数据和凭据；没有将私有目录提交。

## 边界与下一步

本轮仅验收持久准入。整轮费用/期限和原累计账本的实际宿主绑定、当前运行时隔离、无工具分析、超时/溢出与进程清理仍需独立完成，然后才可评估是否启动有限真实分析对照。源码/config哈希真实性仍由可信宿主核对；不提供对故意回滚旧账本副本的检测，也不自动修复被外部改写的数据库。

没有调用外部模型、修改真实累计20元账本、释放未知预留、运行完整业务CI、合并main或部署。45项语义质量仍unknown，自动执行和发布权限不因此改变。19项pi_lab/pi_live未选入不能算通过。
