# 剩余待办

2026-09-30。本文是**唯一的剩余工作量清单**，把散在三处的未完成事项合成一份：

- [公网部署前检查](archive/PUBLIC-DEPLOYMENT-CHECKLIST.md)（2026-09-19）的「上线阻断项」
- [上线前检查报告](archive/LAUNCH-READINESS-2026-09-27.md) §四「已知残留风险」、§五「未能验证」
- [内置平台密钥与免费额度方案](todo/PLATFORM-KEY-QUOTA-PLAN.md)（2026-09-30 设计稿，其口径已被本文 §3 取代）

上面三份是当时的快照，保留作历史记录；**结论以本文为准**（§0 列出了其中已经过期的两条）。
每条都标了实测证据或明确标注「未验证」。

## 文档怎么放

- `docs/` 根 —— 还需要看的参考文档（`AUTH.md` / `ADMIN.md` / `DEPLOY.md` / `DEMO.md` /
  `PROD-CREDENTIALS.md` / `SHORT-FORM.md`），以及**本文**。
- `docs/archive/` —— 已完成的施工单、验收记录与检查报告。都**没有删**，每份顶部标了状态；
  里面的结论是当时的，不再更新。
- `docs/todo/` —— 未做方案的详细文档。三份，由本文汇总跟踪：
  - [内置平台密钥与免费额度方案](todo/PLATFORM-KEY-QUOTA-PLAN.md) —— 早期设计稿，口径以本文 §3 为准（已实现、未上线）
  - [不可达提示施工单](todo/UNREACHABLE-HINT-PLAN.md) —— 把「本部署连不上」和「上游拒绝了你」
    分开提示，开工前有 3 个问题待拍板
  - [Jev 判定层](todo/JEV-JUDGE-LAYER.md) —— 决策记录，**暂缓非否决**，前置是先扩展
    conflict-sample 评测集
- `docs/superpowers/` —— 2026-09-19 ~ 09-24 那轮开发的计划与设计稿（25 份），全部已落地，
  保留作过程记录，未整理。
- `docs/evaluations/` —— 评测数据。

---

## 0. 先修正两条已经过期的结论

| 出处 | 当时的说法 | 2026-09-30 实测 |
|---|---|---|
| 部署清单「密钥与基础设施凭据」 | 「DB/RabbitMQ 仍有本地默认凭据，Redis 未启用认证」 | **不成立**。四个口令都是 48 位随机十六进制；Redis 无口令 `PING` 直接回 `NOAUTH Authentication required` |
| 部署清单「当前结论」 | 「当前 Compose 仅适合本机验收，不能直接开放公网」 | **已过期**。站点已于 2026-09-29 上线（裸 IP + Let's Encrypt IP 证书，备案前的过渡方案） |

`JWT_SECRET` 与 `MODEL_CREDENTIAL_KEY` 也确认是两把独立的 64 位随机数，都与 [上线前检查报告](archive/LAUNCH-READINESS-2026-09-27.md) §六 的修复一致。

---

## 1. 还没上线的代码

### 1.1 短篇建书改成多会话 + 自动落点 —— ✅ 2026-09-30 已提交并部署

已提交为 `79c945a`，已推送，已部署。部署证据：本地与线上镜像 ID 一致、服务器 `docker-compose.yml`
与本地逐字节相同、线上 `index.html` 引用的 bundle 哈希与本地构建产物一致、`/readyz` 回 ok、
`queue:tasks` 消费者 2 个。下面这份是提交前的文件清单，留作查证「那一次改了什么」。

| 文件 | 改动 |
|---|---|
| `src/myink/api/routes_short_creation.py` | `_latest` → `_latest_active`（只落**还没开写**的会话）；`get_session` 重写 |
| `spec/api-openapi.json` | 随之重新导出（`/api/v1/short/creation` GET 的 description） |
| `tests/test_short_creation.py` | 新增 2 个测试；`_open` 语义改为「落到还没开写的」 |
| `web/src/pages/ShortCreationPage.tsx` | 页头 `<select>` 换成「历史会话」折叠列表 |
| `web/src/pages/ShortCreationPage.module.css` | 删 `.picker`，加 `.history` / `.historyItem` / `.caret` |
| `web/src/pages/ShortCreationPage.test.tsx` | 4 处断言改用 `aria-current`；新增 1 个测试 |
| `web/src/lib/apiError.ts` | `SESSION_COMMITTED` 文案改为「点『新建会话』另起一篇」 |
| `web/src/lib/apiError.test.ts` | 同步断言 |
| `docker-compose.yml` | worker 去掉 `container_name`、改 `deploy.replicas: 2`（见 §2.9） |

### 1.2 运维与硬化一批 —— ✅ 2026-10-01 已提交并部署

关掉了 §2.1 / §2.3 / §2.4 / §2.6 / §2.7 五条，外加一轮「去痕」（仓库里不再出现参照对象的名字，
只剩 NOTICE.md / README.md / .gitignore / .dockerignore 里 AGPL 必要的那些）。

