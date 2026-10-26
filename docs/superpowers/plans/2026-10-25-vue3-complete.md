# Complete Vue Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with test-driven-development and independent review. Continue all tasks without per-module approval.

**Goal:** Replace every existing frontend feature with genuine Vue3 components, preserve behavior/API/storage/styles, and remove all pending route placeholders.
**Architecture:** Existing single-lock dual-build remains. Shared TS/CSS is reused. Vue SFCs/Composition API own all migrated UI, no React mounting/iframe/compatibility-runtime shortcut. Production remains React until explicit publishing authorization; a complete independently buildable Vue candidate is the implementation deliverable.
**Tech Stack:** Vue3, Router4, TS6, Vite8, Vitest, browser fixtures.
**Spec:** ../../work-items/vue3-migration-20261025/brief.md and original React source/tests as behavioral reference.

## Global Constraints

Worktree codex/vue3-migration; preserve prior uncommitted work. Pi excluded. No commit/push/merge/deployment. Do not clear user storage or run shared fixed-port services concurrently. Every behavior change starts with a failing test; finish each wave with scoped tests/typecheck/lint and independent review. No feature may be silently dropped to make build pass.

## Review Focus

Account revocation and stale replies; leaf-only environment updates; resource version conflicts; draft save races and SSE replay/Unicode; creation idempotency/short intent; theme preview and media cleanup; admin role/403; dirty navigation and old-client update safety.

### Task 1: Navigation/account/environment/project read pages
- [x] ProjectRail/AdminRail Vue shared components; account password/MFA settings and auth scope methods.
- [x] EnvironmentPage, SettingsPage, LorePage, AuditPage plus WorldGraph/ConnectionNotices/FindingsList/StatusBadge.
- [x] Preserve old tests' behaviors and add Vue coverage; independent review.

### Task 2: Theme/style/feedback
- [x] Theme scope/injection + AppearancePage/StyleLibraryPage + CanvasMedia/PendantLamp/FeedbackWidget.
- [x] All existing media/preset/preview/style/profile/feedback/attachments behavior; Vue tests; independent review.

### Task 3: Administrator
- [x] AdminPage and all pages/admin components, reusable resource fields; server verified access and error boundaries.
- [x] Register all admin routes through master integration, test all roles/edits/details/analytics; independent review.

### Task 4: Creation
- [x] Long/short creation, StructuredTextField/AutoTextarea/RankingsPanel/GenrePackFields.
- [x] Restore drafts, idempotency, IME, resource-first vs auto-start intent; tests and independent review.

### Task 5: Writing workspace
- [x] Vue useTaskEvents/useChapterDraft, streaming/plan/editor/history/candidate/audit/task controls and WorkspacePage.
- [x] Preserve all existing long/short, replay/attempt/codepoint, retry/recovery, save409 and late-response behavior; tests and original browser flow against Vue.

### Task 6: Integration and completion gates
- [x] Resource picker/update components shared with settings/workspace; connect every route and shell/theme/feedback.
- [x] Remove pending route list and enforce route/behavior matrix; no React imports in production Vue dependency graph.
- [x] Safe update notification, build provenance/cache/rollback preparation; dual original/expanded synthetic browser tests, mobile/IME/media coverage.
- [x] Run all applicable React/Vue lint/test/build, isolated service integration where available; report real-service blockers separately, never call skipped checks passing.
- [x] Final independent integrated review, resolve regressions, update coverage/docs. No per-phase final answer that asks user to continue; continue until completed or genuinely blocked.

## Ownership

Subagents own non-overlapping directories/files; only root edits App.vue/router.ts and global integration tests/docs. Common component interfaces are published to other workers. Any dependencies still being implemented are not replaced with permanent stubs. Task-specific reports persist under docs/work-items/vue3-migration-20261025/.

## Final execution evidence

All implementation and candidate verification tasks completed; see docs/work-items/vue3-migration-20261025/final-verification.md and real-integration-report.md. This marks the Vue candidate implementation, not production deployment approval. Model worker/TLS/live rollout remain outside the executed verification scope. Branch/worktree remain uncommitted and retained by user instruction.
