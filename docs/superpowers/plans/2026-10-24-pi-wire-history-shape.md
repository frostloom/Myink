# Pi source-history SDK representation fix

> Execute inline using executing-plans and TDD; one independent review at the end. User has delegated routine decisions and opted out of repeated clarification. No Git actions.

**Goal:** Make existing strict request-only stale-source projection work for canonical string tool results actually emitted by pinned Pi1.1.0, alongside existing one-text-block arrays.

**Architecture:** Preserve current source identity/binding/window/receipt checks and original representation. Decode only string or exactly one text block; require canonical JSON and all existing checks before replacing only stale `evidence.text`. No changes to durable session/receipt, current source, tools, fees, limits or host execution schema.

**Scope:** `ops/pi/lab/pi-wire-guard.mjs`, pinned no-tool guard SHA in `ops/pi/pi_config.py`, Node history tests, documentation/report. Product source untouched. Existing dirty files snapshotted privately. Memory recall attempted but localhost service timed out; continue without it.

**Evidence:** Actual002 route13 contains canonical string results, not arrays; current projection leaves it unchanged. UTF8 body is60093 bytes but actual host ensure_ascii wire is67814, over65536. Actual003 must be separately classified; invalid/failed reads continue preventing elision rather than silently passing. No historical run replay or fee ledger mutation.

- [x] Offline recorded-request diagnosis; capture string/array and ensure_ascii sizes, preserve source files.
- [x] RED tests: real SDK strings, mixed representations, Unicode, canonical/malformed strings, binding/failed/pending/recurring-source boundaries, original no-mutation; existing arrays unchanged.
- [x] Minimal decoder/writer preserving representation; update owned pinned SHA; related Node/Python checks.
- [x] Replay actual002/003 offline, explicitly report residual fail-closed cases. Fresh full runtime and real Linux MOCK verifies pinned SDK wire projection while durable session remains original, original cap remains enforced. No paid calls required for protocol fix.
- [x] Full Pi/4Node tests and fresh independent review; fix findings, document evidence and limits; memory and protected-file audit. No commit/push/main merge/deploy or server enable.

验收：Node21，相关Python73，完整Pi2455/19未选，4Node脚本；Linux MOCK分析1+开发11、固定10PASS、三次投影及持久原文认证通过。真实账本/策略/凭据不变，零真实费用。记忆读取已尝试但服务超时，按项目规则不阻塞。见docs/evaluations/pi-wire-history-shape-2026-10-24.md。