分成三笔提交：`0f305dc` 运维与硬化、`70ce4fb` 账号维度限流、`b3c86f7` 去痕。已推送。

部署证据：本地与线上两个镜像 ID 逐字节一致（`c4ba5a8a…` / `581b9feb…`，都带
`org.opencontainers.image.revision=b3c86f7`）、服务器 compose 与本地 md5 相同、首页 bundle 哈希
与镜像里的产物一致、`/readyz` 回 `ok`、`queue:tasks` 消费者 2 个、migrate 退出码 0、四个长驻
进程都是 uid 10001、api 进程里 `get_admin_engine().url.username` = `myink_report` 而
`get_engine()` = `myink_app`、worker 的 `ADMIN_DATABASE_URL` 为空。功能上也验了一条：对不存在的
账号连打登录，第 11 次开始 429（`AUTH_ACCOUNT_MAX=10`），说明新代码确实在跑。

线上准备按硬顺序做完：先补 `myink_report` 角色（验过读得到 6 用户 / 13 项目、`create table`
被 `ReadOnlyTransaction` 拒），再 chown 三个命名卷到 10001，最后 `up -d`。**证书没被重签**
（仍是 9-29 那张 LE IP 证书，10-06 到期），说明 chown 后 caddy 读写自己的 /data 正常。

下面是提交前的本地验证证据与文件清单，留作查证。

验证证据：`1388 passed, 5 xfailed`（在**与生产同一份依赖**的镜像上跑，SQLAlchemy 2.1.1）；
`myink contract export` 后 `spec/api-openapi.json` 哈希不变（依赖升级没有改变对外契约）；
开发栈整套 `up -d` 起来后 api/caddy healthy、migrate 退出码 0、三个长驻进程都是 uid 10001；
备份脚本跑通并**真恢复到临时库**，38 张表行数与 24 条 RLS 策略逐项一致。

### 1.3 管理员第二因子（TOTP）—— ✅ 2026-10-01 已提交并部署

已提交为 `3b45ee5`（30 个文件，+1886/−70），未推送。细节与设计在 §2.8，部署证据在那一节末尾。

部署口径：**动了 `pyproject.toml` / `docker/constraints.txt`，两个镜像都要重建**；新列由一次性
`myink-migrate` 里的 `myink init` 补上，服务器不需要新增环境变量。`docker-compose.yml` 没动，
服务器那份不用重传。

---

## 2. 生产环境安全与运维

按「真出事时的后果」排序，不按文档里的原始顺序。

### 2.1 备份没有定时，也没演练过（唯一会真的丢数据）—— ✅ 2026-10-01 全部做完

`scripts/backup.sh`：一次 `pg_dump` + 轮转保留 14 份，产物写成 `.part` 再改名（半份不会被当成好备份），
`gzip -t` 校验后才认，`sudo docker` 与 `docker` 自动探测（服务器要 sudo、开发机不要）。

已实测：连跑三次、`KEEP=2` 后确实只剩 2 份、不残留 `.part`；**真恢复到临时库**后 38 张表行数与
24 条 RLS 策略与线上逐项一致（恢复出来的库可直接顶上去，不用重建）。

2026-10-01 服务器侧完成：`backup.sh` / `create-report-role.sh` 已拷到 `~/myink/`；cron 装好
（`17 3 * * *`，写入前 crontab 为空、没覆盖任何东西）；上线前手工跑了一次
（`myink-20261001000538.sql.gz`，2.7 MB），`sudo docker` 探测路径也验证到了。**随后那个触发点
真跑过一次**——`myink-20261001031701.sql.gz` 与 `backup.log` 里的一行都是证据，不是「配好了」。

离机副本：新增 `scripts/pull-backup.sh`，在**本机**跑（rsync 只读服务器、落地后逐份 `gzip -t`、
本机按 KEEP 轮转，手工的一次性备份不删）。已实拉一次到 `~/myink-backups/`。本机还需要挂个
定时任务，否则这份副本停了自己不会发现。

下面是当时的现状描述。

服务器 `~/myink/backups/` 里只有**一个**文件：`prod-before-zlx-migrate-20260929180025.sql.gz`，13 KB，2026-09-29 手工跑的迁移前备份。**没有定时任务**——`crontab -l` 只有腾讯云自己的 agent。

也就是说，线上作品数据的唯一副本就是 PostgreSQL 数据卷本身。磁盘坏一块就全没了。那个备份也**从没做过恢复演练**，[公网部署前检查](archive/PUBLIC-DEPLOYMENT-CHECKLIST.md) 里那句「备份没有做恢复演练，不等于已验证灾难恢复」仍然成立。

- 要做：`pg_dump` 定时化（每天一次 + 保留 N 份）→ **真恢复到临时库验一遍** → 备份文件拉离服务器（同机备份挡不住整机故障）。
- 成本：最低。半天以内。

