# Versioned Pi selection semantics acceptance (2026-10-27)

The selection prompt now distinguishes reproduced pre-repair assertion failures from test errors or insufficient evidence. New frozen cycle bundles explicitly choose version 2. Missing versions preserve the exact version 1 system; old approvals, sessions, billing and abandonment proofs retain their original meaning. Null remains legal. No tools, development permissions or adoption were added.

## Matched real selection experiment

Five repeated pairs of **one** frozen synthetic NFC task, with version order 1/2, 2/1, 1/2, 2/1, 1/2, were preregistered before execution. Source, gold, parsed catalog, task problem, baseline (5 cases, 2 assertion failures, 0 errors/skips), model, output cap and wire limit were fixed. Unique IDs, reviewed authorization/context hashes and current ledger checkpoints necessarily differ between calls. The new catalog serialization differs from the previous stage, but its parsed object and canonical digest match exactly and its bytes were pinned before all ten trials.

- Version 1 selected 2/5 and returned null 3/5; version 2 selected 5/5 and returned null 0/5.
- All 10/10 scheduled results retained; 10 real model attempts, 21424 microyuan estimated known fees (CNY 0.021424), zero new unknown fees.
- Ten fresh independent selection approvals; 120 seconds and one no-tool call per trial, parent limit 1800 seconds; observed parent duration 907.33 seconds including independent reviews.
- 10 owned containers and 10 operation labels directly confirmed absent on the pinned daemon.
- No retries, development calls, candidate adoption, main merge or deployment. Original policy restored closed; credentials, manager ledger and historical billing rows/events prefix unchanged. Nine historical unknown fees remain reserved.

| Pair | v1 selected | v2 selected |
| --- | --- | --- |
| 1 | False | True |
| 2 | True | True |
| 3 | False | True |
| 4 | True | True |
| 5 | False | True |

Full descriptive call counts, null reasons, fees, request sizes and wall times are in the [sanitized JSON](pi-selection-semantics-2026-10-27.json). Private request/session/RPC, approvals, checkpoints and cleanup proofs are retained locally.

## Verification and interpretation

Twelve new regression cases were observed failing before implementation. Final Pi offline suite: 2825 passed / 19 opt-in cases deselected, Node: 54 passed, compileall and diff checks passed. One independent final code review found no issues; reviewer focused suite: 175 passed. The initial unmarked pytest command was rejected by the opt-in collection guard, with no tests run. The corrected offline suite passed. The core commit passed all four original remote CI gates: [40466065103](https://github.com/frostloom/Myink/actions/runs/40466065103). Product/service-backed tests were not run locally; their current core validation is remote.

This is descriptive evidence from one task repeated five times per version, not five distinct tasks, a general production success-rate increase or a causal efficiency estimate. Balanced order does not remove model sampling variance or temporal effects. Wire sizes and fees are raw observations; no token saving or latency improvement is claimed. Selecting a task does not prove its repair is correct. Upstream Pi 1.1.0 core is unchanged.

Next acceptance should broaden to distinct fixed task types and authenticated development/checker outcomes while retaining legal abstentions and independent adoption boundaries.
