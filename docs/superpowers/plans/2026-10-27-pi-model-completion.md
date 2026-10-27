# Model-request completion reserve implementation plan

> Use executing-plans inline, TDD and one fresh independent final review.

**Goal:** Protect fixed model-request budget from source exploration without granting extra calls.
**Architecture:** Extend existing sticky Limits completion mode, read-only input validation and prompt; no gateway/budget or live execution change.
**Tech Stack:** Python3.12, existing controlled tool receipts.
**Spec:** docs/superpowers/specs/2026-10-27-pi-model-completion-design.md

## Global constraints
- Original cumulative50CNY policy stays closed,735historicalattempts/9unknown unchanged;0newmodelcalls.
- Original failed repository pilot remains blocked; no retry, adoption, main merge or deployment.
- Active reserve4futuremodels/8RPC; sourcecaps4096perread/12288total unchanged.
- Legacy Limits without reserve unchanged; active configs at least7requests, hard maxima unchanged.

## Review focus
- Model exhaustion with abundant RPC triggers source stop before paying for further exploration.
- Warning/repeated reads/cached receipts preserve authentication and original immutable receipts.
- Patch/check/status each leave enough future models and RPC, including zero/late/odd budgets.
- Small configurations fail before enable/payment; legacy short nondevelopment users remain valid.
- Offline tests do not become real candidate-success, Unicode-correctness or financial-reliability claims.

### Task 1: Model-aware finite completion path

**Files:** Modify ops/pi/development_launcher.py and development_inputs.py; create ops/pi/tests/test_model_completion_budget.py; update evaluation/metrics.
**Interface:** Limits.before_tool/admit_tool with existing Bridge; prepare_template rejects active budget<7.

- [x] Add meaningful request-budget/receipt/legacy/preflight/launcher tests; observe RED against current RPC-only code.
- [x] Minimal implementation and prompt, focused tests GREEN; original completion/launcher/inputs/wire-feedback regression.
- [x] One fresh independent review, author RED/GREEN fixes if required, fullPi/Node/syntax/diff verification.
- [x] Verify canonical ledger/closed policy/product state unchanged, publish offline-only result, commit/push samePi branch and exactHEAD4CI. No real retry.

Actual:25newcases23RED/2existingcontrols,84focusedGREEN,2906full/19deselected,Node54.0realmodels; original ledger/policy/manager/product unchanged and failedpilot retained. Independentreview record private; exact finalHEAD4CI checked afterpush.

Ruling: final6e202159CI Pi/image/backend passed but frontend failed atFeedbackWidget.test.tsx96. One author-only post-review CI fix: deterministic pending-submit diagnostic proves global text query matchesTEXTAREA; replace with awaited historylist+within. Original8 and full457tests/lint/build passed, diagnostic removed; no product/dependency/timeout/skip change, no secondreview or modelcall. Preserve failedCI, check successor exactHEAD4gates.
