# Independent architecture review — 2026-10-30

Reviewer: confirmation_architecture_review. Read-only, no model/SSH calls or file changes by reviewer. Reviewed experimental scripts and complete collected outputs, not a release review of the whole branch.

- **P1 — supported results bypass confirmation.** `inspect` confirms only initial non-supported findings; final pass follows empty findings/holds. In the actual run source2 caught the own-route omission while duplicate source3 incorrectly said supported. Confirmation cannot recover an initial false pass.
- **P1 — discovery `none` silently removes specialized checks.** Actual P05 discovery returned none for explicit own-route requirements; replaying the same input later succeeds. Successful replay does not erase the real miss or demonstrate stability.
- **P2 — aggregate labels hide reasoning errors.** U01 invents uncertainty about a ledger that the draft explicitly locks back in the room; U09 changes two people into three. J10 label agreement also lacks full daughter-posture evidence in the cited explanation. Calibration label agreement is not semantic proof or prose-quality improvement.
- **P1 — repair is not transactional.** First patch changes an omitted identity into an explicit inability to return by the original route. An unapplicable second patch triggers full rewrite that invents a collapsed route and remains noncompliant. Budget then exhausts at32.

Recommended single lower-cost next experiment: freeze prompts, stage one local patch, validate that repair target before replacing the draft, roll back on missing/violated/uncertain, disable full rewrite for this experiment. Run the existing reverse-goal patch and collapsed-route rewrite as must-reject controls; only a target-passing candidate may proceed to one full final audit. Record target fulfillment, invented facts, retained text, actual requests/tokens. This tests the execution problem directly.

Reviewer reran the11 local gate tests successfully, and demonstrated that a falsely claimed rejected+supported result with a valid evidence ID still passes schema validation. This is expected of a protocol validator and illustrates why those tests do not establish semantic truth.

No runtime integration, commit, push or deployment approved by this review.
