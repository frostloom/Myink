# First visit contradiction implementation plan

> Execute inline with executing-plans; real Pi implements product code, independent reviewers inspect frozen scope and final candidate.

**Goal:** Detect explicit first-visit claims contradicted by earlier same-character/same-location events, while preserving revisits and explicit memory explanations.
**Architecture:** Narrow deterministic Character/Event query plus current draft evidence in first_visit_check, called from existing ValidationService. No schema/LLM changes.
**Tech Stack:** Python, SQLAlchemy, SQLite unittest, isolated Linux Pi, dedicated PostgreSQL/Redis/RabbitMQ regressions.
**Spec:** ../specs/2026-10-24-pi-first-visit-design.md

## Constraints

Reuse codex/pi-autonomy-design worktree. Preserve previous dirty bytes and item_rule implementation. Existing paid/private source authorization;30model/96tool/900sec; canonical ledger/policy/credential untouched except normal append-only metering/temporary owned policy lease. No automatic Git operations, merge or deployment. No model test edits, no old session replay. Only l1.py/service.py production changes. Exact actor/place, time, negation, explanation scope and real evidence are review priorities.

- [x] Capture Git/dirty hashes; read relevant sample/model/service code.
- [x] Add real SQLite/service fixed tests, observe RED without implementation.
- [x] Freeze source/runtime/Plan/test/baseline/canonical checkpoint; independent concrete review before real execution.
- [x] Execute fresh real Pi; require actual patch→complete unit→status→session/tool authentication, policy restored and containers removed.
- [x] Independently review aggregate exact file SHAs and boundary tests; adopt only approved candidate.
- [x] Update real service sample5/29 and metrics23/26, remove only5xfail; run targeted and full ordinary regression with independent resources; preserve other7/8/9 and exactskip.
- [x] Record actual fees, failures, checks and limitations; update Myink memory. No commit/push/merge/deploy.

Completed: final007 exact SHA reviewed/adopted,106 fixedPASS (58firstvisit+48item), targeted223PASS3xfail, ordinary1760PASS1skip3xfail159deselected; full Pi2337PASS19deselected. All65paid333739microyuan accounted,0newunknown, closed/ownedcleanup verified. See final evaluation report; no Git/main/deploy.
