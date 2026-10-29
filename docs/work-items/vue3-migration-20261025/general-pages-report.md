# Vue Task 1 — Navigation, account, environment and project read pages

Date: 2026-10-25. Branch: `codex/vue3-migration`. Implementation is ready for independent review; integration and whole-app completion remain with root. No commit, push, merge, deployment, route/App changes or backend modifications were made by this worker.

## Source behavior and Vue ownership

| Original React source | Vue implementation | Preserved behavior / verification |
| --- | --- | --- |
| components/ProjectRail.tsx and tests | components/ProjectRail.vue / ProjectRail.test.ts | Section inferred from path or current book, legacy form=long, draft exclusion, global both-form listing, short-book ledger hiding, account/global navigation, verified administrator gating, authenticated mobile feedback DOM/event, guest login, logout. AdminRail shares the test file. |
| components/AdminRail.tsx | components/AdminRail.vue | All operations/resource/account links, query-tab/detail-owner aria-current, mobile expansion/collapse on link, auth logout; 4 combined rail tests. |
| pages/AccountPage.tsx and tests | pages/AccountPage.vue / AccountPage.test.ts; session.ts / session.account.test.ts | Account display/tier/role, password policy/confirmation/current password validation, password API and revocation, administrator rail, verified-only MFA status/enrollment/secret+URI/code confirmation/disable, rejected-code retry, explicit login navigation. Sensitive input state is memory-only and cleared on account transition/disposal/revocation. Added generation and storage-owner checks for late MFA replies; session password mutation does not clear a newer stored account. 6 page + 3 scope tests. |
| pages/EnvironmentPage.tsx and all 12 original test cases | pages/EnvironmentPage.vue / EnvironmentPage.test.ts | Full original suite ported to Vue: collapsed advanced controls and remount reset, published models only, no connection credentials/MCP UI, model/thinking dirty leaves including explicit false, rankings/budget validation, overridden-field metadata, per-leaf reset, server effective values, dirty unrelated/sibling fields retained, failed mutation drafts kept, failed initial-load controls disabled and retry. All 12 pass. Added page generation guard for account/load lifetime. |
| components/ConnectionNotices.tsx and tests | components/ConnectionNotices.vue / ConnectionNotices.test.ts | Body Teleport, separate items/tone alert/status, scroll-to-top on changed newest notice, no focus stealing, Escape/click dismiss and connected focus return. Vue contract: exported ConnectionNotice type, items prop, dismiss(id) event. |
| pages/SettingsPage.tsx and tests | pages/SettingsPage.vue / SettingsPage.test.ts | Read-only historical managed genre snapshot, badge/version, before-writing instruction and planWarning history state, original resource picker, target words 500–20000 and fallback 3000, successful save+reload, A→B load success/failure and old-save-failure race isolation. ResourcePicker implementation belongs to admin worker; test stubs that UI to isolate settings races. 4 tests pass once shared file exists. |
| pages/LorePage.tsx and tests | pages/LorePage.vue / LorePage.test.ts | All original sections preserved: outline objective/volumes/stage folds/goal/KRs/end events; lazy once-per-character history including invalidated rows; base attrs/current state; chapter memory sorted descending; events with participants; WorldGraph; item/skill/location groups; foreshadow lifecycle ordering and resolved chapters; world realm arrows/rules, constraints, factions and locations. Original 2 behavior tests plus complete-sections fixture pass. Added project generation guard. |
| components/WorldGraph.tsx | components/WorldGraph.vue / WorldGraph.test.ts | Same shared graph converter/cap and SVG ECharts registrations, resize observer, empty/error/clipping display, switch-book stale suppression and observer/chart disposal. 2 lifecycle/data tests pass. |
| pages/AuditPage.tsx | pages/AuditPage.vue / AuditPage.test.ts | Report loading/empty/list metadata/status/window/volume counts, detail expand/collapse, failure reason, manual trigger opening current newest response, 400 no-chapter explanation, 502 failed-report refresh, findings chapter route. Added project/detail version guards. 5 tests pass. |
| components/FindingsList.tsx / StatusBadge.tsx | components/FindingsList.vue / StatusBadge.vue / FindingsList.test.ts | Severity ordering, translated badges/type/scope/source, quoted evidence, optional chapter navigation, suggestions and empty state. 2 tests pass. Badge types support existing component contract. |

## Test-first evidence

