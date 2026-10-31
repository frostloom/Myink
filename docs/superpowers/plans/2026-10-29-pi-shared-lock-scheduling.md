# Pi Shared Lock Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans inline, TDD, one fresh final reviewer and one author fixpass/no rereview. User authorized continuous decisions and commits/pushes; no implementer subagents.

**Goal:** Let diagnostics and due fixed regressions obtain the existing shared maintenance lock promptly when the original manager has no work.
**Architecture:** Use the existing manager CLI's idle_seconds=0 and the existing60second systemd timer. Each tick performs one inbox scan and exits if idle; genuine admitted development keeps the same exclusive lock and2100second host bound. No lock is removed or narrowed during actual execution.
**Tech Stack:** Existing Python manager and Ubuntu/systemd255 service configuration.
**Spec:** docs/superpowers/specs/2026-10-28-pi-online-closed-loop-design.md phases2/3/5 and the actual live-diagnosis001 lock contention observed during postpilot acceptance.

## Global Constraints
- Pi worktree/branch only, no mainmerge/product release/admin UI/auth changes.
- Keep original manager/canonical fee state, cumulative50CNY and9legacyunknown holds. Current actual diagnostic001 added4952microyuan:762attempts, feeSHAfe7c37ea1259b0d92d51524d818703a7063a953e54e53b062dbc36b6eb844afb. Never restore oldera818fee.
- Original manager005 runtime and credentials remain immutable; only the root-owned service's already-supported idle argument changes. Preserve source service.env and all execution/cleanup/approval limits.
- Original observer004, diagnosis001 and followup004 configs/registries stay pinned. Actual Oct29 03:00 followup remains pending until real receipt; do not move its due time or reset claims.
- Preserve complete failures/idle/cancellation events and old service configuration. A claimed/unknown task cannot be replayed. New service config version is distinct from product/SDK/source versions.

## Review Focus
- Idle0 still polls a ready inbox once; it must not prevent already approved work from entering the existing manager.
- An empty queue returns promptly and releases both manager and external service locks.
- Keep max_tasks1, host seconds2100, RuntimeMax2400, Restart=no, identity/Docker group, paths and original authorization gates.
- Never cancel an actual dispatch or replay a completed one to demonstrate scheduling; use idle ticks only and preserve original event prefixes/fees.
- Actual old process may retain600seconds until its natural exit. Record this explicitly; verify new config took effect from real service command/results, not only the file content.

### Task 1: Existing single-scan manager semantics and service contract
**Files:** ops/pi/deploy/myink-pi-manager.service, ops/pi/tests/test_manager_scheduling.py, docs/pi deployment notes.
- [x] RED service contract requires idle_seconds0 while all existing bounds/paths remain.
- [x] Verify existing CLI0 makes exactly one empty/ready inbox poll and promptly releases its manager lock without fees (synthetic fixtures only).
- [x] Change only service idle argument600->0, document normally-next-tick admission when idle/uncontended, plus accuracy/scheduling and contention delay and quiet idle behavior. Target manager/signal/diagnosis/followup tests.
- [x] One fresh final review, one author fixpass, preserve all findings/minors/declines. Commit/push with exact CI.

### Task 2: Actual owned host scheduling acceptance
**Inputs:** exact root-owned current service digestb02efe12567776c854f3a6fce98452a194e91052ced78aa9ee4622ec32035da1, canonical ledger/current manager snapshots, closedpolicy, original service.env; verified new service artifact.
**Outputs:** private intent/old service/actual timing receipt, readonly audit version+test events, public dated evaluation.
- [x] Check queued/inflight status and preserve old root unit. Install reviewed service, systemd verify/reload; keep current actual work protected. Prefer natural idle completion; do not restart a dispatch.
- [x] Observe at least2new idle ticks (one actualtimer-generated), each0dispatch/0fee/unchanged original tasks, prompt exit and shared lock obtainable. Record actual durations and exact unit digest.
- [x] Verify observer/diagnosis/followup timers and registry pins unchanged, readyz normal, original fee and manager prefixes intact; append config version/change scope and actual acceptance audit.
- [x] Publish evaluation/exact HEAD4CI, preserve failed attempts, archive only this completed plan workspace after verifiedcopy. Rootgoal staysactive for automatic source-bound task/review/dev/release/recovery and cross-day acceptance.

Completion: source7970f31a/4CI40733978564;112related+3finaltests passed;freshreview0C/0I/2M accepted once/no rereview. Actual2automaticidle ticks485.888/502.689ms with2external-lock acquisitions,0model/fees, exactoriginalruntimec097 preserved. Configunit45ed3ba9...only1livefile+1/-1. Fullrootgoalactive;due03followupunchanged.
