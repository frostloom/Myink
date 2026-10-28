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
