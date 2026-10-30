# VIP Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理员可管理会员与模型权限，VIP 优先且普通任务不饥饿。
**Architecture:** 扩展现有平台 JSON 配置与用户 tier；双 FIFO 队列加权拉取，批次 checkpoint 让出 worker。
**Tech Stack:** FastAPI / SQLAlchemy / Pika / LangGraph / Vue 3。
**Spec:** docs/superpowers/specs/2026-10-28-vip-service-design.md

## Global Constraints
不提交、推送、合并或发布。不处理 Pi。保留旧配置、队列与消息兼容。权重各 1–10，默认 3:1。无支付。

## Review Focus
降级后旧模型选择与隐藏平台默认；多个 worker 的公平性；批次让出时确认丢失与崩溃；重试/死信跨等级路由；后台多个表单保存不能丢会员配置。

### Task 1: Membership and model policy
Files: src/myink/platform_configuration.py, providers/__init__.py, environment.py, platform_readiness.py, api/routes_environment.py, api/routes_platform.py; tests/test_vip_policy.py.
Interfaces: configuration adds minimum_tier, vip_model_routes, queue_weights; catalog/resolve/validate accept tier; tier_for_user reads current user.
- [x] Write tests for normal rejection, VIP access, downgrade, hidden defaults and invalid admin policy; run and observe failures.
- [x] Implement tier-aware policy and propagate identity through all entry points; add audited admin membership PUT.
- [x] Run targeted Python tests, including existing platform tests.

### Task 2: Fair queue and batch yielding
Files: worker/amqp.py, worker/consumer.py, worker/scheduling.py, worker/processor.py, workflow/runner.py; tests/test_vip_scheduler.py.
Interfaces: FairScheduler.take(channel, weights) returns delivery tuple; invoke_batch_slice returns scheduler_yield at chapter bridge, same checkpoint resumes.
- [x] Write continuous-traffic, empty-queue, legacy, confirmed-redelivery, checkpoint continuation and inflight-retention tests; observe failures.
- [x] Add separate durable FIFO queues and delay routes, weighted pull loop; route publications using existing server-selected priority.
- [x] Yield batches after bridge, mark queued, confirm continuation before ack and retain inflight membership.
- [x] Run queue/worker/batch tests with isolated services.

### Task 3: Administrator controls
Files: web/src/lib/platformApi.ts, adminApi.ts; web/vue/src/pages/admin/ModelManagement.ts, PlatformConfiguration.ts, UserDetail.ts and their tests.
Interfaces: preserve new configuration fields across every save; membership update returns id/tier.
- [x] Write and run failing interaction tests for minimum tier, VIP role routes, queue weights and membership changes.
- [x] Extend established forms and styles, preserve unrelated fields and handle errors/forbidden state.
- [x] Run frontend targeted tests then lint, all tests, build.

### Task 4: Review and verification
- [x] Run complete Python tests against isolated PostgreSQL/Redis/RabbitMQ; export API contract.
- [x] Independent reviewer reads full working diff and design; fix significant findings with regression tests.
- [x] Record real verification results and deployment migration instructions, leave changes uncommitted for user review.
