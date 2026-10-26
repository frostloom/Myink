# Final integration repair wave

2026-10-25 · `codex/vue3-migration` · implementation stopped, awaiting independent re-review. No commit, push, merge, publication, service startup or subagent invocation.

## Confirmed failures and repairs

### P1: confirmed generation target must remain the submitted target

Re-ran `vue/src/review-final-integration.test.ts` before editing: **4/4 failed**, including both rewrite timing windows in final-review.md. Added adjacent tests before implementation: next/batch request snapshots across pending resource preflight and pending POST, disposal after an account-owned instance unmounts, renewal/owner/403/role boundaries, and current-token reads for all four retained detail routes. The expanded pre-repair run had **8 failed / 5 passed** for integration/access tests; the four detail-token cases were separately **4/4 failed**.

`GenerationPanel.vue` now captures project, chapter id/sequence, writing mode, trimmed instruction, batch size, preflight function and completion callback before any asynchronous work. Rewrite confirmation names the captured chapter. Its preflight, POST, task callback and notice use that same operation snapshot. Next-chapter and batch actions follow the same rule, including callback chapter/start/count after the UI changes. Batch request fields remain exactly the existing size/start contract; no new API payload is introduced.

Project request invalidation now watches the scalar project id synchronously. Every continuation still requires the captured request version and project identity to match; scope disposal runs the watch cleanup. Existing old-project preflight, late-response and new-project busy-state tests remain passing. The added unmount test confirms a disposed account-owned instance cannot report a rewrite completion. Account ownership remains enforced by the existing caller instance key; no new account API or global ownership mechanism was added.

### P2: same-account token renewal must preserve administrator edits

`AdminPage.vue` now keys its protected subtree by **userId + detail route path**, without token. The forbidden latch resets only on owner change. Same-owner renewal therefore retains model/resource editing instances; owner changes and detail path changes still recreate descendants, role/roleVerified checks still remove protected content, and a 403 forbidden decision cannot be cleared merely by renewing a token.

AdminConsole, ProjectDetailPage, TaskDetailPage, RunDetailPage and UserDetailPage keep the injected adminContext object instead of destructuring its token getter. Their loaders and render props read `adminContext.token` at the point of use. Retained views therefore use renewed credentials without remounting. Child resource loaders continue tracking reactive token reads and cancelling superseded reads. Platform API calls that already obtain the current token dynamically were left unchanged.

### Additional authorized original-parity regression: manual stream following

The master supplied a fifth original StreamingChapterView parity case. Reproduced **1 failed / 4 passed**: after scrolling up, a new delta reset following and moved scrollTop from 120 to 900. `StreamingChapterView.vue` now watches separate scalar chapterSeq/artifactId sources, rather than a getter returning a new array whenever an artifact object changes. New text in the same artifact preserves manual pause; the existing “回到最新” action still resumes following. An onMounted step scrolls initial existing body content to the end. Re-ran the supplied parity file: **5/5 passed**.

## Files changed in this wave

- `web/vue/src/components/GenerationPanel.vue`
- `web/vue/src/components/StreamingChapterView.vue` (explicit later authorization)
- `web/vue/src/pages/AdminPage.vue`
- `web/vue/src/pages/admin/{AdminConsole,ProjectDetail,TaskDetail,RunDetail,UserDetail}.ts`
- `web/vue/src/pages/admin/access.test.ts`
- `web/vue/src/pages/admin/renewed-token.test.ts`
- `web/vue/src/review-final-integration.test.ts`
- This report.

No App, router, main, creation, API contract, other workspace component or unrelated source was changed.

## Final verification

Ran the following combined affected suite after all repairs:

`npm run test:vue -- vue/src/pages/admin vue/src/components/GenerationPanel.test.ts vue/src/components/WorkspaceLifecycle.test.ts vue/src/pages/WorkspacePage.test.ts vue/src/pages/WorkspacePage.live.test.ts vue/src/review-final-integration.test.ts vue/src/review-admin-creation-regressions.test.ts vue/src/App.test.ts vue/src/session.auth.test.ts vue/src/components/StreamingChapterView.parity.test.ts`

Result: **27 files / 236 tests passed**, no skips, exit 0. This includes the original administrator/affected generation suites, the original four final integration regressions, the added adjacent tests, previous administrator/creation review regressions and the supplied five stream parity behaviors.

- `npm run typecheck:vue`: **exit 0**, complete project Vue source/tests and node config.
- ESLint with the Vue project config over GenerationPanel.vue, StreamingChapterView.vue, AdminPage.vue, the full admin directory and review-final-integration.test.ts: **exit 0, no diagnostics**.
- oxlint over the same assigned scope: **exit 0, no diagnostics**.

The initial reproduction command included incorrect root-prefixed read paths while running from web; those reads failed without modifying files. The test command itself used the correct web-relative test path and produced the recorded four true failures. Only actual test executions above are counted.

Independent re-review, rebuilt artifact/provenance and any global browser/backend checks remain the master integration gates. The master's separately reported real isolated API/browser and same-origin recovery results were not rerun or claimed as this worker's results. This wave has not published or changed the React production entry. Stopped writing.
