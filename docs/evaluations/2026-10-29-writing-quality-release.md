# 个人页面与写作资源发布回执

2026-10-29，用户授权先推送部署已验收界面，再核对写作资源、调研 GitHub 并将合适的规则与通用文风用于系统。用户明确选择自然表达与情节推进兼顾、按题材调整。

## 已发布版本

| 组件 | 源码版本 | 发布结果 |
| --- | --- | --- |
| Caddy / Vue | `a8a4361ec1a9d3b5b8aa82ffa081f006d542ed82` | 高级设置、注册登录及文风库改版；公网浏览器确认新登录标题及 Vue 挂载 |
| API / 两份 Worker | `d25d82752d4821ae701f3ed7ebbffea01b4b63f7` | 三组规则、三种通用文风、长篇私人文风审改输入修复 |

代码推送 `origin/codex/vip-service`，未合并 main。入口 https://myink.cloud 。本轮未更新 localhost 的质量后端，localhost 仍为此前个人页面预览；不要混淆本地与生产镜像身份。

## 资源与使用

新增公开版本 1：

- `writing-rule:scene-causality`：场景因果与有效推进。
- `expression-rule:dialogue`：人物对白与潜台词。
- `writing-rule:genre-pacing`：题材节奏与承诺兑现。
- `style:natural-narration`：自然叙事（通用）。
- `style:brisk-narration`：明快叙事（情节向）。
- `style:character-narration`：细腻叙事（人物向）。

文风库实际运行注册表已核对为原四项加新三项，共七项。新文风由作者选择，私人档案优先；新规则沿用现有项目初始化与显式选择机制，已有快照、明确取消项和管理员已有出版版本不强制变更。使用方式与来源选择见 [WRITING-QUALITY-SOURCES.md](../WRITING-QUALITY-SOURCES.md)。

## 验证

- 前端 207 共享 + 809 Vue = 1016 项通过；lint 0 errors、9 项既有 warnings；类型检查和构建通过。
- 后端最终 2212 passed、1 skipped、5 既有 xfailed、2 subtests passed，292.71 秒；跳过项要求单独批准的评估库身份，未算通过。
- 资源相关隔离集成 167 项、审查后相关集 99 项通过；独立 reviewer 38 项纯测试通过。角色替换、输入不变、版本冻结、取消选择、预算超限及 provider 边界均覆盖。
- 生产原生 amd64、无网络临时候选镜像通过源码、测试核心依赖版本、119 路径 API 契约和 healthz 冒烟；临时容器清理无错误。
- 前端发布时 API/Worker 容器 ID 未变，两个旧入口资源逐字节保留；后端发布时 Caddy 容器 ID 未变。
- 最终 readyz 的 Redis/DB/worker 全部 ok，两份新 Worker 均有有效心跳，API 与两份 Worker 完整 revision 一致、无源码绑定挂载。
- 后端升级前无 queued/running/retrying 任务和四类队列积压。关闭 API 接收后再次核对，然后停 Worker、保存数据库 custom dump 并通过 pg_restore 清单校验。
- 只在迁移服务的管理员会话中事务创建本轮六项缺失条目，没有运行全量 init 或 seed；发布前后新增集合精确匹配，原有 **134 项资源**的 generation/current_version/body/publication 哈希均保持不变，**作品资源快照哈希不变**。
- 聚合核对前后均为 **9 账号、20 作品、60 章**。不将聚合计数冒充所有业务字段的逐字段比对。

未调用付费模型做文学质量盲评；这些检查证明接入和运行保护，不证明真实生成文字更好或 AI 检测概率下降。参考资料的目录注入与真实工具读取也已明确区分。

## 备份与恢复

服务器私有目录：

- `/home/ubuntu/myink/releases/personal-ui-a8a4361e/`：前端发布脚本、回执、原镜像和带旧新资源并集的兼容回退镜像。
- `/home/ubuntu/myink/releases/writing-quality-d25d8275/`：后端原镜像身份、原环境/Compose 私密副本、数据库备份与清单、资源/作品快照哈希、定向发布脚本和验证回执。

后端旧镜像标记 `myink-api:before-quality-d25d8275`，恢复前关闭接收并检查活跃任务与普通/VIP主/延迟队列，不能删除积压或恢复旧数据库来回退应用。新增资源为兼容的附加数据，失败回退不删除管理员和作者可能已经采用的资源。保持两份 Worker 同版。
