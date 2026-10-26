# Administrator and creation migration independent review

2026-10-25. Reviewed the native Vue administrator/resource and long/short creation scope against the existing React implementations, behavior tests and migration brief. No production source was edited. No commits, services, model calls or deployment.

## Spec compliance: changes required

1. **P2 — Trend charts never initialize on first display.** `web/vue/src/pages/admin/AdminTrends.ts:26` uses an immediate watch in setup; its first execution reaches `if (!ref.value) return` before the DOM ref is assigned. DOM mount does not change either watched source (`props.points`, `props.series`), so initialization is never rerun. Three hosts with accessible image roles appear but the count/token/cost charts are blank. Original React effect ran after DOM commit. Actual reproduction in `web/vue/src/review-admin-creation-regressions.test.ts`: after data loads and all chart hosts mount, `echarts.init` expected 3, actual 0. Initialize in mounted/ref-aware lifecycle and retain watch update/dispose behavior.

2. **P2 — Every administrator detail return link has empty text.** `web/vue/src/pages/admin/shared.ts:84` passes `children: ['返回']` as a RouterLink prop and supplies an empty children array. Vue RouterLink reads its default slot, so output is `<a href="/admin?tab=tasks" ...></a>` with no accessible name, and Vue warns while assigning the DOM's readonly children property. User/project/task/run detail views all use this helper. Original links displayed “返回”. Actual reproduction: `getByRole('link',{name:'返回'})` fails; accessible roles show a link named empty string. Supply a default slot and keep the tab URL.

## Task quality: changes required

3. **P3 — React numeric CSS lengths remain in administrator render functions.** At `web/vue/src/pages/admin/RolePromptFields.ts:83`, `gap: 8` and `marginTop: 24` no longer become pixels. Vue does not apply React's numeric-length conversion; browser discards the invalid margin. Similar nonzero numeric lengths exist in this file (lines 95/98/99), `WritingResources.ts` (32px section spacing), and `WritingResourcePicker.ts` (24px group spacing). Actual reproduction: supplement label `style.marginTop` expected `24px`, actual empty string. Convert nonzero length-valued numbers to explicit units, preserving unitless styles such as fontWeight/minWidth zero/border zero. This affects visual parity rather than data integrity.

## Confirmed coverage and limits

- Ran `npm run test:vue -- vue/src/pages/admin vue/src/pages/NewProjectPage.test.ts vue/src/pages/ShortCreationPage.test.ts vue/src/components/RankingsPanel.test.ts`: **20 files / 176 tests passed**, exit 0, no skips.
- Added `web/vue/src/review-admin-creation-regressions.test.ts`, ran it: **3 tests failed**, each failure is an independently confirmed issue above, not an environment blocker. These tests intentionally remain RED for the implementation worker to repair.
- Inspected verified-role gate/403 clearing, route-ID recreation in AdminPage, asynchronous resource grouping, role-template loading, writable/read-only boundaries, resource generation/revision/target_generation payloads, overridden selection protection, draft/history/preview handling, original creation request id storage, draft restore races, long form editing and confirmation, short input/IME/pending message/new-account lifecycle, modal focus, two navigation intents and scan-rankings lifecycle.
- No additional confirmed creation defects found in the reviewed scope. Existing creation64 tests and administrator112 tests were independently reproduced as GREEN. This is not a proof against all possible runtime defects.
- No real browser chart drawing/geometry, real backend role revocation, queue/worker integration or full global regression was run by this reviewer. Parent integration gates still apply.

Implementation status: do not accept scope until issues are repaired and these reproductions are GREEN. Stopped writing.

## Scoped re-review — 2026-10-25 23:06

**All three findings addressed; scoped specification and quality review approved.**

- TrendChart watch sources now include the actual DOM host ref, so the first ref assignment schedules initialization. Cleanup still runs for each source change and unmount, disconnecting ResizeObserver, removing window resize and disposing ECharts. The repaired regression verifies initial three chart instances and one disposal per chart on unmount.
- DetailPage now supplies the return label through the Vue RouterLink default slot and preserves the backTab URL. The accessible link regression passes without the earlier readonly children warning.
- RolePromptFields, WritingResources and WritingResourcePicker use explicit px strings for the identified nonzero spacing lengths; unitless fontWeight and legal zeros remain unchanged. Supplement margin/gap, template textarea and fixed-contract details spacing are covered by the repaired regression.
- Independently reran `npm run test:vue -- vue/src/review-admin-creation-regressions.test.ts`: **1 file / 3 tests passed**, exit 0, no skips (23:06:35).

No production changes or expanded review scope in this re-review. Global integration and real-service/browser limitations remain the parent task's gates. Stopped writing.
