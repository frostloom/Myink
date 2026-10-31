# Pi Live Observer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, task-by-task, with TDD and one fresh final reviewer. User explicitly authorized continuous work without stage questions; do not create implementer subagents or new branches.

**Goal:** Enable real, least-privilege production metric collection on a timer and publish honest, versioned audit output without making model calls or changing product data.
**Architecture:** Fixed PostgreSQL metadata views and NOLOGIN role → pinned Docker/psql SELECT transport → existing collect_snapshot → immutable private source snapshots and audit v1. Preserve missing historical identity and insufficient samples; this observer produces evidence, not execution approval.
**Tech Stack:** Python3.12 standard library, PostgreSQL16/psql, existing Docker and systemd; reuse existing metrics engine. No new Python runtime dependency.
**Spec:** docs/superpowers/specs/2026-10-28-pi-online-closed-loop-design.md, phase2. Audit foundation is already complete at cee9c65d with3133Pi tests/4CI and actualaudit004 verification.

## Global Constraints
- Worktree /Users/a1/.codex/worktrees/myink-pi-current/Myink, branch codex/pi-autonomy-design; preserve other changes. Commit/push authorized, no mainmerge/productrelease/adminpage changes.
- Canonical server original fee/manager remain /home/ubuntu/myink-pi-managed/state;761attempts,9unknown18115200microyuan held, cumulative50000000microyuan cap, used22816453. No new paid calls/scope/credential access in this plan.
- Models receive no SQL, Docker, DB or installer capability. Trusted host executes fixed SQL under nonprivileged NOLOGIN role; never open arbitrary network endpoints or render model text as SQL.
- Public/raw user bodies, auth/password/provider secrets and whole detail JSON are excluded at the database view boundary. Metadata projection is typed/bounded; role has no product-table write or raw-table SELECT grants.
- SQL readonly/repeatable-read transaction, statement timeout≤5000ms, host call≤10s, bounded pages/bytes/window≤120s. Collect at most2pages of500rows per source by default; mark truncation unknown.
- Source role/view conflicts, extra privilege, timeout, daemon/container/image change, malformed/missing output fail explicitly and publish blocked/unknown audit. Never reset a ledger, replay paid intent or count empty/unknown as success.
- Historical version fields stay unknown; do not synthesize generation1 or backfill current deployment onto old runs. Mixed task types, <20same-type complete samples and p95<100 cannot certify improvement.
- This plan ends with actual online timer/evidence only. Automatic task review/development/release/recovery and approved nextday fixed-check execution remain root-goal work; original2026-10-29T03+08 followup staysplanned until genuinely executed.
- Local PG test uses a unique owned networknone container/no publishedports, pinned local image7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a; do not touch fixed myink-test resources. Explicit integration is not a claim that all19existingpi_lab tests ran.

## Review Focus
- Existing role/schema or PUBLIC/inherited privileges must not silently widen source access or alter product permissions.
- JSON values/IDs/SQL parameters with quotes, oversized metadata or forged role receipts must not become SQL or leaked raw body.
- Parent-path aliases, failed publish, concurrent manager idle logs and duplicate windows must preserve original evidence and last good export.
- Missing provenance, mixed source versions/types, zero-vsunknown, empty/truncated pages and deadlines must not create fabricated measured improvements.
- Timer/worker lacks model/provider credentials, cannot run candidate code, and remains read-only even when host transport holds Docker authority.

### Task 1: Fixed SELECT contract and real isolated PostgreSQL proof
**Files:** Create ops/pi/metrics_query.py, ops/pi/metrics_sql.py, ops/pi/psql_metrics.py; modify ops/pi/db_reader.py metric-validation method only; tests ops/pi/tests/test_psql_metrics.py and ops/pi/tests/integration/test_live_metrics_pg.py.
**Interfaces:** validate_metric_request(request)->None preserves existing metric SQL forms; metadata_bootstrap_sql()->str creates exclusively pi_metrics views +myink_pi_metrics NOLOGIN role; PsqlMetricsReader(config,run=None).__call__(request)->list[dict]. Config exact fixed docker/endpoint/daemon_id/container_id/image_id/database/database_user/view_sha256 fields, not model supplied. Source tasks/agent_runs shapes remain metrics._PROJECTIONS; timestamps converted to aware datetime.
- [ ] RED tests fixed valid query/typed bounds, arbitrarySQL/unknownparams/typebool injection refusal, parameter quoting as data, role/view mismatch, hostile metadata/output/timeout, no arbitrary CLI command.
- [ ] Implement pure validator delegated by existing SQLAlchemy reader; fixed bounded metadata DDL and transport. Reuse existing collect_snapshot rather than duplicate metrics calculations.
- [ ] Explicit isolated PG integration RED→GREEN: actual role flags/view projection, planted private_body absent, direct users/agent_runs reads and product writes denied, timeout enforced, all role/view install steps rollback on conflict. Own container cleanup in finally; use separate pi_observer_pg marker and --pi-observer-pg opt-in, deselect it from default offline suite and run this file explicitly; originalpi_lab guard unchanged.
- [ ] GREEN relevant existing metric/db_reader tests and new tests; commit. Expected: no production connection/DDL yet, no shared resources/ports affected.

