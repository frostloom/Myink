# Local Pi lab

Task 7 uses only the private `MyinkPiLab` WSL distribution whose VHD is under
`E:\tools\myink-pi\runtime\wsl`. The trusted controller verifies daemon ID
`364e8400-3844-47e2-b86d-8b626332f61c`, Docker 29.1.3, systemd and cgroup v2
before each operation. Existing arbitrary same-name distributions are refused.

Run `python -m ops.pi.control lab preflight --root E:/tools/myink-pi` and
`python -m ops.pi.control lab up --state-dir E:/tools/myink-pi/state` for identity
and fresh resource receipts. The latter adopts the already provisioned, verified
lab; new provisioning requires the reviewed root-owned `provision.sh up` after
trusted native source and pinned images have been prepared. Installation is
fresh-only: `install.ps1 -Root E:/tools/myink-pi -Distribution MyinkPiLab -Rootfs
E:/tools/myink-pi/cache/noble-wsl-amd64.wsl`. It checks the fixed official Canonical
hash against the official manifest and uses signed official Docker apt sources.
It never overwrites an existing distro, changes global Docker context, reboots,
or shuts down other distributions. A second fresh installation was not exercised;
actual acceptance uses the separately verified prepared distribution.

Pi has 384 MiB, 0.5 CPU and zero swap. Every ephemeral test fixture, runner and
descendant shares the 1536 MiB / 2 CPU / at most 256 MiB swap heavy parent. The
mock gateway and watchdog are separately accounted infrastructure. Future stable
maintenance services need their own infrastructure group. Test and build share
a mutex while Pi remains alive. Both real Windows available physical memory and
guest `/proc/meminfo` MemAvailable are sampled; ten continuous seconds below
512 MiB kills the owned heavy group. The guest watcher binds a unique operation,
lab UUID, active systemd unit and heavy group, and stops before releasing the lock.

Candidate source excludes Git history, dotenv files, credentials, private ledger,
backups and policy configuration; links and path escapes are rejected. Candidate
processes are nonroot, read-only, capability-free and cannot access the daemon.
Scoped private bridge INPUT and DOCKER-USER rules permit only authenticated mock
HTTP with the required token and scope. DNS uses no external resolver. Reachable
controlled peers and trusted DNS resolution distinguish real denials from absent
endpoints. No real model requests or production SSH/data are used.

Fixtures use UUID labels, named volumes and dynamic loopback ports. Synthetic
full environment replaces default application dotenv configuration. The trusted
SELECT adapter uses projection-only role grants, transaction read-only and server
statement timeout 5 seconds; Pi receives no database credential or arbitrary SQL
interface. Git/build/backup/restore IDs remain blocked until their later trusted
handlers are implemented; stress primitives are not BuildKit build acceptance.

Offline tests use `-m 'not pi_lab and not pi_live'`. Selected lab tests require
`--pi-lab` and fresh preflight; missing prerequisites raise UsageError. Selected
live tests cannot bypass the remaining B-stage and price/cumulative scope gates.
Actual isolation runs via the guarded Windows executor, not an unguarded shell.
Per-operation stdout, stderr, controller receipts and guest receipts live under
`E:/tools/myink-pi/state` and `E:/tools/myink-pi/evidence`; ledger exports retain
source event IDs. Mutable latest pointers are convenience only.

Cleanup is explicit `provision.sh cleanup UUID`: it verifies frozen daemon,
container/network/volume labels before any removal and touches only manifest-owned
objects. Historical anonymous recovery volumes from the authorized cold copy are
retained. No general Docker prune or distribution shutdown is performed. The
scoped Windows keepalive is a bounded local trial dependency, separate from Pi;
only its recorded PID/start time may be cleaned up by its trusted owner.
