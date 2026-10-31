# Pi 管理台接入与人工发布

入口 `/admin/pi`，只向每次请求仍具备管理员角色的账号开放。产品 API 先验证真实会话、写入现有访问审计，才访问宿主 Unix socket。页面显示原始审计导出中的运行、指标窗口、判断、模型建议、工具输入/输出摘要、检查计数、每日版本/变更范围和次日计划。固定输入回归通过不代表线上效果改善，窗口重叠不累加样本；未知及未执行保持原样。

候选准备后长期等待。点击“查看并发布”打开精确镜像/产物确认，再点击“确认发布镜像”才记录决定；“暂不发布”只记录继续等待，不取消已经受理的发布。服务器重新核对当前轮次、镜像、源码、比较参数和产物摘要。请求幂等，已受理的轮次不并发发布；宿主中断或结果未知保留 `uncertain`，不能自动重放。只有物理部署核验通过才进入观察，并以实际部署日的次日北京时间 03:00 登记冻结回归和指标观察。旧调度器不能绕过本轮等待。

此发布通道只替换同一 Docker daemon 中 API 与两个 worker 的本地镜像，保留命令、环境业务配置、挂载、数据库、缓存、队列和 Caddy。业务队列必须空闲。它在根拥有的私有 Git 对象库保留与完整 Python 镜像包字节对应的候选提交，不改 main、不推 GitHub/registry。源码推送仍需另行核对和执行。未知结果需人工核对原操作回执、实际容器及原 Gate，不能删除 intent 或新建请求尝试重放。

## 上线前准备

2026-10-31 首次服务器发布与真实观察交接已按明确批准完成，见[实际回执](../evaluations/pi-main-actual-release-2026-10-31.md)。以下保留可复核的运行手册；合入 main 本身不会执行这些宿主操作，浏览器不能提供路径或配置。

- 既有根目录固定为 `/home/ubuntu/myink-pi-managed`，产品 Compose 在 `/home/ubuntu/myink`。复用原 `state/nightly-approval.sqlite`、`state/actual-manager.sqlite`、`state/ledger.sqlite` 与 `audit/state/events.sqlite`；不初始化新任务/费用账本，不覆盖已有审批。
- 将本提交的 `docker-compose.pi-console.yml` 放到产品目录，与原 Compose 一起运行。只有 API 挂载 `/run/myink-pi-console`，只读，容器 UID/GID 为现有 10001。worker 不挂载，产品容器不持有 Docker socket、模型凭据或原 Pi 账本。该目录由 systemd 生成，不能让 Compose 自动创建。
- 使用 `ops/pi/deploy/build_runtime.py:build()` 构建独立闭合 runtime，参数为全长已审查提交 SHA，发布到新的 `releases/admin-console-<commit>/runtime`。构建环境使用已锁定依赖；记录输出 `runtime_sha256`，清单逐文件验证，整棵目录 root 拥有且禁止组/其他写入。不要替换正在使用的 nightly runtime。
- 从本地可信 Git checkout 生成包含生产基线与已合入提交的 bundle（`git bundle create <private-output> main`），核对 bundle SHA 后传入宿主。以 root 将它 clone 为 `/home/ubuntu/myink-pi-managed/control/source.git`（bare，0700）；已存在时先核对对象再 fetch，禁止重新初始化/覆盖。宿主产品目录没有 `.git`，不能从镜像标签猜源码。必须用 `git cat-file -e <实际部署基线提交>^{commit}` 验证对象确实存在。仓库不配置 GitHub 写入凭据。
- 安装前用 `getent group 10001` 核对宿主组；首次主机缺少该组时创建固定 GID10001 的专用组，不授予登录或Docker权限。若该GID已被无关用途占用，先核对用途，不覆盖。systemd的数值Group也要求宿主可解析该组，否则会216/GROUP退出。
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

## 从旧版首次发布 main

2026-10-31只读核对的旧生产 f230 缺少维护控制四张表及锁函数；旧 API/worker 也不会检查新屏障。首次更新不等同后续候选镜像发布，不能直接复用候选发布按钮。迁移已完成[隔离演练](../evaluations/pi-main-schema-upgrade-2026-10-31.md)，生产仍需明确批准后执行：

