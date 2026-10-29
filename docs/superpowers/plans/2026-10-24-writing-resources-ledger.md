# Implementation ledger

User approved full implementation on 2026-10-24, specifically requiring frontend/backend synchronization.

Ruling: use independent backend/frontend/runtime agents with frozen interface contract /tmp/myink-resource-contract.md instead of sequential inline implementation — the three file ownership domains are independent once DTO/API boundaries are fixed; root integrates/reviews and verifies. No automatic commits/push/merge/public deployment. Existing uncommitted UI work is baseline and must be preserved.

Snapshot/optional update popup/admin rollback/private-data separation remain binding. Backend DTO and endpoint contract must drive actual UI; tests must capture actual generation inputs rather than only mirror fields.

## Implemented and reviewed

- Six resource kinds with admin drafts, immutable revisions/publication events, generation CAS, audit and published-only metadata. Private owner library and RLS project snapshots are separate.
- Canonical platform snapshots remain on ordinary selection saves; explicit adopt advances selected releases. Explicit personal-library saves refresh owned versions, preserving project overrides.
- Actual bundled source seed: 37 genres, six refinements, four styles, 78 attributed corpus files, continuity and two expression preferences. Local initialization verified these counts without importing private content.
- Runtime captures Task.payload at admission, DB payload wins over retry transport, child execution inherits; actual provider messages and reference tool bodies use frozen choices. Private styles/samples remain; output protocol stays fixed.
- UI cards use real per-kind fields, user picker has visible primary/secondary order, new style form uses consumed profile dimensions. Entry and pre-generation release checks support dismissal/manual adoption/rollback.
- Independent review found and resolved: ordinary saves silently upgrading platform selections; dropped private style; incorrect planner/audit/summary role assignment; archived snapshot removal; pre-generation update reminder; actual subgenre DTO mismatch; primary/secondary 7:3 priority; new style description field not consumed.
- PostgreSQL authenticated API / RLS / concurrent CAS integration and full persisted worker graph freeze checks: three tests passed. Browser against isolated API verified publish, selection, dismissal retaining v1, manual adoption of v2, rollback publication generation4, and adoption back to v1.
- Final frontend verification by root: 64 files / 521 tests pass; lint and build pass with existing warnings. OpenAPI exported from app: 112 paths including 12 writing-resource paths.
- Local user preview: additive `myink init` without --seed completed, API restarted, Vite restored at 127.0.0.1:5173. Dedicated browser API18102/frontend5182 stopped after validation. No real provider call, no commit/push/main merge/public deployment.
- Runtime implementation originally preceded its new tests; later regression fixes were reproduced RED/GREEN. This does not claim strict test-first sequencing for the complete runtime slice.

## Final verification

- Root full backend: **1767 passed, 1 skipped, 5 xfailed, 2 subtests passed** in 315.70s (log `/tmp/myink-writing-resources-backend-final.log`). The skipped comparison evaluation requires a separately approved evaluation database identity; five pre-existing conflict samples remain expected failures. Neither is counted as passed. No unexpected failure remains.
- Root full frontend: **64 files / 521 passed**, lint/build exit0 (logs `/tmp/myink-writing-resources-{frontend,lint,build}-final.log`); existing FastRefresh/hooks and large-bundle warnings remain.
- Fresh `git diff --check` passed. Actual local API advertises 112 paths including 12 writing-resource paths; live catalog counts verified as 37 genres,6 refinements,4 styles,78 references,1 writing rule,2 expression rules.
- Dedicated PostgreSQL/Redis/RabbitMQ Compose project `myink-admin-default-test` stopped and volumes removed after verification; only this test project was cleaned. Isolated browser API18102/frontend5182 were also stopped. User localhost5173/admin preview and normal services remain available.
- No paid model request or real-model quality assessment was performed. Existing unrelated edits remain preserved; no commit, push, main merge or public release.
