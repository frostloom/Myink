# Pi 冻结请求的计费前校验

> 使用 superpowers:executing-plans；当前 Pi worktree 内联执行，完成后独立审查、单独提交推送。

**Goal:** 将可信宿主的冻结请求校验接入实际 HTTP 网关，在预算预留之前拒绝漂移或未获准请求。
**Architecture:** 为现有 make_gateway_handler 和 serve_gateway 增加可选 request_guard。校验只在身份认证、严格 JSON 解码之后调用；只有明确 True 才允许进入原计费流程。沿用原账本，不添加新预算或授权来源。
**Tech Stack:** Python、pytest、httpx、本机 HTTP 与隔离测试账本。
**Spec:** docs/superpowers/specs/2026-10-10-pi-autonomy-design.md；docs/evaluations/pi-analysis-contract-preregistration-2026-10-18.md；docs/superpowers/plans/2026-10-20-pi-analysis-runtime.md 的后续宿主绑定要求。

## Global Constraints

- 不触碰 main 和四项既有 Pi 修改；不发布、不调用付费模型、不修改原累计账本。
- 本目标仅完成网关校验接口，不声称完成持久化槽位、资源隔离或30槽真实对照。
- request_guard 是宿主代码，不接受请求参数指定；配置时必须有 scope_token，错误配置启动即拒绝。
- False、None、非布尔真值、异常均拒绝；不公开异常内容，不预留费用，不自动重试。
- 已有未配置 guard 的调用保持兼容；工具与证明路由仍由已有 broker 校验。

## Review Focus

- 认证和严格解析必须先于 guard；guard 必须先于 reserve/transport。
- SDK 两条 messages 路由一致，serve_gateway 必须传递 guard。
- 真实 HTTP 测试使用隔离账本，明确拒绝零条账本变化和已通过请求按原逻辑计费。
- callback 共享并发状态、跨进程恢复及持久化 cursor 不由此接口保证，文档必须说明。

### Task 1: 计费前宿主校验接口

**Files:** ops/pi/control.py；ops/pi/tests/test_gateway_admission.py；docs/pi/analysis-and-scoring.md。
**Interfaces:** make_gateway_handler(..., request_guard=None)；serve_gateway(..., request_guard=None)。宿主 callback(body) 必须返回 True。

- [x] 新增测试：两条路由实际 HTTP 请求，明确允许/拒绝/异常/错误返回值，冻结请求漂移，未认证与坏 JSON 不调用 guard，未配置保持兼容。
- [x] 运行 RED，确认缺失 request_guard 接口；最小实现再运行 GREEN。
- [x] 跑网关、工具 broker、冻结槽位相关回归，记录准确通过与跳过。
- [x] 更新维护文档，独立审查，修正阻断，提交并推送 Pi 分支，核对远程 SHA。

## 后续

持久化30槽游标/重放拒绝、整轮预算与期限绑定、当前源码版本严格进程隔离仍需完成。原累计20元及未知预留保持，不能把本接口测试通过当作付费调用许可。
