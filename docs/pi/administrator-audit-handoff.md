# Pi administrator audit handoff

This is a read-only integration contract for the future main/admin implementation.
It does not enable the admin UI, change authentication or grant execution rights.
Use `src/myink/pi_audit.py` and `docs/contracts/pi-audit-v1.md`; never query the
billing/manager SQLite databases from the browser or copy their private payloads.

## Required admin views

| View | Reader input | Required interpretation |
|---|---|---|
| Runs and inspection | `runs()`, `events(run_id)` | Show ACTUAL/SIMULATED, domain, time, status and unknown identity |
| Analysis | analysis events | Model summary is an untrusted hypothesis; host counts/gaps remain separate |
| Repair and tools | plan/review/development/tool/test events | Link operation, fixed candidate, review and outcome; proposed is not approved |
| Memory and enhancements | memory/enhancement events, `enhancements()` | Show provenance, availability, bounds and expiry; memory grants no permission |
| Rollback | deployment/rollback events | Require actual deployment ownership and verified recovery; cleanup is not business rollback |
| Next-day tests | `daily(day).next_tests` | Display planned due time and separate actual result matched by target run/test/candidate; null is pending |
| Daily versions | version events, `daily(day)` | Controller, SDK, policy and observed product versions are distinct; unknown stays unknown |
| Change scope | each event's changes | Keep file category/additions/deletions and base/candidate identities; controller changes are not product adoption |
| Cost | analysis/development host counters | Original cumulative ledger accounting only; unknown reservations remain held |

The reader validates the complete append-only chain and content-addressed export
before returning data. Invalid/missing/oversized snapshots must be unavailable,
not silently presented as a successful run or empty history. Use bounded event
pagination; do not import raw sessions, writing inputs, SQL rows, credentials or
host paths into the panel. The export is audit-only, never execution authority.

## Diagnosis and development flow

A fixed metadata observer freezes the source window, identity and cohort hash.
The host verifies receipts and constructs bounded source-bound audit memory.
The no-tool Pi diagnosis may return `investigate` or `no_action`; it cannot
approve code, arbitrary shell, database writes, budget changes or release.
A finite root-approved queue admits at most one model request per evidence
fingerprint. Window refresh, elapsed date and additional audit/memory output do
not authorize another charge. New evidence without a matching fixed permit
creates an investigation record only. Partial claims and new unknown fees stop
further paid diagnosis; the original nine unknown holds are not released.

A later repair requires a source-bound reproducer, independent file review,
frozen baseline/test/candidate, phase-limited tools, fixed checks, candidate
review and independent acceptance. Keep each tool intent/result and failed
attempt. Repair failure is feedback, not authority to expand scope. Product
release and ownership-safe business rollback remain separate gates.

## Status and evidence rules

- A closed known model charge can accompany a failed output contract. Preserve
  both facts; never retry it as though no request happened.
- A pending/uncertain claim cannot be cleared by deleting files, changing the
  run ID, updating a billing checkpoint or acknowledging a new unknown as legacy.
- Rolling windows may overlap. Show each window and its sample count; do not
  add them into daily independent samples or claim improvement from one task.
- Source/controller/policy/cohort/time/expiry bind memory. It is context only;
  the server does not yet have a Hindsight adapter.
- A scheduled test becomes an actual result only after its real due time and
  fixed execution receipt. Previous-day results cannot satisfy it.
- Keep all controller version events and failed rollout records. UI labels must
  distinguish implemented, scheduled, deployed, actually verified and adopted.

Current deployment evidence and limitations live in `docs/evaluations/` and
`docs/pi/agent-enhancements.md`. The overall management loop remains incomplete
until new-task review, repair, authorized product observation/recovery and real
cross-day validation all have their own evidence.

## Historical plans and corrected metadata

A due-today view must include earlier plans whose scheduled_for falls today; daily.next_tests contains plans recorded on that report day, so reading only today misses a previous-night forecast. Preserve its separate actual result. Daily.versions is a history of event contexts, including failed or subsequently corrected metadata; it is not a single current deployment. Show host review/correction events and their corrects_controller_pin_record evidence links. Use the appropriate component version event for the current controller/config view, while retaining original records.


## Independent SDK review and actual cross-day example

New pre-development SDK review events expose only host-projected recommendation,
reason, request count, known charge and dossier evidence. `passed` means a
verified approve recommendation; it does not grant execution or candidate/product
acceptance. `reject`/`needs_evidence` and invalid output remain non-authorizing.
Complete untrusted commentary stays private. This code path is not yet deployed;
its future issuer must publish exact FileReview independently.

The original Oct28 owner002 plan now has a real Oct29 03:02+08 passed offline
result,18/18cases and0modelrequests. Read the Oct28 report's matching next_tests
entry to display its separate result, including actual time and event evidence.
Keep unknown product release identity unchanged; this fixed candidate regression
is not a production deployment or a24–48hour online validation.
