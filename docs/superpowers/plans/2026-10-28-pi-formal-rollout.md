# Pi Formal Rollout Implementation Plan

> Use executing-plans inline, one fresh final review of concrete service/cutover implementation.

**Goal:** Actual Pi service, original state custody, realprovider job and post-launch checks.
**Architecture:** Existing fixed SDK/container pipeline + cancel-aware finite manager CLI/systemd; concrete readonly backup/restore before canonical cutover.
**Tech:** Python3.12,Node24.22/Pi1.1,Docker,SQLite,systemd255.
**Spec:** docs/superpowers/specs/2026-10-28-pi-formal-rollout-design.md

## Constraints
- Originalmanager/billing,50CNY and9unknown holds; no new scope,mainmerge or unrelatedmessages.
- All newunits/runtime/source archives exclusive; no existingtarget overwrite.
- Source freeze only after concrete readiness; immutable historical/evidenceprefix.
- No candidate execution/import on host; onefreshfinalreview/oneauthorfixpass.

## Review Focus
Signal cancellation/cleanup and handler lifecycle; NoNewPrivileges/Docker/TMPDIR compatibility; state/path/secret isolation; exact original custody and consistentrestore; no paid fork/replay; finite owner jobs and posthealth.

### Task 1: Safe finite service and runtime
- [x] RED realSIGINT/SIGTERM empty-queue subprocess cancellation; minimal CLI handler GREEN plus manager compatibility.
- [x] Concrete hardened .service/.timer, systemd-analyze validation; newfullruntime fixedbytes/native/2SDKmock+cleanup/productionunchanged.
### Task 2: Backup/restore and canonical cutover
- [ ] Consistent originalstate readonlybackups+requiredraw audit/review/policy, serverreadonlyrestore/schema/tuples/holds; no credentials or paid authority.
- [ ] Finalfreshreview of concretecutover/service; oneauthorRED/GREENfixpass, appropriatefullchecks.
- [ ] Originalsourcefreeze/export,targetactivate/apply/privatecredential, serviceenable; preserveallhistory andfailedstates.
### Task 3: Actual provider and post-launch proof
- [ ] Fresh bounded independentlyadmitted realtask, finalcheck/status/session/protocol/cleanup/policyclose+50budget.
- [ ] Idle service stop/restart0repeat, exactlatestrestore rehearsal, logs/health/ownresources/produnchanged; publishmetrics/push/exact4CI.
- [ ] Requirement-by-requirement goalaudit. No synthetic/narrower completion claim.
