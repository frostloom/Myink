# Pi Analysis Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对宿主选择的原试验账本执行无逻辑写入的可重复预检，明确真实启动的未完成条件。

**Architecture:** 抽取原 Ledger 的 SELECT-only schema/record 校验供写入口与只读入口共用。新模块以只读一致事务核对原20元授权链、全量逻辑指纹及严格费用汇总，规范化 policy 固定身份；CLI 仅输出无正文审计信息，永不授予 paid admission。

**Tech Stack:** Python3.12、SQLite、pytest；不引入依赖。

**Spec:** docs/superpowers/specs/2026-10-22-pi-analysis-preflight-design.md

## Global Constraints

- 仅在 codex/pi-autonomy-design 原 worktree 开发；保留原账本/历史未知预留。
- 禁止付费调用、授权变更、合入 main 或部署；用户已授权提交和推送。
- 原累计预算20000000 microyuan，原scope100次/10000000，v1及v2审批链必须有效。
- paid_admission 永远false；policy声明不等于价格/输入校准验收。

## Review Focus

- 活动WAL中的新记录可见，读取不可切换journal模式或创建新数据库。
- bool/负数/超预留已知结算/折扣未知预留必须拒绝。
- 缺失原scope或审批事件必须拒绝，不接受默认预算回退。
- 私有记录可含正文或provider ID，stdout/错误只含固定字段。
- 报告不是实时锁、签名或canonical路径证明，不可转为启动授权。

---

### Task 1: 只读预检与真实账本回执

**Files:**
- Modify: `ops/pi/ledger.py`，抽取 `validate_connection(connection)`，保持原构造校验语义。
- Create: `ops/pi/analysis_preflight.py`
- Test: `ops/pi/tests/test_analysis_preflight.py`
- Update: `docs/pi/README.md`，新增 `docs/evaluations/pi-analysis-preflight-2026-10-22.md/.json`。

**Interfaces:**
- Consumes: `_scope_identity(db)`、`load_policy(path)`、`Ledger._decode`；数据库 row_factory=sqlite3.Row。
- Produces: `audit(ledger_path, policy_path, *, expected_scope_sha256, expected_policy_sha256) -> dict`；身份/存储/金额异常抛出固定安全错误；CLI参数为ledger/policy/scope-sha256/policy-sha256。

- [x] Step 1: 写失败测试，断言只读查询/完整指纹、原授权链、金额与隐私边界、WAL可见及并发一致性、失败不创建文件。
- [x] Step 2: 运行 `.venv/bin/python -m pytest ops/pi/tests/test_analysis_preflight.py -q`；Expected: 新模块缺失导致失败。
- [x] Step 3: 抽取原校验，最小实现只读入口与CLI；增加金额校验且未知预留不释放。
- [x] Step 4: 运行定向及完整Pi离线测试、compileall、diff-check；Expected: 全通过、0 skipped，记录deselected。
- [x] Step 5: 对真实原账本运行只读预检，保存无正文回执与限制；独立审查后修复必要问题并验证，提交并推送Pi分支。