### Task 2: Bounded live observation and audit publisher
**Files:** Create ops/pi/live_observer.py; tests ops/pi/tests/test_live_observer.py; use ops/pi/audit.py and audit_export.py unchanged unless a concrete compatibility test requires a fix.
**Interfaces:** ObservationIdentity is a separate frozen observation-only dataclass with nullable deployment/generation/owner/commit/schema/config and observed image IDs (not release Identity). observe(config_path,*,clock=None,reader=None)->receipt freezes a completed time window, calls existing collect_snapshot, writes a ≤1MiB private metric aggregate and audit observation/version events, exports audit v1. Injected reader is allowed only in SIMULATED test mode; ACTUAL selects pinned PsqlMetricsReader. CLI is one bounded tick, not a model loop.
- [ ] RED tests real-vs-simulated binding, missing identity, insufficient/mixed cohort, null-vszero, row/page truncation, failed collection and immutable duplicatewindow, atomic last-good audit export, source/path drift and source byte limits. Source/fee/manager must remain readonly, no credentials or raw bodies copied to reports.
- [ ] Implement strict private config and host-only observer, with capability/version inventory event on activation. Fixed-window identity includes source/config, not completion timestamp; completed replay returns old facts, conflicting input refuses. Failed ticks retain unique failure evidence instead of falsely succeeding.
- [ ] Preserve aggregate artifact hash and explicit evidence_domain=online_business only for actual production transport. Unknown historical provenance remainsunknown; mixed task types prevent comparable claims. Use existing observations intake only if its source-tree binding is actually known; otherwise retain investigation/insufficient_evidence output, never invent source_sha256 or approve a task.
- [ ] GREEN new +audit/metrics/proposal compatibility; commit. Expected: pure main reader consumes new evidence while originalcap/unknownholds remain unchanged.

### Task 3: Timer, deployment and actual online acceptance
**Files:** Create ops/pi/deploy/myink-pi-observer.service and .timer, ops/pi/deploy/observer_entry.py with tests ops/pi/tests/test_observer_entry.py; modify ops/pi/live_observer.py CLI/ACTUAL expected-config pin and its tests; update ops/pi/deploy/README.md, docs/pi/agent-enhancements.md; tests ops/pi/tests/test_live_observer_deploy.py; evaluation docs/evaluations/pi-live-observer-2026-10-28.{md,json}.
**Interfaces:** observe(...,expected_config_sha256=None) requires the exact file digest in ACTUAL mode; CLI --config-sha256 comes from root-owned unit environment, not model input. Root-owned frozen observer runtime/unit; private0600 service-readable config pinned by a root-owned expected SHA; trusted Ubuntu host with service-only Docker group uses fixed daemon/container, no provider credentials, read-only originalstate/jobs/runtime and writable private observations/audit only. Timer every15minutes, one tick≤120s, no Restart/model retry. Separate source DB bootstrap is a trusted installer with private receipt and exact own-role/view removal instructions; no broad GRANT/REVOKE or CASCADE.
- [ ] RED unit/config scope, no-network/provider settings, bounded timer/runtime and correct readonly/writable mounts. Build new closed runtime, do not modify manager runtime005 or prior audit failures.
- [ ] Isolated PG proof from Task1 must pass before production bootstrap. Read production metadata only to verify known role/schema absence/compatibility, then transactional own-view/role install. Record exact DDL/version/owner/projection digest and verify SELECT/directread/write/timeout boundary on production without modifying product rows.
- [ ] Deploy observer timer and run actual ticks. Original fee operations/events/limits exactunchanged; manager operations/eventprefix preserved and any intervening extra events must be independently verified zero-dispatch manager_run, not silently ignored. Audit failures/empty/unknown snapshots retained. Verify service/timer, source image/container identity and unchanged product health.
- [ ] Actual downloaded redacted export is read by main standalone reader; update capability availability implemented/deployed/active accurately. At least two genuine production observations on distinct windows, no fabricated improvement. Fixed nextday test remainsplanned until next independent executor plan.
- [ ] Full related/offline regression, one fresh final reviewer for this independent plan, one authorTDD fixpass/no rereview, exactHEAD fourCI/push. Archive all proofs and planledger; mark only this observer plan complete and continue rootgoal.

## Pre-flight interface check
Task1 callback returns the exact dict/datetime projections consumed by existing collect_snapshot; Task2 produces auditv1 records accepted by the already-tested puremain reader; Task3 deploys only those fixed host components. Separate nextday executor must use an independent host-approved registry: audit_only plans cannot authorize execution. Hindsight service unavailable at phase start, so skip and use the durable project ledger.