### 2.2 监控告警 —— 🟡 实例告警 2026-10-01 已配，云拨测还没定

**已经在控制台配好**：CPU / 内存 / 硬盘三条告警策略（2026-10-01）。Lighthouse 自带的监控组件
粒度 10 秒，策略类型选「轻量应用服务器-…」那一组；告警走邮件。

**不做的**：证书到期提醒。控制台里没有这一项可选，不再挂着当待办——Caddy 自动续期，
失败排查只能靠人工或别的渠道，这条从清单里删掉。

**还没定的**：站点可达性（云拨测）。问了用户、**尚未答复**，见下。

这台是**轻量应用服务器 Lighthouse**（`ins-mxci6be3`，北京 ap-beijing），两件事的入口不一样，
别按 CVM 的路径找：

- **实例指标**（CPU / 内存 / 磁盘 / 网络流量）：Lighthouse 自带监控组件（随镜像装好，可卸载），
  在**云监控控制台**配告警策略，策略类型选「轻量应用服务器-…」那一组（网络流量那条是
  「轻量应用服务器-网络流量」）。控制台里 Lighthouse 自己的「监控」页也能设。**三条已配。**
- **站点可达性**：云拨测与机型无关——它是腾讯**自己分布在各地的探针**去请求你的公网地址，
  不要求目标在腾讯云、也不在实例上跑任何东西。所以拨测任务填 `https://62.234.106.6/readyz` 即可。

若要做云拨测（一台服务器、一个任务，成本很低）——选它而不是 UptimeRobot 这类境外探针，是因为境外
探国内未备案的裸 IP 会时通时断、误报多：

1. 新建一个拨测任务探 `https://62.234.106.6/readyz`，断言 HTTP 200。任务类型要选能做到
   HTTP 状态判定的那种（「网络质量」那一类只做 ping / DNS / tracert，判不了状态码；控制台里
   以实际可选项为准——**这一步没实操过，按实际选项挑**）。`/readyz` 在任一依赖不健康时返回
   **503 + `{"status":"degraded"}`**（`api/main.py:167`），判状态码就够，不用做内容匹配。
   连续 2 次失败再告警，避免抖动误报；拨测点选国内多地。

覆盖不到的部分要说清楚：站点监控能发现「从外面访问不到」，发现不了「能打开但登录不了」或者
「某个功能静默出错」——那类只能靠日志与应用层指标，不在这一条的范围里。

`/readyz` 存在，返回 `{"status":"ok","checks":{"redis":"ok","db":"ok","worker":"ok"}}`，但**没有任何东西在轮询它**。

代价：API 500 暴增、worker 死掉、证书续期失败——全都不会有人知道，等用户来告诉你。磁盘写满现在有告警兜住了。

### 2.3 DB 最小权限：运行进程同时握着绕过 RLS 的钥匙 —— ✅ 2026-09-30 已做

拆成三个角色，由 compose 按容器注入：`myink`（表属主超级用户）只在跑完即退的 `myink-migrate` 里出现；
api 的 `ADMIN_DATABASE_URL` 指向新建的只读报表角色 `myink_report`（BYPASSRLS + 只授 SELECT +
`default_transaction_read_only=on`）；worker 里该变量**显式置空**——`env_file` 会把 `.env` 里的
owner 串注进来，光删掉那一行不够。

已在开发栈实测：api 容器内 `get_admin_engine().url.username` = `myink_report`，读得到 2 个用户 /
11 个项目，而 `create table` 被拒（`ReadOnlySqlTransaction`）；同库直接用该角色连，`INSERT` /
`CREATE TABLE` / `DROP TABLE` 全被拒，对照 `myink_app` 不设租户仍是 0 行。

备忘：RLS 只覆盖带 `project_id` 的表（`db.py` 的 `enable_rls`），`users` / `projects` 是租户根表，
`invitations` / `feedback` / `short_creation_sessions` / `style_library_items` 等没有该列——这些靠
应用层的 `user_id` 归属校验，**不由数据库兜底**。改这些表的查询时要自己带上条件。

存量数据卷不会重跑 `initdb`，补角色的脚本是 `scripts/create-report-role.sh`；上线顺序见
[DEPLOY.md](DEPLOY.md)。下面是当时的问题描述。

**问题**：每个 api / worker 进程**同时**持有两把数据库连接。`DATABASE_URL` 用 `myink_app`（NOBYPASSRLS，受行级安全策略管），`ADMIN_DATABASE_URL` 用 `myink`（表属主，BYPASSRLS）。

租户隔离的最后一道防线是 RLS，而**同一进程里就放着绕开它的钥匙**。RLS 防的是「写错的查询」，不防「拿管理员连接去查的代码」。api 进程一旦被攻破（SSRF 打进内网、依赖投毒、任何 RCE），攻击者可以直接用管理员连接读全表，所有用户的隔离等于不存在。[上线前检查报告](archive/LAUNCH-READINESS-2026-09-27.md) §四 那句「数据库管理员不属于 RLS 能防御的攻击者」说的正是这个；`routes_admin.py` 的跨用户报表就走这条连接。

