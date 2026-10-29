# Main Vue Cutover Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans inline, TDD and one independent final review. User authorized fixing main-integration findings; no per-stage confirmation.

**Goal:** Close both P2 findings and make default dev/build/lint/test/Docker select Vue with explicit React rollback.
**Architecture:** Keep existing output paths Vue dist-vue / React dist to preserve verified bundles and rollback. Default Vite re-exports Vue config, old React config becomes explicit. Shared TS tests and Vue tests run by default. Use existing synthetic browser harnesses across three real browser engines.
**Tech Stack:** Python stdlib, Vue3/TS/Vite/Vitest, Playwright Chromium/Firefox/WebKit, Docker.
**Spec:** docs/work-items/vue3-migration-20261025/brief.md:174-176 and main-integration-review.md; latest user fixes authorization.

## Global Constraints
- Existing dirty codex/vue3-migration worktree; protect all prior work. No commit/push/merge/deploy, Pi excluded.
- Never report skip/unavailable engine as passed. No production database/API or paid models.
- No new UI design or unrelated refactor; actual application Vue bytes should stay identical if only tooling changes.

## Review Focus
- Docker create partial failure and nonexistent-container cleanup do not leak or report success.
- Default main command actually loads Vue; React commands must keep standalone React output.
- Shared TS tests must remain in default gate while excluding legacy React UI tests.
- Firefox/WebKit actual download and engine-supported encoded video decode/persist must be asserted, not just DOM mount.
- Tablet768 navigation/controls must be usable, not just body-width check.

### Task 1: Asset capture cleanup
- [x] Add stdlib executable fakeDocker regression for partial-create failure, success and nonexistent-container failure; RED before implementation.
- [x] Register cleanup responsibility before create, preserve original failure, tolerate confirmed absence but fail real cleanup errors; regression GREEN.

### Task 2: Default Vue cutover and rollback
- [x] Pin baseline main build/runtime is React; default assertions RED.
- [x] Add explicit vite.react.config, shared Vitest config; make main scripts Vue/shared by default and retain dev/build/lint/test/preview:react.
- [x] Set Docker/Compose defaultVue, explicitreact branch invokes build:react; CI/local checks defaultVue plus explicitReact, browser matrix gates.
- [x] Run default lint/test/build, React lint/test/build and default Vite runtime proof, no React modules in active Vue graph.

### Task 3: Browser acceptance and final gate
- [x] Enable engine parameter in existing browser harnesses; preserve API/SSE assertions. Add768 usable navigation and actual Markdown download; use supported recorded video MIME per engine, no fake decode.
- [x] Run all3 engines serially and save receipts/screenshots for edit/media/download/router +390/768/1440. Investigate/fix actual failures; no skipped critical cases.
- [x] Rebuild defaultVue and explicitReact images; verify labels/runtime/legacy-assets and cleanup. Existing API/backend1966 unchanged, no need unrelated service reruns.
- [x] Final independent review; update reports/provenance and mark both P2 closed only with evidence.

## Ledger
Ruling: Retain dist-vue/dist rather than move directories — default framework is determined by Vite/scripts/selector, keeping established paths avoids unnecessary application/artifact changes; cost: readers must use documented output paths until the separate stable-cleanup phase.

Task1 complete: helper4 cases first2RED/2GREEN then4GREEN, no actualDocker in failure injection. Task2: real defaultVite root RED→VueGREEN; explicitReact config+merge5 testsGREEN; default lint,shared191+Vue564,build exit0; React599/lint/build exit0; rootVue solution vue-tsc -b exit0.
Task3 browser matrix final: all3 engines each28smoke+10workspace+26readiness, all9groupsGREEN; JS remainsLHE8ace... unchanged from previously realTLS11-tested artifact.
Ruling: Use fresh ordinary temporary profiles for all engines — independent WebKit probe proved ephemeral contexts reject Blob writes while ordinary profiles store File/Blob/bytes correctly; cost: private-mode durable media is not claimed.
Ruling: Correct malformed PNG test CRC and emit seeded terminal statuses, await state/network completion before testing refresh — original simultaneous EOF/hard navigation yielded WebKit native fetch errors in bothReact/Vue; keep middle-stream disconnect/cursor/dedup and all page-error gates, no filters. Extra HTTP adapter experiment did not help and was removed.
Ruling: User denies automaticGit publication; no per-task commits or commit-range-only review, final review must inspect workingtree/untracked files. Cost: candidate remains local until separately authorized commit/merge.

Task3 images: default selector omitted → nativeVue LHE, explicitreact → nativeReact BDxd; each7 checks and cleanupErrors=[]; receipts main-cutover-evidence. Source/application SHA checked identical. Final reviewer dispatched once, pending.

Final review: fresh independent reviewer noImportant/Critical; independently helper4/4; reviewed actual dirty/untracked source and all9 browser receipts. Final: minor (deferred): browser matrix hard timeout may leave synthetic temporary profile directory; normal-path cleanup verified.
All tasks complete, no commit/merge/deploy. Keep worktree/evidence because uncommitted user work must be preserved.
