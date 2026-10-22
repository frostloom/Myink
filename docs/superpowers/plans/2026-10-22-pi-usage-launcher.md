# Pi Usage Diagnostics Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect existing sanitized asynchronous metering evidence to the trusted analysis host without changing settlement.
**Architecture:** Optional AnalysisRun callback forwards to existing gateway; a bounded private sink is created per slot before admission. Existing dispatcher owns delivery, so host never waits for diagnostics.
**Tech Stack:** Python3.12, SQLite, httpx, pytest, POSIX private files.
**Spec:** docs/superpowers/specs/2026-10-22-pi-usage-launcher-design.md

## Global Constraints

- Actual live=false; no real provider, canonical state access, deployment or dependency changes.
- One record/write attempt per file; maximum8192 encoded bytes including newline; parent0700/file0600.
- Existing model_gateway sanitization/parser, budget, at-most-once and queue semantics unchanged.
- Record may drop; no delivery claim, wait, retry or automatic restart.
- Keep existing Pi worktree/branch. User already authorized commit/push and declined questions.

## Review Focus

- A sink destination is replaced/symlinked/hardlinked after setup: never append outside original private inode.
- Async callback stalls or raises: HTTP and immutable settlement must still finish.
- Missing cache counters or malformed/unknown upstream: stop run and retain full reservation, diagnostic never invents zero.
- Diagnostic file setup fails: no paid admission or container creation for the slot.
- Upstream injects strings/body or retries replay: persisted records stay sanitized, per-file bounded, and correlated to slot/attempt.

### Task 1: Private sink and real host integration

**Files:**
- Create: ops/pi/usage_diagnostics.py
- Modify: ops/pi/analysis_run.py, ops/pi/analysis_launcher.py, docs/pi/README.md
- Test: ops/pi/tests/test_launcher_usage_diagnostics.py
- Evidence: docs/evaluations/pi-usage-launcher-2026-10-22.md/json

**Interfaces:**
- Consumes: model_gateway async usage_observer snapshot, AnalysisRun.gateway_handler, existing synthetic launcher boundaries.
- Produces: make_usage_observer(path, *, slot_index) callback; optional usage_observer=None argument on AnalysisRun.gateway_handler; launcher per-slot private files and public best-effort mode.

- [x] Step 1: Add tests for bounded0600 files, exclusive creation/private parent, symlink/inode/hardlink/mode replacements, concurrent/oversized writes, real HTTP forwarding/unknown counters/replay, two-slot launcher files, setup failure before admission and callback failure/stall independence.
- [x] Step 2: Run `.venv/bin/python -m pytest ops/pi/tests/test_launcher_usage_diagnostics.py -q`; expect failures for missing sink module/callback argument/files.
- [x] Step 3: Implement minimal private sink and callback plumbing; do not alter parser or budget logic. Import sink only on host, never expose file details in public result.
- [x] Step 4: Run same tests; expect all pass. Run existing analysis launcher/run/budget and usage diagnostics/cache tests; expect no regressions.
- [x] Step 5: Run `.venv/bin/python -m pytest ops/pi/tests/ -q -m 'not pi_lab and not pi_live'`; expect green, report all skips/deselections. Run compileall and diff-check, record actual evidence.
- [x] Step 6: Update docs/evaluation with finite safety/delivery limitations, commit. task-done runs targeted new file and records task completion.
- [x] Step 7: One independent whole-change review against96400ef; fix Important/Critical once with RED→GREEN and full suite. Record all declined judgments/rulings.
- [ ] Step 8: Update myink memory, push Pi branch, preserve worktree and archive only current plan workspace.