- 要做：迁移抽成跑完即退的一次性 job，只它拿管理员连接；运行时 api/worker 只留 `myink_app`；管理面板的只读报表另建最小权限角色。
- 代价：属结构性改动，管理面板目前靠 admin 连接跑跨用户查询。**注意 [上线前检查报告](archive/LAUNCH-READINESS-2026-09-27.md) §三 的提醒**：PG 角色类变更只对全新数据卷首启生效，已有数据卷要手工 `ALTER ROLE`。

### 2.4 防撞库只有 IP 维度，两个方向都会出问题 —— ✅ 2026-09-30 已加账号维度

新增账号维度失败计数（`api/ratelimit.py` 的 `account_auth_guard` / `account_auth_failed` /
`account_auth_cleared`）：按账号分桶、**跨 IP 生效**（换代理池绕不过）、**只计失败**（验密通过先清零
再放行，正常用户不会被自己刚才的输错拖住），与 IP 桶共用同一个 Lua 与 60 秒窗口。

IP 桶同时从 20 提到 60：那个桶按 IP 分，同一个 NAT / 公司出口后面的人**共用一个**，20 太低，
一个人刷就能把同网段的人挡在登录页外；而「盯住单个账号」的职责已经交给账号维度了。

新增 4 个测试（跨 IP 触发、账号之间互不牵连、成功后清零、Redis 挂了 fail-closed）。

**已知残留，选择接受**：攻击者可以故意把某个账号刷满，让真正的用户 60 秒内登不进来（定向锁号）。
退避 / 验证码 / 告警列为后续——窗口只有 60 秒且只计失败，代价可控。

注册与改密**没有**加这个桶：注册是邀请制、改密要已登录的 token，除非以后放开注册或发现 token
被滥用，不必再加一层。下面是当时的问题描述。

**现状**：注册 / 登录 / 改密共享「每客户端地址每分钟 20 次」，桶按 Caddy 覆盖写入的 `X-Myink-Client-IP` 分（客户端伪造同名头无效，这层是好的）。**没有账号维度。**

- 攻击者换 IP（代理池）就能对同一账号无限试密码——IP 桶拦不住。
- 反方向：同一个 NAT / 公司出口后面的所有用户**共用一个 20/分钟的桶**，一个人刷就能把其他人锁在登录页外。

注册滥用那一半已经做了：注册是邀请制（`invitations.py:91` 拿不到码直接 `INVITATION_REQUIRED`）。写作成本那侧**还没有账号维度上限**——`QUOTA_DAILY_CHAPTERS=0`、`DAILY_BUDGET_YUAN=0`（0 = 不限），前提是「模型 Key 是用户自己的」。**这条会跟着 §3 一起变**：一旦有内置密钥，这两个 0 必须打开。

- 要做：「真实客户端地址 + 账号」组合计数 + 退避 / 验证码 / 告警。

### 2.5 浏览器令牌在 localStorage，CSP 只写了一半

JWT 存在 `localStorage`（键名 `myink.session`，`web/src/lib/token.ts:4`），同源 JavaScript 读得到。一旦有 XSS，token 直接被拿走，可以在任意机器上重放到过期。HttpOnly Cookie 的价值就是让 JS 读不到。

但实际风险比字面低，两点实测：

- 全站 `dangerouslySetInnerHTML` **零处**，章节正文与聊天内容都是当纯文本渲染的。
- CSP 已有一半：`frame-ancestors 'none'; base-uri 'self'; object-src 'none'`（`caddy/Caddyfile` 的 `header` 块）。**没有** `script-src` / `connect-src`，文件里写明原因：`index.html` 那段主题引导内联脚本要配哈希、还要放开 `blob:`（用户上传的媒体背景），贸然上完整 CSP 会直接白屏。

所以最现实的入口不是自己代码，是**第三方依赖**。改成 Cookie 也不是换个存储位置，而是一整套联动：前端不再手动带 `Authorization` 头、后端读 Cookie、SSE 长连接跟着改、还要补 CSRF（Cookie 自动携带，反而开了新面）。

### 2.6 镜像与依赖版本全都没锁 —— ✅ 2026-09-30 已锁定

- `docker/constraints.txt`：整棵依赖树（含间接依赖）的精确版本，Dockerfile 用 `-c` 生效。
  已验证镜像内 `pip freeze` 与锁文件 **77 个包逐行一致**。
- 两个镜像都带 `org.opencontainers.image.revision` 标签（compose 传
  `GIT_REVISION=$(git rev-parse --short HEAD)`），`docker inspect` 就能回答「线上跑的是哪一版」。
