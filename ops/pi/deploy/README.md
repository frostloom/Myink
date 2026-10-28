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
