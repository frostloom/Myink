# 真实Pi分析与开发接力 Implementation Plan

> Execute inline with executing-plans/TDD; fresh static independent review; no candidate import on host or automatic Git operations.

Spec: ../specs/2026-10-24-pi-live-handoff-design.md

Files: new ops/pi/selection_launcher.py and workers/selection.py (single no-tool real analysis); new ops/pi/maintenance_adapters.py (authenticated selection and frozen-development preparation); new focused tests; development_launcher._exchange adds only fixed worker enum/default preserving original path. Product l1.py may only be changed by later reviewed realPi candidate. Existing dirty bytes protected.

- [x] Capture state/memory/dirty hashes; inspect phase, gateway, closure, preflight interfaces.
- [x] Freeze real-service entity-name regression plus prior106; actual isolated RED, no host product changes.
- [x] Write failing selection input/session/RPC/route/cleanup tests, implement bounded no-tool launcher/worker.
- [x] Write failing adapter/template/review/checkpoint/identity tests; implement trusted adapters without own approval or new budgets.
- [x] Run focused/fullPi/Node, independent static review/fixes; freeze current runtime and actualLinux synthetic chain, verify failure boundaries.
- [x] Independently approve exact fresh analysis config and task pack; real ACTUAL coordinator→Pi selection→fresh independent development review→Pi patch/check/status/auth; audit all fees/closed/cleanup/history.
- [x] Static final product exactSHA review then adopt; targeted/full product regression with fresh dedicated resources, preserve skips/xfails accurately.
- [x] Report actual outcomes/limits, update readiness/plan/memory, final protected-hash audit. No commit/push/merge/deploy.

实际验收见 docs/evaluations/pi-live-handoff-2026-10-24.md/json。先修复实际Pi cwd/system/RPC与离线fixture差异，保留MOCK001–003失败后MOCK004成功。真实001虽126PASS但静态审查拒绝，新增5边界隔离复现；002/003因固定64KiB请求停止，费用已知且清理完成；第四轮新身份131PASS/结束认证/独立静态精确SHA采纳。宿主只协调与写测试，产品补丁由真实Pi产生。完整产品1785PASS/1SKIP/3XFAIL/159未选，Pi2455PASS/19未选；全部原历史与非本轮脏文件保留。未提交、推送、合并、部署。
