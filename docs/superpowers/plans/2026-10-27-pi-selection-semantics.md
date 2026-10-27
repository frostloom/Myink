# Versioned Selection Semantics Implementation Plan

> Use executing-plans inline with one fresh independent final review.

Goal: clarify positive failed-baseline reproduction evidence while retaining abstention and historical proofs.
Spec: docs/superpowers/specs/2026-10-27-pi-selection-semantics-design.md

- [x] Add failing tests for reviewed prompt_version routing, unsupported types, current bundle default, legacy audit replay and cross-version wire rejection.
- [x] Implement fixed v1/v2 systems in selection_launcher; explicit v2 in cycle_bundle; original-version reconstruction in selection_abandonment. Preserve all budgets, raw artifacts and null contract.
- [ ] Independent final code review; author red/green fixes; full Pi/Node checks. Freeze new runtime and preregister five matched pairs of a single NFC fixture; fresh independent review/checkpoint per actual selection call, max10/1800sec, no retries.
- [ ] Audit all outcomes/fees/resources, record descriptive paired counts and limitations, push existing Pi branch, confirm latest four remote CI gates.

Review focus: absent vs bool/unknown versions; no reinterpretation of old approvals; version included in authorization and frozen wire; no untrusted text becomes permission; null remains valid; pairing does not silently alter source/gold/model/budget or drop failures.

Implementation verification: 12 new cases observed RED before implementation; final full offline suite 2825 passed / 19 opt-in tests deselected (not executed), Node 54 passed, compileall and diff checks passed. Independent final reviewer reported no findings; reviewer focused suite 175 passed. Runtime and preregistration frozen before actual calls; each actual call waits for independent selection approval. Initial unmarked full-suite invocation was rejected by the opt-in collection guard with no tests run; corrected to the offline marker filter. No product/service suite run locally.
