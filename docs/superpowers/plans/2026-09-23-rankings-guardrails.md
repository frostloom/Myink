# 扫榜客户端防护 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans.

**Goal:** 消除分类假书、工具猜测及参数错配；不声称切源完成。
**Spec:** docs/superpowers/specs/2026-09-23-rankings-guardrails-design.md
**Architecture:** 当前 MCP 客户端的精确分派与确定性输入过滤；无服务/数据库变更。
**Tech Stack:** Python / pytest。

## Global Constraints

- 用户已授权连续执行、逐目标提交推送与 CI；有风险的外部前置暂缓而非代为接受。
- 不碰 Jev、模型网络守卫、正式配置和数据卷；保留 worktree/测试记录。

## Review Focus

- 分类容器混入真实书籍、包装在 items 中、伪造 rank 字段是否仍会显示为书。
- source/tool 覆盖错配；未知工具不得调用；缺工具明确降级；成功才写缓存。
- 旧合法书籍无需新增字段即可显示；现有账户缓存隔离不退化。

### Task 1: 客户端精确分派和分类过滤

**Files:** Modify src/myink/integrations/rankings.py, tests/test_rankings_mcp.py.
**Interfaces:** _find_tool(tools, source, override) -> str | None; _tool_args(tool) -> dict | None; sanitize(raw, limit) unchanged.

- [ ] 添加回归：未知 source 不猜；list_rankings/未知 override 不调用；community override 使用 community 参数；分类顶层/嵌套/混合不能当书；失败不缓存；取消文案不误导。
- [ ] Run python -m pytest tests/test_rankings_mcp.py -q; Expected: RED on existing behavior.
- [ ] 按精确工具名取参数，无映射返回明确 sample；过滤分类容器而非递归猜测；不修改配置默认。
- [ ] Run python -m pytest tests/test_rankings_mcp.py tests/test_environment_routes.py -q; Expected: green.
- [ ] Run python -m pytest tests/ -q; Expected: green, existing xfails disclosed.
- [ ] 提交目标；新上下文独立审查，Important/Critical 一次 RED→GREEN 修正；推送 main，确认精确 SHA CI 三项成功。
