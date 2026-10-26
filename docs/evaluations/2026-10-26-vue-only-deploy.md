# Vue-only 发布回执（2026-10-26）

用户在审核及验证完成后授权提交、推送、更新部署。产品提交 `34b472cbc5efbc5ec705512be6c2c4467d8e73c3` 已推送 GitHub main，包含 Vue-only 清理及审核修复，不包含 Pi。

## 发布前确认

规范与需求两路复审无剩余可操作发现。同一源码最终回归：前端813通过、三浏览器222检查通过；Python1971通过、1跳过、5既有预期失败、2子测试通过。lint/build通过，有原有警告。跳过和预期失败不是通过，具体原因见[审核报告](2026-10-26-vue-only-review.md)。本次新增验证针对实际发布镜像，不伪称再次运行整套测试。

远程与本机均无queued/running/retrying任务。数据库custom dump及pg_restore目录校验通过，备份留在各自环境，未下载生产数据。重新捕获实际服务的旧assets并校验碰撞，保留10份兼容资源。首次用远程Docker包装器执行资源脚本时cp目标位于错误主机而失败，随后改为只读tar流捕获并逐文件碰撞校验；前次不计成功。

## 镜像

| 目标 | 镜像 | SHA256 |
|---|---|---|
| 远程amd64 API/worker | myink-api:34b472cb | bb2fa092b849c732df98729b5beffab5dedd59ff1cde41d2480f2f1b455b6034 |
| 远程amd64 Caddy | myink-caddy:34b472cb | 4b0b5a5d6665fb3045f50cf02d4ddf801fc6dbafc7a9fad37c9852031b94f31a |
| 本机arm64 API/worker | myink-api:local-34b472cb | c2f76a3e2efe860d188950abb688c0698c56dbd228c834b53db9c3d0926872f8 |
| 本机arm64 Caddy | myink-caddy:local-34b472cb | 117b40dc7805f6ccc7dc7a46ba296a7f1e82a78811ee63464f682516b515c54b |

revision标签均为完整产品提交。ARM API基于本轮已测试镜像，仅添加正式提交标签；x86 API按Dockerfile和依赖锁重新构建，在远程原生x86无网络临时容器验证SSE源码、25项核心依赖、113条契约及healthz。Caddy仅把Node构建阶段设为BUILDPLATFORM，运行层保持目标架构。

Vue release为 `vue-c36790bf5607dad89d0ce4f2705081b9dca7087c81ff373fb77b86c7dc41113e`，入口 `index-DAVLUFWH.js`。隔离候选、浏览器Vue实例、HTML/manifest配对、深链、缓存、旧资源哈希和404门禁通过。

## 运行与回退

本机已更新，API/Caddy healthy，worker运行；readyz的DB/Redis/worker均ok。原有1账号/1作品/1章，任务done1/failed1聚合计数未变。运维入口为 `.local/vue-only-34b472cb/compose.sh`，沿用上一轮保存的配置及原环境，保持1个worker，无旧源码挂载。

远程正式更新已完成。API/Caddy healthy、两个worker运行，四个容器revision均为产品提交；公网readyz的DB/Redis/worker均ok。公网真实浏览器确认Vue实例和新release，10份旧资源哈希及深链/缓存/404验证通过。升级前后均为8账号、20作品、59章，任务done23/failed9/awaiting_review1，孤立资源快照0。隔离候选容器、网络、SSH隧道和浏览器会话已清理。

备份位于远程 `/home/ubuntu/myink/releases/vue-only-34b472cb/` 和本机Git忽略的 `.local/vue-only-34b472cb/`。上一版API和Vue镜像保留before-vue-only-34b472cb标签；部署脚本失败时恢复上一版Vue，不恢复数据库。未删除数据卷、证书、密钥或其他分支/worktree。历史React镜像仅是旧备份，不再提供产品入口或日常部署切换流程。

证据目录 `/tmp/myink-vue-only-release/`。未调用付费模型、未写生产作品；聚合计数不能证明逐字段数据一致。长期线上观察及真实硬件输入法验收未冒充完成。
