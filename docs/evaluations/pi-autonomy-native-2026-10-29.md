# Pi autonomous host native verification — 2026-10-29

Status: source/native subset verified; automatic source coordination is not activated.
Code: `8d1802af4072d2d6537b16fcff4bfb5e2959e42c` on `codex/pi-autonomy-design`.
No main merge, product deployment or business rollback occurred.

## Evidence

- One fresh whole-plan independent review:0Critical,2Important. The author reproduced and fixed cancellation/revocation after admission and finite issuer validity immediately before selection forwarding. No second review loop.
- Full offline tests:3751passed,36deselected,253.36seconds. Deselected private/native/paid suites are not claimed as passing.
- Closed controller:a66c01a50638bbe94ed5c9b3818db08b15fadbf9fccd59e45bee8d517bde617f,366files,explicit HTTP dependency versions/licenses.
- Matching guest code:3cff5eb6a2c10c94c71524239211c84db34d34f1ae1cefca3f4b999106816db9. Original Node24.22/Pi1.1 dependency fingerprint9b6d4479661dfea5cba51e5dcaa8b77e30e911fbf3432c28fd522ee7a59ce0af unchanged.
- Native two fresh SDK mock sessions:passed,2mock calls,0paid calls. Both exact owned containers stopped/exited0/removed. Root-owned closed source verified before imports; actual ordinary-user execution uses fixed setpriv, zero capabilities and no-new-privileges.
- Native closed manager cold reentry:two separate processes,ACTUAL/done/idle,0dispatches,870.934ms and840.807ms. Original50CNY ledger and manager history remain authoritative. Only normal manager idle history appended.
- First idle precondition incorrectly assumed no retained inbox files. It stopped before manager execution. Readonly inspection found original server-owner-002 manifest already dispatched and ten historical dispatched tasks. All retained; corrected probe verifies no **unexecuted** tasks. The original failure receipt remains private.
- Throughout these probes original fee logical digestfe7c37ea1259b0d92d51524d818703a7063a953e54e53b062dbc36b6eb844afb unchanged:762attempts,753known,9legacyunknown. Known4706205+held18115200=22821405/50000000microyuan; no reset/refund/new unknown.

Private proof location is intentionally omitted from admin exports. Repository-local `.local/pi-autonomous-admission-20261029/verification/` retains full pytest, packet manifest, SDK mock wrapper, initial idle failure and corrected cold-reentry receipts. Remote temporary owned evidence stays available. Existing service units were not replaced or restarted.

Exact source CI: all four jobs passed in [run40792029642](https://github.com/frostloom/Myink/actions/runs/40792029642).

## Remaining acceptance

Native generic SDK mock success is not actual new-task admission, a paid independent candidate review or a production improvement measurement. Keep automatic activation, candidate/diff-bound post-development review, full private lab qualification, genuine new finding/no_task, automatic handoff, original-fee checkpoint/duplicate wakeup and main-reader real export as separate gates. Main/product adoption and ownership-safe business rollback still require their original explicit authorization and real deployment evidence. The existing actual Oct29 03:02 followup18/18 remains separate from24–48hour online verification.