- **顺带发现一个真问题**：本地 `myink-api:pytest` 是十天前建的，跑的是 SQLAlchemy **2.0.54**，
  而锁文件让线上跑 **2.1.1**——在那之前，测试验的和线上跑的根本不是同一套依赖。现在测试镜像
  以生产镜像为底座重建（配方见 [DEPLOY.md](DEPLOY.md)「自动化回归」），全套 1388 passed 是在 2.1.1 上跑的。

仍缺：CI 里加一轮依赖与镜像扫描（pip-audit / trivy 之类）。下面是当时的现状描述。

`pyproject.toml` 里依赖都是区间（`sqlalchemy>=2.0` 这种），今天构建和下周构建拿到的是不同版本；镜像 tag 是 `myink-api:local`，不指向任何 commit。也**没有**任何扫描（pip-audit / trivy 之类）。

- 要做：加锁文件（`uv.lock` / `pip-compile`）、镜像 tag 带上 commit、CI 里加一轮依赖与镜像扫描。

### 2.7 容器以 root 运行，且无资源上限 —— ✅ 2026-09-30 已做

两个 Dockerfile 都以 uid 10001 非 root 运行（api 侧 `useradd`、caddy 侧 `adduser`；容器内非 root
绑 80/443 靠 Docker 默认能力集里的 `NET_BIND_SERVICE`）。compose 给 api / worker / caddy 加了
`mem_limit` 与 `cpus`——是**天花板不是预留**（实测 api ~154MB、caddy ~21MB）；pg / redis / rabbitmq
**刻意不设**：有状态服务被 OOM kill 比跑飞更糟。worker 那份注释另外写了「开 `EMBED_ENABLED`
必须同时抬高它」。

实测：两个镜像里 `id` 都是 10001；caddy 挂新卷起来后 80 端口回 200、`/data` 与 `/config` 都写得进；
compose 起来后 api / worker / caddy 的 `HostConfig.Memory` 分别是 1g / 1g / 256m。

一次性代价：**已存在的命名卷仍是 root**，切非 root 前要 chown 三个卷（caddy 写不进证书目录会直接
起不来）。已在本机开发栈演练过，命令见 [DEPLOY.md](DEPLOY.md)。下面是当时的现状描述。

`Dockerfile` 与 `caddy/Dockerfile` 都没有 `USER`，都是 root；`docker-compose.yml` 里没有任何 `mem_limit` / `cpus`（2026-09-30 新加的 `deploy: replicas` 只管副本数）。

眼下不危险（两个 worker 各 108 MB、整个栈才用掉约 1.8 GB / 3.7 GB），但**没有任何上限**：哪天 `EMBED_ENABLED` 打开，每份 worker 要再加约 2 GB（bge-m3），无约束地乘上去。

### 2.8 管理面板的第二因子（TOTP）—— ✅ 2026-10-01 已提交并部署

`/admin` 只有密码。这是全站唯一能跨用户读数据的地方，也是单点。

已实现：TOTP 认证器（`pyotp`），只在**登录时**拦截，命令行兜底，不做恢复码。默认关闭、**不强制**——
没开的账号登录行为逐字节不变，所以它不保护尚未开启的账号；强制开启 + 丢手机 = 必须登服务器，
比现状更容易把自己锁在外面，所以选择不强制。

四处关键设计（都配了测试）：

- **挑战票与访问令牌分开**：密码对但账号开了第二因子时，`POST /auth/token` 回 200 +
  `{mfa_required, mfa_token, expires_in: 300}`。挑战票换个签发方（`myink-mfa`）签，
  `_decode_token` 一行没动——所以线上已发的访问令牌全部继续有效，部署不会把在线会话踢掉，
  而挑战票过不了任何受保护路由。
- **开启/关闭都自增 `auth_version`**：`/auth/session` 是滑动续期，标签页开着令牌就永不过期，
  不撤销的话攻击者用密码拿到的、开启之前签发的令牌会一直有效，第二因子整个被绕过。
  代价是刚开完要重新登录一次（前端会跳到登录页并说明原因）。
- **enroll 要再输一次账号密码**（不在最初的设计里）：光有令牌就够的话，偷到令牌的人能绑上
  自己的认证器实现持久化占坑。
- **密钥域分离**：`_cipher()` 参数化 namespace（默认值不变 ⇒ 存量模型密钥密文照旧解得开），
  TOTP 密钥走 `mfa` 域，与模型凭据不是同一把派生密钥。

验码失败统一 401 `MFA_INVALID`（码错 / 码过期 / 挑战票过期合并，区分它们等于告诉对方密码对不对）；
验码另有 `rate:mfa:` 账号维度限流（5 次/分钟，比登录的 10 更紧）。

兜底命令 `myink mfa-disable <username>` 清密钥 + 撤销全部会话。

验证：`tests/test_mfa.py`（12 条）、`tests/test_mfa_migration.py`（2 条，临时 schema 验幂等）、
新限流面 2 条，存量断言全绿（后端 1412 passed / 5 xfailed，前端 430 passed）。
dev 库真跑过一遍 `myink init` 补列，浏览器真走完「登录 → 开 → 密钥 → 错码拒 → 对码确认 → 被踢 →
重登要码 → 错码拒 → 对码进 → CLI 清掉 → 密码直通」，含 390px 窄屏。

