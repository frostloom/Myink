# Pi Approved Follow-up Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline with TDD, one fresh final review, one author fixpass and no rereview. User authorized continuous execution and routine decisions; no stage questions or implementer subagents.

**Goal:** Execute the already reserved owner002 nextday regression at its real due time, preserve original fee/manager state and publish an actual correlated result for main/admin audit.
**Architecture:** A root-owned, SHA-pinned fixed-test registry is the execution authority; audit followup plans are correlation only. One bounded host worker takes the existing maintenance.lock, validates source/candidate/gold/review and audit plan, persists a once-only claim, invokes the existing isolated `_fixed_check`, verifies cleanup and input stability, then appends test/tool/version evidence and exports auditv1. A closed runtime and separate systemd timer invoke it without a model or provider access.
**Tech Stack:** Existing Python standard library, SQLite audit, fixed Docker checker and systemd. Reuse development_launcher.Limits/OwnedHosts/_fixed_check and development_inputs hashing/snapshots.
**Spec:** docs/superpowers/specs/2026-10-28-pi-online-closed-loop-design.md phases4/5; the observer plan may still await its second automatic window while this independent worker is implemented.

## Global Constraints
- Pi worktree/long-lived branch only; commit/push authorized. No mainmerge, product release, admin auth/UI, extra paid scope, credentials or model requests.
- Original server state only: cumulative50CNY,761attempts/9unknown18115200held. Compare fee exact and manager history under shared maintenance.lock; no restore/reset/replay.
- Original owner002 run/candidate e60cb0f664606240acbe48c40f65347956ce81c48595fa2edc0c10ea338ab4d1; due2026-10-28T19:00:00Z (=Oct29 03:00 Shanghai). Never mark nextday passed before that actual time.
- Candidate/gold may execute only in the fixed Docker checker, UID65534, networknone, readonly source, bounded CPU/RAM/pids/output/time and operation ownership. Never import either on host; no arbitrary shell or user-supplied command.
- Runtime/unit/root registry are trusted host control, not model tools. ACTUAL rejects injected backend; SIMULATED injection produces synthetic audit only. Root-owned registry0640/root:ubuntu is not writable by service; exactbytes also pinned by root-owned environment. Parent may be root:ubuntu0750; no worldread/write or groupwrite. All output/audit/claims remain private.
- Main audit-only followup does not authorize work. Require matching planned test_id/run/candidate/due and independently frozen review digest. Missing/drifted input, pending claim, cleanup uncertainty or crossed cutoff block and retain evidence.
- New work only02:00–05:30 Shanghai; deadline<=300sec and complete before06:00. Missed/paused windows remain pending/blocked, never reset due date or fake nextday proof. Timer can wake every5min but only a due, valid registry entry can claim once.

## Review Focus
- Forged audit plan/model text cannot execute; altered registry/pin/review/gold/candidate/source fails before claim/check.
- Crashes after durable intent do not rerun Docker; completed receipts are verified and reused without new execution.
- Shared lock contention and time cutoff create no partial claim or false successful test.
- Wrong checker report, missing cases, cleanup failure, cancellation/deadline and input mutation after execution preserve failure, never convert it to pass.
- Runtime/service cannot access provider keys or mutate jobs, original fee/manager/policy; output paths cannot alias any input/source/state.

### Task 1: Reviewed registry, due admission and once-only claims
**Files:** ops/pi/followup.py; ops/pi/tests/test_followup.py.
**Interfaces:** run_due(registry_path,expected_registry_sha256,*,clock=None,runner=None)->bounded summary. Registry exact fields schema/mode/root/audit_path/export_root/lock_path/billing_path/manager_path/entries. Each entry binds test_id/run_id/scheduled_for/candidate_path/candidate_sha256/source_path/source_sha256/test_path/test_sha256/test_cases/review_path/review_sha256/checker. checker exact docker/endpoint/daemon_id/checker_image_id. Max32entries/1MiB registry, each<=200fixedcases. ACTUAL rootowner,0640file/root-owned0750parent; synthetic private0600/0700 and callback only. Root and every input are canonical, nonaliasing, bounded; read-only audit user_version1001 check precedes AuditStore. Claim identity is digest(entry), durable intent includes registry and inputs; an existing intent without finalreceipt returns uncertain and never calls runner. Finalreceipt selfhash and artifact hashes are validated.
- [x] RED missing module; wrong mode/pin/schema/owner/permissions/unknown fields/paths; premature/outsidewindow/cutoff; plan mismatch; concurrent lock; completed and pending reentry.
- [x] Implement strict admission and private once-only claim under sharedlock, using existing audit record schema. Audit plans remain unchanged.
- [x] GREEN targeted tests; commit. Expect no production connection/model execution yet.

