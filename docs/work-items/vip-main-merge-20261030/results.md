# VIP 与非 Pi 分支合并验收

用户授权：将 VIP 及其余非 Pi 分支完整并入本地 main。此次不推送、不部署，不收录其他工作区未提交实验。

## 计划与边界

- [x] Fetch 后核对本地与远程分支；保护原有两个未跟踪文件。
- [x] 管理员 `06c94cee`、Vue 迁移 `4d4ff31e` 已是 main 的祖先，无需重复合并。
- [x] main 基线 `b6f38a886efd653c529455ca098c0a583f8116ee`；VIP 来源 `a3a37960`，共 11 个新增提交。来源包含 main，采用完整 no-ff 合并，无冲突。
- [x] 独立审查合并范围与关键业务风险。
- [x] 隔离 PostgreSQL / Redis / RabbitMQ 全量 Python 回归及 API 契约校验。
- [x] 前端 lint、单测、类型检查、构建、浏览器矩阵及静态资源辅助门禁。
- [x] 镜像构建验证、清理本轮专用测试环境、完成本地合并提交。

使用专用 Compose 项目 `myink-vip-merge-20261030`，随机 loopback 端口；不连接生产数据库，不调用真实模型。现有 localhost 与远程服务不切换。

Pi 的本地与远程独有提交均不参与本次合并；VIP 工作区未跟踪的 proof-loop/action-matrix/chapter-checks 实验文件不属于分支提交，不复制进 main。

## 验证结果

- 原合并树全量 Python：2261 passed、1 skipped、5 xfailed、2 subtests passed；628.48 秒，退出 0。跳过项要求指定 localhost:15432 评测数据库身份，本轮随机端口隔离库不满足该条件；5 项为既有冲突检出能力 xfail。2 个既有 warning。日志 `/tmp/myink-vip-merge-python.log`。
- API 契约导出后与合并索引一致；语法检查和评测案例清单验证通过。
- 前端 shared 207、Vue 821 项通过；lint 无错误、9 个既有 warning；严格类型检查和构建通过（既有 PostCSS/chunk 提示）。
- 三浏览器最终矩阵 21/21 通过：`/tmp/myink-vip-merge-final-matrix/receipt.json`。首次运行暴露旧定位器/fixture，修正后完整重跑，不计首次失败为通过。
- Node 辅助门禁 10/10、公开资产提取失败路径 4/4 通过；npm audit 无漏洞。辅助检查首次缺少 Playwright 路径，明确配置已有测试浏览器后重跑通过。
- Python 与 Caddy 镜像构建通过；官方源首次超时后使用项目既有镜像源构建。Caddy 镜像以 uid 10001 检查入口、release、配置和 assets 可读，通过。均未用于部署。

## 审查修复

独立审查发现 VIP 切片批次在规划失败到达 END 后，续跑只重放旧错误。先添加真实 LangGraph 内存 checkpoint 回归，原实现失败；修复后区分未完成/成功终态与失败终态，失败时合并 checkpoint 进度并清理旧 error/batch_failed，再重新规划。新增两项回归覆盖失败重试、保留 position、后续让出调度、成功终态不重跑。复审通过。全量测试在修复前启动，最终修复另跑相关定向回归，最终定向回归 82 passed / 1 failed：双 Worker 压力测试在 20 秒内未达到 104 个完成任务。原始 Worker 日志显示 101/104 完成、零 ERROR/WARNING；不改代码和超时单独复跑，104/104 完成并通过。后续批次/恢复/全局审计/复盘与该压力案例共 74 项通过（97.04 秒）；日志 `/tmp/myink-vip-merge-resume-confirm.log`。新增真实 checkpoint 回归独立 2/2 通过。

四个浏览器脚本随新界面同步：按可访问名称选六角色模型；移动端先展开后台菜单；注册卡片标题和 612px 内容宽度；资源选择区分新建作品个人版本与已有草稿快照，并显式补上新文风目录 GET fixture。原未知请求、选择提交顺序、生成次数及不溢出断言保留，独立复审通过。

Go 未运行：gateway 无改动。真实模型效果评测、生产迁移/发布、远程 CI 未运行：本轮仅本地合并与隔离验证，没有推送。

最终处理：临时测试容器、匿名卷、专用网络与本轮检查镜像清理；原有未跟踪文件和其他工作区保留。main 合并提交的两个父节点分别为 b6f38a88 与 a3a37960；除审查修复、浏览器测试适配和本文外，保留整个 VIP 分支内容。
