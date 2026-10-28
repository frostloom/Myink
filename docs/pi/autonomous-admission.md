# Autonomous investigation and independent review admission

Implementation plan: `docs/superpowers/plans/2026-10-29-pi-autonomous-investigation-admission.md`.
The full pipeline is in development; the server still uses its previously
verified finite approved queue. This document does not announce autonomous task
admission as active.

## Implemented input contract

`Plan.evidence_domain=code_regression` represents an isolated functional assertion
failure. It is restricted to stability/fixed_test_failures, a complete frozen
case inventory, at least one failure, zero errors/skips and a source/gold/report
binding. It does not create online samples or synthetic paired groups. Existing
online20/synthetic5 gates, protected paths/types and soft/hard scope limits remain
applicable. Actual execution still requires independent FileReview.

`review_dossier.compile_dossier` reads the exact development template, baseline
request and completed isolated outcome. It verifies the source/gold/plan, task
catalog, report, matching container cleanup and actual checked copy. The reviewer
receives complete selected source and test text within a24000ASCII-byte model
view, marked untrusted and recommendation_only. Oversize or credential-shaped
material is rejected before model execution. Host paths and credentials are not
supplied as configuration fields in the model view.

The returned dossier has authority=none; it neither writes an approval nor calls
a model/starts a container. An assertion failure alone does not prove the test's
expectation is correct; the separate reviewer must assess existing behavior and
can reject or ask for evidence.

## Paid review and exact authorization

A reviewer recommendation binds immutable semantic scope: run/root/source/gold/
plan/policy/runtime/limits. Its hash excludes the latest fee checkpoint, review
publication location/hash and a deadline that may only decrease under a frozen
ceiling. Changing file scope, limits, source, policy or execution root changes the
semantic identity. The future host issuer must separately validate its allowed
publication location and current canonical fee/legacy holds.

A paid review changes the original fee checkpoint. The readonly template/dossier
API can revalidate at an explicitly provided current fee hash without changing
the frozen input or granting permission. Actual `prepare()` still requires the
config's exact checkpoint and independent review; using the readonly override on
that execution path is prohibited. The host issuer will publish a new exact
FileReview only after verified review and current-state checks. Model JSON is
never copied directly into an approval file.

## Implemented independent SDK recommendation (not activated)

`sdk_review_launcher.execute` uses a fresh fixed no-tool session and the original
model gateway/ledger. Strict role, root ACTUAL permit, original50CNY/nineholds,
frozen dossier/source/runtime/policy/credential and an at-most120second/one-call
limit are checked before forwarding. It validates authenticated SDK/RPC output,
strict copied identities, cleanup and preserved financial history, then restores
the exact owned policy. An existing output claim prevents replay, even after
partial execution. Intent files and directory entries are synced before payment.

The strict report is a recommendation only: approve/reject/needs_evidence.
No FileReview or development config is written. Host audit retains a bounded
decision/reason, original known charge, model count and dossier hash; private
model commentary is not exported. Invalid output, missing usage, cleanup or
revocation remains failed/blocked without permission or automatic retries.

## Remaining wiring

The semantic lease/publisher, new test proposal
and real baseline coordinator, original manager admission and actual autonomous
handoff still need implementation/acceptance. Candidate acceptance uses a separate
candidate/diff-bound review; a pre-development recommendation cannot approve a
finished candidate. Product adoption/release and ownership-safe recovery retain
their explicit authorization and actual-validation requirements.

## Exact authorization core (publisher still pending)

`review_issuer.development_review(lease, config, request, current_fee, now=...)`
validates data already authenticated by a trusted host. It does not authenticate
an arbitrary lease, construct one from model output, read/write permission files,
contact a provider or start development. No entry point currently activates it.

The closed lease binds reviewed semantic scope and a deadline ceiling, independent
review identity, expiry, host prepared-config parent and original fee snapshot.
The exact request must match config/plan/base/run/task and the host-owned
`prepared/<task>/config.json` / `review.json` location. All semantic changes reject;
only the latest fee checkpoint, lowered remaining deadline and controlled review
publication location may differ. Existing FileReview validation accepts the
returned exact review structure, after the future publisher authenticates it.

Fee refresh preserves every original operation, event prefix and effective
limits. At most one explicitly identified selection model operation may be
appended, and it must have known usage, a completed settlement and nonnegative
known charge. A different operation, modified history, new unknown or a changed
prepared checkpoint rejects. ACTUAL retains the canonical original50CNY ledger
and nine historical holds. Hashes detect inconsistent data; they do not prove
that an untrusted producer is honest.

The remaining publisher must authenticate root policy and actual independent SDK
receipts, revalidate frozen inputs, hold its own publication and original tools
locks, fsync an exclusive intent and retain uncertain partial publication without
replay. It must not wait for the maintenance lock while the manager waits for
FileReview. SDK recommendation-only permits cannot substitute for host execution
policy, and this pre-development lease cannot approve the finished candidate.

## Host lease and external FileReview prototype (not activated)

`review_lease.create` authenticates an independent review against a separate host
execution policy. ACTUAL policy is root-owned0640 in a root-owned0750 parent,
binds a finite reference-source hash/file scope, original runtime/policy/credential
and canonical50CNY ledger/nineholds, private host roots, phase limits and expiry.
A recommendation-only SDK permit does not replace this execution policy.

The host replays verification of the stopped SDK session/RPC against its frozen
initial input and relayed request, checks the strict approve report and private
manifest, then matches the one known paid request to before/after original fee
snapshots and cleanup. A fsynced exclusive claim precedes its immutable private
lease. Neither construction nor publication pays for another model request.
Complete reports and fee snapshots remain private; they are not admin exports.

`review_publisher.publish` rechecks this provenance, frozen prepared config and
request, current policy/fees, and the semantic scope. It uses a separate
publication lock and the original tools lock, never maintenance.lock. Final
FileReview appears atomically and exclusively after fee-lock release, allowing
the original development adapter to acquire its own fee lock. Development still
checks the exact fee pin, so concurrent changes reject execution. Partial claims,
conflicts and uncertain publication are retained without overwrite/replay.

A distinct host review event records actual issuance with dossier/lease/exact
review evidence. It does not overwrite the independent SDK request/cost counters.
The original FileReview and FrozenDevelopmentAdapter thread-wait path has been
verified in SIMULATED tests, without new provider requests or a started candidate.
This is not server activation or actual autonomous handoff acceptance.

Still required before ACTUAL activation: bind the gateway-generated selection
attempt ID from a verified completed selection receipt (it is a UUID allocated
at reservation and cannot be guessed before selection), issue the separately
bound selection-config review, connect refreshed templates and the coordinator,
and verify new-task/candidate acceptance. The current prototype's explicit
selection_operation_id is a host-provided synthetic test identity, not evidence
that this pending actual binding is complete. Do not admit paid work using a
placeholder ID. Whole-plan final independent review and actual closed-runtime
acceptance remain pending.
