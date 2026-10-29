# Vue 生产切换回执（2026-10-26）

## 授权与结果

用户授权验证后关闭原 React 生产入口并更新远程服务器，随后明确确认活跃用户已保存并关闭旧页面、可以切换。目标站点 https://myink.cloud ，SSH 别名 myink，部署目录 /home/ubuntu/myink。

已完成：原 c1f7a84 后端升级为 28ec51ba7a322001d47629455997bd1d5ab3ba02；先发布安全 React 过渡并验证，再将生产入口切为 Vue。API、Caddy 和两名 worker 均为该提交，API/Caddy healthy，readyz 的 Redis / DB / worker 全部 ok。生产 React 入口已替换；React 源码、回退镜像和旧资产继续保留。

本次未推送 GitHub main，未操作 Pi、其他开发分支或迁移 worktree；用户随后明确授权本机 localhost 同步切换，完成情况见文末。本回执是部署记录，运行时代码身份仍为 28ec51ba。

## 版本与资源

| 镜像 | SHA256 |
| --- | --- |
| myink-api:28ec51ba | 74767853ce222b3f02b05ffb94d4076f11d52fb1db22e0f85a32bf0b3b48d8c8 |
| myink-caddy:vue-28ec51ba | 30ba443e1f4cf4332caeebdb3163395533ca3cba3eee0530bb72ebe17f13ef6d |
| myink-caddy:react-28ec51ba | 46d31df66353bb05172e2805fb56ac82a2231b0cf5d126faaa6f7c1e45cdb39c |

全部 linux/amd64，revision 标签为完整 28ec51ba 提交；载入远程后的镜像身份逐字一致。Node 静态构建阶段使用本机架构（临时 Dockerfile 仅改 FROM --platform=$BUILDPLATFORM），运行镜像为目标架构。Node 实际 24.22.1，Caddy 2.11.4-alpine，Python 3.12-slim，核心 Python 依赖与已测试锁定版本一致。

Vue release：`vue-4f4b435d784b5a93b0cd69adb685740b635f0c9716d2fd362ab393425b7be1d2`，入口 `index-Bk-yDMAg.js`。
React 回退 release：`react-d22006ca4cb39f03420f9fb47f3e40b20035ac26e1d69cd0351c3b1a51153e3c`，入口 `index-BcR2NWy9.js`。

从远程实际运行镜像捕获 DgNUFC6h/BKYXJbT6 JS/CSS，从服务器保留的上一版镜像捕获 0E1RlPNN/BmUKS9ke JS/CSS，加上新 Vue/React 各两份，共 8 份 hashed assets。两个发布镜像携带相同并集；生产逐文件下载 SHA256 均与捕获/构建字节一致。资源仍由 Git 忽略，不把 .gitkeep 当作发布资产。

## 验证与保护

- 合并前已执行完整双端 lint/test/build、三引擎矩阵、SSE 50 项与后端最终1966通过，详见同日 main 合并报告；本次不伪称重复跑了整套测试。
- 本次重新构建实际发布镜像并验证产物；远程隔离候选的 Vue/React 版本、原生框架、登录页、深链、manifest/HTML 绑定、no-store/immutable、缺失资源404及非v1 API不落SPA通过。
- 原生 x86 无网络 API 镜像检查：SSE 源码、25个核心依赖版本、113条契约、healthz通过，临时容器清理无错误。
- ECR x86 Caddy清单首次401，改用同版本官方Docker Hub镜像成功；本机ARM模拟x86冒烟首次未在期限内就绪，不计通过，改在远程x86隔离容器实际验证通过。
- 用 agent-browser 独立会话先验证线上安全React过渡，再验证Vue上线；公网实际 `#root.__vue_app__` 为真、release正确，截图保留。没有登录真实账号或写生产作品，没有调用付费模型。
- 匿名 `/api/v1/projects` 按设计返回200空列表；管理员overview返回401。
- 升级前无 queued/running/retrying 任务；已有1个awaiting_review保持原状。前后聚合核对：8账号、20作品、59章；任务done23/failed9/awaiting_review1均未变。不以计数核对冒充逐字段数据一致性验证。
- 远程原API带Anthropic SSE空格热修复标记，部署前取出对应公开源码并比对，当前源码保留该逻辑，另含finish_reason/重试修复。
- 生产初始化只运行 `myink init`，未用seed；新增资源表/字段与关联约束，不重建数据库、不更换密钥、不清浏览器草稿。

