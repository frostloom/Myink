# Guest Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add isolated guest accounts with durable IP-shared short=2 and long=10 generation allowances and registration upgrade.
**Architecture:** Reuse ordinary user tenant boundaries; separate durable guest recovery credentials and IP quota records. Enforce generation admission server-side and expose Vue onboarding/remaining allowances without changing production deployment.
**Tech Stack:** Python/FastAPI/SQLAlchemy/PostgreSQL, Redis/RabbitMQ, Vue/TypeScript.
**Spec:** docs/superpowers/specs/2026-10-27-guest-mode-design.md (approved 2026-10-28).

## Global Constraints

- Ordinary user functionality, role=user only; short 2 generations and long 10 chapter generations per lifetime IP bucket.
- Rewrites/manual repeated body generation consume; system retries, first continuation, approval and persistence do not double charge.
- IP limits quota, never identifies ownership; original/current IP buckets both enforced and normalized; HMAC keys, no raw IP ledger.
- Refresh/new session/deleting projects never resets quota; independent short/long allowances.
- Successful guest registration preserves data, uses existing invitation requirements, revokes guest recovery credentials and old JWTs.
- Native Vue theme/components only; no React/Pi/admin scope; no production data/model calls.
- Work in main as user requested for this chat; protect existing untracked files. No commit/push/deploy in this feature request. Review packages use working-tree diffs plus task-owned untracked files instead of commit ranges.

## Review Focus

- Same-IP separate browsers cannot recover each other's identity (Task 1).
- Forged or missing edge IP and equivalent IPv6 forms cannot obtain fresh buckets (Tasks 1–2).
- Concurrent admission and ambiguous broker confirmation cannot overspend or refund running work (Task 2).
- Manual retry through old task identifiers cannot bypass quotas, while accepted operations can finish at zero balance (Task 2).
- Registration/login cache changes cannot expose other users' work or lose guest drafts (Tasks 1,3).

### Task 1: Guest identity, persistence and registration upgrade

**Files:** Create src/myink/guests.py, src/myink/models/guest.py, tests/test_guest_auth.py; modify src/myink/models/project.py, models/__init__.py, db.py, cli.py, api/auth.py, api/schemas.py and router registration if needed.
**Interfaces:** User.is_guest bool (default false); _AuthenticatedUser.is_guest bool default false. AuthResponse/AuthSessionOut add is_guest bool default false. POST /api/v1/auth/guest with JSON {restore_only?: bool}: return ordinary auth payload; private HttpOnly SameSite cookie stores random opaque recovery secret, DB stores only digest. restore_only must never create a new identity. guests.ip_key(raw: str)->str normalizes valid addresses and HMACs with domain-separated server secret; fail closed on unknown/malformed. Guest identity stores original_ip_key and recovery hash; no quota yet. Guest upgrade uses POST /auth/register with current guest Bearer credential (optional for ordinary registration), retains same user ID, validates invitation, invalidates old auth_version and recovery credential. Existing login/registration remain compatible.
- [x] Add failing tests: two cookie jars/same IP yield different IDs; cookie restores own ID; restore_only missing/invalid credential fails; invalid IP fails; is_guest cannot be client elevated; valid invitation upgrade preserves user ID/projects, invalidates recovery and JWT; failed upgrade remains guest.
- [x] Run focused tests and record expected RED.
- [x] Implement identity and additive migration (including safe legacy defaults); guest cannot gain permanent access via password/account endpoints; ordinary user behavior unchanged. Decide cookie expiry policy explicitly in report; no automatic data deletion.
- [x] Run guest/auth/password/invitation focused regression; record GREEN and review diff, no commit.

### Task 2: Durable quota admission and continuation semantics

