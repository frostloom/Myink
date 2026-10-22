# Pi explicit single-slot manifest implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline; prior user authorizes autonomous development, commits/pushes and no routine questions.

**Goal:** Prepare a genuinely single-slot, budget-compatible manifest and check it without real execution.
**Architecture:** Add closed schema pi-analysis-launch-v2 with mandatory integer selected_slots in {1,2}; v1 remains exactly two slots and forbids new fields. Both check and execute select only the first N frozen slots; registration remains 30, request identity/config hash/cumulative budget binding unchanged.
**Tech Stack:** Existing Python, pytest/SQLite/HTTPX and fixed Linux Pi runtime; no new dependencies.
**Spec:** This plan contains the scoped design. Selection is a host-controlled prefix, not arbitrary slot IDs. Single-slot baseline is a transport/usage diagnostic, never a baseline/candidate quality comparison.

## Global Constraints

- v1 field set and two-slot behavior unchanged; v2 adds exactly selected_slots, type int excluding bool, values 1 or 2 only, mandatory.
- selected_slots is included in config hash and AnalysisRun identity. No resume, retries, skipping ahead or invisible budget-only selection.
- Single-slot successful synthetic execution produces 1 DONE/29 NOT_RUN and exactly one model request/container; unknown stops with 1 UNCERTAIN/29 NOT_RUN and full reservation.
- 0 real model requests, canonical policy live=false and ledger/credentials/input bytes unchanged. Read public official pricing/capacity sources without credentials; no private payload upload.
- Prepare cap=2016384 microyuan if the unchanged policy and current audited reserve agree; canonical remaining must cover it. Keep remaining 77241 microyuan outside this proposed run. 240-second check deadline; expired manifests require fresh check, never replay.
- Real input files and source snapshots stay private; no key/hash or writing text in Git/memory. Public evidence includes non-secret numeric counts, code/source hashes and private receipt commitments only.

## Review Focus

- bool/float/missing/unknown schema selections fail before any writer/provider/Docker action.
- Read-only v2 check reports one selection without side effects; global disabled policy cannot execute.
- Low run cap is not a substitute for prefix selection: single success never attempts a second request even with spare synthetic funds.
- Config identity binds single versus pair; schema/selection drift is visible in the hash.
- Unknown charge/cleanup failures keep durable claim, preserve first failure, and never proceed to another slot.

### Task 1: Implement and verify explicit selection

**Files:** ops/pi/analysis_launcher.py, ops/pi/tests/test_analysis_launcher.py.
**Interfaces:** _selected_count(config) returns 2 for valid v1, selected_slots for validated v2. _prepare checks exact field set and selection before any side effect. Result selected_slots and both initial-frame check/execution loops use the same count.
- [x] Write RED tests: v2 read-only check (1/2), successful single execution, single unknown, invalid selections, strict v1, disabled execution, distinct hashes.
- [x] Implement minimal schema validation/prefix selection; targeted/full Pi suite, compileall and diff-check.
- [x] Fixed real Linux synthetic single-slot acceptance; independent fresh review; resolve Important with TDD.

### Task 2: Freeze private actual-input check and deliver

**Files:** Private .local/pi-single-slot-20261022; public docs/evaluations/pi-single-slot-2026-10-22.md/json, docs/pi/README.md.
**Interfaces:** v2 frozen manifest selected_slots=1, canonical disabled policy, original ledger/input identities, current source closure and official evidence; launcher.launch(config) default check only.
- [x] Refresh unauthenticated official price/capacity sources, record bounded bytes/digests; verify current pricing agrees with frozen policy; never infer provider usage/billing validation.
- [x] Clone fixed runtime/current code source into a fresh private directory; synthetic acceptance runs separately and never touches real inputs/ledger.
- [x] Audit canonical snapshot before/after; build actual-input frozen v2 check with cap and deadline, record checked/launch_ready=false/root absent; inspect only local daemon/image identities, no real-input containers.
- [x] Preserve non-executable recipe; expose exact check timestamp/deadline and ensure no stale readiness claim. Review public docs.
- Delivery: commit/push Pi branch and update myink memory after verification; completion is recorded in Git and the myink bank.

## Execution record

- Start 1494119 on clean Pi worktree. Ruling: implement the missing explicit single-slot capability because a two-slot manifest plus a small cap does not fulfill the requested selection.
- Ruling: retain v1 unchanged, use v2 mandatory field rather than silently extending historical closed manifests.

- Code/test stage complete: RED6 failed/11 passed; launcher72 passed; full Pi2112 passed/0 skipped/19 deselected.
- Independent review0 Critical/Important, minorCLI description corrected; new source-reviewed/synthetic-002 accepted before actual check. Prior evidence preserved.
- Actual private input check complete at2026-10-22T10:30:18Z; deadline10:34:14Z, live=false, root absent, no execute/reserve/provider request, canonical snapshot/DB-WAL/policy/credentials/original input bytes unchanged.
- Pricing ruling: official page now distinguishes peak/off-peak; keep existing peak-rate policy as conservative upper bound, no lower reservation or inferred billing proof.

- Final evidence verification: public report, actual-input check, synthetic-002 and verified absolute source-reviewed closure agree; all 15 private evidence commitments match. Public documentation review: 0 Critical / 0 Important, original CLI Minor fixed.