### Task 2: Reuse isolated checker and authenticated audit results
**Files:** ops/pi/followup.py; ops/pi/tests/test_followup.py; ops/pi/tests/test_followup_checker.py.
**Interfaces:** default ACTUAL checker calls existing _fixed_check with frozen candidate and registry checker/gold/cases, Limits/OwnedHosts, timer/cancel and persistent perhost ownership receipts. Full source/candidate/gold/review hashes checked before/after; full fee snapshot and manager snapshot preserved under shared lock. Result appends tool/test/version with details.test_id, candidate version, actual occurred_at, mode/domain and report/case/cleanup evidence hashes. main daily links only genuine due matching results. Failure/audit publication failure retains claim/outcome and stops replay.
- [x] RED checker pass/failure/missingcase/cleanup/inputdrift/deadline/fee or manager mutation, no host candidate import, synthetic cannot certify actual followup.
- [x] Implement bounded default runner and audit event/export, raw failure details remain private, public error summary class only. Test authority doesn't imply product adoption or metric improvement.
- [x] GREEN existing audit/development checker controls; independently owned real local Docker fixed-check acceptance with unique receipt/cleanup (original19pi_lab gate unchanged). Commit.

### Task 3: Closed startup, timer and actual scheduled handoff
**Files:** ops/pi/deploy/observer_entry.py (optional fixed followup component flag, defaultobserver unchanged); ops/pi/deploy/myink-pi-followup.service/.timer; ops/pi/tests/test_followup_deploy.py; deploy README, enhancement inventory and docs/evaluations/pi-followup-2026-10-28.{md,json}.
**Interfaces:** same closedtree verifier before importing executor; root env pins runtime+registry. ServiceUbuntu/serviceonlydockergroup, read-only originalstate/jobs/config/releases; credentials inaccessible; writable followup root/audit/maintenance.lock only; private Unixnetwork, timeout<=330seconds/noRestart. Timer every5min; worker enforces true due/maintenance/cutoff. Root-owned approved registry includes actual original18cases/gold/source/candidate/review/source daemon/image, and cannot be populated from arbitrary audit/model text.
- [x] RED root source/config pin/component/unit scopes/time/lock. Implement fixed entry/unit with no paid/provider imports executed. Full offline and targeted checker tests.
- [x] One fresh final reviewer before activation; one authorTDD Important/Critical fixpass, record minors, no rereview. Preserve rollout/failure evidence.
- [x] Deploy new frozen runtime/registry/service/timer, verify true production candidate+gold+review pins and audit plan; a pre-due tick must report planned/no execution. Original history/fee/health unchanged. Nextday remainsplanned until actualOct29 due run; rootgoal staysactive during ongoing loop work.
- [x] ExactHEAD fourCI and push. When due, consume actual receipt through main reader; independently verify real checker cleanup/casecount/fee invariance. Archive only this plan workspace after actual acceptance, continue rootgoal.

## Pre-flight interface check
Task1 audit correlation consumes existing followup exactkeys and user_version1001; Task2 checker accepts source/src + fixed gold/case list and produces REPORT_FIELDS, OwnedHosts owns all containers; Task3 startup verifier uses existing root closedtree and adds only an explicit fixed component choice. Observer and paid manager remain separate; both paid manager/followup share existing maintenance.lock. No schema/fee/main deployment authority added.

Actual due acceptance: Oct29 03:02:39+08, original18/18pass, no newmodels/fees, cleanup independently verified, originalclaim retained; standalone main reader links prior-day plan to actual result. See docs/evaluations/pi-followup-2026-10-28.{md,json}. Full root goal remains active.
