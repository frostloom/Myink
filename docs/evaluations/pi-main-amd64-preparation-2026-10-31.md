# main 7e99f45f 的 amd64 生产产物准备

本记录推进已合入 main 的 Pi 管理台向生产接线准备，不构成产品发布或完整线上闭环验收。源提交 `7e99f45f6b70ee9713058f73b247552b4520c6b4` 的[四项远程 CI 均通过](https://github.com/frostloom/Myink/actions/runs/41174361943)，生产宿主架构只读核对为 x86_64。上一轮 arm64 镜像仅保留为本地验证历史，本轮另行使用 `--platform linux/amd64` 构建。

[完整机器可读清单](pi-main-amd64-preparation-2026-10-31.json)包含精确构建来源、镜像身份、源码/静态产物摘要、归档及原账本证明。

## 产物与验证

- `myink-api:pi-admin-amd64-7e99f45f`：amd64/Linux、固定 UID10001。在本地 Docker Desktop 的 amd64 仿真容器中验证 155 个 Python 源文件与源提交完整一致，包摘要 `72c97066e7dbf72b5745fddae46489e9ae62908023b786a5e83b125a4be8fe25`。镜像的 128 条 OpenAPI 路径与提交契约完整一致；非 root 实际进程、无网络、只读文件系统、丢弃 capabilities 下，未登录访问 `/api/v1/admin/pi/status` 返回 401 和 no-store。
- `myink-caddy:pi-admin-amd64-7e99f45f`：amd64/Linux、固定 UID10001，Dockerfile 内类型检查、Vue 构建和 Caddy 配置校验均通过。成品 5 个静态文件与已完成三引擎验收的构建逐文件相等，完整静态文件映射摘要 `dd53871e2e223ef6bd9b1193f5769e611fa5693ac90a63bdfcb55c4ae9889e76`；index 摘要 `3fcdda72ae5455deb2ac0defc0de4a759e8e47774f3ced9592c009b9b9d85629`。
- 两张镜像均带相同全长 revision label。仅以 amd64 平台导出本地 `/private/tmp/myink-pi-admin-amd64-7e99f45f.tar`，127,964,160 字节，SHA-256 `9bb13ed90f4ddb9bfdcea29029a825c53d4a1b5960e42f88a756531b616102de`。已读取归档 manifest/config，确认只有上述两个新 tag、均为 amd64/Linux/UID10001、来源 label 一致；未包含 `myink-api:local` 等生产常用 tag。
- 构建 daemon 的 image ID 可为 manifest index；目标 daemon 加载后的 ID 须重新读取。归档内 API config 为 `sha256:c95261f0a3e9d4bc077619e80d4c99b00194e1a8174c1762216cfdc40dc4dab7`，Caddy config 为 `sha256:ea3c94f49ed6b229d75182800766dc0672d2c4c845675776261266e759bf15ac`。不能将本地 ID 直接写成生产实际核验收据。

## 原线上状态与费用

通过服务器已验证的闭合 runtime，只读核对原 manager 和费用账本：manager 23 operations/2017 events，逻辑摘要仍为 `a588accf16ed7e7b1d3fc5e04709e000924010c6f840586ffbc2d2599ebf1eff`；费用账本 1478 operations/2559 events，摘要仍为 `fe7c37ea1259b0d92d51524d818703a7063a953e54e53b062dbc36b6eb844afb`。累计预算仍为50元，9笔历史未知预留不变；本轮没有模型请求、费用审批变更、未知费用释放或新账本。

原周期 `0ad352dc-888b-4a75-97d4-39296f327c6b` 仍处于 observing，实际部署时间 `2026-10-31T00:27:33.997950+00:00`，仍绑定原 `18b53e…` 镜像。直接检查 observation/assessment-* 目录列表为空。nightly timer active/waiting，下一次检查为11月1日02:00北京时间，服务上次结果 success/0；原部署次日评测在11月1日03:00到期。本轮未提前运行评测、修改时钟、回绑周期或重复旧意图。

## 仍待完成

本地 amd64 仿真与字节验证不替代 ACTUAL Linux 宿主、systemd 沙箱或 Unix peer 权限接线验收。归档未上传/加载至生产，root 桥接未安装，运行容器未替换。仍需明确批准新产品及桥接部署，按[管理员运行手册](../pi/admin-console.md)检查当前生产有效配置、原周期观察归属、原账本、物理镜像和权限，再核验实际运行版本。不得把本批 main 产物当成旧 f230 候选的原审批，亦不得改旧记录冒充已完成比较。

整体目标还需要真实到期的次日结果及由真实业务指标驱动的新任务、审核、隔离开发、失败调整和再次人工发布观察证据。准备镜像、绿色 CI 或旧固定案例不证明该闭环已完成。