## 备份、回退与清理

服务器 `/home/ubuntu/myink/releases/vue-28ec51ba/` 保留原 compose、仅服务器本地的私密环境副本（0600）、原镜像身份、数据库custom dump及pg_restore目录校验、初始化日志、过渡/Vue/健康回执和部署脚本。数据库备份3491046字节，不下载生产数据。原镜像另标记 before-vue-28ec51ba。

前端回退使用已验证的安全React镜像，保留当前API/worker与数据库：

```sh
cd ~/myink
sudo -n docker tag myink-caddy:react-28ec51ba myink-caddy:local
sudo -n docker compose up -d --no-deps --no-build myink-caddy
```

不得改用缺少新Vue资源的历史裸React镜像。后端有新表/字段；不要自动恢复旧数据库来回退前端。

本次远程隔离候选容器、专用网络、API smoke临时容器、本地SSH隧道及独立浏览器会话已清理。生产Redis/PG/RabbitMQ及证书卷保留；两worker规模保留。原未跟踪 .DS_Store 和 brief.pre-merge-local.md 未纳入提交。

本轮证据目录 `/tmp/myink-vue-release-28ec51ba/`。真实用户一周观察、硬件输入法及业务登录后实际写作验收仍需观察；旧离线标签页不会自动获得守卫，继续保留旧资源。合并报告中的既有同书调度竞态及两个P3未因上线被宣称已修复。


## 本机 localhost 同步切换

用户随后明确回答“也更新本机 localhost 为 Vue”。本机原由管理员 worktree Compose 与临时覆盖文件启动，API/worker 绑定旧管理员源码；本轮采用最小覆盖去掉 `/app/src` 绑定并清空 PYTHONPATH，实际运行 main 镜像。保留 `myink_pgdata_v2`、反馈/队列/证书卷、原环境配置及一个 worker。没有修改管理员 worktree 文件。

已备份本地原配置、镜像ID及数据库并校验dump目录；备份和运维覆盖在 Git 忽略的 `.local/vue-runtime-28ec51ba/`，敏感解析配置/备份未提交。原配置副本持久保存，未来运维不再依赖 /tmp 覆盖文件；project-directory 仍使用原管理员 worktree 以保留其环境配置，不应删除该 worktree/env 后直接运行此入口。

实际 ARM 发布镜像先通过隔离前端和无网络API检查，再安全React过渡、切Vue。localhost真实浏览器框架/版本、深链、缓存、10份旧新资产、API/资源404通过；API/Caddy healthy、单worker运行，readyz三项ok。前后仍为1账号、1作品、1章、done1/failed1任务。最终API/worker无旧源码挂载。

| 本机镜像 | SHA256 |
| --- | --- |
| myink-api:local-28ec51ba | 4de2fae3b6594e5b6ce2ff6c3677a44ea52ff7d3de29f32dec0efc1ca2d5b10d |
| myink-caddy:vue-local-28ec51ba | 3d8dedf1903e6bc593049d4a5dca2f9b49f97f438c99a3db7761acc075ec26bb |

本机继续运维使用 `.local/vue-runtime-28ec51ba/compose.sh`，而非旧管理员预览命令。前端回退：

```sh
.local/vue-runtime-28ec51ba/compose.sh -f "$PWD/.local/vue-runtime-28ec51ba/react.override.yml" up -d --no-deps --no-build myink-caddy
```

移除上述 React override 并用 compose.sh 启动 myink-caddy 即恢复Vue。过渡过程中出现一次短暂连接重置，重试后版本/健康全部通过；Compose提示已有命名卷不是它创建，原卷已核对并复用，没有删除重建。候选容器及独立浏览器清理完成。Hindsight写入超时，部署事实以本报告为准。