**Files:** Create src/myink/guest_quota.py, tests/test_guest_quota.py, tests/test_guest_admission.py; extend models/guest.py and CLI/schema migration; modify worker/enqueue.py, api/routes_tasks.py, routes_chapters.py and other confirmed generation/resume routes, task_budget.py as needed; exclude guests from redundant platform create-book caps in routes_book.py/routes_short_creation.py.
**Interfaces:** guest_quota.quota_view(user_id, client_ip)->dict with short {limit:2,used,remaining} and long {limit:10,used,remaining}; GET /api/v1/auth/guest/quota authenticated guests. Durable reserve/release operation APIs (exact signatures chosen and documented by implementer after admission inspection), atomic ordered bucket locks, operation idempotency. Failure code GUEST_QUOTA_EXHAUSTED in standard error envelope; unavailable storage fails closed. Current IP is supplied by server request context, never request body. Original/current buckets consumed once each if distinct. Non-guests unchanged.
- [x] Add failing tests for exactly 2/10, independent dimensions, batch 3 with remaining 2 rejected unchanged, concurrent last unit, normalization, multiple identities same IP, original/current IP switch, durable restart and deletion, idempotent reservation/release.
- [x] Add admission failures: rejected gate/broker nack releases, unknown publish outcome retains, generated tasks carry valid charge despite worker-before-materialization; zero remaining still permits existing confirm/save/system retry. Manual failed-body re-execution charges anew, paused first continuation does not. Tests must exercise actual admission/resume handlers, not only helper arithmetic.
- [x] Run RED, implement minimal shared ledger/admission integration with explicit transaction/failure ordering; inspect all AI body paths including local revisions and budget resumes to prevent bypass. Document which stages count and how attempts are identified.
- [x] Run focused tests and isolated PostgreSQL concurrency/migration tests, record GREEN. Ordinary account admission/platform quota tests remain passing. No production services, no commit.

### Task 3: Vue guest entry, quota feedback and upgrade

**Files:** web/src/lib/auth.ts, api.ts, types.ts and session types as applicable; web/vue/src/session.ts, LoginPage.vue, AccountPage.vue, shared unauthenticated prompts/rail and error UI; new GuestQuota component/composable and focused tests; guest browser acceptance script.
**Interfaces:** Consume Task 1 auth is_guest and Task 2 quota endpoint/error; keep session optional fields backward compatible. startGuest({restoreOnly?}) uses same-origin credentials, stores only ordinary short-lived auth payload; upgrade sends guest auth while preserving in-memory drafts until success. Guest token renewal uses restore-only, never silently creates new accounts. No ordinary account automatic guest fallback.
- [x] Add RED tests for unauthenticated choice, pending/disabled entry, restore without new identity, guest badge/short+long remaining, exhausted error registration link with preserved draft, invitation upgrade success/failure, ordinary login switch and account-scoped cache cleanup.
- [x] Implement using existing Vue theme tokens and shared components; compact fixed-rail presentation, native dialogs, loading and accessible labels. Make register call compatible with prior anonymous registration. Refresh quota after admissions and page focus, distinguish quota-load errors from zero.
- [x] Run focused GREEN, lint/test/build and browser scenarios using synthetic loopback APIs. Cover desktop/mobile and guest-to-user transitions, no real accounts/models. No commit.

### Task 4: Integrated verification and final review

**Files:** spec/api-openapi.json; new guest isolation regression fixtures/scripts if necessary; docs/work-items/guest-mode-20261028/results.md.
**Interfaces:** Exact built frontend + actual isolated backend auth/quota flows with fake model boundaries, no production data.
- [x] Export API contract and verify schema; run focused backend plus full Python suite on isolated Docker resources, frontend lint/test/build and browser matrix; no fixed shared test ports.
- [x] Verify upgrade migration on pre-feature schema, concurrent quota reservations and cookie/IP boundary, accepted task recovery at zero; exercise guest UI in real browser using test data.
- [x] Record exact checks, skips/blockers, remaining risks and local start instructions. Request independent whole-change spec/security review and fix validated findings, retest covering checks.
- [x] Keep feature changes uncommitted for user local testing; report evidence and files, no push/deploy.

## Verification completion record — 2026-10-28

The checklist records implemented work and executed verification, not an unconditional clean full-suite claim. Evidence and controller rulings: [guest-mode results](../../work-items/guest-mode-20261028/results.md). Task1/2/3 RED/GREEN and independent corrections are recorded in their SDD reports; Task4 includes the permanent old-schema regression, all-engine matrix and actual isolated API/browser verification.

The pre-final-auth full Python run had2095passes,1explicit evaluation-database skip,5known xfails and1AMQPteardown error; the unchanged single affected case passed its serial retry. Final auth/config changes have112plus15covering checks. Full Vue782/shared207 and the21-stage matrix passed before the final label-only supplement; that supplement has43covering tests, changed-file lint/typecheck, final rebuild and repeated real-API4-group acceptance. No skipped or infrastructure-failed check is represented as passed. Warnings, artifact/receipt hashes and exact snapshot boundaries remain in the results record.

All feature changes remain uncommitted for local testing; no push, merge or deployment. Dedicated Docker test services and ignored evidence remain available. No interactive API/Vite server is currently running; local startup instructions are in the linked results.
