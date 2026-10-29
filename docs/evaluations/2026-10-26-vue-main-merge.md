# Vue 迁移本地 main 合并验收（2026-10-26）

## 范围与身份

- 合并前 main / origin/main：`a96066c43b41e535da4b73e260a998ba9350c415`。
- SSH fetch 后来源 `origin/codex/vue3-migration`：`4d4ff31e0793b1bb53c7f2db7432c7e9e82c69ce`，与用户指定提交相同。
- main 是来源祖先；采用 `--no-ff --no-commit` 完整合并后验证，没有冲突。不合入 Pi 或其他分支。
- 阅读 AGENTS.md、remote-merge-handoff.md、safe-update-fixes.md、build-provenance.json、preview-and-rollback.md。
- 原未跟踪 `.DS_Store` 保持不动；同路径旧 brief 内容与迁移文档不同，原样另存未跟踪 `docs/work-items/vue3-migration-20261025/brief.pre-merge-local.md`，另有 `/tmp/myink-vue-main-merge/brief.original.md` 副本，不纳入合并提交。
- 合并包含完整 Vue、保留 React、构建/资源机制以及 `routes_sse.py` 和 `tests/test_sse.py`，无数据库 schema 改动。

## 审查与追加修复

code-review 两个独立只读审查分别检查 Standards 和 Spec；两轴均无新增阻断发现，不能代替运行验收。

本地 Node 门禁首次出现 3 FAIL：资产测试以 `URL.pathname` 启动子进程，在中文工作目录得到百分号编码路径，导致 MODULE_NOT_FOUND。仅改测试脚本使用 `fileURLToPath()`，保持生产脚本不变；同一门禁从 2 PASS / 3 FAIL 变为 5 PASS。追加差异经独立只读复核，无新增问题。原失败日志保留，不计通过。

## 验证环境与证据

本轮日志目录 `/tmp/myink-vue-main-merge/`。本地 Node 24.22.0，npm 11.19.1，执行 npm ci。Docker 构建使用缓存 ECR Node 24-bookworm-slim（实测 24.22.1）、Caddy 2.11.4-alpine、Python 3.12-slim；记录此基础系统与默认 Node alpine 的差异。

后端专用 Compose 项目 `myink-vue-main-merge`，PostgreSQL 45432 / Redis 46380 / RabbitMQ 45673，合成 seed 与模型替身；显式清空平台模型密钥，不借用生产数据、不启动生产 worker。没有运行固定项目/端口的 ci-local.sh，改用隔离环境下等价相关命令。

初始源码摘要与 build-provenance.json 一致：`af015b44509149b51d6b632b46bc3ab3852ffd39c3a22f5c4b680d3e1b62c387`。本轮双端构建 10 个记录产物 SHA256 全部与交接匹配；仅测试路径修复不改变运行时代码/产物。

| 检查 | 本轮结果 |
| --- | --- |
| 默认 Vue lint / 类型 / build | 通过，9 条 lint warning、大 chunk 提示 |
| npm test | 共享 205、Vue 576 通过，无跳过 |
| 显式 React lint / 类型 / build | 通过，12 条既有 lint warning、大 chunk 提示 |
| npm run test:react | 613 通过，无跳过；含共享测试，不累计为独立覆盖 |
| npm audit --audit-level=moderate | 0 vulnerabilities |
| Python 旧资产 helper | 4 通过 |
| Node 配置/资产门禁 | 修复后 5 通过 |
| compileall / evaluate validate / OpenAPI contract | 通过，113 路径契约无变化 |
| 后端完整重跑 | 1966 通过，1 skip、5 xfail 明确不计通过 |
| 隔离 SSE 专项 | 50 通过，1 条 Starlette 既有弃用 warning |
| 三引擎浏览器矩阵 | Chromium / Firefox / WebKit 共 12 组通过，各 28 冒烟 + 10 工作台 + 26 readiness + 10 发布切换检查 |
| React 回退工作台浏览器 | 10 项通过 |

