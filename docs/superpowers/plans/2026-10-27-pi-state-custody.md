# Pi State Custody Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. One fresh final feature review after all tasks.

**Goal:** Prevent a server handoff from forking the original cumulative model budget.
**Architecture:** Add strict append-only freeze/activation chain checks inside the existing reserve transaction; bind active authority to native host and canonical ledger path. Keep SQLite backup and operator-controlled transport separate from paid authorization.
**Tech Stack:** Python3.12, SQLite, native Linux/macOS identity, existing Ledger/budget/backup APIs.
**Spec:** docs/superpowers/specs/2026-10-27-pi-state-custody-design.md

## Global Constraints
- Preserve original50CNY scope,9terminalunknown holds, all historical operations/events and manager terminal states.
- No canonical migration, credentials, server service, policy expansion, real model call, product adoption or main merge in this implementation stage.
- Never execute/import unreviewed candidate code on host.
- Exactly one fresh final feature review; one author correction pass, preserve all test evidence.

## Review Focus
- Freeze/reserve atomic race and no bypass via analysis_slot, expired pending permits or copied active ledgers.
- Full event-chain validation, malformed/unknown kind fails closed, no partial activation or stale digest authority.
- Stable host identity, canonical path binding, raw IDs absent from outputs, unsupported platform rejection.
- Original scope/fees/unknowns/history preservation; diagnostics vs paid mutation boundary honestly documented.

### Task 1: Atomic custody state and reservation guard

**Files:** create ops/pi/state_custody.py and ops/pi/tests/test_state_custody.py; modify ops/pi/budget.py minimally.
**Interface:** current_binding(path), status(ledger), freeze(ledger,transfer_id,destination,authorization_reference), activate(ledger,transfer_id,snapshot_sha256,authorization_reference); guard(connection,ledger.path) called first inside reserve transaction. BudgetDenied remains paid-denial API, custody errors must not authorize fallback.

- [x] Write tests using existing finite50 fixtures for legacy/unknown preservation, freeze/pending refusal, source denial, successful matching activation, wrong host/path, stale digest, tampered chains, duplicates/return transfer and cross-process/race outcomes. Expected RED: missing custody API or bypassing reserve.
- [x] Implement strict native identity/chain/digest functions and minimal transaction-integrated guard. Expected GREEN: targeted custody tests plus existing budget/analysis-budget/ledger compatibility.

### Task 2: Operator CLI and actual isolated handoff proof

**Files:** CLI in state_custody.py; test_state_custody.py; docs/pi/server-enablement.md, new evaluation and metrics; private synthetic artifacts under .local/pi-state-custody-20261027.
**Interface:** python -m ops.pi.state_custody --ledger PATH status|freeze|activate; explicit JSON destination and authorization reference, activation snapshot hash. Use existing SQLite backup helper only on fresh private paths.

- [x] Add subprocess CLI/schema/output/no-effect failure tests RED, implement fixed parser GREEN.
- [x] Run related tests, fullPi/Node, one fresh final review, correct actionable findings once RED/GREEN.
- [x] Freeze a synthetic original-scope ledger, back it up, carry it to the existing server private acceptance directory and activate only at pinned destination; verify source/copy denial and matching destination synthetic reservation, settle without transport, snapshots and unknown totals retained. No real credentials or canonical mutations. Expected0 real calls, unchanged production7 identities/readyz.
- [ ] Publish sanitized proof/limits, commit and push existingPi branch, verify exactHEAD4CI. Advance goal to concrete canonical state custody/leastprivilege service rollout; do not mark Pi live from this prerequisite.