上线注意：这次动了 `pyproject.toml` / `docker/constraints.txt`，**两个镜像都要重建**；
新列由一次性 `myink-migrate` 里的 `myink init` 补上，服务器不需要新增任何环境变量。

**2026-10-01 部署证据**（提交 `3b45ee5`）：部署前在**与生产同一份依赖**的 pytest 镜像上跑完整套，
`1412 passed, 5 xfailed`；本地 build 的两个 amd64 镜像都带
`org.opencontainers.image.revision=3b45ee5`，`docker save | load` 到服务器后镜像 ID 与本地
逐字节一致（`f101d1384f78` / `7a8f0bffc23b`）；上线前 `users` 表 `totp%` 两列 **0 行**，
`up -d` 后 migrate 退出码 0、两列就位；`/readyz` 回 200 ok；线上 API 里 5 条 MFA 路由都在；
6 个存量账号 `totp_confirmed_at` 全为 NULL（**默认不生效**），拿错密码打 `/auth/token` 回的是
普通 `401 {"detail":"INVALID_CREDENTIALS"}`、不是挑战形状；首页 bundle 里能读到「两步验证」「验证码」
文案，说明前端产物也换了新的。

### 2.9 worker 副本数（2026-09-30 已做，留档）

服务器 worker 从 1 份加到 **2 份**，因为已经有不止一个用户，而消费循环是 `prefetch=1` + 单线程（`worker/consumer.py`），一个进程同时只跑一个任务，多一本书就得排队等。

- 改法：`docker-compose.yml` 里去掉 `container_name: myink-worker`（与副本数互斥），加 `deploy: replicas: 2`。**没有用 `--scale`**，因为它不落盘，下次 `docker compose up -d` 会缩回一份。
- 多实例安全性已核查：锁按资源分（`lock:task:{id}` / `lock:book:{pid}`），重复投递由 `process()` 先重查锁与 DB 状态兜住。
- 实测：两个 worker_id 不同、`queue:tasks` 消费者数 1 → 2、`/readyz` 的 worker 项仍 `ok`、各占 108.3 MiB。
- **不会提速的场景**：同一本书。`rate:inflight:{uid}:{pid}` 的 `inflight > 0` 硬检查加 `lock:book:{pid}` 把同书任务串行——这是有意的。
- 注意：本地 dev 也会起两份（仓库只有一份 compose，没有 dev/prod 分叉）。
- 与 §3 的耦合：多一个 worker 会让单个用户在共享的 `rate:cost` 桶上花得更快。当前 `DAILY_BUDGET_YUAN=0`（不限）且 Key 是用户自己的，所以现在没有账单风险；**§3 落地时必须同时给这个桶设上限**。

---

## 3. 内置平台密钥与免费额度（✅ 2026-10-01 实现完成，未上线）

现状：模型密钥完全归用户，没配就是 `MissingModelProvider`（`providers/base.py:207`），报「请先在环境配置里添加模型连接」。新用户注册完第一件事就是去弄一个 API key，否则看不到产品能干什么。

目标：**部署方提供一套内置密钥兜底**，新用户开箱即用，用完终身免费额度才要求配自己的 key。

### 3.1 已拍定的口径

| 项 | 决定 |
|---|---|
| 「一次短篇」 | 点「确认，开写」（`POST /api/v1/short/creation/sessions/{id}/commit`）扣一次 |
| 「一次长篇」 | 建书（`POST /api/v1/projects`）扣一次；该书章节上限 30 章 ← 与现状冲突，见 §3.4 问题 1 |
| 额度是否重置 | **终身一次性**，不重置 |
| 构思 / 规划阶段的模型调用 | 不计入额度，但要有总量保护 |
| 内置密钥可选的模型 | 写死一个，用户不可挑 |

### 3.2 为什么是小改：两处结构已经就有

- **凭据解析已有唯一收敛点**：「override → provider」的唯一入口是 `providers/__init__.py:53 _chain_from_override`，兜底出口只有 `_no_model_chain`（`:47`）。所以只动这一处，作品级 `make_chain` 与账号级 `make_user_chain` 两个入口同时获得平台兜底。
- **配额闸门已有原子实现**：`worker/gates.lua` 五项，语义都是「0 = 不限」。账号级另有 `model_admission.py:90 generate_account_model()`（Redis `rate:account-model:calls:{uid}:{day}`，上限 `ACCOUNT_MODEL_CALLS_DAILY=60`，**默认就生效**）。**所以构思阶段的「总量保护」不用新做。**

真正缺的只有三样：平台密钥、终身计数、把成本桶从 0 打开。

### 3.3 设计要点

