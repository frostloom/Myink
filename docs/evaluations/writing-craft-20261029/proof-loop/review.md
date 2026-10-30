# Source-linked repair prototype: independent review and limits

2026-10-29, no runtime integration or release accepted.

Independent reviewer read the helper, actual scripts and raw synthetic texts, without invoking models or network. The family example and P02/P03 completed their occurrence obligations with mostly preserved prose; added explicit motive wording was more explanatory, not evidence of better literary style. Earlier full fallback incorrectly added another missed class and was correctly not accepted. Model verdicts are not independent literary acceptance.

Blocking findings:

- Character coverage is provenance only. A single irrelevant claim can cite a whole compound event. This cannot establish semantic equivalence. The module now documents that limitation explicitly. An independent semantic fidelity gate or review is required before using compilation as an automatic approval gate.
- Occurrence and closing state must remain distinct. The local helper now requires temporal_scope=occurrence|end_state, includes scope in identity, and rejects missing/unknown scopes. Existing logged v0 experiments did not carry that field and are not retroactively reclassified as passing the new contract. For the pre-existing family benchmark, earlier agreed acceptance allowed finishing the required interaction before the very last line; future explicit closing-state cases must test revocation separately.
- Natural implication is not omission. The same unfinished motive line was accepted in one run and failed in another. “Look at the three red marks / confirm yes” was falsely treated as not checking in earlier runs. Fixed good controls and repeated observations are necessary; otherwise the system will damage natural ellipsis.
- The prototype initially used Python assert checks. The local helper now has strict batch parsing (bool/float/duplicate/missing/unknown index rejected), but the archived server v0 script has not yet used that parser. Need schema for consistency evidence as well.
- Integration must use existing task budgets, tenant/model routing, run recording, real style profiles, immutable resource opt-in, extract/validate/audit and bounded patch/full-revision paths. Temporary scripts do not prove those requirements.
- Several development examples are case-specific. Successful development-set repairs cannot establish generalization; require unseen scenarios, changed names/order, repeated writing and independent review.

Local helper verification: 25 targeted tests passed (chapter checks + craft + evaluator + release tests). Full suite result in the parent report predates this new helper; no claim of a new full regression. No production resource rows, snapshots, queue deliveries, author books or model routes changed.

Historical checkpoint: the corrected-suite launch initially timed out twice in automatic review. The user subsequently explicitly approved continued isolation testing; the resumed outcomes below supersede that pause.


## Resumed outcome

Corrective16/v1 19/v2 35/v3 22/fidelity controls6 additional attempts completed,98 after the last pause; cumulative317. v2 model-reported5/6 is NOT genuine acceptance: P01 still has missing-password/export contradiction and P05 still has no evidence its chosen exit was its incoming route. v3 had no stable completion; it also unnecessarily rewrote the good clock control. Minimal fidelity controls5/6 correct, with an explicit missing-second-actor negative falsely approved. This is a hard release blocker.

The helper now supports immutable draft evidence IDs resolved by the server (rejects bool/string/out-of-range/empty-positive IDs), strict consistency groups, and complete fidelity-source reports.40 targeted tests including private-style boundary checks passed. It remains unused by runtime. No source-character/protocol validation is represented as semantic proof. Latest helper saved as chapter_checks-v3.py; older exact helper versions were not all captured, so raw older experiments must not be presented as fully reproducible against that newer schema.

A product choice is pending about explicit author confirmation before continuing chapters. No authorization boundary or model credential is missing for the already-approved isolated tests; they completed. The current automated proof-loop direction failed its fixed negative controls and is not accepted for deployment.
