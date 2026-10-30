# Current human approval hold — 2026-10-30

The operator changed the delivery boundary: prepare one evaluated candidate,
local image and next-day comparison parameters, then wait indefinitely for human
confirmation. GitHub/registry pushes and product deployment require approval of
that exact package. Approval alone does not start observations: actual deployment
must be verified first. No new nightly round while confirmation/deployment or the
current comparison is pending. See
[the current specification](../../../docs/superpowers/specs/2026-10-30-pi-human-gated-nightly-design.md).

All seven installed Pi timers were disabled and their services stopped; a fresh
2026-10-30 read confirmed seven `disabled` results and no active Pi services.
Product services were left running. **Do not use the historical resume commands
below to restart the old pipeline.** They describe the earlier operating contract.

The new unit templates use `--human-gated`. After runtime source verification the
entry checks `nightly-approval.sqlite` against the original manager/fee identity
before importing the requested host. Missing/invalid metadata fails closed;
waiting, idle and blocked cycles do no scheduled work. Only a claimed preparation
admits the existing preparation pipeline. Only a verified deployment admits
observers and fixed follow-up checks; it does not admit a new development round.

These templates and the gate have not yet been installed/activated on the host.
The single-cycle driver and private package sealing are implemented locally,
with original-manager proof, a single immutable task binding and relative
next-day parameters. The real server package is sealed in awaiting_approval;
postdeployment binding and finite source issuance are locally implemented.
Operator-pinned templates, approved installation and actual postdeployment
qualification remain required before enabling this workflow. Keep the existing
timers off.
Do not initialize another manager, billing ledger, budget or historical intent.
The new `myink-pi-nightly.timer` template has calendar-only night checks and no
boot catchup. Actual approval metadata format7402 already exists and contains
the pending candidate: never reinitialize it. Only a genuinely new, absent
metadata file may be initialized as the original Ubuntu state owner during a
verified handoff; never reinterpret an older file or either original
financial/task ledger as approval metadata.

# Server unit contract

These units target the verified Ubuntu/systemd255 host. They are installed only after
runtime, original-state backup/restore, exact custody transfer and credential checks.
Do not initialize another manager or enable the timer against a backup.

The root-owned service environment contains only exact runtime/dependency PYTHONPATH,
not provider credentials. Existing credentials stay in the private state directory
and are loaded by trusted host code. The model worker receives neither Docker socket
nor host credentials and keeps its existing UID65534/network-none containment.

The trusted host process gets Docker's supplementary group only in this service;
the login user's groups are unchanged. NoNewPrivileges remains enabled. Docker
group access is root-equivalent for trusted host code, so runtime/config are immutable
and candidate code must never execute there. This does not protect against malicious
root or a compromised trusted controller.

TMPDIR is explicit: PrivateTmp's namespace must not hide paths passed to the Docker
daemon. The maintenance lock is outside movable state. Stop the timer, stop the
service and take that lock before state maintenance. Do not restore an old billing
snapshot over later writes; only an exact latest quiescent checkpoint is eligible.

SIGTERM sets the existing manager cancel Event. KillMode=mixed gives the main process
time to close its workers/containers; after the finite stop grace systemd kills
remaining host children. Docker objects are separately ownership-checked by the
controller. A blocked/uncertain job remains a failure; Restart=no avoids automatic
transport retry. The timer cannot bypass unresolved-state or original50CNY guards.

Validate with systemd-analyze verify on the actual host before installation.
References: [execution sandbox](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html),
[service lifecycle](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html),
[timer lifecycle](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html).

The manager has 2100 seconds for an admitted cycle capped at 1800 seconds; startup, registration and graceful unwinding consume the difference. RuntimeMaxSec=2400 is an outer stop fuse. Equal manager/cycle=1800 bounds are unusable because preflight compares against remaining time after startup. A queued task with no dispatch may proceed after the host margin is corrected; never replay an existing dispatched intent.


## Current owner and operations

The original local ledger is frozen archival state. The active original ledger and
manager are under /home/ubuntu/myink-pi-managed/state on the configured SSH host
alias myink. Do not initialize another manager or reactivate a local copy. The
selected runtime is releases/rollout-20261028-005; systemd loads its nonsecret
PYTHONPATH from the root-owned config/service.env.

Inspect the finite service/timer and its logs:

