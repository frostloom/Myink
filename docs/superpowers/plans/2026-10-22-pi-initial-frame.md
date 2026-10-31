# Pi initial frame Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Bind full real retained inputs without changing prompts or relay boundaries.
**Architecture:** Separate the one trusted initial message from subsequent relay frames; keep bounded byte-level validation at every input boundary.
**Tech Stack:** Python3.12, pytest, fixed Linux Docker Node/Pi runtime.
**Spec:** docs/superpowers/specs/2026-10-22-pi-initial-frame-design.md

## Global Constraints

INITIAL_FRAME_LIMIT524288 includes newline; subsequent FRAME_LIMIT196608, HTTP65536 and aggregate output1048576 unchanged. Full views/report and identities preserved. Canonical policy stays disabled; no paid execution, new scope, unknown release, merge or deploy.

## Review Focus

- ASCII encoding expansion and terminating newline counted identically at each initial boundary.
- Larger initial allowance never leaks into relay replies or untrusted output.
- Full report and frozen request identity survive transmission.
- Oversize/slot drift stop before admission; source pin changes after code edits.
- Non-live binding preserves canonical DB/WAL/policy/credential bytes and real reports.

### Task 1: Separate initial limit and complete real-input binding

**Files:** container_runtime.py (initial transport cap), analysis_launcher.py (preflight cap), lab/container_runtime_worker.py (read/validate cap), tests/test_container_initial_budget.py and existing worker oversize test; evaluations and README.
**Interfaces:** consumes existing full frozen slot/view/report; produces INITIAL_FRAME_LIMIT and unchanged exchange/launch signatures. Shared interface: launcher/exchange/worker must use identical initial byte limit; subsequent paths keep existing FRAME_LIMIT.

- [x] Write tests for large full report through launch and worker, exact byte boundaries through real stdio child, drift and unchanged relay limits. Run targeted test: expect large initial cases fail under old196608 limit.
- [x] Add minimal INITIAL_FRAME_LIMIT524288 initial-only handling, update existing oversize fixture above new cap. Run targeted tests: expect all pass.
- [x] Freeze new source, actual Linux two-slot synthetic acceptance with300KB unused report metadata: expect full identities/diagnostics/settlement/cleanup pass. Rebind real five-group inputs and current source; default check must succeed with launch_ready=false and no result root, preserve protected original bytes. Keep all first failed preparation evidence.
- [x] Run full offline Pi suite and syntax/diff checks; expect no failures, record skips/deselections accurately. Publish no-secret evaluation with retained evidence SHA.
- [x] Independent final review, act on findings, commit/push Pi branch and update myink memory. No paid execution.
