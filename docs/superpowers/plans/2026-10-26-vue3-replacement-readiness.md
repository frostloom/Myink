# Vue Replacement Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with TDD, independent review and verification-before-completion. User requests continuous testing/fixing until replacement ready; no per-stage approval.

**Goal:** Produce a verified Vue candidate suitable to replace existing React while preserving all existing behavior and data, with no open confirmed product defects in the acceptance matrix.
**Architecture:** Preserve single-lock dual builds and shared backend/protocol/CSS. Run deterministic model endpoint through actual API/queue/worker in dedicated ephemeral infrastructure; exercise actual built Vue with real browser and backend. Retain React for rollback. No production service/data changes.
**Tech Stack:** Vue3/TS/Vitest/Playwright, Python API+worker, PostgreSQL/Redis/RabbitMQ, local model HTTP fixture, Caddy.
**Spec:** docs/work-items/vue3-migration-20261025/brief.md, latest user instruction 2026-10-26 and existing coverage reports.

## Global Constraints

- Existing codex/vue3-migration worktree; preserve all uncommitted work. Pi excluded.
- No commit/push/merge/production deploy or shared data mutations. Actual replacement remains separate explicit authorization.
- Only one product implementer at a time; other parallel tasks own disjoint test scripts/reports and isolated runtime resources.
- New failures must be reproduced and fixed, not skipped or weakened. Tests bind a concrete built asset identity.
- Do not run fixed myink-test stack concurrently; use dedicated unique project/network/ports/DB/queues.
- No paid/external model calls or secrets in outputs. Local model fixture proves transport/worker behavior, not creative model quality.

## Review Focus

Password mutation across renewal vs new account/new login; stale initial history vs newer task; long/short resume/dedup/revision/resource gates; feedback/attachment/role changes; long text/IME/scroll/media cleanup; old-client assets and same-origin rollback.

### Task 1: Close current confirmed defects
- [x] Reproduce review-second-session.test.ts (2 RED) and pages/review-second-spec-history.test.ts (1 RED).
- [x] Fix session changePassword same-owner revalidation without clearing different owner or later valid login. Add boundary tests.
- [x] Fix initial history/loadChapters auto-selection ownership with taskStartVersion and project/account/disposal guards; test late history after new task, initial existing task recovery and switch/unmount.
- [x] Run affected suites, full Vue checks and independent scoped review; fix all confirmed findings.

### Task 2: Real isolated full-chain acceptance
- [x] Establish dedicated resources and actual API/worker/Caddy with explicit disabled external provider keys. Preserve old runtime stacks.
- [x] Controlled OpenAI-compatible endpoint drives actual model-client HTTP calls, queue admission, worker consumption, DB/SSE persistence; complete long creation/plan/write/review/candidate/rewrite/history and short creation/generation/resources-first/manual start/recovery where applicable.
- [x] Real authentication/MFA/account revocation/cross-account boundaries, settings/resources409, administrator operations and feedback attachment paths.
- [x] Actual Caddy HTTP/TLS-local proxy/SSE/cache/deep-link and same-origin Vue↔React session/draft/theme/task recovery rehearsal. Clearly distinguish local trusted test CA from production certificate issuance.
- [x] Full relevant Python regression (prefer full tests suite with dedicated infrastructure), no false SKIP acceptance. Record fixture/model worker limitations precisely.
- [x] On final stable build re-run acceptance and clean only created resources.

### Task 3: Browser interaction and long-content acceptance
- [x] Audit coverage against original 72 test-file inventory and all routes; fill missing meaningful behavior checks.
- [x] Actual Chromium large chapter/SSE/replay/input/scroll/save409 and IME composition; compare React and Vue on same deterministic data. Measure latency/heap/overflow, not a generic performance promise.
- [x] Browser reduced motion/background upload/readback/video lifecycle, feedback draft/file handling, desktop+390px navigation; fix actual failures through the product owner.
- [x] Preserve executable regression entry points and scoped evidence; no claim real model/backend when synthetic.

### Task 4: Final readiness gate
- [x] Resolve npm audit findings via Vite8.2.4/Vitest4.1.12 patch-only updates; audit must report zero known findings and both frontend suites/builds must re-pass.
- [x] Prepare an explicit React/Vue Caddy build selector (default React), provenance label and rollback command; build/inspect both image variants without running production services. Exclude candidate output from Docker context and align supported Node builder with tested/CI runtime.
- [x] React and Vue lint/test/types/build, original+expanded synthetic browser and final real-chain runs on fixed identity; CI entry points and YAML valid.
- [x] Final independent spec/quality review after fixes; no open confirmed blockers or unverified replacement-critical behavior hidden as passed.
- [x] Update coverage, provenance and release/rollback runbook with exact executed scope, known warnings, external operational checks and cleanup evidence.
- [x] Deliver readiness verdict for candidate. Do not perform production switch without separate authorization.

## Acceptance rulings

- Production DNS/certificate issuance and actual deployment remain authorization-bound operations. Testing unchanged TLS proxy behavior with a dedicated local CA is the pre-switch technical gate; no production certificate claim.
- Real paid model output quality is not a frontend replacement regression gate when backend/model code is unchanged. Full transport/queue/worker/persistence/SSE must still run against deterministic local model responses, not mocked API endpoints.
- "Everything" means the explicit behavior/route/operational matrix plus all defects actually discovered; it is not a claim of exhaustive proof of absence of all possible bugs.

## Latest checkpoint

2026-10-26: frozenDdkQzNNW follows two native-change/blur fixes, independently reviewed; completeVue76/561, React72/599, finalaudit0, type/build/lintGREEN. Cyxw A/B24checks remains explicitly older-snapshot evidence. FinalrealTLSbrowser and canonical retained-assetsVue/React images are ongoing; no final technical release verdict yet.

2026-10-26 later checkpoint: frozen frontendLHE4QUm9 follows confirmed duplicate rail logout fix (2RED then49related/independent7GREEN), Vue76/564 and fresh browser27/10/24GREEN. ActualDdk10 chainGREEN retained as prior identity. New real edge caught backend terminal+observer summarize/metrics replay hang; fixed in routes_sse with17new RED→GREEN,95related and independent17GREEN. Final fullPython now uses separateDB myink_vue_final_pytest/Redis1; one failure marker under investigation, not passed. Final newbackend+LHE11/real postdone-tail replay/retained images remain mandatory. Docker prior candidate build canceled130 after prolonged typecheck; original temporaryRabbit became daemon zombie, recoverybroker hasinit and actualAMQP consumer. Do not touch old project stacks or claim residual cleanup passed.

Final clean backend regression:1966passed/1skip/5xfail/2subtests,192.34s. Initial newDB env contamination11failed/21errors retained, corrected only isolated model config/env, targeted92 and complete rerun GREEN. Newbackend realedge/LHE11 and images still pending.

Allfinal executable gates nowGREEN:Vue/Reactimages7each/APIimageSource+25versions+contract+health;invalidselector64;realbrowser11/edge4;completeownedcleanup includingformerzombie. Independentfinalsignoff/deliveryremainbeforeconclusion.

Final independent signoff APPROVED. All plan gates completed within explicit scope, current source/assets/image identities reverified, no open confirmed blocker. No production switch or Git publication performed.
