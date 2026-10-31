# Pi 管理台接入与人工发布

入口 `/admin/pi`，只向每次请求仍具备管理员角色的账号开放。产品 API 先验证真实会话、写入现有访问审计，才访问宿主 Unix socket。页面显示原始审计导出中的运行、指标窗口、判断、模型建议、工具输入/输出摘要、检查计数、每日版本/变更范围和次日计划。固定输入回归通过不代表线上效果改善，窗口重叠不累加样本；未知及未执行保持原样。

候选准备后长期等待。点击“查看并发布”打开精确镜像/产物确认，再点击“确认发布镜像”才记录决定；“暂不发布”只记录继续等待，不取消已经受理的发布。服务器重新核对当前轮次、镜像、源码、比较参数和产物摘要。请求幂等，已受理的轮次不并发发布；宿主中断或结果未知保留 `uncertain`，不能自动重放。只有物理部署核验通过才进入观察，并以实际部署日的次日北京时间 03:00 登记冻结回归和指标观察。旧调度器不能绕过本轮等待。

此发布通道只替换同一 Docker daemon 中 API 与两个 worker 的本地镜像，保留命令、环境业务配置、挂载、数据库、缓存、队列和 Caddy。业务队列必须空闲。它在根拥有的私有 Git 对象库保留与完整 Python 镜像包字节对应的候选提交，不改 main、不推 GitHub/registry。源码推送仍需另行核对和执行。未知结果需人工核对原操作回执、实际容器及原 Gate，不能删除 intent 或新建请求尝试重放。

## 上线前准备

本文件是待执行的部署清单；合入 main 不会自动更新服务器镜像、安装服务或开放发布。先完成 main CI 并确认产品部署。以下操作只由有宿主权限的运维执行，浏览器不能提供这些路径或配置。

- 既有根目录固定为 `/home/ubuntu/myink-pi-managed`，产品 Compose 在 `/home/ubuntu/myink`。复用原 `state/nightly-approval.sqlite`、`state/actual-manager.sqlite`、`state/ledger.sqlite` 与 `audit/state/events.sqlite`；不初始化新任务/费用账本，不覆盖已有审批。
- 将本提交的 `docker-compose.pi-console.yml` 放到产品目录，与原 Compose 一起运行。只有 API 挂载 `/run/myink-pi-console`，只读，容器 UID/GID 为现有 10001。worker 不挂载，产品容器不持有 Docker socket、模型凭据或原 Pi 账本。该目录由 systemd 生成，不能让 Compose 自动创建。
- 使用 `ops/pi/deploy/build_runtime.py:build()` 构建独立闭合 runtime，参数为全长已审查提交 SHA，发布到新的 `releases/admin-console-<commit>/runtime`。构建环境使用已锁定依赖；记录输出 `runtime_sha256`，清单逐文件验证，整棵目录 root 拥有且禁止组/其他写入。不要替换正在使用的 nightly runtime。
- 从本地可信 Git checkout 生成包含生产基线与已合入提交的 bundle（`git bundle create <private-output> main`），核对 bundle SHA 后传入宿主。以 root 将它 clone 为 `/home/ubuntu/myink-pi-managed/control/source.git`（bare，0700）；已存在时先核对对象再 fetch，禁止重新初始化/覆盖。宿主产品目录没有 `.git`，不能从镜像标签猜源码。必须用 `git cat-file -e <实际部署基线提交>^{commit}` 验证对象确实存在。仓库不配置 GitHub 写入凭据。
- 根目录已有 `control/nightly.lock`，新增唯一 console lifetime lock 由 tmpfiles 管理。安装 `ops/pi/deploy/myink-pi-admin-console-tmpfiles.conf`，执行 `systemd-tmpfiles --create`；它不更改原账本所有权。

根拥有、0640 的固定 `config/admin-console.json`：

```json
{"schema":"pi-admin-console-v1","mode":"ACTUAL","socket_path":"/run/myink-pi-console/control.sock","token_file":"/home/ubuntu/myink-pi-managed/config/admin-console-token","allowed_uid":10001,"publication_config_sha256":null}
```

初次接入用 `null` 只读核对；候选页面明确显示发布通道不可用。生成至少 32 字节、单行 ASCII 的随机服务 token 到 `config/admin-console-token`（root0600），不要打印、提交或放入产品 `.env`。服务原子生成 `/run/myink-pi-console/client-token`（root:10001 0640）供只读挂载；这不是管理员会话或模型凭据。轮换 token 后重启服务，API 每请求重读文件。

根拥有、0600 的 `config/admin-console.env` 应包含三个非敏感值：

```text
PI_CONSOLE_ENTRYPOINT=/home/ubuntu/myink-pi-managed/releases/admin-console-<commit>/runtime/entry.py
PI_OBSERVER_RUNTIME_SHA256=<build_runtime 返回的 runtime_sha256>
PI_CONSOLE_CONFIG_SHA256=<admin-console.json 原始字节的 sha256>
```

在宿主执行 `systemd-analyze verify` 验证单元后安装 `ops/pi/deploy/myink-pi-admin-console.service`、daemon-reload、启动该服务。该手动服务不是新增 nightly timer，不触发模型调用。服务创建并核对 `/run/myink-pi-console` 为 root:10001 0750、socket0660。重启不会重放旧发布，旧 queued/running 变为待人工核对。

随后按已批准部署更新产品 Python/Caddy 镜像并带上显式 Compose override；需要保留平台已有 provenance/环境配置。确认 API 能读取状态，普通用户 403、未登录 401；只读 GET 不改变原模型账本。先核对真实导出记录和候选摘要，再开放发布。

## 开放候选发布

配置 root0640 `config/admin-publication.json`：

```json
{"schema":"pi-admin-publication-v1","mode":"ACTUAL","source_repository":"/home/ubuntu/myink-pi-managed/control/source.git","compose_files":["/home/ubuntu/myink/docker-compose.yml","/home/ubuntu/myink/docker-compose.pi-console.yml"]}
```

固定 Compose 必须完整包含当前生产服务的有效配置。若生产依赖另一个人工发布 override，先将其**已核对的有效配置**整合入上述受控文件；不要丢失当前 provenance、挂载或启动参数。仅允许这两个固定路径。

记录该文件原始字节 SHA，填入 `admin-console.json.publication_config_sha256`，重新记录 `PI_CONSOLE_CONFIG_SHA256`，再重启桥接服务。未配置、哈希漂移、候选不匹配或队列忙均拒绝发布。开放通道不构成对任何候选的自动批准；每轮仍由管理员在页面最终确认。

回执：产品数据库的 `admin_access_logs` 记录真实管理员/请求/轮次，原 Pi 审计记录决定和结果；`state/admin-console.sqlite` 仅保存操作幂等状态，不是任务或费用账本。候选目录 `nightly/<cycle>/console-publication/` 保留固定计划、旧 Compose（含私有环境，不对网页公开）、命令回执、intent 和物理核验结果。完成前没有成功标记。需要回退时使用保留的旧镜像及完整旧配置，由人工核对并授权；不自动恢复数据库或历史账本。

## 验证与限制

`tests/test_admin_pi_integration.py` 使用真实 JWT/隔离 PG 与真实本地 Unix socket，宿主发布效果为 SIMULATED；`ops/pi/tests/test_admin_publication.py` 的 Docker effects 也是模拟。浏览器 fixture 明确标记模拟，不是真实线上发布验收。真正的 ACTUAL Linux peer 身份、systemd 沙箱和 Docker 物理替换，须按本清单在已批准部署时验证并单独记录。
