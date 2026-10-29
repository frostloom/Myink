# Workspace migration implementation report

2026-10-25 22:58 CST. DONE for implementation scope; independent review and master browser acceptance remain pending. No commit/push/merge/deployment.

## Scope

Native Vue Composition API with Vue `h()` rendering, retaining existing TS/CSS/API/storage contracts:
- `web/vue/src/pages/WorkspacePage.vue`
- components `GenerationPanel`, `ChapterPlanPanel` (including local PlanEditor), `ChapterList`, `CandidatePanel`, `AuditPanel`, `LessonsPanel`, `TaskTimeline`, `TaskHistory`, `TaskBudgetPanel`, `RingProgress`, `RunNodeCard`.
- 8 test files and test-only native Vue mounting/router helpers (`workspaceTestUtils.ts`, `workspaceRouterTestUtils.ts`). The test helper accepts VNodes and mounts real Vue components / Vue Router. It has no React import or runtime.
- Existing root-owned task/draft composables, editors, streaming, structured fields, rail and admin-owned ResourceUpdates are imported, not overwritten.

All original WorkspacePage (38), WorkspacePage.live (1), GenerationPanel/ChapterPlanPanel/TaskBudgetPanel/ReviewFlow/RevisionScope component behavior tests (46) have direct Vue equivalents, plus 2 lifecycle regressions = 87 tests. Original tests remain untouched.

## Behaviors retained

Long/short pipeline distinction; chapter selection/deep link; project changes invalidate old replies; optimistic pending chapter plus 40x250ms materialization recovery; persisted activeWrite recovery without duplicate generation; task snapshot/flow by chapter and attempt; Plan until actual Write artifact; manual stage choice not stolen by later deltas; short history readiness before auto intent, adopt existing task before POST, lost enqueue response recovery, paused/failed server resume; missing chapters/degraded review/length warnings; short-only progress ring and whole-story runs; right-panel preference while content stays mounted; Markdown export/book delete; generation/rewrite/batch/instructions; plan edit/confirm/cancel/history; candidate confirm/reject/revise/resume/retry and batch chapter ownership; budget idempotent operation ids and uncertain-publication repair; full audit and task summaries.

## RED → GREEN evidence

- First component tests failed because native Vue modules did not exist; after conversion and native event/lifecycle fixes, original 46 passed.
- Workspace first run 34/39 passed; missing intent/warning and stage navigation failures exposed test router URL/state handling and Vue same-path replace semantics. After correcting real navigation parsing and state consumption, 39/39 passed.
- `WorkspaceLifecycle.test.ts`: ring width expected 148px, actual empty; initial dialog focus expected close button, actual body. Both reproduced RED and passed after CSS px and onMounted focus fixes.
- Vue state merge preserves omitted history fields. Intent clearing now explicitly sets beginShortWriting undefined, forces same-path replacement, and updates local handover before navigation to prevent repeated watcher navigation. Warning remains. Configuration-first warning-only entry does not start generation.
- PlanEditor immediate post-flush watch runs before initial refs; onMounted autoGrow restores initial box sizing (original test RED → GREEN).

## Verification receipts

Commands run in migration worktree/web, 2026-10-25 around 22:55–22:58:
- `npm run test:vue --` with 8 owned files: exit 0, **8 files / 87 tests passed**, `/tmp/ws-all-tests.log`.
- `npm run typecheck:vue`: exit 0, full Vue and config strict checks, `/tmp/ws-types.log`.
- Scoped ESLint: exit 0, no errors; only 2 existing-layout local multiple-component warnings in ChapterPlanPanel, `/tmp/ws-lint.log`.
- Scoped oxlint: exit 0, no output after optional-chain cleanup, `/tmp/ws-oxlint.log`.
- Final narrow budget follow-up after cleanup: exit 0, 6 tests, `/tmp/ws-budget-final.log`.
- Scope search has no React imports/hooks/portal runtime.

No browser fixture, real backend, worker, Docker integration or media browser verification was run by this worker; master integration owns those gates. User/account switches are keyed by the master shell. Master must independently review all untracked Vue files, not only git diff HEAD.

## Independent review fix round 1 (2026-10-25 23:15 CST)

Read `workspace-integration-review.md` and independently re-ran both reviewer reproduction files: **3/3 failed RED** (`/tmp/ws-review-red.log`). Confirmed all three findings.

- ChapterList initial empty branch now runs inside the Vue render function; later asynchronous chapters become navigable.
- Manual plan draft initialization now uses a true Vue multi-source watch over scalar attempt and editability. Equivalent same-attempt snapshot objects preserve unsaved edits; actual new attempt/status retains prior initialization behavior.
- Export captures its project/account/chapter snapshot and operation version before awaiting. Project/account changes invalidate the export, immediately free the new page's export control, and stale success/error/finally cannot request subsequent chapters, download a stale result, set a new page error, or clear a new export busy state. Disposal invalidates the operation as well. Added two direct resolve/reject cross-project export regressions.

Verification after fixes:
- Reviewer tests: **3/3 GREEN**, `/tmp/ws-review-green.log`.
- Original migrated 87 + reviewer3 + additional export2: **11 files / 92 tests passed**, exit0, `/tmp/ws-review-all.log`.
- Full `npm run typecheck:vue`: exit0, `/tmp/ws-review-types.log`.
- Scoped ESLint: exit0, only the same two ChapterPlanPanel internal-component layout warnings, `/tmp/ws-review-lint.log`.
- Scoped oxlint: exit0 with no output, `/tmp/ws-review-oxlint.log`.

Stopped writing for scoped independent re-review. No commits, pushes or publishing.
