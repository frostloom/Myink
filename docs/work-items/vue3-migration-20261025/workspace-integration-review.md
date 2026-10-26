# Workspace and global integration independent review

2026-10-25, review of the current uncommitted migration worktree. No production files edited. Tests added only. No commits/push/merge/deployment. Hindsight was unavailable and skipped.

## Verdict

Spec compliance: **changes required**, because the first asynchronous chapter list does not render, user-edited manual plans can be overwritten by an equivalent snapshot, and an in-flight export can mix the new project id with old chapter ids. Task quality: **changes required** for the same three confirmed lifecycle/reactivity regressions. The original 87 migrated tests all pass, but they do not exercise these production-component boundaries.

## Confirmed findings

### P1 — ChapterList returns a VNode from setup before asynchronous chapters arrive

`web/vue/src/components/ChapterList.vue:25–26`.

Workspace always starts with `chapters=[]`. The early setup branch returns a VNode object rather than a render function. Vue warns that setup must not return VNodes directly, registers no renderer, and the component stays completely blank when the API later supplies chapters. Existing long works therefore have no chapter navigation after loading. This is the cause of the real browser workflow `/tmp/myink-vue-full-browser-2259/receipt.json` stopping at the chapter button after its first seven writing/review checks; it is a production defect, not a whitespace selector issue.

Actual RED reproduction: `web/vue/src/review-workspace-regressions.test.ts`, first test renders with `[]`, rerenders with chapter1/雨夜, and cannot find any button/accessibility role. Move the empty rendering branch inside the returned renderer, preserving the reactive props.

### P2 — An equivalent same-attempt snapshot overwrites manual plan edits

`web/vue/src/components/ChapterPlanPanel.vue:152–158`.

The source getter returns a fresh array containing current attempt and editability. When new `runs` arrive with the same current attempt, `current` recomputes, the watch getter runs, and Vue treats the newly returned array as a changed value. It then clones the server plan into `draft`, erasing unsubmitted manual changes. The React effect used scalar dependency comparison and did not reset on the same attempt.

Actual RED reproduction: `review-workspace-regressions.test.ts`, second test edits the goal to `尚未提交的目标`, replaces runs with an equivalent cloned snapshot of attempt1, and observes the field revert to `原目标`. Use a multi-source watch or compare the scalar identity before initializing the draft; retain initialization for a genuinely new attempt/status.

### P2 — Markdown export reads a reactive new project id after awaiting an old chapter

`web/vue/src/pages/WorkspacePage.vue:769–772`.

The export iterates the original chapter array but evaluates `projectId.value` separately for each request. Start export of A and navigate to B while the first chapter is loading; the next request becomes `getChapter('b','a2')`. This causes an incorrect project/chapter request and an export failure on B (or potentially mixed content if the server permits lookup), unlike the original React callback that captured its original project id.

Actual RED reproduction: `web/vue/src/review-workspace-export.test.ts` starts A export, holds a1 response, pushes `/projects/b`, releases a1, and sees the second request `('b','a2')`. Capture project id and chapter snapshot for the operation, or cancel it on ownership change. Also prevent stale completion/error from modifying the new page.

## Scope and passing checks

Compared Workspace and generation/plan/list/candidate/audit/lessons/task/history/budget/ring/run components with their original React equivalents and examined App/router/main, GuestShell, RouteBoundary, AppVersionGuard and ProjectsPage. Initial-login deep-link startup had already been fixed by the root before this review. All routes are connected, guest project mounting is blocked, verified-role admin routing remains enforced, account subtree is keyed by user id, and safe update notification does not auto-refresh editing state. No additional confirmed global blocker found in this review.

Re-ran all eight implementation-owned Workspace/component test files: **87/87 passed**, exit0, 23:04:34 CST. The two added review test files contain **3 actual failing reproductions** above. Their failures must be fixed, not skipped. Real backend/model/queue/RLS and complete browser acceptance were not run by this reviewer; root owns those gates.

## Scoped re-review — fix round 1

All three findings are **addressed**. Read the changed production areas and adjacent operation ownership logic, then executed the reviewer reproduction files plus the author's new export lifecycle regressions.

- ChapterList now always returns a render function, with the empty-state branch evaluated inside it. Asynchronous empty→populated props render navigable chapters.
- ChapterPlanPanel now uses a genuine multi-source watch of scalar attempt and computed editability. Equivalent same-attempt snapshots retain manual draft edits while a changed attempt/status still reinitializes through the existing behavior.
- Export snapshots project/account/chapter ids and validates a version counter before/after each awaited chapter. Synchronous ownership watchers invalidate the old operation and free the new page's control. Disposal invalidates as well. Stale resolve/reject/finally cannot fetch the next chapter, download a prior book, write a new-page error, or clear another export's busy state.

Verification: `npm run test:vue -- vue/src/review-workspace-regressions.test.ts vue/src/review-workspace-export.test.ts vue/src/components/WorkspaceExportLifecycle.test.ts` — **3 files / 5 tests passed**, exit0, run at23:10:03 CST. No production edits by reviewer; no newly introduced adjacent defect found. Scoped spec and quality verdict: **approved**. This is a scoped repair verification, not a fresh whole-app/backend/browser acceptance claim. Stopped writing.
