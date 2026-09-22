# 局部修订 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 将现有 scope 接入确定性局部修订，保持结构修订与记忆一致性。
**Architecture:** 独立纯函数补丁层、patch 节点、原图回到 extract；复用 writer/运行观测。
**Tech Stack:** Python / pytest / LangGraph / React / Vitest。
**Spec:** docs/superpowers/specs/2026-09-22-revision-scope-design.md

**Execution status (2026-09-23):** Tasks 1–2 implemented; independent review's two Important findings fixed in one RED→GREEN pass (malformed patch denominator and new-attempt budget reset). Final local verification: 1012 Python passed / 5 expected xfails, 253 frontend passed, lint/build passed; exact-SHA CI confirmation follows push. Checkboxes below preserve the original implementation brief, not the live status.

## Global Constraints

- 不删除数据或卷，不修改历史 finding，不碰 Jev。
- 未填 scope=unknown；max_patches=2 独立，结构重写预算保持。
- patch → extract → validate → audit，LLM 无写工具。
- 前端沿用标签与既有组件，不增加冗余说明。
- 连续执行；测试后分目标提交推送 main，CI 成功后推进下一计划。

## Review Focus

- audit 覆盖同键结构 finding：原始规则发现仍能阻止误走 patch。
- 重复/重叠匹配和前一补丁产生的文本：全部基于原稿定位，歧义拒绝。
- 小稿/大段替换冒充补丁：限制单块与总范围，保留原文。
- summary 有阻塞但缺 finding：不得因空列表走局部或放行。
- 补丁失败/用尽：原稿不变、预算终止、重新校验、不得伪造 fixed。

### Task 1: 确定性补丁与保守模式

**Files:** Create src/myink/workflow/patches.py, tests/test_revision_patches.py; modify schemas/contract.py, models/validation.py.
**Interfaces:** Produces Patch(target: str, replacement: str), ApplyResult(content: str, applied: bool, applied_count: int, skipped_count: int, rejected_reason: str | None), parse_patches(raw: str) -> list[Patch], apply_patches(original: str, patches: list[Patch]) -> ApplyResult, resolve_revise_mode(state: dict) -> str.

- [ ] Write literal-fixture tests, including:

```python
def test_exact_patch_preserves_surroundings():
    original = "前文不动。" * 30 + "他握着旧剑。" + "后文不动。" * 30
    result = apply_patches(original, [Patch("他握着旧剑。", "他握着青剑。")])
    assert result.content == "前文不动。" * 30 + "他握着青剑。" + "后文不动。" * 30
    assert result.applied_count == 1
```

- [ ] Run python -m pytest tests/test_revision_patches.py -q; Expected: RED missing module/behavior.
- [ ] Implement frozen dataclasses and pure parsing/application: regex PATCHES section; enumerate exact matches including overlaps; normalized character/index list fallback; collect original spans, reject overlap; threshold then apply spans right-to-left. Limits: 600/block, max(100, len(original)*0.3) total touched characters.
- [ ] Implement mode from all blocking findings with missing/unknown and unmatched rule-summary conservative full; change Python defaults only.
- [ ] Run python -m pytest tests/test_revision_patches.py -q; Expected: all pass.
- [ ] Commit only this task's source/tests and plan/spec after focused verification; keep push until caller is connected in Task 2 (no dead-code rollout).

### Task 2: 图路由、运行记录与前端

**Files:** Modify workflow/{chapter_graph,nodes,state,prompts}.py, config.py, web/src/{types.ts,lib/labels.ts,lib/taskFlow.ts,components/TaskTimeline.tsx}, spec/state-flow.md; create tests/test_revision_scope.py; extend TaskTimeline tests.
**Interfaces:** Consumes Task 1 pure API; produces node_patch(state: ChapterState) -> ChapterState, patch_count, revise_mode, patch_applied, patch_skipped, patch_rejected_reason.

- [ ] Write routing tests with report critical local:

```python
def test_local_critical_cannot_pass():
    f = {"severity": "critical", "scope": "local", "source": "L1"}
    state = {"report": {"summary": {"critical": 1}, "findings": [f]},
             "audit_verdict": {"verdict": "pass"}, "revision_count": 2}
    assert route_after_audit(state) == "patch"
    assert route_after_audit({**state, "patch_count": 2}) == "needs_review"
```

- [ ] Add real graph cycle test with external provider controlled output; assert patch/extract/validate/audit order, candidate replacement, record metrics, no revision_count consumption; malformed/full patch output preserves draft.
- [ ] Run focused tests; Expected: RED missing patch route/node.
- [ ] Add writer-only patch prompt, including scope/evidence/plan context without full rewrite instructions; _llm node patch with 4096 cap; apply server-side and record_run_detail.
- [ ] Add patch graph edge and independent budget branch only where revise was previously selected; keep full revise unchanged. Route records include mode/count/application metrics. Reset patch state on replan.
- [ ] Add frontend test that route=patch and node=patch render human labels; implement labels, task history inference, scope unknown type. No new layout.
- [ ] Run python -m pytest tests/test_revision_scope.py tests/test_revision_patches.py tests/test_review_routing.py tests/test_ledger_l2.py -q; Expected: pass including unchanged original six budget cases.
- [ ] Run python -m pytest tests/ -q; npm run lint; npm test; npm run build; python -m myink.cli contract export. Expected: green; existing lint/build warnings disclosed.
- [ ] Commit; independent whole-goal review, single RED→GREEN fix pass for Important/Critical; full verification; push main and confirm exact SHA CI success.
