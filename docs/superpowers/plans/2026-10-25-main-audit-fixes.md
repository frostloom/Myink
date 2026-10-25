# Main audit fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all eleven confirmed main audit defects, validating and pushing each fix separately.

**Architecture:** Keep existing API, workflow and React boundaries. Correct provenance, transaction/queue ordering and asynchronous lifecycle guards with regression tests at their real consumers.

**Tech Stack:** Python, SQLAlchemy/PostgreSQL, LangGraph, RabbitMQ, React/TypeScript, pytest, Vitest.

**Spec:** docs/superpowers/specs/2026-10-25-main-audit.md

## Global Constraints

- Work on main, protect unrelated .DS_Store, no Pi changes, no deployment.
- User explicitly authorizes baseline push and each independently verified fix commit/push without confirmation.
- Reproduce each bug with a failing regression before implementation; run the relevant full language suite before each push.
- Isolated Docker services only, never fixed myink-test or production services.

## Review Focus

- Legacy character provenance must favor preserving author data (task 1).
- Reject/confirm races and retry idempotency must not resurrect rejected data (tasks 2, 4, 5).
- Broker failures and process restarts must preserve recoverability (tasks 3, 7).
- Previously expired temporal records must stay expired (task 6).
- Route reuse and unmount during pending requests must not leak results (tasks 9, 11).

### Task 1: Preserve author character registry

**Files:** Modify src/myink/memory/invalidation.py, src/myink/workflow/nodes.py; regression tests in tests/test_chapter_delete.py (resolve existing test module names before writing).

**Interfaces:** Consumes existing public entrypoints. Produces the same signatures with corrected behavior; no new cross-task API.

- [ ] Write regression assertions: Deleting a chapter preserves manual and legacy characters; explicitly generated characters introduced in the deleted tail are removed.
- [ ] Run the regression, expect FAIL on the audited defective behavior.
- [ ] Implement the smallest correction in the listed production boundary.
- [ ] Run regression, expect PASS; then `python -m pytest tests/ -q` using the isolated test environment, expect exit 0 (record skips/xfails).
- [ ] Commit only this task and its tests/docs; push main normally; record SHA and verification in the ledger before proceeding.

### Task 2: Retain approved revision memory

**Files:** Modify src/myink/workflow/nodes.py; regression tests in tests/test_invalidation.py (resolve existing test module names before writing).

**Interfaces:** Consumes existing public entrypoints. Produces the same signatures with corrected behavior; no new cross-task API.

- [ ] Write regression assertions: Review revision finalization retains newly approved memory, excludes rejected and superseded memory, and is idempotent.
- [ ] Run the regression, expect FAIL on the audited defective behavior.
- [ ] Implement the smallest correction in the listed production boundary.
- [ ] Run regression, expect PASS; then `python -m pytest tests/ -q` using the isolated test environment, expect exit 0 (record skips/xfails).
- [ ] Commit only this task and its tests/docs; push main normally; record SHA and verification in the ledger before proceeding.

### Task 3: Confirm retry publication before acknowledgement

**Files:** Modify src/myink/worker/consumer.py; regression tests in tests/test_worker_consumer.py (resolve existing test module names before writing).

**Interfaces:** Consumes existing public entrypoints. Produces the same signatures with corrected behavior; no new cross-task API.

- [ ] Write regression assertions: Retry and defer keep the original delivery recoverable until replacement publication succeeds.
- [ ] Run the regression, expect FAIL on the audited defective behavior.
- [ ] Implement the smallest correction in the listed production boundary.
- [ ] Run regression, expect PASS; then `python -m pytest tests/ -q` using the isolated test environment, expect exit 0 (record skips/xfails).
- [ ] Commit only this task and its tests/docs; push main normally; record SHA and verification in the ledger before proceeding.

### Task 4: Allow restoration of removed facts

**Files:** Modify src/myink/memory/correction.py; regression tests in tests/test_memory_correction.py (resolve existing test module names before writing).

**Interfaces:** Consumes existing public entrypoints. Produces the same signatures with corrected behavior; no new cross-task API.