1. 保留当前物理镜像、完整有效 Compose、部署身份、数据库可恢复备份和原周期观察证据。先核对旧 observing 周期归属；不能把旧批准、旧镜像或旧结果改记为新 main。
2. 使用对旧版确实有效的入口关闭与排空步骤，停止新增工作并核对队列、任务和执行者。旧进程不遵守新 PostgreSQL 标志，单写关闭标志不能完成这一步。
3. 用精确已验证的新成品运行 `myink init`，核对新增表、锁函数、角色权限与既有数据。bootstrap/initial/gen0 默认行仅用于初始化，不能作为实际生产身份。
4. 在屏障关闭状态核对并绑定精确待部署身份，保留CAS前后回执，再更新 API/worker/Caddy 和显式 console 挂载。保留现有 provenance、命令、业务环境和挂载；当前生产引用原周期的 override，不能只复制基础 Compose 丢弃其有效配置。
5. 实际核对新物理镜像、健康状态、维护身份及 Unix peer/systemd 权限，再开放工作入口。桥接先用 `publication_config_sha256:null` 只读验收管理员、普通账号及未登录访问，核对原费用账本没有变化，再单独开放候选发布。

本次首次人工发布限定北京时间 06:00–23:00 开工、最多30分钟维护，留出下一次02:00检查前的完整发布后指标窗口；时间或原周期/物理版本漂移时停止重核。Caddy换镜像前要核对入口503配置及其autosave内容均已持久化，新Caddy以已验证的 --resume 读取同一配置卷，避免默认配置短暂重开入口。新镜像还应保留从实际旧生产镜像核验过的哈希资源，不得使用本机混杂缓存；恢复入口前核对当前新页面与旧资源均可读取。

任何阶段结果未知都保持入口关闭并保留回执；不得通过重复初始化、删除 intent 或更换账本恢复。旧数据库回退须按实际迁移与备份判断，不能仅回退镜像就宣称完成恢复。

## 人工 main 更新后的观察交接

首次 main 更新属于人工发布，不借用旧 Pi 候选的批准。旧周期可能仍为 observing 或因旧版本已退出而 blocked；不能将它改绑到新镜像，不能调用比较完成接口，也不能等待旧版本已不可能再产生的样本。

先核对是否已被 native 产品协议接管。2026-10-31 实际服务器没有 product-release/product-control 配置，也没有维护四表；现有 nightly 发布并非 native 接管，不能直接使用只接受原反馈挂载、只激活三个后端的 native 工厂来完成首次前端/socket更新。本次走明确批准的人工首次主线发布：关闭入口、自然排空、备份、迁移、绑定维护身份、替换 API/双worker/Caddy，并保留全部失败和原收据。若执行前发现 native 配置或接管状态已经变化，则停止重核，不能把此首次例外用于绕过已经接管的协议；已接管版本仍使用原固定产品入口。更新产品期间持有原 nightly 锁；交接入口随后会自行获取原 nightly.lock 和 maintenance.lock，调用时不要再在外层持有同一把锁。两阶段间旧 Gate 仍禁止新任务或模型执行。只有已健康运行的新 API/双worker、完整包摘要、revision、PG维护身份及原模型账本均核对后，才准备元数据交接。

封存新 `config/autonomy-profile.json` 和 `config/nightly-source-template.json`，原 manager、费用库、50元及9笔未知预留不变。两者使用相同的 source-free 配置，模板 source_scope 与新真实源码一致。driver 保持 `inherit_task_id:null`，绑定新 Python 镜像，并同时钉住上述有限 profile 和固定模板。新 observer 绑定准确部署身份、1小时窗口和至少20样本；next-day计划不能移用旧周期。nightly.env 的入口、闭合 runtime pin 和 driver pin 也必须一致。

独立 root 批准位于 `config/manual-handoffs/<operation UUID>.json`（root:ubuntu0640，父目录root0750），原始字节SHA必须由操作者核对。封闭字段：

```json
{"schema":"pi-nightly-manual-handoff-v1","mode":"ACTUAL","issuer":"human_operator","action":"interrupt_for_manual_main_release","operation_id":"<UUID>","cycle_id":"<旧周期UUID>","package_sha256":"<旧package摘要>","deployment_sha256":"<旧deployment收据摘要>","new_identity":{"deployment_id":"<实际新部署>","generation":2,"owner":"<实际owner>","image_ids":{"python":"sha256:<实际新Python镜像>"},"commit_sha":"<新产品40位commit>","schema_id":"<实际schema>","config_hash":"<实际config摘要>"},"new_package_sha256":"<新完整Python包摘要>","driver_sha256":"<新driver原始字节摘要>","profile_sha256":"<新profile原始字节摘要>","issued_at":"<UTC时间>","expires_at":"<最多1小时后>"}
```

