# Pi empty writing data and pre-execution recovery implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Zero eligible writing samples finish a night without analysis/model/development, and verified pre-exec launcher failures can be reconciled without erasing history or replaying any intent.

**Architecture:** Reuse original Gate, source observer, audit store and manager/fee ledgers. Only fixed Docker-independent setpriv failures before Python exec qualify for append-only root reconciliation. Preserve the sealed human baseline/standing-template bytes; upgrade the root controller while retaining the verified existing sandbox worker runtime.

**Tech Stack:** Existing Python3.12, pytest, SQLite audit, root systemd runtime.

**Spec:** User 2026-11-01 explicitly requested repair and normal skipping when online writing data is absent. Prior 50CNY/nine holds and human candidate deployment boundaries remain.

## Global constraints
- Do not delete/reset claims, rewrite old receipts, release unknown fees, replay old execution, or treat missing/invalid metrics as zero.
- ACTUAL reconciliation must be root, exact canonical original paths, no injected effects; SIMULATED tests use isolated stores.
- No business image/DB changes, new paid calls or future candidate approval.
- Preserve preexisting native integration WIP.

## Review focus
- 0 samples vs unknown/negative/bool/failed observation.
- Nonzero samples still use normal admission; an incomplete old intent still blocks.
- Exact known setpriv preexec failure vs generic127, interrupted capture, nonempty stdout, or fee drift.
- Only blocked unadmitted current cycle can settle; selected task/candidate/approval/deployment or manager intent cannot.
- New nightly root controller must preserve baseline/template hashes and original sandbox worker restrictions.

### Task 1: normal zero-sample night
- [x] Add failing source/driver regressions: no source analysis/admission/manager/image on 0, freeze a no-release receipt; next tick and next night do not replay same window.
- [x] Implement early source stage `no_evidence` and auditable nightly skip; leave invalid/unknown observations blocked.
- [x] Run related tests.

### Task 2: explicit no-effect reconciliation
- [x] Add failing tests for exact terminal preexec failure proof, tampering/refusal, immutable history and gate restrictions.
- [x] Implement root append-only preexec certificate, checked by coordinator history; preserve old uncertain receipt and fee data.
- [x] Add a controlled blocked-unadmitted cycle settlement based on verified zero models/no manager work; append audit, not comparison success.
- [x] Qualify current Linux worker privilege drop read-only before allowing future data admission.

### Task 3: actual recovery and verification
- [x] One fresh independent review, one fix pass if required; run complete Pi offline suite.
- [x] Build/install exact root controller runtime under existing repair authorization, preserve standing-template and legacy worker pins.
- [x] Reconcile the proved old preexec failure and settle only current no-data blocked cycle; do not rerun the night or call models by day.
- [x] Verify ACTUAL fresh zero-data path without fake clock or paid requests; original stores unchanged, audit visible, timer healthy.
- [x] Document actual limits, commit/push Pi and authorized main fix; no future candidate publication.

- [ ] Follow-up: verify the next NEW actual scheduled nightly on 2026-11-03; do not replay recovered cycle or claim daytime/offline evidence as scheduled execution.