- [ ] Write regression assertions: A fact confirmed then removed can be extracted again; pending and live duplicates remain deduplicated.
- [ ] Run the regression, expect FAIL on the audited defective behavior.
- [ ] Implement the smallest correction in the listed production boundary.
- [ ] Run regression, expect PASS; then `python -m pytest tests/ -q` using the isolated test environment, expect exit 0 (record skips/xfails).
- [ ] Commit only this task and its tests/docs; push main normally; record SHA and verification in the ledger before proceeding.

### Task 5: Serialize candidate decisions

**Files:** Modify src/myink/workflow/nodes.py, src/myink/api/routes_candidates.py; regression tests in tests/test_candidates.py (resolve existing test module names before writing).

**Interfaces:** Consumes existing public entrypoints. Produces the same signatures with corrected behavior; no new cross-task API.

- [ ] Write regression assertions: Concurrent confirmations persist only one memory; confirm versus reject has one winner under PostgreSQL.
- [ ] Run the regression, expect FAIL on the audited defective behavior.
- [ ] Implement the smallest correction in the listed production boundary.
- [ ] Run regression, expect PASS; then `python -m pytest tests/ -q` using the isolated test environment, expect exit 0 (record skips/xfails).
- [ ] Commit only this task and its tests/docs; push main normally; record SHA and verification in the ledger before proceeding.

### Task 6: Restore prior relation after invalidation

**Files:** Modify src/myink/memory/invalidation.py; regression tests in tests/test_invalidation.py (resolve existing test module names before writing).

**Interfaces:** Consumes existing public entrypoints. Produces the same signatures with corrected behavior; no new cross-task API.

- [ ] Write regression assertions: Invalidating a relation change restores the latest retained prior relation without reopening explicitly expired relations.
- [ ] Run the regression, expect FAIL on the audited defective behavior.
- [ ] Implement the smallest correction in the listed production boundary.
- [ ] Run regression, expect PASS; then `python -m pytest tests/ -q` using the isolated test environment, expect exit 0 (record skips/xfails).
- [ ] Commit only this task and its tests/docs; push main normally; record SHA and verification in the ledger before proceeding.

### Task 7: Resume review finalization after budget pause

**Files:** Modify src/myink/workflow/runner.py, src/myink/worker/consumer.py; regression tests in tests/test_review.py (resolve existing test module names before writing).

**Interfaces:** Consumes existing public entrypoints. Produces the same signatures with corrected behavior; no new cross-task API.

- [ ] Write regression assertions: A budget pause during summarization resumes the remaining phase without losing approvals or repeating persistence.
- [ ] Run the regression, expect FAIL on the audited defective behavior.
- [ ] Implement the smallest correction in the listed production boundary.
- [ ] Run regression, expect PASS; then `python -m pytest tests/ -q` using the isolated test environment, expect exit 0 (record skips/xfails).
- [ ] Commit only this task and its tests/docs; push main normally; record SHA and verification in the ledger before proceeding.

### Task 8: Preserve provider truncation reason

**Files:** Modify src/myink/providers/deepseek.py, src/myink/providers/anthropic.py; regression tests in tests/test_providers.py (resolve existing test module names before writing).

**Interfaces:** Consumes existing public entrypoints. Produces the same signatures with corrected behavior; no new cross-task API.

- [ ] Write regression assertions: Streaming and nonstreaming length termination yields the short draft truncation warning.
- [ ] Run the regression, expect FAIL on the audited defective behavior.
- [ ] Implement the smallest correction in the listed production boundary.
- [ ] Run regression, expect PASS; then `python -m pytest tests/ -q` using the isolated test environment, expect exit 0 (record skips/xfails).
- [ ] Commit only this task and its tests/docs; push main normally; record SHA and verification in the ledger before proceeding.

### Task 9: Ignore stale generation responses across projects

**Files:** Modify web/src/pages/WorkspacePage.tsx, web/src/components/GenerationPanel.tsx; regression tests in web/src (resolve existing test module names before writing).

