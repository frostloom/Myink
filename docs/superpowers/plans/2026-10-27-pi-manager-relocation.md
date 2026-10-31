# Pi Manager Relocation Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, one fresh final review.

**Goal:** Relocate the original manager while keeping history and mandatory evidence checks.
**Architecture:** Frozen-billing quiescent source export, sealed immutable manager prefix, byte-preserving archive and append-only destination identity. Optional trusted resolver retains original audit facts.
**Tech Stack:** Python3.12,SQLite,existing manager locks/path checks,state_custody.
**Spec:** docs/superpowers/specs/2026-10-27-pi-manager-relocation-design.md

## Global Constraints
- Originalmanager/billing/50CNY/9unknown unchanged; no reinitialization/replay/status upgrade.
- Implementation proof synthetic only,0realmodel/canonical/credentials/service writes.
- No hostexecution of Pi candidates; onefreshfinalreview+oneauthorfixpass.

## Review Focus
- Billing/native/managerpath owner binding and immutable prefix cannot hide runnable/unresolved tasks.
- Full original abandonment evidence through exact byte/hash archive, original logical identities, no fallback.
- New foreignbillingtasks denied, source frozen no metadata/inbox effects, chained transfer and cold recovery.

### Task 1: Relocation identity and strict retirement

**Files:** new ops/pi/manager_relocation.py/test_manager_relocation.py; minimal ops/pi/manager.py integration.
**Interface:** prepare source bundle under existing managerlock; apply destination transfer; context resolves immutable header/current identity/historical task origins and known relocation operations.
- [x] BehavioralRED current path failure/sourcefrozen effects, source quiescence and transfer/prefix tampering.
- [x] Minimal strict prefix/relocation/currentcustodian validation; preserve exact legacy behavior. GREEN manager/custody tests.

### Task 2: Original evidence and actual synthetic proof

**Files:** manager_relocation.py/tests; optional archive resolver in selection_abandonment.py; evaluation/readiness/metrics.
**Interface:** original audit/review bytes at mapped private locations; original logical identities unchanged.
- [x] RED archive missing/corrupt/foreign/partial and prior raw outcomes; implement complete hash/schema checks, no waived evidence. GREEN oldabandonment+manager suites.
- [x] Onefresh finalreview/oneauthorfixpass,fullPi/Node.
- [x] Local-to-server synthetic originalmanager/billing/evidence proof, sourcefreeze/noeffects/cold0dispatch and7productionidentity/readyz equality.
- [x] Publish metrics/limits,push existingPi branch,exactHEAD4CI; then formal canonical backup/restore/state migration/service rollout.
