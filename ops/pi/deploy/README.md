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