For each page/component batch, wrote behavior tests, supplied only empty Vue template where module import needed to resolve, and ran tests to observe actual missing UI/method assertions before implementation. Recorded RED runs included rails 4/4, connection notices 1/1, session account methods 3/3, account page 4/4, environment 12/12, settings 4/4, graph/findings 4/4, lore 3/3, audit 5/5. Later account tests extended rejected-code and disable parity. Corrected a test expectation from “严重” to the existing shared critical label “致命”; corrected React synchronous fireEvent assumptions by awaiting Vue DOM ticks. No original React tests were modified.

## Verification

- Latest targeted command: `npm run test:vue -- vue/src/components/ProjectRail.test.ts vue/src/components/ConnectionNotices.test.ts vue/src/components/WorldGraph.test.ts vue/src/components/FindingsList.test.ts vue/src/pages/AccountPage.test.ts vue/src/pages/EnvironmentPage.test.ts vue/src/pages/SettingsPage.test.ts vue/src/pages/LorePage.test.ts vue/src/pages/AuditPage.test.ts vue/src/session.account.test.ts` — **10 files / 42 tests passed**, exit 0 (22:26:32 local).
- Scoped ESLint over all owned SFCs/tests/session files — exit 0, no warnings after Vue template autofix. New SFC scripts formatted with TypeScript printer for review readability.
- Scoped oxlint over the same owned paths — exit 0.
- Whole `npm run test:vue` at 22:24:30 — **31 suites passed, 1 suite failed; 211 tests passed**. Failure was `FeedbackWidget.regression.test.ts` transform error (`await` in non-async callbacks); this file belongs to parallel theme worker and was still being edited. This is not reported as a whole-suite pass.
- Whole `npm run typecheck:vue` at 22:25 — failed on concurrent work: ChapterViews fixture, FeedbackWidget test query option, FormFields test generics, admin test imports/fireEvent signatures and Resource* wrapper multiple-default-export errors. No errors remained in this worker's owned files. Root handled shared pure badge type imports. Whole check needs rerun after parallel tasks finish.
- Browser/real-service integration and whole-app build not executed by this worker. Routes are deliberately left to root; Vue account/settings/lore/audit integration is not asserted by isolated component tests.

## Explicit limits for review

Automated parity is strongest for the full 12-case original environment suite and original settings race cases. Additional production paths retained by code inspection but not exhaustively tested individually include every password validation/error permutation, MFA status/enroll network failure, graph clipping/error variants, every outline empty branch, notice click/disconnected-focus branch, and audit load/detail failure permutations. Mobile appearance, real chart geometry, real backend account revocation and multi-tab storage scheduling still require integrated/browser verification. No tests were skipped and no real services were started.

## Interfaces

- ProjectRail: `projects: Project[]`, optional `onLogout`; emits `logout`; fallback uses auth logout. AdminRail same logout contract.
- ConnectionNotices: `ConnectionNotice` type; items prop; dismiss event.
- WorldGraph: projectId prop. FindingsList: findings + optional onNavigateChapter callback. StatusBadge: tone + slot.
- Auth scope additions: `endSession(message): void`, `changePassword(currentPassword,newPassword): Promise<void>`; existing authentication lifecycle retained.
- Settings expects WritingResourcePicker.vue default component with projectId prop.

## Independent review repair — Settings history state (P2)

Independent review found that a React-style standalone `:state` prop on Vue RouterLink did not enter router history, so the plan warning disappeared on return to the workspace. Computed values read only non-reactive history state and could retain the prior project's configure/warning values when the settings instance was reused.

Added two real navigation regressions before repair: clicking the return link must populate `router.options.history.state.planWarning`; changing A settings to B settings in the same instance must refresh the configure message and return B's warning. RED at 22:31:07 showed both failures: missing warning in destination history and A's configure banner remaining on B. Updated the RouterLink destination to `{ path, state: { planWarning } }` and mirrored history state in a ref refreshed from reactive `route.fullPath` changes. Resource-first configuration still returns to a manual writing start; no `beginShortWriting` state is introduced.

GREEN at 22:31:36: `npm run test:vue -- vue/src/pages/SettingsPage.test.ts` — **6 tests passed**, exit 0. Scoped ESLint and oxlint for SettingsPage.vue/test both exit 0 without warnings. Only SettingsPage.vue, SettingsPage.test.ts and this report changed in this repair. Task1 now has 44 tests including the two new regressions; the full 44-case command has not been rerun during this narrow review repair. Stopped writing pending review.