~~~sh
ssh myink 'systemctl status myink-pi-manager.service myink-pi-manager.timer --no-pager'
ssh myink 'sudo -n journalctl -u myink-pi-manager.service -n 50 --no-pager'
~~~

Stop the timer before the service for maintenance; take control/maintenance.lock
before changing state. Successful idle runs may leave the service inactive until
the timer fires. An operator stop records cancellation and may show exit1; this
does not authorize a model retry.

~~~sh
ssh myink 'sudo -n systemctl stop myink-pi-manager.timer'
ssh myink 'sudo -n systemctl stop myink-pi-manager.service'
~~~

Resume the existing owner:

~~~sh
ssh myink 'sudo -n systemctl start myink-pi-manager.timer'
ssh myink 'sudo -n systemctl start myink-pi-manager.service'
~~~

Global policy remains closed. A fresh, bounded task requires frozen source/tests,
a fresh isolated baseline, separately bound independent selection/development
reviews and an exclusive inbox admission. Approved execution opens only its
in-memory phase gate. Unknown billing, protocol or cleanup uncertainty stops work;
do not edit terminal records, release historical holds or replay a failed intent.

Launch evidence lives in control/postlaunch-health-receipt.json,
control/latest-restore-drill-receipt.json, control/cold-restart-receipt.json and the
private job directory. Per-task session/tool/checker evidence, append-only fee
history and manager run events remain the detailed record. The archived launch
receipt is a checkpoint, not a replacement for querying current status/ledger.

