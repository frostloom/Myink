# Pi Finished Candidate Independent Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans inline and TDD. Continuous execution is already authorized; no stage questions. One fresh final review for this independent plan, then one author fixpass without rereview.

**Goal:** Produce a fresh independent no-tool recommendation bound to the final candidate, actual diff and frozen checks, plus administrator-readable outcomes and next-day tasks, without granting product adoption.

**Architecture:** A readonly host compiler authenticates frozen source/candidate/gold/plan and completed fixed-check receipts. A distinct candidate-review role reuses the original single-request SDK/fee lifecycle and finite root permit. A host verifier authenticates stopped sessions/known settlement and appends recommendation/changes/version/followup audit. Recommendations never become FileReview or release authority.

**Tech Stack:** Existing Python/SQLite/Node24.22/Pi1.1/Docker/DeepSeek gateway; no new provider, billing scope or dependencies.

**Spec:** docs/superpowers/specs/2026-10-28-pi-online-closed-loop-design.md phases3–5; docs/pi/administrator-audit-handoff.md.

## Global constraints

- Original canonical50CNY cumulative scope and9legacyunknown holds; no resets, replay, new scope or released unknowns. At most1candidate-review request/120seconds under separate finite root permission.
- Pi worktree/branch only. No main/admin UI/auth/product release changes. Candidate review is recommendation_only and cannot grant merge/deployment/rollback.
- Bind complete candidate, allowed production files, source/gold/plan, exact final check and independently authenticated development receipt; no arbitrary paths from model output. Full comments/source/test/diff stay private.
- Same immutable candidate+review intent cannot charge twice; failure/unknown/expired/cancelled/partial states remain retained. ACTUAL forbids injected transport/clock.
- Diff/context bounds fail before paid execution; actual fixed checks must have exact nonempty inventory,0failures/errors/skips/load failures and matching checked copy/owned cleanup. Domain remains real_provider_fixed_input, never online_business.

## Review focus

- Green check for older candidate or changed gold must reject; test copied-tree/candidate/source/check pins.
- Candidate changes outside reviewed files, added hidden files/links or excessive diff reject; test whole-tree inventory and policy soft/hard scope.
- Reviewer approval text alone does not establish stopped SDK/fee/cleanup proof; test substituted report/session, unknown charge and missing receipt.
- Final review cancellation/expiry or altered candidate just before forwarding stops charging; test preclaim and live-forward races.
- Duplicate audit/export and cross-day scheduled plans cannot duplicate charges or masquerade as actual tests; test reader linkage and terminal reentry.

### Task 1: Candidate-bound readonly dossier

Files: create ops/pi/candidate_dossier.py; tests ops/pi/tests/test_candidate_dossier.py.
Interface: compile_dossier(request_path,request_sha256) -> dict(authority='none',candidate_sha256,model_view,model_view_sha256,artifact_pins).
- [x] RED unchanged/truncated/out-of-scope/oversize/secret/links, old-green-check, gold drift, unverified/unclean development and exact checks.
- [x] Compile complete selected original/candidate source and gold with bounded diff, frozen plan, baseline/final test facts and hash provenance; no imports/execution from candidate and no authority.
- [x] Run targeted tests; commit.22candidate tests and related suites passed; compiler is not an authenticator of completed SDK/manager provenance.

### Task 2: Fixed fresh SDK candidate review and proof

Files: create ops/pi/candidate_review_launcher.py and candidate_review_evidence.py; modify no_tool_host.py fixed role map; tests test_candidate_review_launcher.py.
Interface: prepare/prompt/input_hash/validate_output/check_live/publish_audit as existing no-tool contract; inspect(config,pin) authenticates immutable stopped/known-settlement proof.
- [ ] RED role/finite-root-permit/identity/budget pins, preforward expiry/revocation/candidate races, approve/reject/needs_evidence/invalid output, uncertain usage/cleanup, no replay and audit cost once.
- [ ] Reuse existing host lifecycle, independent no-tool session and original canonical ledger; bind candidate/dossier/report; keep executable_approval=False.
- [ ] Run related no-tool lifecycle suites and full offline tests; commit.

### Task 3: Host completion audit and native integration

Files: fixed post-manager completion adapter/service connection, docs/pi/agent-enhancements.md, administrator-audit-handoff.md and evaluation record; tests for completion paths and pure main reader.
- [ ] RED host-owned completed manager/proof only; failed/abstaining/pending runs retain truthful stages without fake acceptance. Duplicate ticks never repay.
- [ ] Generate finite candidate review inputs mechanically after verified successful development. Append distinct development/tools/test/review/no-release/version/changes and next-day test plan; export only bounded allowlisted fields. Existing followup controller remains sole execution authority.
- [ ] One independent final review/authorfix; full tests, exact HEAD CI, matched closed host/guest native proof and controlled real candidate review only for genuinely completed eligible candidate. Preserve existing owner002 acceptance/history without charging to rediscover it.

This plan does not complete the root goal. Genuine automatic new-task admission, authorized product adoption/observation/ownership-safe rollback and real24–48hour validation remain required.
