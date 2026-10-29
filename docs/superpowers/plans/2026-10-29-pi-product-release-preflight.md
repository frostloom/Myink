# Pi Product Identity and Release Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans inline and TDD. Continuous execution already authorized. One fresh final source review for this independent plan, then one author fixpass without rereview.

**Goal:** Capture real component-specific product reality and produce an honest host-owned release preflight, with administrator-readable missing prerequisites, before asking for a concrete main/product adoption approval.

**Architecture:** A fixed read-only Docker/PostgreSQL metadata collector observes the existing myink Compose project, independently of the paid candidate manager. It pins running containers and images, verifies a stable before/after census and probes only maintenance/provenance catalog availability in a read-only transaction. A deterministic preflight explains readiness gaps; image labels and historical recommendations never create deployment ownership or permission. The append-only audit contains bounded component observations and blocked release reasons, not raw Docker environments or secrets.

**Tech Stack:** Existing Python3.12/stdlib, Docker CLI, PostgreSQL16 psql, existing auditv1 and standalone main reader. No new dependency, provider, fee scope, app migration or model tool.

**Spec:** docs/superpowers/specs/2026-10-28-pi-online-closed-loop-design.md phases4–5; docs/pi/administrator-audit-handoff.md. This plan does not replace or complete the full root goal or the still-pending genuine candidate/actual nextday gates in the candidate-acceptance plan.

## Global Constraints

- Pi branch/worktree only, authorized commits/pushes; preserve current main/admin branches and production data. No main merge, application image switch, table/role change, credential reading/export or product release without explicit final authorization.
- Original canonical50CNY cumulative scope/nine unknown holds; this collector has zero model routes and does not open any fee/manager ledger. Observation must keep working when paid work is frozen.
- Models have no Docker/SQL/shell/Git/release capability. Fixed host commands only; no query, executable, project, service or container argument originates in model prose.
- ACTUAL requires canonical root-owned640 config under root-owned750 directory, ordinary worker identity and original pinned Docker daemon; no injected runner/clock. SIMULATED requires isolated explicit callback and private config/output.
- Source Git references and image revision labels do not prove deployed source, ownership, generation, maintenance epoch or release approval. Missing values stay unknown. Different frontend/backend revisions are legitimate independent component history.
- Infrastructure and exited migration containers are not running product workers. Preserve excluded metadata reasons; unknown health is not healthy. A changed census during observation is confounded, not a coherent release base.
- Raw inspect/environment, database contents, source/prose and keys never enter audit. Only fixed metadata fields and hashes. No SMTP/message sending or exposed static audit directory.

## Review Focus

- Docker daemon substitution, duplicate/extra/missing services, stale IDs and non-running replicas must block coherent reality, with no product side effect.
- Compose labels or image revision claims cannot grant product identity/permission; malicious labels must not leak arbitrary strings or become commands.
- A container/image/manual deployment changes during the catalog query invalidates the snapshot; a cached observation is never fresh execution authority.
- Missing/failed/read-write metadata query is unknown, not false/success; even a present maintenance table is not proof of live paused/checkpointed work or recovery readiness.
- Audit/export failure retains partial evidence and never manufactures release readiness; daily version history must not overwrite historical task provenance with the current image labels.

### Task 1: Fixed read-only product reality capture

Files: create ops/pi/product_reality.py; tests ops/pi/tests/test_product_reality.py.
Interfaces: observe(config_path,config_sha256,*,runner=None,clock=None) -> private bounded observation, authority='none', status observed/confounded/blocked, model_requests=0; exact fixed Docker command and metadata SQL maps.
- [x] RED real-shaped Docker fixtures for API/2workers/Caddy/PG/Redis/Rabbit plus exited migrate; independently versioned frontend/backend, explicit unknown deployed owner/generation and unattested image label claims.
- [x] RED daemon/role/count/image/ID/schema drift, command injection fields, ACTUAL callback/clock/private-mode rejection, before/after manual deployment, failed metadata vs absent metadata distinction and no secrets exported.
- [x] Implement root config, canonical resource boundaries, stable bounded capture and fixed read-only PG catalog probe. No app code imports/execution or SQL mutations.
- [x] Targeted24tests/87related passed; source checkpoint commit, not activation.

### Task 2: Honest release preflight and audit projections

Files: create ops/pi/product_preflight.py; tests ops/pi/tests/test_product_preflight.py; extend admin handoff and enhancement inventory.
Interfaces: inspect_reality(observation) -> authority='none', release_allowed=False, blockers with explicit evidence classes; project to bounded component version and blocked release audit through the existing ordinary audit mechanism.
- [ ] RED missing maintenance/provenance, unknown ownership/generation/source attestation, stale/confounded observations and caller-supplied approved flags never allow release. Do not equate table presence with functional pause/backup/restore or merged/tested product code.
- [ ] Produce exact release prerequisites and next actions for concrete later approval; preserve original fees, failed/unknown observation and component identity separately.
- [ ] Standalone -I-S-B main reader verifies new records; no product deployment/rollback success inferred. Commit.

### Task 3: Source review and actual read-only qualification

Files: fixed ordinary product-observation entry/config if needed; deployment documentation and dated MD/JSON evidence.
- [ ] One fresh final review and one author fixpass. Full offline regression and exact implementation CI.
- [ ] Match closed runtime and capture actual seven running product containers, separate exited migration record and actual catalog absence/presence without changing production.
- [ ] Export actual readiness blockers and component versions; standalone main reader verifies. New actual deployment identity still does not retroactively label old metric cohorts.
- [ ] Record concrete next required integration: main maintenance/provenance bootstrap, approved PRE/POST/restore evidence, fixed owned application image switch and rollback, genuine paid pipeline and24–48h. No goal completion from this preflight.

## Authoritative reconnaissance (2026-10-29)

Read-only Docker:7running product containers; API and2workers image6906d533 with revision labeld25d8275, Caddy72c96066 with labela8a4361e, PGccc6e83d/Redis858f009f/Rabbite582c0bc. Exited migrate uses another older image and is retained separately. Product directory has no Git metadata; Git fetch failed twice (HTTP2/HTTP1 transport), but GitHub API independently confirmed currentmain remainsb6f38a88. Local objects exist for both image revision labels; neither label commit is a main ancestor. The labeled backend-to-main Python diff spans18files(+68/-395). Label claims still require independent source attestation; do not deploy a whole old-main tree over product fixes.
Read-only PG catalog: maintenance_control=false, maintenance_executions=false, maintenance lock function=false, no run_provenance column tables. No schema or product changes, no model requests. Current finite Pi1ea1d514 remains active under profile63383ce9 untilOct30 11:27+08.