For restore, stop both units and take the external lock. Use SQLite checkpoint
completion, not manual WAL deletion; require that both canonical logical
snapshots still equal the latest captured checkpoint before replacement, and
verify owner, history, unknown holds, budget, policy and credential hashes after.
Never restore a stale financial snapshot over later writes.
See [SQLite checkpoint semantics](https://www.sqlite.org/pragma.html#pragma_wal_checkpoint).

## Fixed metadata observer

The observer is a separate, read-only sidecar, not the paid manager. Its code is
implemented and locally verified; production activation must have its own dated
receipt. Do not infer live activation from this template or from a green test.

`myink-pi-observer.service` runs one tick (120 seconds maximum) every 15 minutes.
It uses a root-owned closed Python runtime, `-I -S -B`, no provider credentials,
private networking restricted to Unix sockets, and a dedicated nonblocking lock.
Only observations, audit state/export and that lock are writable. Original fee,
manager, jobs, config and releases remain read-only; provider credentials are
inaccessible. The trusted host's Docker group is root-equivalent authority; the
model has no Docker or SQL capability. The host transport only executes its fixed
PostgreSQL metadata query protocol under the dedicated NOLOGIN role.

The service-readable JSON config is `config/observer/observer.json`, inside its
own0700 Ubuntu-owned child directory of the root-owned shared config directory.
The file is private0600, pinned by the exact SHA256 in a
root-owned `config/observer.env` (`PI_OBSERVER_CONFIG_SHA256`). That environment
also pins the root-owned entry point and `PI_OBSERVER_RUNTIME_SHA256`. Do not put
keys, passwords, billing configuration or arbitrary commands in this config.
ACTUAL calls require the expected config digest and reject an injected source;
SIMULATED calls require a test callback. The latter are not cloud evidence.

Before provisioning, verify the exact Docker daemon, PostgreSQL container/image,
PostgreSQL16, product health and absence of conflicting role/schema. Run the owned
standalone PG tests explicitly with `--pi-observer-pg`; the original guarded
`pi_lab`/paid gates remain unchanged. That test creates no host ports, records its
ownership before Docker creation, keeps failure logs and removes only its own
operation-label containers. Its synthetic environment is not production.

Provision only `myink_pi_metrics` (NOLOGIN/NOSUPERUSER/NOCREATEDB/NOCREATEROLE/
NOREPLICATION/NOBYPASSRLS/NOINHERIT) and the two `pi_metrics` security-barrier views
from `ops/pi/metrics_sql.py`. The transaction refuses unknown existing objects;
never use CREATE OR REPLACE, CASCADE, or broad product GRANT/REVOKE to get past a
conflict. Freeze the approved canonical view definitions, security options and
ordered column types into the config's `view_sha256`. Probe fingerprinting pins
its search_path. The transport checks the role flags/membership, effective raw
privileges, definition digest, read-only transaction and source identity on every
query, with a server statement timeout<=5seconds. It sets its own session bounds;
SET ROLE alone does not apply role configuration defaults.

Views exclude raw detail/body/credentials and project bounded, typed metadata
leaves. Credential-like and encoded-body identifiers become null, not copied
text. The reader sends parameters as quoted psql variables, not SQL. Host calls
have a10second deadline and a4MiB output bound; default snapshots use2pages of500
rows, preserve truncation/confounders and cap the private aggregate at1MiB.
Unknown historical deployment information stays null. Mixed/incomplete cohorts,
missing provenance and fewer than20same-type complete samples are insufficient;
p95 is unavailable below100 samples. No observation admits or approves a repair.

Each tick freezes one completed time window; identical replay uses the prior
receipt and source digest without querying again. Incomplete windows remain
pending rather than being silently overwritten. Publication failures preserve the
last good audit manifest and original artifacts. Set `export_root` explicitly to
the existing private audit export, separate from the writable audit database.
Main consumes auditv1 only, using its standalone reader and authenticated admin
routing; no static directory publication or execution capability is provided.

Rollback preparation: preserve installation receipts, exact DDL, view digest,
role flags, service/unit hashes and audit outputs. Disable only the observer
service/timer. Drop its two views/schema/role only after matching those receipts,
in a transaction without CASCADE; any extra dependencies or drift must abort the
whole cleanup. Never restore an older fee/manager ledger or change product rows.
The original manager and all uncertain reservations remain authoritative.

## Approved nextday fixed regressions

`myink-pi-followup.service` is separate from both observer and paid manager. The
same closed-tree verifier selects only the explicit `followup` component after
verification; the default observer component remains unchanged. A root-owned
`config/followup.env` pins `PI_OBSERVER_RUNTIME_SHA256` (the shared verifier),
`PI_FOLLOWUP_ENTRYPOINT`, and `PI_FOLLOWUP_REGISTRY_SHA256`.

The execution authority is a root-owned0640/root:ubuntu registry in the existing
root-owned0750 config directory, not the audit followup record. Registry entries
pin the original source, candidate, fixed gold/case list, independent acceptance
review, Docker daemon and immutable checker image. No arbitrary command or model
request is supported. Audit plans must match test/run/version/due time but cannot
supply execution authority. The registry is rechecked before claiming and after
checking. ACTUAL disallows injected clock/runner; SIMULATED callbacks remain
synthetic and cannot certify a real nextday result.

The5minute timer only wakes the worker. Actual admission requires genuine due
UTC time and02:00–05:30 Shanghai; completion must be before06:00 on that maintenance
date, within300seconds total. The checker itself has90seconds and capture<=30.
At most one new check starts per tick. The worker internally takes the existing
`control/maintenance.lock`, so do not add an outer flock on the same file. Busy
locks and early/outside-window wakes create no execution claim.

Only followups and audit state/export are writable; original state/jobs/config/
releases and the shared lock are read-only, provider credentials inaccessible,
network Unix-only. The candidate and gold run only in the fixed UID65534/network
none checker. It persists ownership before Docker creation and sweeps only owned
containers. Runtime/service/Docker host are trusted; the model receives none of
this authority.

The durable intent identity binds test/run/candidate and exact entry digest.
Fsync the claim parent after mkdir, then publish/fsync intent and its directory
before checking. A failed sync blocks execution; an incomplete directory is
retained as uncertain rather than reused. All writable destinations (claims,
audit database and export) must be disjoint from frozen inputs and canonical
state, including ancestor/descendant aliases. A
pending intent without final receipt is uncertain and never automatically
replayed. Preserve its staged checker, output, ownership and cleanup receipts;
reconcile only the recorded operation labels/daemon/image, then arrange a newly
reviewed test identity if a rerun is necessary. Never delete intent or rewind
fees/manager state to retry. Blocked/uncertain outcomes propagate to nonzero service exit and stop new work;
assertion failures are explicitly failed and also exit nonzero. Cached failures
retain those states without retry. A completed receipt verifies its own digest and
private outcome; re-reading it returns old facts without invoking Docker.

Append separate tool/test/version audit events and correlate true ACTUAL results
by test_id/candidate/due time. The original followup plan remains planned with a
separate result. A successful regression is neither a product release nor online
metric improvement. Pre-due deployment only proves scheduling; mark result null
until the actual due run. Disable only this timer/service to withdraw scheduling,
preserve all registry/claims/results, and never restore old canonical ledgers.

The fixed checker core is `ops/pi/fixed_checker.py`, using the standard library
and existing container/feedback primitives. Followup never imports the paid
development/analysis launchers or HTTP client. The SDK development launcher
retains its public `_fixed_check`/OwnedHosts wrappers, delegating the same core
with its existing host factory/cleanup hooks. Verify both dependency loading and
the three real Docker scenarios under `python -I -S -B`; a pre-due scheduling
check alone does not exercise the default checker imports.

## Shared-lock idle scheduling

The service uses the existing manager idle_seconds=0 mode and60second timer. An idle tick scans the inbox once and exits, leaving maintenance.lock available for diagnostics and due fixed regressions. When idle and uncontended, approved work is normally admitted on the next timer tick, roughly60seconds after the previous service completes (plus timer accuracy/scheduling delay). Lock contention or genuine execution can delay admission further. Genuine execution keeps the same exclusive lock, max_tasks1 and2100second host deadline. An old process started with idle600 retains that value until it exits; a unit-file reload alone does not prove the new scheduling is active. Verify actual new idle ticks, zero dispatch/fees and obtainable shared lock, and keep the old root-owned unit and events. This is controller scheduling, not a product release.

## External exact review worker (finite activation2026-10-29)

`myink-pi-review-worker.service` uses the same closed-tree verifier with explicit
`review_worker`, its own root-owned0640 registry in root-owned0750 config, and a
5second timer. `review-worker.env` must pin PI_OBSERVER_RUNTIME_SHA256,
PI_REVIEW_WORKER_ENTRYPOINT and PI_REVIEW_WORKER_REGISTRY_SHA256. At most16 pinned
requests under canonical `handoffs` are admitted, only after completed handoff
receipts. It does not acquire maintenance.lock; the original manager holds that
lock while waiting for FileReview. An outer flock would deadlock this design.

Keep state/credentials/reproductions/config/releases read-only. Only reviews,
handoffs and audit state/export are writable. This worker never calls a model,
starts a candidate, changes fees or authorizes main/product release. Partial
claims remain uncertain; withdrawing a registry entry stops future publication
but does not undo an already issued review or replay any phase. Install only with
matching verified host/SDK code after whole-plan review and native acceptance;
the old runtime005 cannot stand in for the new host closure.

## Finite source coordinator and closed manager (active8d1802af)

The source `myink-pi-manager.service` now uses the closed verified entry with
`--component manager`; max_tasks1/2100seconds/idle0 are fixed in manager_host.
The old005 service/unit/runtime is retained in the rollout backup; the live
manager now uses the independently reviewed8d1802af closed host. Its actual
outside-window/idle/cold-reentry and main-reader evidence is documented in
`docs/evaluations/pi-autonomy-finite-2026-10-29.md`. Source profile expires
Oct30 08:47+08; no perpetual renewal or actual new night-task success is implied.
New root-owned0640 config files in root-owned0750 config are:
`autonomy-profile.json`, `autonomy.env`, `manager-host.json`, `closed-manager.env`,
`review-worker-registry.json` and `review-worker.env`. Preserve old service.env,
unit files, config, runtimes and canonical fee/manager histories.

The parent environment pins PI_OBSERVER_RUNTIME_SHA256, PI_AUTONOMY_ENTRYPOINT
and PI_AUTONOMY_PROFILE_SHA256. The manager environment pins the same closure,
PI_MANAGER_ENTRYPOINT and PI_MANAGER_CONFIG_SHA256. Worker registration updates
only the finite review registry and its fixed three-field environment, retaining
private previous versions. A partial pair can block a wakeup; it cannot approve
an unverified phase. Do not install these units against an old host closure or
new guest code without the matching verified SDK snapshot.

Create canonical autonomy/investigations/reproductions/handoffs/reviews private
roots for ubuntu; config/autonomy-permits is root:ubuntu0750. Root-generated
permits stay root:ubuntu0640, ordinary inputs/claims ubuntu0600/0700. The parent
needs only its declared privilege-drop/chown/read/kill capabilities. It holds the
existing maintenance lock internally; do not add an outer flock. It dispatches
fixed setpriv/zero-capability/no-new-privileges ubuntu workers with a minimal
environment and private bounded output. Docker-group host code remains trusted.

The ordinary manager still takes the outer maintenance lock and has the original
60second timer. Before original-manager execution, automatic admissions require
completed coordinator and all five phase/result/hash links. Missing/uncertain
metadata cannot start selection. Withdrawal only preserves/moves an exact own
manifest before manager registration; registered/foreign data is never removed.
The external review service never takes maintenance.lock, so it can answer the
original manager while FileReview waits. Signal cancellation, original finance,
owned cleanup, cold reentry and main audit reading remain required before any
new rollout. The deployed8d1802af has its one whole-plan review/author fixpass,
native SDK mock/idle/window guards and actual audit-reading evidence; genuine
new paid night-task and private-lab/full24–48hour qualification remain separate.
Newer candidate post-review/completion source is not in that live closure.
Main/product release is a different authorization boundary.

## Product identity/preflight observer (not active merely from this template)

`myink-pi-product-observer.service` is a separate ordinary-user, AF_UNIX-only,
private-network oneshot. A root-owned640 config at config/product-observer.json
pins the original Docker daemon, exact fixed project/services/replica count and
canonical private outputs; root-owned product-observer.env pins closed entry and
config digest. Create product-observations and product-observer.lock as ubuntu
0700/0600 only during separately verified activation. Do not replace existing
Pi units or relax any paid/runtime permission. Source imports are stdlib-only;
no credential files, fee/manager DB, arbitrary SQL, image switches or app schema
changes are involved. Docker-group access remains trusted/root-equivalent.

The 15minute timer records component image observations and explicit release
blockers. Stable inventory/table presence is never source/ownership/pause/backup
or product release authority. Exact actual main/product adoption, functional
maintenance and owned image rollback remain later explicit execution gates.
# Postdeployment nightly configuration (human-confirmed rollout only)

An initial compatibility rebuild is a separate explicit operator action. The
`pi-nightly-human-rebuild-v1` receipt must be root:ubuntu0640 in root:ubuntu0750
`config/rebuild-approvals`, bind the old cycle/package, new cycle/night, exact base
image, compatibility report digest and a validity of at most24hours, with issuer
`human_operator` and action `prepare_same_candidate`. Never generate it before
direct human authorization. `ApprovalGate.begin_rebuild` transactionally adds the
immutable forward link and new same-task preparation; only then does approval
metadata become7403. Existing7402 metadata stays unchanged on ordinary startup.
Do not initialize/reset either format or edit the original pending row. The old
artifact is retained without a fake completed comparison and loses action
authority. This permission grants no push/deploy/metric authority; the new sealed
package waits for a new publication approval. Scheduler and generic host entry
refuse operator rebuild work. The explicit `nightly_rebuild.run` wrapper holds
the same nightly lock, verifies the old package/original completed SDK evidence,
and checks the root-protected compatible-base report against the human receipt.
ACTUAL has no injected verifier/image/checker: its fixed Docker verifier checks
the current healthy API/worker parent, nonroot images, whole installed Python
package hashes, exact telemetry-file changes and owned stopped-probe cleanup.
No application code is imported by those probes.

Rebuild preparation stays unsealed until the new image passes the original
frozen regression with verified cleanup and unchanged original accounting.
Only then are rebuilt-image check/compatibility hashes bound into the evaluation
and final manifest before the publication gate becomes awaiting_approval.
Interruption before that transition leaves no approvable new package; partial
intents are retained without automatic replay. Standard rebuild audit records
and immutable receipts preserve the old/new link without claiming a release.
Compatible-base report/image production and actual native qualification remain
separate steps; local wrapper tests are not a product rollout.

The 2026-10-30 human hold still takes precedence over historical activation
instructions below. The new controller and timer are not activated by building
their archive. Before an explicitly approved installation starts the nightly
unit, install/apply `myink-pi-nightly-tmpfiles.conf` with systemd-tmpfiles and
verify `nightly-source-inputs` is a real root:ubuntu directory with mode0750.
The same rule creates the new private root:ubuntu0600 `control/nightly.lock`;
verify it is a plain file, and preserve the original maintenance lock.
The mandatory `ReadWritePaths` mount is established before Python runs; its
directory cannot be created for the first time inside that service.

Pin an operator-issued private observer template at
`config/observer/nightly-template.json` (root0600 in root0700). It contains the
existing fixed PostgreSQL reader, audit destinations,15minute interval,1hour
lookback and minimum20samples. The driver `observation_template` holds its path
and raw file SHA256. After human approval **and** physical deployment attestation,
the controller derives the actual process identity and writes a separate
`config/nightly-observers/<cycle>/observer.json`. Completed config/receipt history
is never replaced. Ordinary worker inputs and metrics receipts remain private
but readable by ubuntu; the database source and sample rules do not expand.

The driver may also pin `source_template` at
`config/nightly-source-template.json` (root:ubuntu0640 in root:ubuntu0750).
Its closed schema is `pi-nightly-source-template-v1`, with `mode`, `profile`,
`source_scope` (`files` and `behavior`) and `validity_seconds` (at most86400).
`profile` contains the existing autonomy-profile fields **except** `source`,
`observer`, `checker_image_id`, `issued_at` and `expires_at`. It is an explicitly
configured standing construction policy, not a renamed expired finite permit.
Keep the original manager/fee paths,50CNY/nine unknown holds, calibrated closed
policy, fixed SDK host image/entry and bounded phase limits. Prefer7200seconds
for an individual source profile. Do not copy dates from an old finite profile.

A new unadmitted nightly round derives a source profile only from the last
completed human-deployed comparison, operator-selected installed Python files, and a
fresh read-only window whose running cohort is unchanged before/after collection.
It retains the fixed SDK host image while updating the business checker/base
image to that confirmed version. Missing evidence, changed identity, altered
fees or partial intents stop issuance; they do not renew permits or replay model
calls. The original coordinator/manager remain the only paid execution path.
Selected files need not have been modified by the previous candidate. The fixed
reader checks the complete installed Python package against the approved package
digest, then verifies each selected body against that package's file digest.
It reads at most3 canonical Python paths, at most24000bytes each, as uid10001
using only the standard library under `-I -S -B`; it does not import application
code. The live cohort is checked again after both metric and source reads.
Keep the operator's existing file scope; do not narrow it to the previous patch
just to make a source snapshot fit. Any copied-byte drift stops profile issuance.
Per-cycle source inputs/profiles and their receipts are retained. No configuration
here permits GitHub/registry pushes or product deployment without the separate
exact-artifact human approval.

Next-day `observation/assessment-*/audit.json` reserves standard AuditStore
records for fixed tests, version-bound observations, unchanged version/scope and
manual rollback advice. Import/export uses the existing audit contract and
main's read-only AuditReader; raw private config, inputs and Docker logs are not
part of those records. A blocked rollback record is advice, never a claim that
an application rollback occurred. Actual installation and postdeployment online
qualification remain separate from local test results.


The operator-only `nightly_compatibility.prepare` prepares the initial telemetry
base without advancing the waiting cycle. It accepts only the fixed three
product-file preimages and candidate hashes from the main companion patch
`4cc8a8c376f3da586efade6942f4a4b032f0c975f0be6e4edb2034b31645c112`.
ACTUAL uses the existing nightly lock and original daemon, checks the current
healthy API/worker cohort before and after, and retains an exclusive intent at
`staging/compatible-<old-cycle>/`. Builds reuse the COPY-only, network-none,
no-pull image adapter and verify the complete installed Python package.
`compatibility.json` binds the old sealed package, parent/result image IDs,
whole-package digests and exact three changes; `image/receipt.json` binds the
private archive. It creates no approval, task, model call or publication.

Before explicit human rebuild, an operator must install the exact reviewed
report at `config/compatible-bases/<image-hex>.json` as root0640 under root0750.
This report is evidence and cannot authorize a rebuild. A separate human receipt
binds its raw SHA256 and exact base image, as described above. Interrupted asset
preparation is retained and never silently replayed.

For the user's standing instruction to complete the initial local package before
publication confirmation, `nightly_rebuild.run` also accepts the separate
`pi-nightly-operator-bootstrap-v1` schema with issuer
`trusted_compatibility_builder`. Its closed fields equal the rebuild instruction
fields, but ACTUAL reads it only from root0640
`config/bootstrap-instructions/` under root0750. `ApprovalGate.begin_bootstrap`
requires the exact fixed companion/report file hashes, the same original task
and package, and refuses bootstrap from an already replaced cycle. Root-only
execution uses the existing nightly lock and image verification/Gold pipeline.
It records `operator_bootstrap_*` events, never `human_approved`; publication
still needs the final package's human approval. Existing explicit human-rebuild
instructions remain separate. A replacement date is a distinct metadata slot;
this does not schedule another paid nightly iteration.
