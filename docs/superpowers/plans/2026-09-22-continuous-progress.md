# 连续执行记录

## 范围

本轮继续此前已确认的 docs 新计划：不可达提示（已完成）、局部修订、短篇、扫榜换源；排除 Jev。
BACKLOG 是 9 月 18 日历史索引（含已完成认证、已取消机制及运维事项），不将其未经核对的 31 条视为本轮新施工单。
用户要求连续执行、不逐项询问；涉及破坏性风险或新增授权时采用安全替代，否则暂缓并继续其他目标。

## 正式部署基线与结果

2026-09-22：6692728 镜像构建成功，compose --no-deps --no-build 仅重建 API/worker/Caddy。
API 与 Caddy 健康；/readyz 返回 redis/db/worker 均 ok；登录页 200。
未登录作品列表为既有 fail-closed 空列表，旧作品章节请求 403。
前后 users=2 / projects=7 / chapters=44 / chapter_versions=19 / project_settings=7，逐表数据摘要完全一致。
PostgreSQL myink_pgdata_v2、RabbitMQ myink_rabbitmq-data、Redis 原匿名卷、Caddy data/config 均未换卷。
保留旧 gateway 孤立容器及所有旧卷，未执行 down/prune/remove。

## 进度

- 已完成：不可达提示，最终 CI 35746819460 三项通过；本轮已部署正式容器。
- 进行中：局部修订（采用全链复审与独立补丁预算）。
- 待执行：短篇、扫榜换源；先核实原施工单前置条件，不把未实测能力称为通过。
