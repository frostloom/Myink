# Manual main release observation handoff Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for inline implementation; the user has explicitly requested continuous execution without design/step confirmation.

**Goal:** Preserve an interrupted old observation when a human releases main, then allow the original nightly manager to use a fresh version-bound source profile.

**Architecture:** Reuse the original Gate terminal state with a distinct `observation_interrupted` event and result, never `comparison_complete`. A root-only metadata handoff verifies an already completed external deployment, original accounting, current native maintenance identity, and the installed finite nightly profile/config before ending the old observation. It never performs publication, initialization, model calls or source admission.

**Tech Stack:** Existing Python, SQLite Gate/AuditStore, Docker read-only cohort probes and PostgreSQL maintenance reader.

**Spec:** This plan records the scoped design decision under the existing user goal and no-step-confirmation authorization. Human product/main publication still requires separate explicit approval.

## Global Constraints

- Original manager/fee/Gate stores; 50 CNY and nine historical uncertain holds remain unchanged.
- No replacement of old package, approval, deployment, task binding or comparison results; no claimed online improvement.
- Existing `completed` also represents ended no-release work. Interruption must have its own event/result and must not satisfy the completed-comparison source issuer.
- Only an exact root-issued short-lived handoff permission after verified actual main deployment may end observing/blocked observation. No browser/model authority, deployment or fee approval.
- New driver seals the explicit new `autonomy_profile`, standing `source_template`, `inherit_task_id=None` and exact new image. The source issuer may use the separately verified human baseline to collect fresh version-bound evidence and issue a new finite profile each night. This prevents the initial 24-hour profile from permanently blocking subsequent nights; original coordinator admission remains unchanged.
- Audit and verified result are durable before the final Gate transaction. Incomplete intent is retained; no automatic replay.

## Review Focus

- Wrong old package/deployment or completed unrelated cycle must not be closed.
- Operator pin/expiry/mode/config/profile/image/physical cohort/source or PG identity drift must reject without ending the old cycle.
- Audit failure must not release the Gate; manager and billing snapshots must remain unchanged.
- Interruption must remain insufficient evidence in the original audit export, with no comparison success event.
- The existing source issuer accepts only a verified manual baseline or completed real comparison; an interrupted comparison is never called passed, and inherited old work cannot replay.

### Task 1: Gate ending and native metadata handoff

Files: `ops/pi/nightly_gate.py`, new `ops/pi/nightly_handoff.py`, `ops/pi/tests/test_nightly_handoff.py`, `ops/pi/deploy/observer_entry.py`, `ops/pi/nightly_source.py` and its tests.

- [x] Write tests for exact human permission, terminal interruption with immutable old fields, expiry/drift rejection, ledger preservation and distinct audit outcome. Run RED first.
- [x] Implement `ApprovalGate.interrupt_observation(cycle, permission_path, permission_pin, result_sha256)` with an `observation_interrupted` event; no schema/table additions and no comparison-complete event.
- [x] Implement `handoff(gate, permission_path, permission_pin, driver_path, driver_pin, root, *, verify=None)`; ACTUAL forbids adapters and uses the original daemon/cohort/source/PG checks plus root nightly env/runtime validation. SIMULATED requires an explicit verifier.
- [x] Persist intent, verify new config/profile and physical source/maintenance identity twice, check both original ledger snapshots, write/validate/export insufficient-evidence audit and verified result, then atomically end the old observation.
- [x] Add root-only `nightly_handoff` launcher component. Tests reject ACTUAL callbacks before any effect, wrong profiles/cohorts/locks, unknown intent and failed audit; exact completed receipt is read-only/idempotent.
- [x] Run related Gate/driver/binding/profile/audit/entry tests and full Pi offline CI command. Review this change once before claiming completion.

### Task 2: Operator procedure and acceptance

Files: `docs/pi/admin-console.md`, evaluation receipt for this handoff.

- [x] Document first main release order: human approval, original nightly lock, fixed existing product-entry prepare/activate and real backup/drain/migration, verify new products/maintenance identity, seal new finite profile/nightly env and exact handoff permission, perform metadata handoff. No early old comparison or borrowed approval.
- [x] Test next-night path days after an interrupted comparison, with fresh source issuance from the verified new human baseline, with original manager/fee accounting; keep rejection for a missing/tampered manual baseline and use `comparison_sha256=null` plus a separate baseline receipt digest.
- [x] Record simulated versus actual evidence, tests/CI and protected WIP. Pi push follows this verification; actual production handoff remains unexecuted pending explicit release approval.
