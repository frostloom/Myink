# Late Docker removal reconciliation implementation plan

> Use executing-plans inline, author TDD and one fresh final review for this newly observed bugfix (not a re-review of the earlier fixtures/reporter).

Goal: reconcile only a previously authenticated stopped owned container whose removal was attempted but the Docker client timed out, without replaying model work, accepting generic inspection errors or weakening ownership checks.

Observed: diverse-ordering development stopped after3 known calls, fixed-check raw stdout5/5 passed, first cleanup Docker rm CID timed out15sec, final ownership cleanup RuntimeError. Original complete phase proof absent; all receipts remain failed/blocked. Current direct daemon/operation-label/CID inspections show absence, but Docker's underlying timing cause is unknown. New three-task batch remains stopped: numeric/parsing unstarted, no paid retries/cold recovery. This fix is offline; a future actual acceptance needs a fresh runtime/config/review/identity.

- [x] Reproduce late removal completion (after CLI timeout), generic inspect failure, daemon drift, contradictory labels, missing prior removal intent and stopped exit evidence, preserving no foreign deletion or repeated rm.
- [x] Keep per-CID verified stop/exit evidence immediately before rm. Only after an owned removal attempt, confirm exact known Docker not-found response plus pinned daemon and current operation label absence for that CID. No arbitrary-ID absence grant. Confirmed late removal returns a separate removal reconciliation flag; incomplete/foreign evidence still fails. Preserve sticky operation failure: final sweep must never upgrade a failed model phase.
- [x] Retain successful partial cleanup history in development results when final cleanup raises; leave cleanup_failure_class and verified=false intact.
- [x] Run focused and full Pi/Node checks, fresh final bugfix review; fixes by author RED/GREEN, no re-review. Preserve all old snapshots and failed ACTUAL artifacts. Record post-stop direct resource audit separately, original known fees4calls11601microyuan and all3 scheduled rows, two actual entry reviews, zero new unknown; no successful repair count.
- [x] Prepare final evidence/patch push on existing Pi branch; exact latest four CI gates checked after push and retained in private final-ci.json. Two deferred fixture coverage minors remain recorded without editing frozen gold.

Review focus: only a prior owned removal intent can reconcile absence; Docker transport errors are not absence; exact daemon/CID/label binding survives retries; retained exit evidence cannot be invented; partial/sticky cleanup failure cannot become execution success. No global cleanup, rm --force, model retry, candidate host execution, main merge or deploy.

Verification: related71 passed; full2846passed/19deselected; Node54. Four initial regressions failed as expected and pending-intent success marker independently failed before fix; negative controls stayed rejecting. Actual archived965b closure and failed receipts unchanged; no new runtime used and no paid retest. Final separate bugfix review recorded in private late-removal-review.json. Two fixture coverage Minors are deferred and recorded in the original plan/report.

Final review: fixed Important per-CID receipt-loss finding — later CID and final-label failure tests RED→GREEN; targeted73/full2846 passed,19 deselected. Sticky failed/cancel and no repeated rm remain verified; no second code approval. Real fixed Docker canary with lost-rm-ack injection passed using one actual rm and zero models/candidate execution; original natural timeout timing not reproduced.