- **平台密钥（新增，结构上不可见）**：`config.py` 加 6 个字段（`PLATFORM_MODEL_API_KEY/BASE_URL/NAME/PROTOCOL`、`PLATFORM_SHORT_QUOTA=10`、`PLATFORM_LONG_QUOTA=3`）。`_no_model_chain` 里改为先试 `_platform_chain`，失败再回落现状。平台 key 是进程配置里的明文，**不走 `decrypt_api_key`**。
  **「不显示在前端」是结构性的**：平台 key 从不写入 `users.environment`，而 `GET /environment` 只回用户自己的连接（`environment.py:52 load_environment`）。这条不变式要防的是以后有人图省事把它塞进 `environment`。
- **终身计数落在 DB 两列**：`users.platform_short_used` / `platform_long_used`。不放 Redis（现有 `rate:*` 全是日桶带 `EXPIRE 86400`，终身额度塞进同一命名空间迟早踩错）；不放 `users.environment` JSON（那个 JSON 的语义是对外契约，且并发写整个 JSON 会互相覆盖）；不新建表（判据只有「有没有自备 key」「是不是 admin」，没有维度可查，逐次明细已有 `agent_runs`）。
  **原子性复用已有的 `User` 行锁**：短篇 `routes_short_creation.py` 与长篇 `routes_book.py` 的 `create_project` 都已经是 `with_for_update()`，读-判-增在同一事务内闭环。
  迁移仿 `ensure_user_tier` / `ensure_user_environment` 加一个幂等升级函数（本仓库硬规矩：`create_all` 只建新表、不 ALTER 已存在的表）。
- **扣减位置**：短篇放在 `_create_project_row` **之后**、`db.commit()` **之前**——建书那一步会抛 `BookCountExceeded`，扣减在它后面，整个事务一起回滚，额度不会被建书失败白白吃掉。长篇同法。**不能写进 `_create_project_row`**：那个函数被两条动线共用，必须靠 `form` 分叉、写在两个调用点（它自己的 docstring 就警告过「两条动线各写一份就会有两种上限口径」）。
- **拒绝码**：新增 `PLATFORM_QUOTA_EXCEEDED`，沿用 429 + `{"error": code}` 信封（照抄 `_book_cnt_response`）。前端 `web/src/lib/apiError.ts` 的 `GATE_CODES` 加一行，文案直接说结论和下一步，**不写灰色小字说明**。引导入口是 `/environment`（不是 `SettingsPage`，那个是「本书创作设置」）。
- **成本护栏（不打开就有真实账单风险）**：`QUOTA_DAILY_CHAPTERS=0` / `DAILY_BUDGET_YUAN=0` 这两个默认值成立的前提是「Key 是用户自己的」。一旦有平台密钥，这个前提没了，而 `rate:cost` 是**全体用户共用一个桶**。所以部署时必须把 `DAILY_BUDGET_YUAN` 设成正数（建议先 20，观察一周再调），并在 `config.validate()` 加一条 fail-closed：`is_prod() and platform_model_api_key and daily_budget <= 0` → 拒绝启动。

### 3.4 已拍板（2026-10-01）

1. **「30 章」= 免费建的长篇最多用平台密钥写 30 章**，累计、终身不重置。建书申报的章数区间 **50–1000 不动**——不改 `CHAPTER_COUNT_MIN`，也不给这类书开特例。
2. **豁免范围只有 `role=admin`**，`tier=vip` 照常受限。

落地时另发现两处原设计没覆盖的缺陷，都已修并各有测试：

- **额度必须先问「平台密钥到底配没配」。** 原判据只问「有没有自备连接」，于是没配 key 的部署（以及整个测试套）凭空获得 3 本上限。补 `platform_model_configured()`，凭据层与计费层共用。
- **额度闸门不能挡住幂等重放。** 额度用完后重发同一个 `request_id`，原本回 429，而书其实已经在书架上了。长篇按 `request_id` 回溯已有作品，短篇先查 `session.book_id` 再判额度。

### 3.5 改动的文件（实际）

| 文件 | 改动 |
|---|---|
| `src/myink/config.py` | 7 个平台字段 + `validate()` 两条 fail-closed（协议合法性、prod 必须有预算） |
| `src/myink/providers/__init__.py` | 抽 `_provider_for`；新增 `_platform_chain` / `_fallback_chain` / `platform_model_configured` / `platform_key_active`；`_project_primary` 改返回 `(override, packed)` |
| `src/myink/models/project.py` | `User` 加 `platform_short_used` / `platform_long_used` |
| `src/myink/db.py` | `ensure_platform_quota()` + `_upgrade_platform_quota()` |
| `src/myink/cli.py` | `init()` / `auth-upgrade` 里插幂等升级 |
| `src/myink/api/routes_book.py` | 建书判额度 + 扣减；抽 `_platform_quota_response` / `_find_by_request_id` |
| `src/myink/api/routes_short_creation.py` | commit 判额度 + 扣减（放在 `session.book_id` 复用分支之后） |
| `src/myink/api/routes_tasks.py` | 长篇两个入队口传 `platform_chapter_max` |
| `src/myink/worker/gates.lua` | **新增第 6 道闸门** `rate:platformbook:{uid}:{pid}`（终身计数，不设 EXPIRE） |
| `src/myink/worker/compensate.lua` | 同步回滚该键（仅在 max > 0 时） |
| `src/myink/worker/redis_client.py` / `enqueue.py` | `platform_book_key()`；`platform_chapter_max` 参数（默认 0 = 不限） |
| `web/src/lib/apiError.ts` | `GATE_CODES` 加 `PLATFORM_QUOTA_EXCEEDED` / `PLATFORM_CHAPTER_EXCEEDED` 两条 |
| `.env.example` | 新增 7 个 env 的说明与示例值 |

