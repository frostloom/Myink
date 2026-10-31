# Pi trial lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved v2 full trial execution window and cooperative interruption without changing legacy manifests or billing authority.

**Architecture:** A host lifecycle object owns wall/monotonic deadlines, cancellation, and a shared cleanup wait budget. Optional cancellation propagates through the existing gateway, while a v2-only host adapter bounds Docker calls. Existing canonical ledger claims and settlement remain authoritative.

**Tech Stack:** Python3.12, stdlib, existing httpx/pytest; no new dependencies.

**Spec:** docs/superpowers/specs/2026-10-23-pi-trial-lifecycle-design.md (user approved 2026-10-23).

## Global Constraints

- v2 schema pi-analysis-trial-v2 / time_policy bounded_trial_v1; max initial future deadline3600 seconds, legacy600.
- Shared active cleanup wait budget120 seconds, never later than execution deadline+120; storage persistence has no whole-call hard wall-clock guarantee.
- Fixed30 slots, worker45/exchange60 seconds; strict identity and known-billing gates retained.
- No real credentials, canonical ledger, Docker/provider, policy changes, replay/retries, commit/push or deployment.
- Implementation performed inline under existing user authorization; no extra approval for routine implementation choices.

## Review Focus

- Cancellation race after reservation before transport must preserve uncertainty and never resend (Task2).
- Non-main-thread callers must never install process-wide signal handlers (Task3).
- Cleanup timeout cannot discard owned/pending identities or mask the first stop reason (Task3).
- Wall clock rollback must not extend execution or cleanup (Task1).
- Unknown terminal settlement can be cleanly finalized; pending cannot be reported cleanup_complete (Task3).

### Task 1: Host lifecycle primitives

**Files:** Create ops/pi/analysis_lifecycle.py and ops/pi/tests/test_analysis_lifecycle.py.
**Interfaces:** Lifecycle(deadline), remaining(), check(), stop(reason), begin_cleanup(), cleanup_remaining(); Interrupted lifecycle raises TimeoutError subtype. CLI signal context preserves handlers.
- [x] Write tests for rollback/forward, first reason, shared cleanup budget, explicit signals and restoration; run `.venv/bin/python -m pytest ops/pi/tests/test_analysis_lifecycle.py -q` expecting missing-module failure.
- [x] Implement lifecycle with Event/RLock and monotonic caps; signal context only enabled explicitly and in main thread.
- [x] Re-run same command; expected PASS.

### Task 2: Gateway cooperative cancellation

**Files:** Modify analysis_run.py, control.py, model_gateway.py; create tests/test_analysis_cancellation.py.
**Interfaces:** Optional cancellation Event in gateway_handler/make_gateway_handler/forward_messages/_DeadlineUpstream. Defaults preserve existing paths.
- [x] Write tests asserting cancelled-before-send zero transport calls, blocked transport cancellation returns promptly and terminal unknown reserve remains, existing known settlement immutable; run new test file expecting unsupported keyword failures.
- [x] Propagate Event, check before claim/reserve/transport, poll response queues in bounded slices only for cancellable paths; cancellation closes upstream and settles through existing owner thread.
- [x] Run new tests plus gateway/control/analysis budget tests; expected PASS.

### Task 3: v2 launcher and bounded host cleanup

**Files:** Modify analysis_launcher.py; create tests/test_analysis_trial_lifecycle.py; update spec status and evaluation report.
**Interfaces:** launch(config, execute=False) stays public; internal v2 function receives prepared values and Lifecycle. Bounded ProbeHost subclass clamps every CLI call to active phase remaining. New receipt fields follow approved spec.
- [x] Write v2 check/legacy rejection, short-window no claim/container, full30 normal+contract failure, cancellation/time boundary, initial/terminal receipt, cleanup failure, signal/SystemExit tests. Run expecting v2 rejection.
- [x] Implement schema gating then v2 lifecycle orchestration using existing slot verifier, ordered claims and immutable terminal states; existing launch schemas use original path. Pass lifecycle into _slot optionally; use cancellable stdio wait without raising legacy limits. CLI v2 execute installs/restores signals; library does not.
- [x] Verify new and legacy launcher/full trial/runtime/probe/budget suites. Then run all Pi offline tests with `-m 'not pi_lab and not pi_live'`; expected all selected PASS, report deselections/skips accurately.
- [x] Independent final review, fix important issues with reproducing RED→GREEN tests, rerun affected suite/full Pi as needed. Deliver documented limitations and no paid execution.

## Execution record

Pre-flight: Task1 Lifecycle produces check/stop/Event/cleanup timing consumed by Tasks2–3; Task2 Event optional interface consumed by Task3. Consistent with spec. No commits: repository default overrides skill commit steps. Preserve prior untracked token reports.

Task1: complete — missing module RED, lifecycle clocks/signals GREEN 3/3; stdio cancellation later RED→GREEN.
Task2: complete — unsupported cancel keyword RED, four cancellation cases GREEN; gateway/budget/admission regression148 passed. Initial test command named nonexistent test_control.py; corrected to test_pi_gateway.py and test_gateway_admission.py, no tests claimed for invalid command. Queue timeout regression reproduced by four existing deadline tests and fixed by preserving single-wait behavior without host cancel.
Task3: implementation and offline verification complete — v2 positive cases RED at schema rejection; first combined15 passed, expanded v2 suite17 passed. Launcher/runtime/probe regression194 passed; full Pi offline2181 passed,19 deselected,0 skipped in101.73s. Independent review pending.

Final review: four Important findings fixed with reproducing tests RED→GREEN: signal_does_not_acquire_event_condition_lock; interrupt_during_final_cleanup_still_attempts_receipt; stop_while_waiting_to_finish_does_not_commit_done; cleanup_failure_keeps_container_identity. Config freezing also moved before Lifecycle construction with RED→GREEN test. Expanded targeted suite64 passed in12.59s.
Final: Ruling: standard HTTP shutdown/join must also share the active wait budget, rather than treating it as a cosmetic timing edge — added shutdown_server plus stalled-shutdown RED→GREEN test; cost if wrong: one bounded daemon shutdown helper per slot.
Final: Ruling: freeze config before capturing Lifecycle, rather than trusting caller object immutability during preparation — prevents mismatched deadlines; cost if wrong: one extra bounded JSON snapshot at entry.
Final: no deferred minors. No second review dispatched; important fixes verified by TDD and final regression.

Final: complete —2190 passed,19 deselected,0 skipped in90.99s; final production hashes and test log commitment in docs/evaluations/pi-trial-lifecycle-2026-10-23.json. Working tree retained without commit/push per repository default.