**Interfaces:** Consumes existing public entrypoints. Produces the same signatures with corrected behavior; no new cross-task API.

- [ ] Write regression assertions: Delayed chapter polling and generate/rewrite/batch responses from project A cannot alter project B.
- [ ] Run the regression, expect FAIL on the audited defective behavior.
- [ ] Implement the smallest correction in the listed production boundary.
- [ ] Run regression, expect PASS; then `cd web && npm test && npm run lint && npm run build`, expect exit 0 (record skips/xfails).
- [ ] Commit only this task and its tests/docs; push main normally; record SHA and verification in the ledger before proceeding.

### Task 10: Preserve incomplete multiline form text

**Files:** Modify web/src/pages/NewProjectPage.tsx, web/src/components/ChapterPlanPanel.tsx; regression tests in web/src (resolve existing test module names before writing).

**Interfaces:** Consumes existing public entrypoints. Produces the same signatures with corrected behavior; no new cross-task API.

- [ ] Write regression assertions: Typing partial world rules and Enter then another list item preserves text and submits normalized arrays only on commit.
- [ ] Run the regression, expect FAIL on the audited defective behavior.
- [ ] Implement the smallest correction in the listed production boundary.
- [ ] Run regression, expect PASS; then `cd web && npm test && npm run lint && npm run build`, expect exit 0 (record skips/xfails).
- [ ] Commit only this task and its tests/docs; push main normally; record SHA and verification in the ledger before proceeding.

### Task 11: Ignore stale settings loads

**Files:** Modify web/src/pages/SettingsPage.tsx; regression tests in web/src (resolve existing test module names before writing).

**Interfaces:** Consumes existing public entrypoints. Produces the same signatures with corrected behavior; no new cross-task API.

- [ ] Write regression assertions: Late settings A cannot overwrite settings B or the payload saved to B.
- [ ] Run the regression, expect FAIL on the audited defective behavior.
- [ ] Implement the smallest correction in the listed production boundary.
- [ ] Run regression, expect PASS; then `cd web && npm test && npm run lint && npm run build`, expect exit 0 (record skips/xfails).
- [ ] Commit only this task and its tests/docs; push main normally; record SHA and verification in the ledger before proceeding.


## Final review followups

### Task 12: Deduplicate approved replay and respect rejected restorations

**Files:** src/myink/workflow/nodes.py; tests/test_review_routing.py.
**Interfaces:** Current-revision approvals and historical candidate decisions; preserve public APIs.

- [ ] RED: duplicate confirmed fact/event history must yield one active memory; applied non-superseded rejected restoration must yield zero.
- [ ] GREEN: filter rejected proposals first, replay each approved proposal once.
- [ ] Verify targeted review tests, full `python -m pytest tests/ -q`; expect exit 0 and record skips/xfails.
- [ ] Commit and push before task 13.

### Task 13: Distinguish retained same-chapter relation revisions

**Files:** src/myink/memory/invalidation.py; tests/test_invalidation.py.
**Interfaces:** Closure provenance from task 6, grouped per directed pair and source chapter.

- [ ] RED: ch1 ally; ch2 hostile; invalidate ch2; rewrite ch2 hostile valid_to=4; ch3 knows valid_to=4; invalidate ch3; expect no active ally resurrection.
- [ ] GREEN: only consider a source chapter undone when all its historical rows for that pair are invalidated.
- [ ] Verify invalidation/deletion tests and full Python suite; expect exit 0.
- [ ] Commit and push before task 14.

### Task 14: Deduplicate repeated extraction against live memory

**Files:** src/myink/memory/correction.py; tests/test_correction.py.
**Interfaces:** Existing diff matching and candidate identity; keep confirmed-deleted fact restoration.

- [ ] RED: live confirmed A and extraction [A,A] yield keep=1, zero additions; missing A repeated yields one pending proposal.
- [ ] GREEN: deduplicate equivalent proposals within one extraction before matching.
- [ ] Verify correction tests and full Python suite; expect exit 0.
- [ ] Commit and push; preserve one final review pass, no recursive re-review.
