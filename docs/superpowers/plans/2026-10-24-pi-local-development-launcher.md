# Local controlled development launcher implementation plan

**Goal:** Repeatable host-supervised real Pi development, default read-only check, authenticated candidate output and owned cleanup.
**Architecture:** Strict frozen config → read-only preflight → canonical exclusive lock and recheck → isolated candidate/broker/worker/checker → authenticated completion and durable receipt. Reuse existing Pi, tools, accounting and Docker primitives.
**Tech:** Python, SQLite, unittest/pytest, Docker Linux ARM64, Pi 1.1.0.
**Spec:** ../specs/2026-10-24-pi-local-development-launcher-design.md

Global constraints: original canonical ledger and prior unknowns preserved; no retry or new scope; temporary policy enable must restore only matching bytes; no automatic Git/adoption/deployment; no user confirmation needed within existing authorization. Independent review artifact is host supplied and binds Plan/base/candidate/owner/generation plus config authorization digest. All copied source and runtime dependencies are pinned, not only edited files.

Review focus: (1) check cannot create output/ledger/lock; (2) stale ledger/input/review fails before paid calls; (3) model/tool/frame limits and cancellation fail closed; (4) last patch→unit→status→owned exit is authoritative; (5) failures preserve fees and restore/clean only owned state.

## Task 1 — frozen inputs and read-only check
- [x] Add red tests for strict keys/duplicates, symlinks and source drift, read-only SQLite checkpoint, independent review binding and check purity.
- [x] Implement `ops/pi/development_inputs.py`: bounded source digest/copy, read-only ledger snapshot, strict private config and artifact pins, Plan/baseline/review validation.
- [x] Config schema `pi-development-v1`: run_id/root, source_path/source_sha256, runtime_path/runtime_sha256, ledger_path/ledger_sha256, policy_path/policy_sha256, credential_path/credential_sha256, plan_path/plan_sha256, baseline_path/baseline_sha256, review_path/review_sha256, test_path/test_sha256, test_cases, docker/endpoint/daemon_id/image_id/checker_image_id, max_requests/max_tools/deadline_seconds. Review `authorization_sha256` hashes config excluding review_path/review_sha256, preventing recursive binding. Source root is a closed src-only tree. Runtime code checked against current controller via verify_source.
- [x] `check(config)` validates closed disabled policy, scope effective approval, credentials privately, source+runtime+artifacts and trusted review; no Docker calls. Output only ready/config digest/check count.

## Task 2 — workers and execution
- [x] Add tests for final result rejection, stale checks, limits, conditional restore and cleanup failures using fixed synthetic transports.
- [x] Extract fixed development worker and checker worker from proven private implementation; generalize exact unittest case inventory and model output limit.
- [x] Implement `ops/pi/development_launcher.py`, `--config` dry-run default and `--execute`; exclusive canonical tools lock, recheck, fresh root, full source copy, separate tools DB, host supplied review, finite bridge, fixed checker, cancel propagation, complete tool/session/RPC verification.
- [x] Record failure receipt even on errors, stop owned containers/processes, conditionally restore policy bytes, verify original ledger rows/events unchanged; success includes candidate digest/path and cleanup. No worktree overwrite.

## Task 3 — validation and real use
- [x] Offline focused and full Pi test suite, independent code review, resolve substantive findings.
- [x] Linux normal rehearsal plus cancellation, timeout/unknown, request-limit and cleanup rejection checks using new entry, fresh identities.
- [x] Select and reproduce actual remaining product defect, freeze tests/Plan and independent review. Use new entry for one real paid run; review actual patch and adopt only after matching checks. Real calls retain original cost ledger.
- [x] Appropriate targeted/full product validation, report exact skip/xfail and independent cleanup/accounting audit; update readiness docs and memory.

Baseline verification completed before implementation: ordinary Python 1642 passed, 1 skipped, 159 deselected, 5 xfailed, 2 warnings, 251.64s; isolated services removed. Earlier timeout remains historical timeout.

实际验收见 ../../evaluations/pi-local-development-readiness-2026-10-24.md；所有结果按已运行记录，历史失败保留。
