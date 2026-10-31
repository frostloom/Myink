# 本机维护任务接力 Implementation Plan

> Execute inline with executing-plans; tests before code; fresh independent final review. No automatic Git operations.

Spec: ../specs/2026-10-24-pi-maintenance-handoff-design.md

Files: new ops/pi/maintenance_handoff.py contains strict task/proposal contract and finite durable coordinator; new ops/pi/tests/test_maintenance_handoff.py covers real SQLite claims and existing preflight integration; docs/pi/local-development-launcher.md documents API scope and remaining real-adapter gate. Existing development_launcher.execute adds only optional expected_authorization_sha256 with a pre-side-effect check; plans/budget/permissions/product code remain unchanged.

- [x] Snapshot dirty files and inspect existing iteration/engine/development inputs/launcher contracts.
- [x] Add failing strict catalog/proposal and handoff tests. Observe RED before implementation.
- [x] Implement minimal API and atomic cycle claims, reuse _run_action for stages. Protect current identity, no replay, shared monotonic deadline/cancel, ledger alias before constructor, host adapters, exact baseline.reproduction/preflight and actual-result binding before stage done.
- [x] Add adversarial/concurrency/cancellation/remaining-time/ledger-separation tests and real existing preflight integration. Resolve failures through TDD.
- [x] Run focused then full ops/pi/tests suite plus existing Node scripts. No unrelated product test stacks or real paid calls for this host-only change.
- [x] Fresh independent full change review; fix Important with regression. Recheck all required evidence after last code fix.
- [x] Document exact verified scope, limitations, preserved files and next real-adapter gate; retain Myink memory. Keep Pi branch/worktree, no commit/push/merge/deploy.

Completed:65 new tests,113 focusedPASS,2402 fullPiPASS/19deselected,4Node passed. Two Important RED→GREEN and static re-review clean. Actual live adapters/chain not claimed; no new real calls/budget/Git/server. See evaluation report.
