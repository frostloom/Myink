# Pi DeepSeek Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pi复用CC-Switch DeepSeek密钥，后续模型deepseek-flash，真实宿主预检增加凭据绑定校验。

**Architecture:** 宿主provider_config模块只读提取固定官方Pi/DeepSeek配置并严格验证四项私有凭据；现有HTTP入口和只读预检共用绑定校验。默认新分析注册使用deepseek-flash，显式历史模型保持既有冻结兼容。私有策略/凭据在原state内更新，真实上游仍关闭。

**Tech Stack:** Python3.12、SQLite、现有Pi/Anthropic网关；无新依赖。

**Spec:** docs/superpowers/specs/2026-10-22-pi-deepseek-profile-design.md

## Global Constraints

- 原Pi worktree、codex/pi-autonomy-design；原累计20元账本不变，历史未知预留不释放。
- 密钥只入宿主state/credentials，禁止任何正文/日志/Git/记忆；不改变CC-Switch当前provider。
- 模型deepseek-flash，宿主provider端点https://api.deepseek.com/anthropic，容器只见loopback scope token。
- 无真实provider请求、新支出授权、main合并或部署。

## Review Focus

- CC-Switch重复匹配/环境变量/命令密钥不能执行或任选一个。
- 凭据中的换行、URL/userinfo/模型/protocol漂移必须在HTTP前拒绝。
- 原历史冻结模型兼容不允许已冻结槽位换成新模型。
- 凭据核对不能打印密钥或以hash入公共回执。
- 新policy的价格/上下文声明不冒充真实计费或付费launcher验收。

---

### Task 1: 宿主配置切换与模型接入

**Files:**
- Create `ops/pi/provider_config.py`、`ops/pi/tests/test_provider_config.py`。
- Modify `ops/pi/control.py`、`ops/pi/analysis_preflight.py`、`ops/pi/analysis_execution.py`、`ops/pi/analysis_trial.py`、`ops/pi/container_runtime.py`。
- Update `ops/pi/tests/test_analysis_preflight.py`与模型测试；增加evaluation/md/json，更新docs/pi/README.md。

**Interfaces:**
- `cc_switch_deepseek_credentials(database: Path) -> dict`：mode=ro读取唯一Pi/DeepSeek，固定官方Anthropic映射。
- `load_credentials(path: Path, policy: Policy) -> dict`：严格四字段/ASCII key/同model-url-protocol；错误固定且不含密钥。
- `audit(..., credential_path=None) -> dict`：可选本地绑定验证、结果仅credentials_checked布尔；不产生网络。
- `freeze_contract_trial(..., model='deepseek-flash')`及slot固定模型允许原历史ID；默认MODEL新ID。

- [x] Step 1: 写失败测试，涵盖只读提取、秘密边界、绑定漂移、预检和两代冻结模型。
- [x] Step 2: 运行新测试；Expected: 未实现接口/新模型导致RED。
- [x] Step 3: 最小实现宿主凭据模块、预检绑定和默认模型切换。
- [x] Step 4: 运行定向及全Pi离线、compileall/diff-check；Expected: 全通过，记录跳过/未选入。
- [x] Step 5: 获取官方公开来源并SHA固定；私有备份/原子替换credentials、生成state/policy.json，实际只读预检并核对与CC-Switch同key；不输出key。刷新隔离源码，条件允许时新模型真实Pi合成容器验收。
- [x] Step 6: 独立审查，必要修复RED→GREEN；更新无正文记录，提交/推送/核对远程，更新myink记忆。