### 3.6 明确不做

不新建按维度的用量表；**其余五项闸门的语义一并不改**（第六项是新加的，不碰前五项）；不给平台 key 做加密落库；不在页面常驻显示剩余次数；不动短篇/长篇的生成管道。

### 3.7 上线口径

服务器 `.env` 要加 `PLATFORM_MODEL_API_KEY` / `_BASE_URL` / `_NAME` / `_PROTOCOL` 四项，并把
`DAILY_BUDGET_YUAN` 从 `0` 打开（配了平台密钥却不设预算，`validate()` 会 **fail-closed 拒绝启动**）。
`rate:cost` 是全体用户共用一个桶，有了平台密钥后「Key 是用户自己的」这个前提不再成立，这一条是唯一有真金白银风险的地方。
模型用 `deepseek-flash`（不在 `MODEL_REGISTRY`，上下文预算因此退回 `REQUEST_TOKEN_BUDGET` 而非 1M；价格走 `prices.py` 的 EXACT 表，是准的）。
**平台密钥只进服务器本地 `.env`，不写进任何文档或提交。**

详细施工口径见 [PLATFORM-KEY-QUOTA-PLAN.md](todo/PLATFORM-KEY-QUOTA-PLAN.md) 与新方案文件（`.claude/plans/`，未入库）。

---

## 4. 其他已知残留（低优先）

| 项 | 说明 |
|---|---|
| 文档里有真实标识 | `docs/archive/ADMIN-ACCEPTANCE-2026-09-19.md` 含真实用户名与 UUID；提交元数据是个人邮箱。公网发布前可决定是否处理 |
| git 历史含两个 39MB 二进制 | `gateway/bin/gateway.exe`，pack 共约 113MB 其中约 78MB 是这两个。属体积问题、非泄密；清理需改写历史（破坏性），留待决定 |
| 死配置残留 | `config.py` 的 `worker_stream` / `worker_group` 无人读取；`scripts/ci-local.sh:21` 导出的 `REDIS_ADDR` 是 Go 时代遗物。按「不删既有死代码除非明确要求」处理 |
| `AGENTS.md` 第 26 行仍要求 `go vet ./...` | Go 网关已退场，`gateway/` 只剩构建缓存。该文件是手写的协作规则且未被 git 跟踪 |
| 没有 Alembic 迁移链 | 建表唯一来源是 `create_all` + 幂等 `myink init` 补丁。**项目既定设计**，非缺陷 |
| 两条待手工核对的旧门禁 | `docs/superpowers/specs/` 下两份带日期的规格说明未标注现状；本地过期分支 / stash 未清理 |

---

## 5. 未验证 / 已知限制（不能算通过）

1. **浏览器级视觉验收不完整。** 项目内没有 Playwright / Puppeteer，除下列例外，前端改动仍只经单测（jsdom）与 `npm run build` 验证，**没有在真实浏览器里逐屏走查**。
   例外一：2026-09-30 的短篇会话改动用 headless Chrome + CDP 真跑过两个场景（重进页面落到新会话、连按刷新不堆空会话）并做了 390px 窄屏核查。
   例外二：2026-10-01 的第二因子（§2.8）同样用 headless Chrome + CDP 走了全流程 17 项断言（登录、开启、密钥、错码/对码、被踢、重登两步、命令行兜底），含 390px 窄屏。
   其余页面（主题页上传 MP4 后的动态背景可读性、带灯牌页面的反馈流程、`/admin` 反馈页签）仍未走查。
2. **生产机首次启动路径未复现。** PG / RabbitMQ 口令的「只在全新数据卷首启生效」在本机（已有数据卷）无法完整复现。**线上已于 2026-09-29 首次启动成功，此项对当前部署不再适用**；但将来换机或重建卷时要重新走一遍 §三。
3. **没有生产容量 / 负载测试。** 两个 worker 是照着「4 vCPU / 3.7 GB / 当前闲置」的判断加的，没有压测支撑。真正并发上量后要回头看队列深度（`rabbitmqctl list_queues`）再决定是否继续加。
4. **真实小说质量没有评测结论。** 现有的是机制与测试结果，不是可用性或文笔保证。
