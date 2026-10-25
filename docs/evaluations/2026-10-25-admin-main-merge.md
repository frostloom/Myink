# 管理员分支合并验证（2026-10-25）

## 范围

- 合并前 main：`a4555e5b4082ee028ea7c479ad0bfb888a828121`。
- 管理员目标：`06c94cee6abd80248906e15824400233564c7659`，与拉取后的远程管理员分支一致。
- 合并整个分支的 12 个提交，使用 `--no-ff --no-commit` 先检查合并结果；没有 cherry-pick 或合入 Pi。
- 保留 main 的 AGENTS.md 开发分支约定、docs/BRANCHES.md 和原有去 AI 味能力。
- 唯一 Git 冲突为 docs/PROSE-RULES.md 的 add/add：采用资源版本化的现行说明，保留 main 初次接入的历史验证记录。

## 集成修复与独立审查

自动合并曾将 main 的硬编码表达规则与管理员可选资源并用，导致显式空选仍生效、选中重复注入。
新回归先复现了 8 个阶段的失败，再将默认规则移到未配置资源的公共消息入口。
已配置作品只注入选中的冻结版本；角色提示词目录不再复制可选表达规则。
保留原有默认接入测试，并覆盖空选、选中一次、修改发布内容与回退后的消息。

独立复审无剩余 P1/P2；规则/目录/资源运行时 77 项、角色提示词 13 项通过。
额外检查了角色编辑后的默认规则、固定输出协议和生产调用未绕过公共入口。

## 验证环境

专用 Compose 项目 `myink-main-admin-merge`，PostgreSQL/Redis/RabbitMQ 使用
45432/46380/45673 端口，未使用其他会话正在运行的 35432/36380/35673 环境。
Python 使用独立临时虚拟环境，依赖按 docker/constraints.txt 安装；前端使用 npm ci。

首轮全量测试因本机 .env 平台模型被 CLI 初始化导入专用测试库，产生 13 个失败、21 个 setup 错误。
已在测试进程显式清空 PLATFORM_MODEL_API_KEY/BASE_URL/NAME，仅重建本次专用数据库并重跑，
没有修改本机 .env，也没有改动其他测试环境或线上数据库。

## 检查记录

- 前端：71 个文件、584 项测试通过；lint 和生产构建通过。
- Python 语法编译通过；评测清单校验通过（20 audit cases、40 catalog entries）。
- OpenAPI 导出为 113 条路径，与管理员目标提交的契约一致。
- Python 与 Caddy 镜像构建通过，使用本机缓存的 public.ecr.aws 基础镜像和独立检查标签；Caddy 配置校验通过。
- git diff 空白检查通过。
- gateway 无变更，未运行 Go 验证。

保留前端 Fast Refresh/hooks、构建大 chunk，以及后端测试依赖的原有警告。
真实模型文笔对照不在本次合并验收范围。

最终后端全量结果：**1853 passed、1 skipped、5 xfailed、2 subtests passed**，耗时 209.51 秒。
跳过项为 `test_evaluation_comparison_integration.py::test_direct_full_and_ablation_preserve_all_outputs_and_persisted_body`，
该项要求独立授权的 localhost:15432 评测数据库身份，未为此次合并改动其隔离约束。
5 项既有预期失败为冲突样例 5–9：首次来访经历、已毁物品、伏笔兑现、能力前置条件与势力归属检测缺口。
跳过与预期失败均不计作通过；本次无非预期失败。

本次创建的专用测试容器与网络在验证后清理。构建镜像仅保存在本机独立检查标签，未启动。
按用户授权只创建本地 main 合并提交，不推送、不部署、不发布；原未跟踪 .DS_Store 未纳入提交。
