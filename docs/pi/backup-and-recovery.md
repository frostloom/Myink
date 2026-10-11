# Paired backup and synthetic recovery

The trusted host creates a durable `release_pair` intent before PRE. Its explicit
pair ID binds the frozen plan, expected PRE identity and later POST identity.
`create_backup` has the Task 11 interface plus required keyword `pair`; the caller
passes a trusted finite executor, never candidate SQL, shell, DSNs or file paths.
The logical `backup:<pair>:PRE|POST` ID survives retries; the controller transport
UUID is separate. A nonblocking collection lock and append-only claim establish
one owner. A pending unpublished owner requires reconciliation, not another dump.
A copied manifest cannot authorize completion without the matching ledger event.

Collections validate dump exit/stderr, nonempty gzip, complete artifact hashes,
allowlisted roles, explicit crypto material, attachments, config/certificate and
an external ledger snapshot. SQLite's backup API captures the snapshot's own
source identity, event high-water mark and operation row high-water mark/count.
Later publication and restore events are deliberately absent from that snapshot.
The manifest part is fsynced before publication; its hash is recorded in an
append-only publication event before atomic rename. A published part/final can
be reconciled against that event and verified mirror without rerunning the dump.
Revalidation failures append a separate refusal and preserve original receipts.

The lab stores collections and separately copied/hash-checked mirrors under
`E:/tools/myink-pi/backups/{collections,mirror}`. Trusted synthetic materials live
inside the E-hosted MyinkPiLab VHD under `/opt/myink-pi-lab/backup-materials`.
These collections include private keys and encrypted synthetic credentials: they
must remain outside Git, candidate/build mounts, Pi and model context. The mirror
uses the same physical disk: `offsite_status=not_configured` is explicit.

Use the fixed controller `python -m ops.pi.control backup-lab --state-dir
E:/tools/myink-pi/state --phase source|verify|restore --deadline <aware ISO time>`.
`source` is fresh-only: it claims one creator-derived PostgreSQL database and
queue namespace on the original sealed services, and Redis15 only after native
SELECT/PING and an entire-database empty check. It never flushes, reuses Redis14,
adopts preexisting data or replays a partial initializer. `verify` observes the
existing synthetic source under a new owned operation, with actual service IDs,
PG system identifier/roles, closed control identity, full B10 queue census,
confirmed tasks and real checkpoint/material assertions. Its new receipt is a
current observation; failed or unreceipted creation history remains unchanged.
`restore` re-observes that source and revalidates the canonical PRE publication
before running the complete integration file under the same heavy parent.

Every restore uses a new labelled PG16+pgvector container and named volume, the
original pinned PG image, distinct system identifier, empty public schema,
loopback endpoint, fixture network and the original heavy parent. Necessary
allowlisted roles are imported before SQL using `psql -v ON_ERROR_STOP=1`.
Validation checks two tenants under NOSUPERUSER/NOBYPASSRLS myink_app, empty/
absent context and post-commit isolation; actual PostgresSaver state and pending
writes plus Task/thread/project association; chapter content, relation endpoints,
1024-dimensional vector, credential decryption using an explicit private key,
attachment metadata/bytes/hash, configuration/certificate/key, role ownership,
grants/default grants and the captured ledger integrity/high-water marks.
Checkpointer tables, tasks and account-owned feedback use their architectural
association checks rather than invented tenant RLS policies. Wrong/missing keys,
missing roles, attachments and certificate material must refuse restoration.
Production TLS, real upstream credentials and remote offsite are explicitly not
applicable to this synthetic fixture. This proves lab recovery, not production
completeness or model/workflow quality.

A failed PRE blocks candidate authorization. A release requires complete restore
evidence; POST debt blocks the next ordinary release until POST and its restore
are verified. Recovery is budget-free and remains permitted. Collection manifests
are immutable (`restore_status=pending` at capture); subsequent immutable
`restore_check` receipts are the authority for a caller's trusted retention view.
Never promote a manifest to restore success from gzip checks or caller JSON.

`retention_candidates` keeps the union of every complete collection in the last
14 Asia/Shanghai natural dates, the latest five complete PRE/POST release pairs,
stable/referenced points, and all incomplete pairs or POST debt. All complete
members of a protected pair are conservatively retained. `calendar_gaps` exposes
missing dates without fabricating coverage. This version returns candidates and
performs no automatic deletion: before any future deletion, the trusted caller
must recheck the root allowlist, hashes, live ownership/generation, referenced
materials/images, stable points and actual additional peak capacity. Sparse lab
history is not fourteen-day operational coverage.

Backup and restore operations have a 600-second cap and the caller's absolute
phase deadline; the existing host/guest memory watchdogs and heavy mutual
exclusion remain active. Capacity includes dump/compression/copy/fresh PG restore
peak plus 5GiB reserve on E and the guest. Source/stable volumes are retained. Every target has an exclusive creation registry
bound to its current operation and case, with an append-only registry hash. After
the terminal case result, exact ID/configuration/volume/network ownership is checked
again before bounded STOP; logs, configuration and every target volume are retained.
Failed target evidence is preserved. Application rollback changes only compatible
images and never restores PRE over newer user work. A database incident preserves
the site and collection and leaves any data-loss decision for explicit manual
recovery. Scheduled/production Pi, cron and real models are not enabled here.

Offline checks: `python -m pytest ops/pi/tests/test_backup.py -q`, then the existing
full offline ops command. Actual recovery is the guarded `--phase restore`
selection running `python -m pytest ops/pi/tests/integration/test_restore.py -q
-m pi_lab --pi-lab`; a direct unguarded invocation is refused. Retain per-operation
controller/native ledger events, stdout/stderr, source manifests, capacity and
resource receipts outside Git. The distinct source/test identities must be
checked again after any code/tool/schema change before candidate authorization.
