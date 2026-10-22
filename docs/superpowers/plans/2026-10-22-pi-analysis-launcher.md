# Pi Analysis Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用有界可信宿主清单连接现有预检、原子预算和无网络Pi容器，先完成合成两槽验收。
**Architecture:** 新analysis_launcher加载严格宿主清单和reviewed evidence，默认check只读。显式execute时绑定既有AnalysisRun，逐槽传有界初始帧、复用ProbeHost/exchange/verify_result，provider transport仅留宿主。固定worker支持通用冻结输入，同时保留legacy synthetic probe。
**Tech Stack:** Python3.12、SQLite、现有httpx/Docker/Linux Node24.22/Pi1.1，无新依赖。
**Spec:** docs/superpowers/specs/2026-10-22-pi-analysis-launcher-design.md

## Global Constraints

- 原Pi worktree/codex/pi-autonomy-design；不建scope、不释放历史unknown、不改实际live=false。
- 不真实付费、不合main、不部署；默认check无Ledger构造/网络/目录写入。
- deepseek-flash、官方Anthropic；完整30槽只选择前2槽，不自动重试/恢复。
- 显式正整数cap/绝对未来600秒内deadline，冻结来源/输入/policy/证据、原20元审批链。
- key只留宿主0600/0700；公开不含正文/token/key或其摘要；全异常路径精确清理。

## Review Focus

- 预检后policy/输入/源漂移或同run重启不得换身份、延长预算/期限或重发。
- attach或loopback返回晚于期限、provider未知结算必须阻止下一槽。
- create不确定、attach失败、foreign对象及清理失败不能遗漏或误删容器。
- 新初始帧大小/重复字段/不同domain输入与宿主重算session必须匹配，不能只信worker。
- evidence是有限期宿主声明，不能把live flag/价格快照/已知usage冒充账单/生产验收。

---

### Task 1: 有界宿主入口及冻结worker输入

**Files:** Create ops/pi/analysis_launcher.py、ops/pi/tests/test_analysis_launcher.py；modify ops/pi/lab/container_runtime_worker.py、ops/pi/ledger.py；update docs/pi/README.md；new docs/evaluations/pi-analysis-launcher-2026-10-22.md/json。
**Interfaces:**
- launch(config: dict, *, execute=False) -> body-free receipt；封闭pi-analysis-launch-v1清单、原始sources绑定的pi-provider-evidence-v1证据；main(argv=None) CLI --config及可选--execute，失败固定JSON/exit2。
- worker.prepare_initial(initial: dict) -> validated per-slot config；legacy两字段仍可用，新模式slot_index/token/slot/view/report/deadline必须精确匹配并在FRAME_LIMIT内。
- Consumes AnalysisRun.create/bind_budget/gateway_handler/finish/snapshot、analysis_preflight.audit、ProbeHost、container_runtime.exchange/verify_source/verify_result，不修改累计预算算法。

- [x] Step 1: 写失败测试：check无副作用且无正文、live关闭execute拒绝、错误pin/权限/证据/预算/期限/额外字段拒绝；worker冻结帧重建/大小/过期拒绝；两槽真实SQLite/HTTP/子进程、unknown/清理失败/重复run/超时停止。
- [x] Step 2: `.venv/bin/python -m pytest ops/pi/tests/test_analysis_launcher.py -q`；Expected: 接口缺失RED，保留日志。
- [x] Step 3: 最小实现launch/check/provider上下文与精确清理、初始帧解析；Expected: 新测试GREEN。
- [x] Step 4: 运行定向与完整Pi离线、compileall/diff-check；Expected: 全通过，明确19项未选入；提交功能。
- [ ] Step 5: 刷新封闭源码到新私有snapshot，以固定Docker/Linux Pi+MockTransport验收新入口，原canonical账本/真实凭据/实际live不改；Expected: 两新session、2DONE/28NOT_RUN、计费已知、精确所属清理、0真实provider。
- [ ] Step 6: 独立整段审查，一次RED→GREEN修复Important/Critical；更新验收/计划，提交推送核对远端，myink记忆完成/回查；归档本计划workspace。
