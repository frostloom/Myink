# Admin Managed Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Admins provide ready-to-use creation defaults; users retain preferences under collapsed advanced settings; invalid model configurations fail before paid work/queueing.
**Architecture:** Extend the existing versioned platform singleton, resolve user overrides centrally, reuse existing admission/queue/runtime checks and retries.
**Tech Stack:** FastAPI, SQLAlchemy, React, TypeScript, pytest, Vitest. No new dependencies.
**Spec:** docs/superpowers/specs/2026-10-20-admin-managed-defaults-design.md

## Global Constraints
- Work only in /Users/a1/.codex/worktrees/myink-admin/Myink on codex/admin-control-plane. Preserve original main/Pi and unrelated changes.
- User explicitly requests autonomous completion without questions and authorizes staged commits and pushes of this work. No merge or deployment.
- Existing user preferences remain; missing fields inherit platform defaults. Explicit false and zero remain overrides. Existing saved defaults cannot reliably be distinguished from manual choices; preserve them.
- Default task budget remains 100 requests,5 yuan,1800 seconds when platform setting absent. Existing tasks retain snapshots.
- Credentials stay admin-managed; hidden/disabled models cannot be user overrides. No real vendor calls or production database in verification.
- Test first, observe meaningful RED, implement minimal changes, run targeted GREEN and final appropriate full checks. Record blocked/skipped checks honestly.

## Review Focus
- Admin partial defaults update and old-client omission must not clear another default or secret.
- User false/0 and per-field inheritance must survive unrelated saves and platform updates.
- Reset must delete only named overrides, rejecting unknown fields before mutation.
- Readiness must include internal routes and effective user selections without exposing secrets or pretending probe results guarantee availability.
- Unconfigured generation must not reserve quota, enqueue or create irreversible duplicate work; existing replay/idempotency must remain intact.

### Task 1: Central default preferences and inheritance
**Files:** src/myink/platform_configuration.py, environment.py, task_budget.py, api/routes_environment.py, api/schemas.py; create src/myink/user_defaults.py if useful to avoid circular imports; tests/test_platform_configuration.py, test_environment_routes.py and focused new tests.
**Interfaces:**
- Platform GET/PUT configuration adds user_defaults: {thinking_enabled:boolean,task_budget:{max_requests,max_cost_yuan,max_runtime_seconds},rankings:{enabled,timeout,limit}}. Input optional partial nested object, omitted leaves existing value, explicit null rejected. Responses supply effective complete defaults. Existing CAS version guards all writes.
- GET/PUT environment returns existing effective values plus overridden_fields:string[] (e.g. thinking_enabled,task_budget.max_requests,rankings.timeout,model_routes.writer).
- PUT environment accepts reset_preferences:string[] of dotted supported preference paths (thinking_enabled; task_budget.*; rankings.*; model_routes.writer/planner). Unknown paths 422 before mutation; reset and value supplied for the same path rejected 400; fields not supplied preserved. Models empty references remove overrides as before.
- Shared effective resolution used by runtime thinking, rankings service, budget_defaults and API. No account lookup when user_id None; use platform defaults there.
- [ ] Write failing tests for inheritance, partial nested defaults updates, old-client saves, false/zero and existing overrides, reset isolation/invalid paths, runtime budget snapshots and thinking/rankings.
- [ ] Run focused tests and record RED, then implement interfaces above using existing validation and transaction style.
- [ ] Run affected backend tests, record GREEN and constraints. Commit owned changes with feat(admin): centralize user defaults and preference inheritance.

### Task 2: Admin defaults controls and collapsed user advanced settings
**Files:** web/src/lib/platformApi.ts, api.ts, types.ts, pages/admin/PlatformConfiguration.tsx and tests, pages/EnvironmentPage.tsx and tests, components/ProjectRail.tsx and tests, pages/SettingsPage.tsx; relevant CSS only.
**Interfaces:** consume Task1 exact APIs. user_defaults optional in frontend response type for old fixtures/servers, but preserve fetched defaults on every config save; controls use existing defaults when absent. overridden_fields optional for compatibility, server authoritative for actual state. reset_preferences dotted paths as Task1.
- [ ] Write failing interaction tests: advanced fields absent until explicit expand; existing customization works after expanding; reset restores inherited server values without unrelated updates; admin defaults load/save and survive connection edits.
- [ ] Implement default-collapsed advanced region (accessible button aria-expanded and conditional content); page/rail label 高级设置; retain /environment compatibility. Models/thinking/budget/rankings hidden until expanded. Preserve all capabilities and drafts on failed save; loading failure disables reset/save.
- [ ] Add admin default thinking/budget/rankings controls to current configuration page, explanatory text distinguishes defaults from existing personal overrides and existing task snapshots.
- [ ] Run targeted Vitest RED/GREEN then lint, full frontend tests/build; commit owned files with feat(web): simplify writing with advanced preferences.

### Task 3: Configuration readiness and request reliability
**Files:** new src/myink/platform_readiness.py, api/routes_platform.py, actual shared generation/admission and enqueue entrypoints identified from calls, api/main.py, web/src/lib/platformApi.ts and apiError.ts/tests, pages/admin/PlatformConfiguration.tsx/tests; readiness tests. Docs ADMIN.md and spec export at final.
**Interfaces:** GET /api/v1/admin/configuration/readiness returns {ready:boolean,checks:[{role:string,ready:boolean,reason:string|null}]} for six platform roles using existing admin auth/audit/no-store. Static local checks only; no provider network calls. Add public PLATFORM_NOT_READY stable error code on 503; API message generic and frontend text 平台创作服务暂不可用，请稍后重试或联系管理员.
- [ ] Enumerate synchronous and queued generation entrypoints and role requirements; record table in progress ledger. Check effective user choices, enabled state, decryptability/protocol/address. Use shared provider resolution/fallback rules. Deployment fallback supported only before first config save. Tests can bypass via existing injected provider seam, never a production flag.
- [ ] Write failing tests for unconfigured/decrypt-invalid/internal-role/user-selection readiness, admin-only diagnostics, no secrets, and admission before quota/enqueue. Exercise auth-failure/nonretry, timeout/429 bounded retries, streamed interruption preserving existing no-duplicate behavior; add regressions only where gaps exist.
- [ ] Implement smallest shared readiness checks and route/admission integrations; avoid adding unnecessary model I/O or retry layers. GET checks diagnostic only, user actions re-evaluate actual configuration.
- [ ] Add admin readiness display with explicit refresh and optional-compatible loading; frontend request messages stop telling ordinary users to edit API keys or bypass quotas. Keep existing provider retries and task resume behavior.
- [ ] Run targeted tests, independent whole-change review and fix material findings. Update docs, export OpenAPI, full Python and frontend checks with isolated services, browser smoke for normal/admin paths. Commit/push implementation, then verification report. Verify origin branch SHA equals local HEAD.

## Autonomous decisions
User's no-questions instruction replaces design/plan confirmation pauses. Design check found no essential missing information. Per-field explicit reset API chosen to preserve overrides. Native managed worktree already exists. Only this branch is pushed; no force push. If remote moves, inspect and integrate only compatible branch changes without overwriting work.
