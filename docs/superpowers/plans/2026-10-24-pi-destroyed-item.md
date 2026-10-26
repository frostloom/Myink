# Destroyed item reappearance implementation plan

**Goal:** Detect destroyed item reuse without a valid confirmed repair while retaining legal reforging.
**Architecture:** Deterministic L1 item_rule_check over historical events/current draft/confirmed facts, called by ValidationService; no model in validation. Real Pi implements only l1.py/service.py through the established frozen launcher.
**Tech Stack:** Python/SQLAlchemy/SQLite unittest, isolated Linux Pi, independent PostgreSQL product regressions.
**Spec:** ../specs/2026-10-24-pi-destroyed-item-design.md

Global constraints: existing Pi dirty worktree preserved; existing paid/private-data approval; canonical fees/unknowns append-only; no test edits by model, no Git/merge/deployment. Review focus: no draft means no conflict; legal repair facts specific to item/project/time/status; negation/memory/intent not actual use; current/future destruction not historical; multiple destruction order and stable evidence.

- [x] Read existing real sample and baseline; capture all current tracked/untracked source hashes for preservation.
- [x] Write frozen SQLite ORM unittest using actual ValidationService and explicit spec text; observe red before implementation.
- [x] Independent builder/design and concrete frozen Plan/config review; new identity30model/96tool/900sec with canonical scope, no retry/unknown release.
- [x] Execute real Pi; require real two-file allowed patch, fixed complete tests after last patch, finalstatus, authenticated exit, closed policy and all containers removed.
- [x] Independent candidate review, adopt exact approved hashes; host update sample6/30 real inputs, remove only6xfail and update baseline22/26 and spec history.
- [x] Targeted and full ordinary regression using dedicated isolated services; preserve1evaluationDB skip and remaining4xfail if unchanged; publish actual costs/failure/evidence, update memory.

最终固定库存扩展至48项；008实际认证成功，精确两文件独立审查后采纳。宿主失败反馈和Docker输出顺序解析已TDD/独立审查，Pi离线2274通过19未选。完整产品回归使用专用服务，初次仅服务启动超时并清理，第二次健康后执行；完整回归1701通过/1跳过/4预期失败/159未选、2警告，616.847秒进程耗时；服务清理成功。最终证据见[报告](../../evaluations/pi-destroyed-item-development-2026-10-24.md)。Minor未用helper/旧注释保留以保持精确候选，不阻断本切片。
