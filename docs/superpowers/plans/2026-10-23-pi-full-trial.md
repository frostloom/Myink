# Pi full trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax.

**Goal:** Deliver the approved offline-tested complete trial mode while retaining strict pilots.
**Architecture:** Explicit immutable manifest schema selects all30. A separate host verifier distinguishes ordinary output failure from transport/session failure; the existing orchestrator only records failed after independent billing and cleanup checks.
**Tech Stack:** Python3.12, pytest, existing SQLite/HTTP/stdio; no new dependencies.
**Spec:** docs/superpowers/specs/2026-10-23-pi-full-trial-design.md

## Global Constraints
No paid calls, credentials/private data/ledger reads, Docker, commit/push/merge/deploy. Existing pilot semantics unchanged. Fixed30 order, no retry, no scope reset, known usage retained, unknown reserved. Native inline implementation selected as routine execution under user-approved development scope.

## Review Focus
- Malformed JSON is ordinary failure only after complete independent session evidence.
- Forged worker verdicts and duplicate session IDs must stop, never become FAILED.
- Cleanup or known-billing verification failure must prevent progression even for ordinary invalid output.
- Partial/low-budget runs preserve all30 states and do not count NOT_RUN as output failures.
- Trial manifests cannot be downgraded into pilot or change failure policy/slot order after admission.

### Task 1: Independent output verdict
**Files:** Create ops/pi/analysis_trial_result.py and ops/pi/tests/test_analysis_trial_result.py.
**Interfaces:** verify_trial_result(frame, slot, view, report) returns body-free row with session identity, contract_valid and bounded failure classification or raises on evidence inconsistency.
- [x] Add real-session unit cases for valid, invalid JSON/schema, target failure, dishonest worker verdict, broken session/runtime/evidence.
- [x] Run targeted tests; Expected: RED missing verifier.
- [x] Implement boundary-first verification and host parsing/scoring; no changes to legacy verify_result.
- [x] Run targeted tests; Expected: all pass.

### Task 2: Explicit full mode and regression
**Files:** Modify ops/pi/analysis_launcher.py; Create ops/pi/tests/test_analysis_full_trial.py; document docs/evaluations/pi-full-trial-2026-10-23.md.
**Interfaces:** Existing launch(config, execute=False); new schema pi-analysis-trial-v1 has exact _FIELDS plus failure_policy=continue_known_contract_failure and always30 slots. Existing _slot uses Task1 verifier only in this mode. terminal FAILED only after usage/session/cleanup; summary derived from immutable run snapshot.
- [x] Add real SQLite+HTTP+stdio cases showing 30 outcomes, invalid outputs continuing, strict pilot stopping, unknown/corrupt session/duplicate session/cleanup/deadline/budget blocking.
- [x] Run targeted tests; Expected: RED manifest rejected.
- [x] Implement schema dispatch, verifier selection, failed outcome and full denominator summary.
- [x] Run targeted and full Pi offline suite; Expected: green, report any skips/blocked checks. Preserve source and ledger failure checks.
- [x] Run root tests appropriate to available services, reporting environmental limitations accurately; inspect diff, obtain one fresh final review, fix substantive findings with RED/GREEN, record evidence. Leave all changes uncommitted per project default.

## Completion evidence

2026-10-23: implemented inline in existing Pi worktree.44 new targeted tests passed. Final full Pi offline command `.venv/bin/python -m pytest ops/pi/tests/ -q -m 'not pi_lab and not pi_live' -ra`:2156 passed/19 deselected/0 skipped. Fresh reviewer found1 Important raw-session integrity issue; four unit cases and one end-to-end case RED→GREEN, fixed in one pass followed by final full suite. No deferred findings. Root product PostgreSQL/Redis/RabbitMQ integration and actual Linux/provider acceptance were not run. `git diff --check` passed. All changes remain uncommitted; no push/merge/deploy.
