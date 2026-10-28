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
