# Memory boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans, sequentially, on authorized main.

**Goal:** 修复四项已复现的记忆与恢复边界，逐项验证、提交、推送。
**Architecture:** 保守的文本等价比较；校正事务锁和语义判重；按最新保留来源限制关系撤销；摘要写入前验证正文与版本。
**Tech Stack:** Python, SQLAlchemy/PostgreSQL, LangGraph, pytest.
**Spec:** docs/superpowers/specs/2026-10-25-memory-boundaries.md

## Global Constraints

仅 main，保护无关文件，不部署；每项先 RED 再 GREEN，全量 Python 通过后提交推送再进行下一项。专用 Compose 服务，不与生产或其他会话共用端口。

## Review Focus

- 数值、否定、人物、追加条款不能被相似度吞掉；Task 1 回归覆盖。
- 待审与已拒绝的元数据变化、并发事务与删除后恢复；Task 2 覆盖。
- 有限期、明确删除及同章关系版本；Task 3 覆盖。
- 预算恢复前及模型调用期间的正文/版本变化；Task 4 覆盖。
- 旧 checkpoint 缺少新摘要版本字段时保守兼容；Task 4 覆盖。

### Task 1: Conservatively compare persisted text memory

**Files:** src/myink/memory/correction.py; tests/test_correction.py.
**Interfaces:** _sig, _close, diff_changeset and correct_chapter_memory retain their signatures.

- [ ] Add RED regression: stored 1.5→15, can→cannot, changed actor and appended clause each yield add=1/remove=1/keep=0, no_op=False, with pending decisions.
- [ ] Preserve whitespace/sentence-ending no-op; replace old wording-fuzzy expectation with explicit review-required wording change.
- [ ] GREEN: compare conservative normalized text equality instead of substring/fuzzy similarity.
- [ ] Run targeted correction/identity tests, then `python -m pytest tests/ -q`; expect exit 0, record skips/xfails.
- [ ] Commit and push this fix before Task 2.

### Task 2: Deduplicate across correction transactions

**Files:** src/myink/memory/correction.py; tests/test_correction.py; tests/test_candidate_concurrency.py.
**Interfaces:** Existing proposal identity, candidate status and tenant transaction.

- [ ] RED: two correction calls with payload confidence .9/.8 produce one pending candidate and one fact after approval; metadata-varied rejection remains rejected.
- [ ] RED: overlapping correction transactions for a project yield one pending proposal.
- [ ] GREEN: serialize correction transactions on project and compare proposal identity, including pending local additions; retain restoration behavior.
- [ ] Run correction/concurrency regressions and full Python suite; expect exit 0.
- [ ] Commit and push before Task 3.

### Task 3: Respect later retained relation versions

**Files:** src/myink/memory/invalidation.py; tests/test_invalidation.py.
**Interfaces:** Existing relation closure metadata and invalidation results.

- [ ] RED: ch1 ally→ch2 hostile→ch3 knows(valid_to=4), rewriting ch2 without relation leaves no active ally and preserves ch3.
- [ ] Cover explicit deletion, same-chapter supersession and cascade undo.
- [ ] GREEN: restore only eligible latest retained source, respecting later finite/removal barriers.
- [ ] Run invalidation/deletion tests and full Python suite; expect exit 0.
- [ ] Commit and push before Task 4.

### Task 4: Bind resumed summaries to chapter content/version

**Files:** src/myink/workflow/nodes.py; src/myink/workflow/runner.py; src/myink/workflow/state.py; tests/test_chapter_summary.py; tests/test_review_finalization_resume.py.
**Interfaces:** ChapterState checkpoint and conditional summary persistence.

- [ ] RED: actual historical restore while review summary paused retains restored content and summary on resume.
- [ ] RED: edit/restore during summary generation prevents stale output write; unchanged content/version resumes normally.
- [ ] GREEN: checkpoint summary version where known; check source body/version and conditionally update the same confirmed version after LLM returns, without holding an editing lock during LLM.
- [ ] Run summary/review/budget tests and full Python suite; expect exit 0.
- [ ] Run compileall, evaluate validate and contract diff; build final Python image. One independent read-only final review, resolve important findings by tests; no recursive re-review.
- [ ] Commit and push, clean only own test resources, report evidence and limits.
