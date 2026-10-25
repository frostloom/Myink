# Admin usability and prompt coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task.

**Goal:** 让管理员理解并配置真实写作行为，以清晰滚动布局和真实趋势数据操作后台。
**Architecture:** 保留已有主题、资源版本与任务快照；自动角色模板与用户选用素材分层。统计沿用只读报表连接与审计。
**Tech Stack:** React19, TypeScript, CSS Modules, ECharts6, FastAPI, SQLAlchemy, PostgreSQL.
**Spec:** docs/superpowers/specs/2026-10-24-admin-usability-prompts-design.md

## Global Constraints
- 仅管理员worktree，保护现有未提交代码，不提交/推送/部署。
- 数据库检查只用独立Docker端口35432/36380/35673，串行运行。
- 输出协议不允许平台编辑移除；任务必须冻结发布时资源版本。
- 沿用现有界面主题、表单组件与依赖，不引入新UI库。

## Review Focus
- 长内容、窄屏及弹窗不能出现嵌套纵向滚动。
- 角色模板发布不能污染已受理任务或用户私有资源。
- 旧资源数据技术字段隐藏但保存不能丢失。
- 真实日期趋势必须包含空日期且遵循管理员审计、只读边界。
- 草稿/回退/归档与角色范围不能跨角色覆盖或泄漏。

### Task 1: 布局与表单
Files: AdminPage.module.css, AdminRail.module.css, AdminResources.module.css, AdminDialog.tsx, ResourceBodyFields.tsx, ResourceContent.tsx and focused tests.
- [x] 复现嵌套滚动，新增必要交互测试。
- [x] 移除内层高度限制，弹窗冻结背景；按创作用途隐藏/改写技术字段并保留原始值。
- [x] 定向测试与浏览器长内容验证。

### Task 2: 真实趋势
Files: api/routes_admin.py, api/admin_schemas.py, adminApi.ts, AdminPage.tsx OverviewView, new charts components and tests.
Interface: audited GET /admin/trends with bounded date range returns daily user/project/chapter/task/run/token/cost counts.
- [x] 新增聚合/空日期/边界鉴权测试并确认失败。
- [x] 实现真实日期聚合，汇总指标和自适应图表、日期筛选、空状态。
- [x] 前端定向检查；数据库测试由主代理统一串行执行。

### Task 3: 角色创作要求与资源用途
Files: prompt_catalog.py, writing_resource_seed.py/schemas.py/runtime.py, writing_resources.py, task freeze paths; WritingResources.tsx and role editor components.
- [x] 盘点每阶段系统提示词及固定规范，写覆盖清单。
- [x] 添加自动角色资源，保留固定协议；新增红测覆盖发布/回退/任务快照/私有隔离。
- [x] 自动角色编辑卡片与实际时机说明，可选资源用途标识和用户自行设置说明。
- [x] 实际provider消息验证，契约同步。

### Task 4: 交付验证
- [x] 独立代码复审并处理问题。
- [x] 串行后端全量、前端lint/test/build、浏览器滚动与图表可视验证。
- [x] Hindsight记录长期配置与完成的变化；汇报实际验证及未部署状态。

最终验证：后端1807 passed、1 skipped（独立15432评测库要求）、5 xfailed；前端542 passed、lint无errors、build通过（保留现有lint和大chunk警告）；桌面和390px手机下弹窗仅DIALOG滚动且textareaNested=0，真实QA角色草稿→预览→发布成功。临时QA数据库/进程/浏览器已清理，基础Docker测试环境保留。未提交/推送/合并/部署，用户库未迁移。
