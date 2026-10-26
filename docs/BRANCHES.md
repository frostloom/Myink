# 开发分支与历史归档

2026-10-20 按项目所有者要求，将长期开发收敛为三条分支。

| 分支 | 用途 |
| --- | --- |
| `main` | 产品主线和普通修复 |
| `codex/pi-autonomy-design` | Pi 引擎及自主迭代控制，保持独立开发 |
| `codex/admin-control-plane` | 后台账号、权限、平台配置和管理页面，独立于 Pi |

默认不再创建小分支；Pi、管理员功能合入 main 或部署需另行授权。

## 小分支核对

本次补全浅克隆历史，并核对远程分支。旧历史曾改写作者身份、提交说明及 SHA，因此不能仅凭祖先关系判断功能是否遗漏。以下三组检查点的 Git 文件树 SHA 完全一致，表示整个版本的文件内容一致；对应的新提交都已是 main 的祖先，无需重复合并旧历史。

| 历史分支 | 原检查点 | main 中的对应检查点 | 核对结果 |
| --- | --- | --- | --- |
| `codex/remaining-plans` | `dd9768a` | `cfc4b1b` | 文件树一致 |
| `codex/pre-history-sync-20260923-dd9768a` | `dd9768a` | `cfc4b1b` | 同一旧检查点，文件树一致 |
| `codex/provider-errors` | `6692728` | `8ef0783` | 文件树一致 |
| `feat/precis-and-global-audit` | `e13e557` | `c050fe3` | 文件树一致 |
| `codex/fix-anthropic-sse-spacing` | `6242119`（本地旧头 `502e97c`） | 同 SHA | 已在 main 历史中 |
| `codex/p2-task-budget` | `f140350` | 同 SHA | 已在 main 历史中 |
| `codex/migration-local-settings` | `65a3b59` | 本次合并处理 | 仅删除两项本机忽略规则及项目记忆说明；采用 ours 策略保留 main 现有规则 |

迁移分支不含业务改动。保留 `/worktrees/`、`/myink-pi/` 的忽略规则及项目记忆说明，避免迁移时移除 Mac 所需的本机保护；合并提交记录该分支已处理。

## 恢复历史检查点

删除小分支引用前，为每个原远程分支头保留同名归档标签：`archive/2026-10-20/<原分支名>`。这些标签保存历史，不作为开发分支。

旧 SSE 与 provider worktree 保留目录、文件及原提交，转为 detached HEAD；后续开发使用上面的三条分支。Pi worktree 已快进到远程 `a0b8100`，管理员分支跟踪远程 `de9f241`。

本次验证范围是分支引用、提交祖先关系、文件树一致性、变更白名单及远程归档完整性；没有修改业务代码，没有运行业务测试，也不将这次整理视为 Pi 或管理员功能验收。

## Vue 3 迁移隔离例外（2026-10-25）

用户明确要求创建独立worktree与`codex/vue3-migration`分支，暂不处理Pi。基于main已提交内容开始，原目录未提交修改不复制。React仍为默认生产入口，Vue候选逐阶段验收。此为本轮迁移例外，不自动合入、推送或发布；完成后的整合与归档另行确定。

2026-10-26 用户进一步授权将Vue迁移成果提交并推送`codex/vue3-migration`，交由main工作区另行合并。本迁移分支现已默认Vue并保留显式React回退；上段默认React描述属于迁移初期。发布仍需独立授权，交接见`docs/work-items/vue3-migration-20261025/remote-merge-handoff.md`。