浏览器使用仓库既有 Playwright 验收脚本、临时 profile 和 loopback 合成 API/SSE，不是本轮真实 worker/TLS/模型全链路验收。测试路径修复后的同算法源码摘要为 `282dabcbb582a6f09a4c607f562a1e8ef87a75a421f261334d759db62b4d31f8`；交接 provenance 保留原身份，没有覆盖历史记录。

| 镜像检查 | 本轮结果 |
| --- | --- |
| 默认 Vue / 显式 React / API 镜像构建 | 三者通过；均为本地检查标签，没有部署 |
| 两端 Caddy 镜像运行检查 | 各 7 项通过，cleanupErrors=[]；未声明已验证历史旧资产窗口 |
| API 镜像运行检查 | SSE 源码 SHA、25 个核心依赖版本、113 路径契约、healthz 通过，cleanupErrors=[] |

镜像身份：Vue `sha256:dd8217908fe09e37ea86f3d110ff37b7d2b41940b4da9e63fdd058a590ce27d5`；React `sha256:22409ee59b1b96a72b0d5fb6fb2b5f3c63bc5dd2fafa81bfd934abf2452e88bb`；API `sha256:5e63b2c0ec4fee8dbe3f9fd9472b4b8e69caf13747f7a1e1d30197e9452590a6`。API revision 标签为 unknown；这些是提交前源码检查镜像，正式发布须绑定最终提交重新构建。

首轮后端完整回归：1965 PASS、1 FAIL、1 SKIP、5 XFAIL、2 warnings、2 subtests passed。失败为 `test_multiprocess.py::test_same_book_serial`：两章同时投递时第 2 章先取得执行机会，因当前最大章节仍为 0 而被章节顺序校验拒绝；不是 SSE 断言失败。对比基线确认 worker、该测试及子进程替身完全未变。没有为过关放宽章节校验或修改既有调度策略。多进程模块独立复测 3/3 通过（83.24s），未改代码；最终完整重跑 **1966 PASS、1 SKIP、5 XFAIL、2 warnings、2 subtests passed**（276.55s，退出 0）。重跑通过不等于调度竞态被修复，该既有顺序问题保留为后续事项。

SKIP：comparison 集成要求另行明确批准的 localhost:15432 评测数据库身份，未借用该资源。5 XFAIL 是既有冲突样例 5–9 的未实现检测，不计通过。warnings 为 Starlette BlockingPortal 弃用和测试刻意使用较短 HS512 密钥。

## 发布边界与剩余事项

仅本地合并与验证，不推送 main、不部署、不删除迁移分支或 worktree。React 实现、显式回退命令和公开旧资源保留机制继续保留。

当前 main 的 retained-assets 只有 .gitkeep；历史捕获资产被 Git 忽略。本轮本地检查镜像不具备正式发布的旧客户端资产窗口，不能直接用于发布。正式发布须按 runbook 从当时应支持的实际镜像重新捕获公开资产，验证 Vue/React 双向并集，并配套含 SSE 修复的 API。

上线仍需独立授权：先安全 React 过渡，确认活跃用户保存/导出、关闭重开，再切 Vue。既有休眠/离线旧标签页不会自动获得守卫；30 秒等待不能证明收敛。真实用户至少一周观察、真实手机/硬件输入法和生产切换未执行。

交接已知 P3 保留：预算恢复成功可能保守多提示一次未保存；浏览器矩阵被硬超时终止时可能留下合成 profile 目录。无新增范围外重构。

## 清理与完成

本次专用 Compose 已 down --volumes，按项目标签复查容器和网络均为 0；镜像 smoke 回执 cleanupErrors 均为空。未操作其他会话及生产服务。检查镜像留作本地证据，不删除迁移分支/worktree。

全部要求门禁已完成；Go gateway 无变更，未运行 Go 测试。未触发远程 Actions、未重跑真实模型 HTTP/worker/TLS 全链路与生产旧客户端收敛验收，历史报告不冒充本轮新跑。合并提交通过本文件所在 Git 提交追溯；main 未推送。
