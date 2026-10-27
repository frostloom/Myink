# UI Consistency Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or executing-plans. Preserve all existing dirty work; no commits or pushes.

**Goal:** Stable navigation and consistent resource/editor interactions, audited across all routes.
**Architecture:** Preserve Vue and theme tokens; fix state lifetime at navigation boundary, reuse resource categories/field styles, and use browser interaction evidence.
**Tech Stack:** Vue 3, CSS modules, Vitest, Playwright regression harness.
**Spec:** docs/superpowers/specs/2026-10-27-ui-consistency-design.md

## Global Constraints
- Keep existing personal resource snapshots and genre immutability; no backend redesign.
- No cross-user navigation data; no destructive changes or remote deployment.
- Desktop fixed rail geometry remains; mobile 60px bar remains.
- Form styles use current theme tokens, same fields share styles.

## Review Focus
Delayed list response on route transition; account replacement while request pending; long sidebar scrolling; all resource kinds including empty search; modal controls/long fields on mobile and themed backgrounds.

### Task 1: Stable navigation
Files: App.vue, ProjectRail.vue, admin rail CSS, related navigation lifetime tests; supporting session-scoped navigation module if needed.
- [ ] Reproduce page rail remount/empty book list and lost scroll.
- [ ] Add regression tests for delayed navigation and identity changes.
- [ ] Keep navigation instance/state across route transitions, preserve security boundary.
- [ ] Expand admin rows to44px and consistent group spacing.
- [ ] Run targeted tests, report evidence and diff for review.

### Task 2: Resource category consistency
Files: UserResourceCatalog.vue/.module.css/test, shared category helpers if needed.
- [ ] Use admin category definitions and inspect full editor usage.
- [ ] Add tests category/search/selection persistence/empty result.
- [ ] Implement clear category controls and uniform presentation without changing personal snapshots.
- [ ] Target tests + report and independent review.

### Task 3: Cross-page audit and shared form controls
Files: StructuredTextField.vue, GenrePackFields.vue, shared modal/field styles and only other evidenced defects.
- [ ] Inventory every route and UI primitive, reproduce screenshot color issue.
- [ ] Fix shared field defaults, modal geometry/focus/scroll and evidenced mismatches.
- [ ] Record route audit matrix, regression tests and browser screenshots.

### Task 4: Integrated acceptance
- [ ] Cross-review new changes; fix actionable issues.
- [ ] Full frontend lint/test/build and three-engine browser matrix, dynamic navigation cases.
- [ ] Verify built artifacts, update local frontend only with rollback, health and actual source/release check.
- [ ] Report exact passed/skipped scope; no remote push.
