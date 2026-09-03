# Ai Ink — 长篇网文多 Agent 创作系统

面向长篇网络小说连续创作的多 Agent 智能创作系统。通过多 Agent 编排、审核路由、复盘沉淀与多级记忆召回，解决长文中的人设不一致、战力崩坏、剧情前后矛盾、长上下文过载等问题，实现「规划 → 生成 → 校验 → 记忆沉淀」的完整创作闭环。

## 核心能力

### 多 Agent 编排 + 审核中枢路由

- 基于 LangGraph 的两级图结构（批次循环图 + 单章子图），一次规划 N 章统一推进主线 / 支线 / 伏笔，批次失败断点续跑，不重跑已完成章节
- 审核中枢 Agent 输出 `pass / rewrite / replan` 三级路由：确定性规则层优先约束硬性指标（图谱、数值、时间线拓扑）并守住轮次预算，LLM 仅兜底语义判断；超预算自动转人工 `needs_review`
- Reflexion 复盘范式：批次收尾由 LLM 复盘生成经验（冲突原因 + 规避策略），分级沉淀后在后续章节主动注入，同类冲突自动累计规避，形成「犯错 → 复盘 → 少犯」的自进化闭环
- 整书大纲（建书第 ③ 步）：按梗概 + 大致章节数 + 大致故事线由 Planner 规划主线弧与逐章目标，落库后注入每一章的规划与写作——逐章推进主线、防止章节开头雷同；可编辑确认或暂不规划

### 三层记忆 + 混合召回

- 短期（上一章摘要）/ 中期（事件）/ 长期（事实）三层记忆分层组织
- PostgreSQL + pgvector 向量腿与人物名关键词腿（ILIKE）RRF 融合召回，硬约束恒在 Top-K、不参与相似度截断
- 上下文组装预算控制在 11–15k token，解决十万字长文的上下文过载与远期设定丢失

### 双层一致性校验

- L1 确定性校验（图谱 / 数值 / 时间线，零模型成本）+ L2 语义校验（LLM-as-judge，引用证据 + 置信度）
- 自建 40 条冲突样例评测集逐例验收：检出率 80.8%（21/26）、误报率 0%（0/14）

### 数据流边界

Agent 不直接写库：抽取层只输出候选进入待确认池，用户确认后由编排层落库；`critical` 级冲突自动暂停批次转人工，确认后从 checkpoint 续跑，闭环不可绕过。

### 工程化

- Go(Gin) 网关承载高并发面（限流 / 鉴权 / SSE），与 Python(FastAPI/LangGraph) 推理层通过 HTTP 解耦、独立扩缩容；Redis 队列异步任务 + SSE 实时进度，Last-Event-ID 断线追平不丢帧
- 多租户隔离默认拒绝：PostgreSQL RLS + 事务级 `SET LOCAL` 杜绝连接池跨租户串数据，向量检索显式 `filter` 走 HNSW 过滤索引保召回质量，网关 JWT 验签 + 应用层归属断言双保险
- 已落地 MCP Client 标准协议接入起点 DaoSearch 外部榜单（Streamable HTTP，白名单 sanitize + 优雅降级样例），榜单仅作建书前的题材风向灵感工具、不进入记忆 / 事实层、不注入任何生成节点

## 技术栈

| 层 | 技术 |
|---|---|
| 推理编排 | Python 3.12 / FastAPI / LangGraph / SQLAlchemy |
| 网关 | Go / Gin |
| 存储 | PostgreSQL 16 + pgvector / Redis 7 |
| 前端 | React 18 / TypeScript / Vite / CSS Modules |
| 部署 | Docker Compose 一键启动（单端口 8080） |

## 快速开始

```bash
# 一键启动全部服务（PostgreSQL+pgvector / Redis / Python API / Worker / Go 网关）
docker compose up -d --build
```

访问 http://localhost:8080（网关静态托管前端，同源提供页面 + API + SSE）。

- 无需配置也能启动并浏览界面；执行 AI 生成前在根目录 `.env`（参考 `.env.example`）配置 `DEEPSEEK_API_KEY`
- 向量召回默认关闭（`EMBED_ENABLED=0`），开启与模型下载见 [docs/DEPLOY.md](docs/DEPLOY.md)
- 首次启动自动建表 + RLS + 示例数据，幂等可重复执行

## 项目结构

```
src/aiink/        Python 推理层（workflow 编排 / api / models / providers）
gateway/          Go 网关（转发 / 鉴权 / SSE / 静态托管）
web/              React + TypeScript 前端
tests/            Python 测试（含冲突样例评测集）
spec/             API 契约（OpenAPI）与状态流设计
docs/             部署文档
docker/           initdb 脚本
```

## 测试

- Python：466 项通过 + 5 项预期失败标记，覆盖编排、校验、记忆、成本闸门、越权矩阵、扫榜 MCP 降级、关系图谱、伏笔池台账、整书大纲
- Go：网关契约与转发测试全绿
- 前端：45 项单测 + TypeScript 严格构建 + Vite 生产构建
- 契约：35 条路径 OpenAPI 契约回归闸，`aiink contract export && git diff --exit-code` 防漂移
