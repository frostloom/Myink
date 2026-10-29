# VIP 生产发布

用户验收账号页后，授权在确认 VIP / 普通任务队列区分正确后提交、推送和生产部署。

## 发布门禁

- 最终独立队列审查无新增阻断；真实 RabbitMQ / Redis 隔离验证 38 项通过，包含 3:1 调度、100 条 VIP 积压下两 Worker 处理普通任务、心跳、停机、重投及确认丢失。
- 最终 Python：2190 passed、1 skipped、5 xfailed、2 subtests passed（360.10 秒）。跳过项需要专用评估数据库身份；五项为已有冲突样例预期失败。前端共享 207 + Vue 808 = 1015 项通过；lint 零错误、9 项既有警告，类型检查与生产构建通过。语法、4 项静态资源失败路径测试、评测清单及 119 条路径的 API 契约一致性检查通过。
- 发布镜像绑定本次提交，目标 linux/amd64；保留生产已服务的 hashed assets。
- 生产 API 与全部两份 Worker 协调升级，使用同一镜像版本。新任务接收关闭后再次检查无活跃任务，再停止 Worker 和备份数据库。
- 保留原环境配置、密钥、数据卷及队列参数。不运行 seed，不覆盖会员或模型策略。
- 开放 API 前，在隔离队列命名空间验证生产 broker 的双队列与延迟回投；普通/VIP 真实业务队列只读核对。
- 失败时先关闭新任务接收并检查新队列积压，禁止让旧 Worker 接管有积压的 VIP 队列。数据库不自动回滚。

当前远程基线：API / 两 Worker 为 a5ac4048，Caddy 为 b6f38a88。上线前只读检查：9 个账号、20 个作品、60 章；25 done、12 failed、1 awaiting_review，无 queued/running/retrying。

## 发布结果

发布跨越 2026-10-28 至 2026-10-29（Asia/Shanghai）。独立浏览器检查公网登录页正常显示，Vue 应用成功挂载；未登录真实账号。

源码提交 `d7ce4be90e76e7672d6ebbce6cedf70143efcc18` 已推送 `origin/codex/vip-service`，生产 https://myink.cloud 已运行该提交。API、Caddy 和两份 Worker 的完整 revision 一致，无源码绑定挂载；两份 Worker 均有独立有效心跳，日志确认已启动双队列公平调度。

| 镜像 | 生产与本机构建一致的镜像 ID |
| --- | --- |
| `myink-api:d7ce4be9` | `sha256:e75e0f955f3dff2945b8402dd3fd8cac141a35977055bba2661f75336119788b` |
| `myink-caddy:d7ce4be9` | `sha256:cbc780920d088047c5ac9dea06fe46b4b2d055d6661ef23e001c2f4038191747` |

生产 RabbitMQ 使用 UUID 临时命名空间验证了 `VIP, VIP, VIP, 普通` 两轮真实调度，以及普通/VIP 延迟消息分别返回原队列；测试队列和交换机已清理。实际生产保留原 `queue:tasks` / `queue:delay`，新增 `queue:tasks:vip` / `queue:delay:vip`，四者在发布回执中 ready/unacked 均为零。实际默认权重 3:1；这保证每个 Worker 的调度机会，无法保证固定等待秒数，当前正在生成的章节会先完成。

生产数据库备份已生成并通过 `pg_restore --list` 验证；只运行幂等 `myink init`，未运行 seed。发布前后聚合核对仍为 9 个账号、20 个作品、60 章。此为聚合核对，不宣称逐字段数据比较。环境、密钥、数据库、Redis、RabbitMQ 与证书卷继续使用原配置。生产 `/readyz` 的 Redis/DB/worker 全部 ok，前端 release 匹配候选镜像，两份旧入口静态资源逐字节保留。

服务器私有回执、环境/Compose 快照、数据库备份、隔离烟测脚本、发布脚本与兼容旧新静态资源的回退镜像构建记录位于 `/home/ubuntu/myink/releases/vip-d7ce4be9/`。回退前需关闭新任务接收并检查四类队列和活跃任务；有积压时保留新 Worker，不直接回滚旧消费者或还原数据库。初次构建回退镜像因裸镜像 ID 被误解为仓库名而失败，发生在服务切换前；修正为本地固定标签后重试成功。

未合并 main，未修改 Pi 或 main 工作区无关文件；未调用付费模型或代用户创建写作任务。
