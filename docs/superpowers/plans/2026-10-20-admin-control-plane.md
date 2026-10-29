# Admin Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. This run uses explicit independent backend/frontend ownership and a final fresh review, authorized by the requested superpowers workflow and autonomous completion.

**Goal:** Administrators configure platform generation resources and observe activity; writers only consume published resources.
**Architecture:** Database singleton configuration, admin-only mutation API, sanitized catalog, shared platform runtime resolution, dedicated admin shell.
**Tech Stack:** FastAPI, SQLAlchemy, React 19, TypeScript, Vitest, pytest.
**Spec:** docs/superpowers/specs/2026-10-20-admin-control-plane-design.md

## Global Constraints
- Local worktree codex/admin-control-plane only; no commits/push/merge/publish without explicit user authorization.
- Preserve existing reporting and original dirty main checkout; do not touch pi.
- Match existing CSS tokens; clean responsive accessible pages, no new dependencies unless necessary.
- Shared API contract is fixed in spec; backend owns src/tests and migration support, frontend owns web.

## Review Focus
- Hidden/disabled/stale selections must not execute forbidden connections.
- Never expose raw/encrypted credentials or allow ordinary user SSRF probes.
- Legacy project/user settings cannot bypass centralized policy.
- Prompts reach model requests with budget accounting and structural output unchanged.
- Empty/failed/config conflict states remain recoverable, no accidental secret clearing.

### Task 1: Backend control plane and runtime
Files: src/myink/platform_configuration.py (new), models/platform.py (new), api/routes_platform.py (new), existing environment/providers/genre/settings/main/schema/init permission files; tests/test_platform_configuration.py (new).
Interfaces: exact configuration/catalog/environment contract in spec. Writer preferences are platform model references; no legacy credentials.
- [x] Write regression tests for persistence, redaction, role auth, routing, visibility, prompts, genre overrides and conflict behavior.
- [x] Run focused tests and observe missing implementation failure.
- [x] Implement model/config service/API and runtime integration using existing helpers and migration conventions.
- [x] Run focused tests plus existing related suites; record actual output.

### Task 2: Frontend administration and writer consumption
Files: web/src/pages/admin/PlatformConfiguration.tsx and module CSS, platformApi.ts, EnvironmentPage.tsx, AdminPage.tsx, router.tsx, login navigation, relevant types/tests.
Interfaces: consume Task 1 API contract; mock API in independent frontend tests.
- [x] Write failing tests for dedicated admin navigation, admin config editing and public model selector.
- [x] Implement dedicated admin shell with existing reports, models/prompts/genre management, home redirect for verified admins.
- [x] Replace writer connection editing with published selectors; remove root genre editing while retaining genre selection and target word preferences.
- [x] Run focused Vitest suites, lint and build.

### Task 3: Integration, docs, verification and independent review
Files: docs/ADMIN.md, README.md, spec/api-openapi.json, progress report.
- [x] Review task diffs against spec, reconcile API contract and failed checks.
- [x] Export OpenAPI; run full frontend lint/test/build and suitable Python suites without touching real data.
- [x] Request independent review of full diff and fix important findings with regression tests.
- [x] Verify original main/pi refs and status unchanged, report worktree/branch, checks and any limitations.