示例generation=2仅解释格式，执行时读取真实部署值；image_ids也必须是完整真实身份。此批准只允许核验已部署版本并结束旧观察，不允许部署、推送、发模型请求、增加预算或释放未知预留。用封闭 runtime 的 `entry.py --component nightly_handoff --config <批准固定路径> --config-sha256 <批准SHA>` 执行，环境中的 `PI_OBSERVER_RUNTIME_SHA256` 指向该 runtime；ACTUAL只允许Linux root和固定路径，拒绝模拟回调。

回执写入原 `nightly/<旧周期>/manual-handoff-<operation UUID>/`。指标源还必须匹配实际生产PG容器/镜像/daemon/database，两张指标视图通过固定只读角色查询验证；安装的nightly runtime pin必须与当前已验证交接入口一致。同一旧周期存在任何未完成交接时，换operation UUID也不能绕过。新部署和输入在导出审计后再次核对；审计/verified.json持久化后，最后一笔Gate事务以 `observation_interrupted` 关闭旧观察，结论为 `insufficient_evidence`。原包、批准、部署、任务及已有失败不改，绝不写comparison_complete。原追加审计导出向main显示新版本及旧观察中断原因，不宣称线上改善。

后续现有 source issuer 以独立 `pi-human-main-baseline-v1` 解释核验过的人工基线，重新采集新版本窗口、真实物理源码并签发有限输入；source-stage的 `comparison_sha256:null`，另存 `baseline_receipt_sha256` 与 `predecessor_kind:manual_main_release`。固定模板不会续用过期研究输入，因此首次profile过期不会永久卡住；无足够新证据仍不能伪造任务或通过比较。后续Pi候选仍须管理员确认发布，真正比较完成后回到原有比较来源路径。

若intent存在但没有与最终Gate事件匹配的verified回执，入口拒绝重放，保留现场供人工核对。交接未完，旧Gate继续阻止新任务；不能靠删除目录、改UUID、直接改SQLite或降低20样本要求恢复。2026-10-31已完成真实root部署、指标源只读核验及正式交接，详见[实际回执](../evaluations/pi-main-actual-release-2026-10-31.md)；仍未证明线上质量改善。

## 开放候选发布

配置 root0640 `config/admin-publication.json`：

```json
{"schema":"pi-admin-publication-v1","mode":"ACTUAL","source_repository":"/home/ubuntu/myink-pi-managed/control/source.git","compose_files":["/home/ubuntu/myink/docker-compose.yml","/home/ubuntu/myink/docker-compose.pi-console.yml"]}
```

固定 Compose 必须完整包含当前生产服务的有效配置。若生产依赖另一个人工发布 override，先将其**已核对的有效配置**整合入上述受控文件；不要丢失当前 provenance、挂载或启动参数。仅允许这两个固定路径。

记录该文件原始字节 SHA，填入 `admin-console.json.publication_config_sha256`，重新记录 `PI_CONSOLE_CONFIG_SHA256`，再重启桥接服务。未配置、哈希漂移、候选不匹配或队列忙均拒绝发布。开放通道不构成对任何候选的自动批准；每轮仍由管理员在页面最终确认。

回执：产品数据库的 `admin_access_logs` 记录真实管理员/请求/轮次，原 Pi 审计记录决定和结果；`state/admin-console.sqlite` 仅保存操作幂等状态，不是任务或费用账本。候选目录 `nightly/<cycle>/console-publication/` 保留固定计划、旧 Compose（含私有环境，不对网页公开）、命令回执、intent 和物理核验结果。完成前没有成功标记。需要回退时使用保留的旧镜像及完整旧配置，由人工核对并授权；不自动恢复数据库或历史账本。

## 验证与限制

`tests/test_admin_pi_integration.py` 使用真实 JWT/隔离 PG 与真实本地 Unix socket，宿主发布效果为 SIMULATED；`ops/pi/tests/test_admin_publication.py` 的 Docker effects 也是模拟。浏览器 fixture 明确标记模拟，不是真实线上发布验收。2026-10-31已按批准范围单独验证ACTUAL Linux peer、systemd沙箱、首次物理替换及新版本指标读取，见实际回执；未来候选发布的完整业务效果仍需真实逐轮验收。

审查后的发布顺序：准备及执行前还比较实际容器的 Compose config-hash、完整环境、命令和挂载，拒绝提前发生的磁盘配置漂移。真正替换前，对原 PostgreSQL `maintenance_control` 的完整旧行做 CAS，关闭 admission/consumer；提交关闭后重新检查在途任务、执行者、未落定 intake/outbox 和 AMQP。只有完整物理镜像核验完成，才在仍关闭的原行切换部署身份，原 Gate 确认后重新开放。任何关闭后的未知失败都保留关闭状态和 `maintenance-*.json` 回执，需人工核对；不能用删回执或回滚费用库恢复。
