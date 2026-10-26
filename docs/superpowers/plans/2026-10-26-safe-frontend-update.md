# Safe frontend update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development; TDD; scoped task review then final review. User authorized fixes, no repeated confirmation.

**Goal:** Close release-safety P2 in brief §10.1–2 without losing form input or interrupting pending writes.
**Architecture:** Small shared pending-write counter in existing API wrapper, shared release probe validates manifest against served HTML and embedded active release. Both guards prompt explicitly, require confirmation and disallow update during writes. Vue form scopes use lightweight per-scope protection, preserving existing chapter/theme/feedback guards.
**Tech Stack:** Vue3/React/TS/Vite/Vitest/Playwright.
**Spec:** docs/work-items/vue3-migration-20261025/brief.md188–190; recheck-release-safety.md.

## Constraints
Dirty migration worktree; protect existing work. No commit/push/merge/deploy. Pi excluded. Legacy clients already loaded cannot acquire protections without reopening; document transitional release requirement. Do not claim prior artifact hashes cover changed business bundles.

## Review Focus
- Manifest/HTML from mixed deployment must not offer unsafe update; dev must not probe another root.
- React guard never autoreloads; Vue/React confirmation cancellation preserves page.
- All API mutations, including admin/auth/media upload and failure/abort, hold/release save lock.
- NewBook/short/environment/admin/login/account memory forms, custom programmatic form edits, same-component route updates, and tab unload protection.
- Existing draft-storage failure, theme preview and feedback attachments retain protection; avoid duplicate dialogs or blocked auth recovery.

## Tasks
- [x] Task1 parent: RED→GREEN shared pendingWrites counter and API integration; in-flight failures/parallel reads/writes.
- [x] Task2 agent release: RED→GREEN build manifest/HTML binding; shared version probe; safe React/Vue update UI.
- [x] Task3 agent forms: RED→GREEN lightweight Vue form guards across all memory forms; no global dirty framework; coverage ledger mapping.
- [x] Scoped independent task reviews, resolve findings.
- [x] Full default/React lint/test/build; real browser release-safety and existing matrix against NEW artifacts; default/rollback images if product bundle changes.
- [x] Update provenance/retained window/report and independent final review. Preserve all evidence and uncommitted work.

## Interface
Parent owns web/src/lib/pendingWrites.ts: beginWrite():()=>void (idempotent finish); hasPendingWrites():boolean; subscribePendingWrites(listener:()=>void):()=>void. API wrapper request tracks all nonGET/HEAD until finally. Guard agent may import these three, must not edit API.
Form agent owns Vue composable/pages/router only; can use hasPendingWrites for navigation lock, need not implement global write tracking. Guard agent owns version guard components/tests, shared release module and Vite manifest plugin/config/tests. Do not overlap.

Task1: api.pendingWrites4 first3RED/1GREEN then4GREEN, with auth13GREEN; shared suite199GREEN (includes concurrent release tests). Independent scoped reviewer approved, no Important/Critical. No commits.

Task2: Vue2RED andReact2RED on actual guards; release/plugin moduleRED then7GREEN including actualVitebuild; Vue4 andReact2GREEN. BothTypeChecks/scopedLintGREEN. Task2 fresh scoped review pending. Parent added actualproduction release switch/browser and image manifest gates; matrix now also requires builtReact output.

Task3 actual3coreRED + shortunsentcommitRED + manualauthenticatedloginRED →GREEN; scoped179GREEN; all3tasks fresh scoped reviews noImportant/Critical. Task2minorlegacyfilename: realVite appfilename RED then fixed explicit naming+plugin reject incompatible output;8release/pluginGREEN. Final default shared205+Vue576 (no stderr errors), lint/types/buildGREEN; React613/lint/buildGREEN. Final3engines each28+10+26+10 all12groupsGREEN, finalVue Bk-yDMAg not priorLHE.
Final: minor (deferred): budget increments retained after successful resume may cause conservative extra unsaved-input prompt; no data loss, existing repeated-input semantics retained. Existing matrix hard-timeout profile P3 remains deferred.

Final: fresh whole-fix review noImportant/Critical ornewminor;26formhashes and12browsergroups+2image10checks verified. All tasks done, ownruntimecleanup0, API/backendunchanged. Keep worktree/evidence uncommitted peruserauthorization. Ruling: retain conservative generated/open-editor and budget prompts rather than infer server persistence from clicks; possible extra confirmation, no silent loss.
