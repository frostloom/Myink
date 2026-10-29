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


## Host authorization and selected-request linkage (source only)

`host.selection_review.v1` is an exact host permission to run one frozen-catalog
selection. `host.selection_binding.v1` is a verified selection analysis with one
original-ledger request and its known charge; `host.file_review.v1` is distinct
host issuance of exact development FileReview. Evidence links keep the original
independent dossier, unbound and derived leases, selection verification and exact
approval separate. Secondary host-review events omit model/cost counters. None
is a product adoption or release event; code remains pending server activation.

Show abstention, partial binding and unavailable completion distinctly. An
original paid result can remain valid while no development permission exists.
Do not infer an authorization from a model's approve text or from an audit event.


## Reproduction and proposed-problem display (source only)

A verified investigation may expose a bounded `details.hypothesis`; label it as an
untrusted proposed problem, never permission. `investigation.reproduction.v1`
test events expose fixed baseline totals/failures/errors/skips and the separate
next action. A failed baseline may be successfully reproduced and eligible for
independent review; it is not a passed candidate or a deployment. Green/error/
no_task/cancelled/host-failed outcomes remain distinct. Frozen tests and full
sessions stay private; execution/adoption authority never comes from audit text.

## Automatic handoff and abstention projection (source only)

A planned `manager.reviewed_handoff.v1` event links the completed isolated
reproduction, independent SDK review config and sealed original-manager cycle.
It announces admission, not successful development. Waiting for selection or
prepared files does not synthesize a successful tool/test/development event.
`host.selection_abstention.v1` is terminal no_change with one verified original
model request and known charge, plus selection-verification/original-lease
hashes. No development permission follows. Re-reading the same receipt does not
append a duplicate charge/event. Partial binding/publication remains uncertain;
never infer completion solely from an inbox or approval file's presence.

## Coordinator grouping and controller history (source only)

`autonomy.coordinator.v1` uses `details.operation_id` for the full research
fingerprint and links `phase_investigation`, `phase_reproducer`,
`phase_sdk_review` and `phase_manager_handoff` receipt hashes when those stages
exist. Its status distinguishes admission, no_task, not_reproduced,
review_rejected, failure and uncertainty. Group `auto-`, `research-`, `repair-`,
`review-` and `select-` run identities by their common first32fingerprint characters;
keep the full operation/evidence hash as the authoritative correlation.

The parent summary omits model/count fields: add only each authenticated primary
SDK analysis/review charge once. `autonomy.controller.v1` is a separate version
context with controller/source-profile policy/SDK identity, never a product release.
Withdrawal retains the exact original manifest privately; unavailable/partial
coordinator evidence cannot be presented as executable or successfully developed.

## Finished-candidate recommendation (source only)

`candidate.sdk_review.v1` is a fresh no-tool post-development recommendation. It
binds the complete final candidate, original source, actual diff, frozen gold,
Plan and matching passed fixed-check copy. Display candidate/policy/SDK identity,
allowlisted approve/reject/needs_evidence and reason, one original-ledger model
charge and complete change scope. Full commentary/source/gold/diff and SDK/RPC
sessions stay private. `passed` means an authenticated approve recommendation;
it does not mean main adoption, product release or verified online improvement.

The host separately reauthenticates stopped session/RPC, exact initial inputs,
original fee history/known settlement and cleanup. A candidate hash selects one
permanent claim under a finite root-approved private parent. Renaming a run or
output cannot replay the same candidate. Expiry/revocation/candidate changes
before forwarding prevent reservation. Missing/invalid/uncertain results retain
their claim and original fee, with no automatic retry. Secondary completion,
version and next-day-plan events must omit the primary review's cost counters.

This role is implemented and offline-tested but has not been activated on the
server. Automatic post-manager scheduling, independent development-provenance
validation and fixed next-day registration still need their own integration.
No release/deployment/rollback success may be inferred from this source contract.


## Actual finite controller activation — 2026-10-29

`autonomy.controller.rollout.v1` version and
`pi.autonomy.finite_deployment.v1` enhancement events now describe the actual
finite8d1802af controller, its source-profile expiry and67controller/config files
(+4659/-129). A standalone main reader has read these exported facts along with
the original actual18/18next-day result. No product release, new paid research or
new candidate is claimed. Newer post-development SDK role/completion code is
source-only until separately verified deployment. The old runtimes, original
fee/manager history and all six timer roles remain separate identities.

`autonomy.rollout.prelock.corrected.v1` links the retained initial lock-busy event;
its exact initial occurrence time was not recorded. Use the correction's
recorded_at, not the prior retrospective emission time as an exact failure time.
Keep both records. No configuration changed or model request occurred in that
initial locked-out attempt. Actual source coordinator ticks can separately report
lock_busy or outside_window without being failed product deployments.

## Candidate completion observation and remaining schedule boundary

New source reaches a fresh fixed candidate review from an actual completed
manager cycle before a cached research fingerprint can end a wakeup. Root
permission is generated from original manager/SDK/tool/fee proof and current
source policy; modelapprove text is not permission. Candidate review outcomes
are retained separately from original admission, including rejected/invalid/
uncertain results and parent-profile revocation. No replay changes the source
claim, original fee history or legacy holds. Completed development config and
old runtime identity are not rewritten for a separately verified current review
runtime. Live parent-profile pin/expiry still gate the new request.

The new source fixed `development_audit` kernel reauthenticates the original
manager/development proof before projecting each controlled tool in durable order,
bounded failed-case feedback, exact candidate diff, final tests and no_release.
Development counters cover development only. Selection binding/abstention and
fresh SDK review keep their own primary charges; parent completion/followup
records omit those counters. Raw arguments, patch, source, gold and model prose
remain private. This preserves failed tool attempts within a reconciled phase.

`candidate.host_completion.v1` links the original manager task to the fresh
candidate recommendation. `candidate.nextday_reservation.v1` is planned only
when root has appended the exact candidate/source/gold/cases/review entry to the
original fixed followup registry and verified its matching env digest. Both old
config preimages and a durable registration intent precede replacement. Partial
pair publication is unverified, never silently repaired or paid again. Original
registry entries and old executed claims are preserved. Existing followup remains
the sole due-time execution authority; it does not adopt product code.
`followup_registered=False` means blocked, not scheduled. A planned record has
no result until an independently linked ACTUAL due-time test exists. Synthetic
cross-day callbacks cannot satisfy that linkage.

`manager.completion_observation.v1` records original stopped, uncertain,
cancelled or abstaining tasks without certifying partial SDK/tool/fee receipts.
Its model/cost fields are null and range_complete is false; its companion is
no_release. Exact partial private receipts remain retained for reconciliation.
This is an observation, not permission to clear unknown fees or replay a task.
Server8d1802af does not include these new completion hooks yet; its finite
rollout record remains authoritative. New source still requires independent
review, matching deployment and actual pipeline acceptance.


Host post-paid reinspection failures have their own durable uncertain completion
and blocked nextday plan even when the earlier SDK recommendation was passed.
Show both stages; the SDK result is not the final host decision. Unknown baseline
counts stay null; code_regression baseline failures use the authenticated nested
reproduction report, not a missing top-level field.

Current source acceptance record:
[2026-10-29 completion](../evaluations/pi-candidate-completion-source-2026-10-29.md).
