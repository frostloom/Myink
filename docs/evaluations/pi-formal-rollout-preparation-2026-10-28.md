# Pi formal rollout preparation — 2026-10-28

This is the earlier pre-launch stage record. Current server acceptance is documented in [Pi server launch](pi-server-launch-2026-10-28.md). At this stage Pi was **not launched**. This stage prepares a standalone finite service; it does not deploy the old product checkout or merge Pi into main.

## Verified changes

- Manager CLI converts SIGINT/SIGTERM into its existing cancellation Event and restores original handlers on all exits. Four regressions cover real subprocess signals and handler restoration.
- SQLite snapshots explicitly close both connections before publication and open the existing source read-only. Two regressions caught disappearing WAL/SHM publication and accidental missing-source creation: both were observed RED before the fix.
- Finite systemd service/timer retain NoNewPrivileges, service-only Docker supplementary group, Docker-visible TMPDIR, external maintenance lock, read-only code/config/history and separate writable operational paths.
- Fresh independent review found no actionable defect in that code/configuration. It did not certify canonical transfer or live deployment.

## Evidence and limits

Python: **3056 passed, 19 deselected** (pytest ops/pi/tests/ -m 'not pi_lab' -q, 401.93 seconds).
The first collection without the marker exclusion correctly refused private-lab opt-in; it ran no tests.
Related snapshot/backup/relocation: **88 passed**. Node protocol/tool tests: **54 passed**.
The excluded private-lab tests are not claimed passed.

Original-state backup002 contains two consistent read-only databases, policy, original audit/review bytes and full logical snapshots, with no credential contents. Every manifest and archive member hash agrees. A local read-only restore verified schema/integrity, refused CREATE TABLE, and matched all original logical rows and manager status. It preserved 9 tasks, 748 attempts and 9 historical unknown holds (18,115,200 microyuan). Conservative usage remains 22,759,695 / 50,000,000 microyuan. This is not proof of server restore.

Actual Ubuntu/systemd255 readiness002 used two real Node/Pi SDK sessions through a mock provider, with zero real requests and exact owned-container cleanup. Seven production container identities and readyz were unchanged. Its code predates the snapshot fix; its success is not attributed to the newer package.
Readiness001 stopped on an independently changed production baseline, before creating its probe. Latest-code readiness003 failed before any mock/provider request: deployment umask made the bind source root 0700, preventing fixed worker UID65534 from importing source. Failed artifacts remain intact. A new independent package and readiness004 explicitly correct source-root permissions; its terminal result passed: systemd exit0/no restart, two actual SDK sessions/two mock requests/zero real requests, owned operation labels absent and exact production before/after equality. Code closure e57595019cd3e7f63049772b76affbfb98adf2b75b710f14916e3a75f4827a6e. Self and maximum-child peak RSS were each193776KiB; these are not simultaneous total memory or cold-cache capacity.

Automatic approval twice refused sending real fee/manager/audit backup to the user's SSH server because the trusted user messages lacked explicit authorization for that specific sensitive data/destination. Neither transfer executed. Canonical source remains unfrozen, target has no canonical database/credentials, and the formal timer is disabled.

## Remaining acceptance

Obtain explicit destination/data permission, prove server read-only restore, freeze/export the original state, transfer/activate/apply once, then run a fresh bounded independently admitted real job. Verify budget/history, protocol, checks, cleanup, finite stop/restart, exact latest unchanged checkpoint restore, logs and production health before claiming launch.
