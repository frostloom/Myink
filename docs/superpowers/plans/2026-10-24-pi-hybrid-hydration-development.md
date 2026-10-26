# Real Pi hybrid hydration boundary fix

**Goal:** Prevent unavailable/foreign fused event IDs from consuming this book's historical extra recall slots.
**Architecture:** In `_hybrid_recall`, constrain hydration query by project and optional strict before_chapter before iterating fused IDs/capping added events. Keep vector search interface/ranking unchanged; missing IDs already skip by_id membership.
**Tech:** SQLAlchemy, SQLite ORM unittest; new finite Linux Pi development launcher.
**Spec:** ../specs/2026-10-24-pi-local-development-launcher-design.md

Scope: only src/myink/memory/recall.py, synthetic mechanical boundary evidence. Source unchanged before actual paid run. Tests/test_recall_hybrid_boundary.py frozen ten cases, observed5fail/5pass. Default before_chapter=None retains direct caller compatibility; project scoping always applies. Existing relation/foreshadow/keyword guards, aliases, limits, dedup and degradation statuses preserved. This does not solve vector Top-K starvation outside the returned IDs.

- [x] Independent host review approves frozen Plan/config identity and scope after new entry synthetic normal/negative checks.
- [x] Freeze complete src dependency tree/runtime/test/Plan/baseline plus original ledger checkpoint; newrun,30request/64tools/900sec, existing uncapped canonical scope. No retry/continuation/unknown release.
- [x] New public launcher default check; then real paid execute. Require actual patch→lastunit10pass→finalstatus→stopped session/RPCauth→ownedcleanup and exact original ledger prefix preservation.
- [x] Independently review actual candidate diff/source digest; adopt only declared delta into current worktree.
- [x] Run recall targeted regressions then ordinary full Python and changed Pi tests. Record exact skips/xfails, real costs, cleanup, global gate false; no Git commit/push/main/deploy.

Review focus: current/future/foreign IDs cannot hydrate or spend slots; allfive valid keyword hits survive; direct unbounded callers remain; no extra vector query/API/limit changes; fixed10 inventory and independent closed fee/cleanup audit.

实际验收见 ../../evaluations/pi-local-development-readiness-2026-10-24.md；所有结果按已运行记录，历史失败保留。
