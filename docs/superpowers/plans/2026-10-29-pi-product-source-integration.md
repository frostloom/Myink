# Pi Product Source Integration Implementation Plan

> Native inline execution under the user's continuous authorization; no step-by-step confirmation. Apply executing-plans, TDD, minimal-change guidance, then one fresh final source reviewer for this independent plan and one author fixpass, no rereview. Do not change main, another worktree or production.

**Goal:** Make the Pi development branch retain current main and the physically verified deployed backend's functionality, while preserving Pi maintenance/provenance/audit boundaries. Produce a concrete source candidate that can later be reviewed for main/product adoption without silently deleting product features.

**Architecture:** Merge the verified deployed backend's existing Git history into the existing Pi branch. Main b6f38a88 is an ancestor of deployed d25d8275, which adds four commits (VIP fair scheduling/model policy, deployment documentation, frontend refinements and genre/private-style behavior). The Pi branch split at99eae0f7. A merge into Pi preserves both histories and is source preparation only. Continue running the old closed server runtime and frozen input/profile without replacement.

**Evidence:** Current read-only collector72ae3911 is active; full3938offline passed/36deselected, exact4CI green. Three backend instances physically matched222tracked d25 files plus6separate package metadata files. Source reference17becf3b already matches those tracked bytes and retains the original expiry,50CNY and9unknown holds. Main/product adoption, business release/recovery and new paid pipeline are still separate root-goal requirements.

**Owner calls:** Prefer a real history-preserving merge over copying an entire tree or cherry-picking Pi files onto main: there are product changes in both branches and Git already merges many files correctly. Resolve conflicts by retaining guest/resource/model/VIP business rules plus explicit maintenance admission/checkpoint/provenance. Do not refactor modules, rewrite old receipts, relax schema/permissions/budget or modify source-profile/runtime pins as part of this integration.

## Files and conflict responsibilities

Read-only merge-tree preview at3b6eebd2 into d25d8275 reports14conflicts:

- scripts/ci-local.sh: retain independent test-service lifecycle and main contract/regression export, including Pi tests; never use production Compose resources.
- src/myink/config.py,db.py,models/__init__.py: retain both product settings/models/migrations and Pi maintenance/provenance schema; no live bootstrap.
- src/myink/api/routes_tasks.py,task_budget.py: guest/VIP quotas, ownership and model policy remain enforced; pause/maintenance admission must run before mutation and stay transaction-safe.
- src/myink/worker/amqp.py,consumer.py,enqueue.py,processor.py: fair membership queue selection and finite acknowledgements/recovery coexist with maintenance pause/checkpoint/claimed execution lifecycle. No duplicate dispatch or quota compensation.
- src/myink/workflow/nodes.py,runner.py: genre/private-style/main model/tool behavior and Pi run identity/checkpoint/failure semantics remain independent and intact.
- tests/test_multiprocess.py: retain real isolated process/queue assertions and maintenance tests, no delete/skip-to-green.
- web/vue/src/components/FeedbackWidget.regression.test.ts: preserve new frontend behavior assertions and genuine deterministic regressions; no unrelated UI redesign.

Auto-merged product files (api/main.py,cli.py,validation/l1.py,batch_graph.py,short_runner.py,tests/conftest.py and related tests) still need semantic reading, not only conflict-marker clearance. AuditReader remains stdlib-only; fees and model tools stay in host modules.

## Task1 — Freeze and integrate both source histories

- [ ] Check clean Pi worktree and pushed3b6eebd2; inspect deeper instructions. Fresh-read remote main/deployed commit references; stop source integration if the actual target changed and update plan first. Do not fetch/reset another checkout.
- [ ] Inventory both sides' tests and intended behaviors at the fixed14conflicts. Run relevant existing main/VIP tests on oldPi to establish missing-feature failures where practical; preserve outputs. Do not invent tests that merely mirror the merge.
- [ ] Merge exactd25 into codex/pi-autonomy-design using --no-commit --no-ff. Preserve MERGE_HEAD until successful verification/commit; no blanket ours/theirs resolution, force reset or whole-tree replacement.
- [ ] Resolve schema/admission/queue/workflow conflicts in dependency order above. Read both versions around each overlap; preserve guest/model/resource/VIP behavior, Pi ownership/maintenance semantics and existing tests. Capture any deliberate behavioral choice and why.
- [ ] Run focused schema, quotas/routes, membership scheduling, queue recovery, workflow and maintenance tests; add a narrow cross-feature regression only where existing tests cannot prove interaction. Tests first for any new behavior. No paid requests or live SQL.

## Task2 — Whole-source and integration verification

- [ ] Verify no unresolved/conflict markers, no dropped source/features, manifest/profile remain unchanged, model tools remain six with existing phase permissions. Compare merge against both parents; complete changed-path/line inventory.
- [ ] Run relevant Python tests then full python -m pytest tests/ -q and complete Pi offline gates; keep lab/live skips separate. Use the current venv and all required isolated services.
- [ ] Frontend lint/test/build and Go vet/test as affected by imported history. Inspect fixed myink-test service occupancy before scripts/ci-local.sh; never run it concurrently across worktrees. If an actual environment block exists, retain it and use exact remoteCI rather than pretending a skip is acceptance.
- [ ] Verify standalone -I-S-B audit reader imports no Pi/app/provider code; existing actual export and prior nextday linkage still validate without writing the server.

## Task3 — Reviewable source candidate and next release gate

- [ ] One fresh final source review against fixed3b6eebd2, with both parent functionality and cross-feature maintenance/queue semantics as focus. One author fixpass, no rereview; rerun checks affected by fixes.
- [ ] Commit the history-preserving merge and push Pi only under existing authorization. Check exact implementation4jobCI. Main, admin branch and product containers remain untouched.
- [ ] Dated MD/JSON records: both parent commits, complete range, preserved feature map, validation/failures/skips, reviewer findings/fix, no product release, no model calls, budget/legacy holds untouched. Update enhancement/admin handoff current status without overwriting historical version events.
- [ ] Prepare the next fixed product maintenance/release executor plan: actual pause/checkpoint/drain/resume, compatible PRE/POST backup+restore, canonical owner/generation/epoch/image binding, fresh checks/authorization and ownership-safe rollback. This merge alone grants no release permission. Ask for main/product approval only when the exact artifact and operation are concrete and independently validated.

## Review focus

1. A newly imported task/guest/VIP scheduling path bypasses Pi pause or changes quota compensation. Prove admission before mutation and maintenance-aware recovery in interaction tests.
2. A migration/model conflict loses a main column/model or overwrites old unknown provenance with current deployment identity. Verify additive bootstrap and null historical identity.
3. A worker acknowledgement/checkpoint ordering duplicates or loses a task under cancellation/maintenance. Exercise original process recovery plus the new scheduling path.
4. Context/tool/genre/private-style changes alter finished task results or leak private settings into audit. Preserve business tests, keep audit allowlist projection.
5. A merge brings current product history into the branch but is mistaken for main adoption/live release. Preserve closed runtime/config pins and no_release evidence; do not run production migration or image switch.

## Remaining root-goal coverage

This plan removes a concrete source integration prerequisite. It does not narrow the root objective to source checks: genuine paid autonomous development, final candidate review, explicitly authorized product adoption, actual business rollback and real nextday/24–48h validation remain required and active. Original ledger and fee policy are never regenerated by merge or test runs.
