# 连续执行记录

## 范围

本轮继续此前已确认的 docs 新计划：不可达提示（已完成）、局部修订、短篇、扫榜换源；排除 Jev。
BACKLOG 是 9 月 18 日历史索引（含已完成认证、已取消机制及运维事项），不将其未经核对的 31 条视为本轮新施工单。
用户要求连续执行、不逐项询问；涉及破坏性风险或新增授权时采用安全替代，否则暂缓并继续其他目标。

## 正式部署基线与结果

2026-09-22：8ef0783 镜像构建成功，compose --no-deps --no-build 仅重建 API/worker/Caddy。
API 与 Caddy 健康；/readyz 返回 redis/db/worker 均 ok；登录页 200。
未登录作品列表为既有 fail-closed 空列表，旧作品章节请求 403。
前后 users=2 / projects=7 / chapters=44 / chapter_versions=19 / project_settings=7，逐表数据摘要完全一致。
PostgreSQL myink_pgdata_v2、RabbitMQ myink_rabbitmq-data、Redis 原匿名卷、Caddy data/config 均未换卷。
保留旧 gateway 孤立容器及所有旧卷，未执行 down/prune/remove。

## 进度

- 已完成：不可达提示，最终 CI 35746819460 三项通过；本轮已部署正式容器。
- 已完成代码与 CI：局部修订（全链复审、独立预算、失败保留原稿、scope 可见）。3225c8d 已推送 main；CI 35754841453 三项成功。本地 Python 1012 passed / 5 xfailed，前端 253 passed，lint/build 通过。独立审查两项 Important 已 RED→GREEN 修复，无遗留 Minor。正式容器最终部署另记。
- 已完成代码与本地验证：扫榜客户端防护（精确工具与参数、拒绝分类假书）。全量 Python 1021 passed / 5 xfailed；独立审查与精确 SHA CI 结果见本任务最终交付。完整换源仍未完成。
- 暂缓：短篇产品实现。管理员 7 项目均无可用 writer 连接，无法通过 2 万字真实输出前置门槛。改进意见及解除条件见 ../specs/2026-09-23-short-form-preflight.md。
- 已完成代码（本地验证待补）：扫榜换源落地——绕开 sidecar 与上游 MCP，直连番茄榜单公开接口 `api-lf.fanqiesdk.com`（形状取自 inkos `radar-source.ts`），httpx 取数隔离在 `integrations/fanqie.py`；`rankings_source` / `rankings_tool` 及其死码删除，MCP 客户端与连通探针保留。
- 暂缓（2026-09-23 后续已解除：改为直连番茄公开接口，见上条）：扫榜 sidecar/正式默认切换。上游 README 有 MIT 字样但无完整 LICENSE 文件（GitHub license=null）；目标 ECS 网络未验证。本机番茄页面 200 不能替代云端验收，且直接 HTML 抓取有 PUA 书名问题。未复制第三方代码、未放宽 SSRF、未部署不存在的 sidecar。见 ../specs/2026-09-23-rankings-guardrails-design.md。

## 可复查的 CI

- 不可达提示：[8ef0783 / 35746819460](https://github.com/frostloom/Myink/actions/runs/35746819460)。
- 局部修订：[3225c8d / 35754841453](https://github.com/frostloom/Myink/actions/runs/35754841453)。
