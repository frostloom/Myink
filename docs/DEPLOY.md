# Myink 本地部署与验证

当前支持密码注册、登录、改密、退出与账号间作品/任务隔离。先阅读 [账号配置与无损升级](AUTH.md)。公网密钥存储加固等后续设计见 [PROD-CREDENTIALS.md](PROD-CREDENTIALS.md)，不要把本文本地配置原样暴露公网。

## 启动应用

安装并启动 Docker Desktop，在项目根目录执行：

```powershell
Copy-Item .env.example .env  # 仅首次执行，已有 .env 时保留原配置
# 填写强随机 JWT_SECRET（至少 32 字节）和独立稳定的 MODEL_CREDENTIAL_KEY
# 已有模型密钥时务必按 AUTH.md 保留原加密密钥，再更换 JWT_SECRET
# 生成章节前在前端「环境配置」填写模型 Key，不要写进 .env
docker compose up -d --build
docker compose ps
```

打开 http://localhost ，注册自己的账号。**注册需要邀请码，空库没有可用账号**，先发一个：

```bash
docker compose exec myink-api myink create-invite   # 打印一次明文码，默认 7 天有效、1 次使用
```

旧 `demo` 账号需管理员通过 `myink reset-password demo` 设置密码后才能访问其示例书，不存在公开默认密码。

如需让用户在项目设置中保存自定义模型 API Key，请在首次使用前设置稳定的
`MODEL_CREDENTIAL_KEY`。该值用于加密数据库中的模型密钥，部署后修改会使旧密钥无法解密；
未设置时会从 `JWT_SECRET` 派生，以兼容本地开发。设置页支持 OpenAI 兼容接口与
Anthropic Messages 原生接口，请按服务商要求填写包含版本前缀的基础地址。

| 本机地址 | 服务 |
|---|---|
| 127.0.0.1:80 / :443 | Caddy 边缘层：前端静态产物、SPA 回退、TLS、安全响应头，把 `/api/v1/*`（含 `/api/v1/tasks/*/events` 的 SSE）全部转给 Python |
| 127.0.0.1:5432 | PostgreSQL + pgvector |
| 127.0.0.1:6380 | Redis：限流、锁、心跳、SSE 事件（默认 requirepass，口令见 `.env` 的 `REDIS_PASSWORD`） |
| 127.0.0.1:5672 | RabbitMQ：任务、延迟重投、死信 |
| 127.0.0.1:15672 | RabbitMQ 管理界面（用户名 myink，口令见 `.env` 的 `RABBITMQ_PASSWORD`） |

Python API 的 8100 端口仅在容器网络内开放（`expose`，不发布宿主机端口）。宿主机上唯一对外发布的是 Caddy：它按设计监听所有网卡的 80/443——那就是公网入口；PostgreSQL、Redis、RabbitMQ 只绑定回环地址。本机跑演示时 Caddy 对同局域网可达，要收口就配宿主防火墙，或把 compose 里 Caddy 的 `ports` 改成 `127.0.0.1:80:80` 这类形式。不要将这份演示配置原样开放到公网。

首次启动由 `docker/initdb/01-roles.sh` 创建非超级用户 `myink_app`（口令取 `MYINK_APP_PASSWORD`，默认 `myink`；只在**空数据卷**首启生效，已有卷要改口令得手工 `ALTER ROLE` 或重建卷）；API 启动时运行 `myink init`，创建表、RLS 与必要补丁（默认不建账号、不建示例数据）；启动不再自动清理遗留表/列。单独升级认证字段可用 `myink auth-upgrade`，不重命名旧账号、不迁移作品归属。已有数据库升级目前使用幂等补丁，尚无完整的 Alembic 版本迁移链。

旧版 `style_library_items` 缺少的 `note` 列与 `(user_id, name)` 唯一约束现在由 `myink init` 增量补齐；原有档案 ID、名称、文风正文及引用保持不变。不要删表重建。如果同一用户已有重名档案，迁移会明确报错并保留全部数据，应先检查并人工处理这些重名，再重试；不会自动删档、合并或改名。不同用户可以使用同一个文风名。

```bash
docker compose logs -f myink-api myink-worker myink-caddy
docker compose down       # 停止应用，保留作品数据卷
docker compose up -d --build
```

`docker compose down -v` 会删除作品数据，不能用作日常重启。

## 本机开发

```bash
docker compose up -d --wait myink-pg myink-redis myink-rabbitmq
python -m pip install -e '.[dev]'
myink init --seed
```

在不同终端运行 `myink-api`、`myink-worker`、`cd web && npm ci && npm run dev`。本机连接 Compose RabbitMQ 使用 `.env.example` 中的 `amqp://myink:myink@localhost:5672/`；容器内使用服务名 `myink-rabbitmq`。不要混用 guest 凭据。

前端开发地址 http://localhost:5173 ，Vite dev proxy 把 `/api` 转发到 Caddy（`http://localhost:80`，见 `web/vite.config.ts`），因此本机开发要同时起 `docker compose up -d myink-caddy`。

## 自动化回归（独立测试数据）

```bash
SKIP_IMAGES=1 bash scripts/ci-local.sh
# 加上镜像构建：
bash scripts/ci-local.sh
```

使用 Bash 环境（Windows 可用 Git Bash）。脚本通过 `docker-compose.test.yml` 启动 `myink-test` 专用项目，不停止开发 worker、不挂载开发数据卷。测试结束后清理临时容器及其卷。测试数据库为 tmpfs，停止或删除容器后不保留数据。

| 测试环境变量 | 值 |
|---|---|
| DATABASE_URL | postgresql+psycopg://myink_app:myink@127.0.0.1:15432/myink |
| ADMIN_DATABASE_URL | postgresql+psycopg://myink:myink@127.0.0.1:15432/myink |
| REDIS_URL | redis://127.0.0.1:16380/0 |
| REDIS_ADDR | 127.0.0.1:16380 |
| AMQP_URL | amqp://myink:myink@127.0.0.1:15673/ |
| JWT_SECRET | test-jwt-secret-at-least-32-bytes-long（脚本设置；CI 没有 `.env`，密钥短于 32 字节会让业务路由全判 503） |

脚本依次执行 Python 语法检查、初始化、契约导出差异检查、Python 全量回归、前端 lint/交互测试/构建。模型和 embedding 使用替身，不产生真实模型费用。

改动 API 后先执行 `myink contract export` 并提交 `spec/api-openapi.json`，再运行检查；未提交的契约变化会被 `git diff --exit-code` 拦截，这是预期行为。

GitHub Actions 的 Python job 提供 RabbitMQ。PG 业务角色在 checkout 后通过 `docker/initdb/01-roles.sh` 创建，避免服务容器早于 checkout 导致初始化脚本缺失。

国内镜像覆盖示例（只用于测试基础设施）：

```bash
PG_IMAGE=docker.m.daocloud.io/pgvector/pgvector:pg16 \
REDIS_IMAGE=docker.m.daocloud.io/library/redis:7-alpine \
RABBITMQ_IMAGE=docker.m.daocloud.io/library/rabbitmq:3.13-management \
SKIP_IMAGES=1 bash scripts/ci-local.sh
```

### 宿主没有 Python 时：在容器里跑

`ci-local.sh` 用的是宿主 venv 里的 `python` / `myink`。宿主没装 Python 时改走容器：生产镜像
再加 pytest。**测试镜像必须以生产镜像为底座**——否则会出现在 SQLAlchemy 2.0 上跑测试、线上跑
2.1 的情况（2026-09-30 真的这样发生过一次，旧测试镜像是十天前建的）。

```bash
# 1) 建测试镜像（前提：docker compose build myink-api 已经跑过）
docker build -t myink-api:pytest -f- . <<'EOF'
FROM myink-api:local
USER root          # 测试要把 spec/api-openapi.json 写回宿主挂载的仓库目录
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://mirrors.aliyun.com/pypi/simple/ \
    "pytest==8.4.2" "pytest-asyncio==1.4.0"
EOF

# 2) 起测试基础设施（tmpfs 数据，随时可重建）
docker compose -p myink-test -f docker-compose.test.yml up -d --wait

# 3) 初始化 → 导出契约 → 全量回归（env 同上表，容器网络里主机名换成服务名）
docker run --rm --network myink-test_default -v "$PWD:/repo" -w /repo \
  -e PYTHONPATH=/repo/src -e APP_ENV=test -e JWT_SECRET=test-jwt-secret-at-least-32-bytes-long \
  -e DATABASE_URL=postgresql+psycopg://myink_app:myink@postgres:5432/myink \
  -e ADMIN_DATABASE_URL=postgresql+psycopg://myink:myink@postgres:5432/myink \
  -e REDIS_URL=redis://redis:6379/0 -e AMQP_URL=amqp://myink:myink@rabbitmq:5672/ \
  -e EMBED_ENABLED=0 -e RANKINGS_ENABLED=0 \
  myink-api:pytest sh -c 'myink init --seed && myink contract export && python -m pytest tests/ -q'
```

两个坑：测试库是 tmpfs，**每次 `--force-recreate` 都从空库开始，必须先 `myink init`**，
否则收集阶段就报 `relation "users" does not exist`；契约那一步在容器里做不了
`git diff --exit-code`（镜像里没有 git），导出后在宿主机上比对 `spec/api-openapi.json`。

## 上下文与向量配置

`REQUEST_TOKEN_BUDGET=64000` 控制完整请求的估算输入上限，包含正文、提示词、记忆和工具 schema/返回。`RECALL_TOKEN_BUDGET=12000` 单独限制可选记忆的增量，不能充当整章正文预算。提示词另预留 1000 tokens 给纠错消息，write/audit 还按实际工具 schema 大小预留；发送前按模型注册表的上下文窗口减输出预留再次限制。估算不是精确 tokenizer，真实 usage 另行记录。超出完整请求上限时仍明确失败，不截断正文或硬约束。

预算覆盖章节规划、写作、抽取、审核及章节节点的模型调用。整书规划、批次复盘、全局审计等独立调用尚未统一到这一预算，不能宣称全系统所有请求均限制在 12k。

Compose 默认 `EMBED_ENABLED=0`，关闭向量腿但仍可使用关系与关键词召回。启用需将 Dockerfile 安装改为 `pip install .[ml]`，重建镜像，并给 API/worker 配置 `EMBED_ENABLED=1`、首次下载时 `EMBED_ALLOW_DOWNLOAD=1`，持久化模型缓存。本地 embedding 会额外占用内存与磁盘。开关只对新写入生效，存量事件的向量要另跑一次 `myink embed-backfill --level event`（事实用 `--level world`，`--project` 可限定单本）补建；否则向量腿索引为空，召回静默退化成纯关键词，`recall_stats.vector_status` 会显示 `enabled_but_empty`。该命令幂等，可重复执行。

## 备案未完成期间：裸 IP 上 HTTPS

大陆服务器上用域名 + HTTPS 需要 ICP 备案；裸 IP 不涉及备案，所以备案批下来之前可以先只跑 IP。注意**域名实名认证通过 ≠ 备案通过**：实名认证未完成时域名会被注册商置为 `clientHold`，全球不解析，解析控制台里加了记录也只会显示「未生效」。

登录要过公网传密码，明文 HTTP 不合适，所以这一步还是上 TLS。但**默认配置下裸 IP 拿到的是自签证书**（浏览器报警），不是公信证书——Caddy 的隐式自动 HTTPS 专门把 IP 指派给 internal 签发者。要拿 Let's Encrypt 的 IP 证书必须显式声明签发者。

**不用改任何文件**，在 `.env` 里改三行即可：

```bash
SITE_ADDRESS=https://<公网 IP>              # 从 http://<公网 IP> 改过来
CADDY_SITE_TLS=tls-public-ip.caddyfile      # 默认 tls-auto.caddyfile（空操作）
CADDY_DEFAULT_SNI=<公网 IP>                  # 默认 localhost（占位）
```

然后 `docker compose up -d myink-caddy` 重建容器（改的是容器环境变量，不用重新 build 镜像；Caddyfile 是 COPY 进镜像的，只有改它才要 build）。

三行分别解决三件事：

1. `SITE_ADDRESS` 带 `https://` 前缀，Caddy 才在 :443 上起 TLS 服务器并在 :80 上开 HTTP→HTTPS 跳转。
2. `CADDY_SITE_TLS` 让站点块 `import` 那个片段，片段里是 `tls { issuer acme { profile shortlived } }`。它必须显式——Caddy 把 IP 派给自签签发者的判据是「是 IP **且** 没有任何显式 automation policy」（`modules/caddyhttp/autohttps.go` 的 `shouldUseInternal`）；公网 IP 本身是够格拿公信证书的，所以只要站点块里出现 tls 指令，前半个条件就为假，于是改走 ACME。`shortlived` 不是可选优化：Let's Encrypt 的 IP 证书**只有短效一种**（160 小时 ≈ 6.6 天，RFC 8738 + ACME profiles）。
3. `CADDY_DEFAULT_SNI` 是给「客户端不发 SNI」兜底的。RFC 6066 不允许把 IP 写进 SNI，Chrome 等浏览器对 `https://<IP>` 确实发空 SNI；没有这行握手选不出证书。它只在 SNI 为空时参与，所以域名场景留着也无害——但不能靠「设成空值让它失效」：`default_sni {$X:}` 在 X 未设时是硬报错，空默认值做不了条件开关（已实测）。

片段本身写在 `caddy/tls-public-ip.caddyfile`（理由也在那），默认值是 `caddy/tls-auto.caddyfile`（只有注释 = 不改动签发者选择）。这样本地 `SITE_ADDRESS=http://localhost` 的纯 HTTP 模式不受影响——HTTP 站点带 `tls` 块会直接报错（`server ... is HTTP, but attempts to configure TLS connection policies`），所以那段必须在默认路径上缺席。

安全组放行 80：ACME 的 http-01 校验由 Let's Encrypt 从境外回连你的 80 端口完成，不涉及 DNS、不涉及备案。证书落在 `caddy-data` 卷，别删——6 天有效期全靠自动续期，删卷会重签。

**确认签成的是公信证书**（而不是自签）：

```bash
docker compose logs myink-caddy | grep -i obtained
```

`certificate obtained successfully` 后面的 `issuer` 要**不是** `local`。正常输出形如 `issuer":"acme-v02.api.letsencrypt.org-directory"`。

**切回域名**：把上面三行恢复成 `SITE_ADDRESS=<域名>`（不带协议前缀）、`CADDY_SITE_TLS=tls-auto.caddyfile`、`CADDY_DEFAULT_SNI=localhost`，再 `docker compose up -d myink-caddy`。域名证书用默认 profile，不该跟着用 `shortlived`——套上会把 90 天证书压成 6 天。

> 2026-09-29 在腾讯云（62.234.106.6，北京 ap-beijing）实测走通：http-01 校验通过、`certificate obtained successfully` 且 issuer 为 `acme-v02.api.letsencrypt.org-directory`、证书 SAN 为 `IP Address:62.234.106.6`、有效期 6.6 天、`:80` 返回 308 跳转到 `https://`、`curl` 不带 `-k` 校验证书链通过（`ssl_verify_result=0`）。空 SNI 路径也有实证：Caddy 访问日志里出现浏览器请求 `"server_name": ""` 且返回 200。

## 切换公网入口（宿主已有 web 服务器时）

Caddy 要占用 80/443，宿主若已跑着 nginx，它会起不来。这一步**手工做**，不要脚本化：

1. **先确认那台 nginx 没有在服务别的站点**。有的话只删对应的 vhost 文件，别卸载 nginx 包。
2. 把 `docker-compose.yml` 里 `myink-caddy` 的 `ports` 临时改成 `"127.0.0.1:8081:80"`，`docker compose up -d --build myink-caddy`，用 `http://127.0.0.1:8081` 走一遍登录与生成，确认新入口自己是对的。
3. 再停 nginx（`systemctl stop nginx`，确认后 `systemctl disable nginx`），把 `ports` 改回 `"80:80"` / `"443:443"` / `"443:443/udp"`，`docker compose up -d myink-caddy`。
4. 域名解析指过来，`SITE_ADDRESS` 填域名（不带协议前缀），Caddy 自动申请续期证书；证书落在 `caddy-data` 卷里，**不要删这个卷**，否则重启会重签并可能撞 Let's Encrypt 速率限制。解析与 `SITE_ADDRESS` 要同时到位：只把域名解析过来、`SITE_ADDRESS` 还留着默认值时，Caddy 不认这个 Host，返回的是 **200 空页**（不报错），浏览器和手机上都表现为白屏，容易误判成前端有问题。

回滚就是把 nginx 起回来、`ports` 改回 8081（第 1 步若删过 vhost，先把它恢复）：Caddy 与 API 都不持有跨启动的业务状态。

## 生产运维

下面四件事在服务器上各做一次；日常更新仍是「本地重建镜像 → 传 → `up -d`」。

### 数据库最小权限：三个角色，各管一段

建表、跨租户报表、业务读写这三件事的权限要求互相冲突，所以拆成三个角色，由 compose
分别注入（见 `docker-compose.yml`）：

| 角色 | 谁在用 | 能力 |
| --- | --- | --- |
| `myink`（表 owner） | 只有 `myink-migrate`（一次性 job） | 超级用户，全栈唯一能 DDL 的地方 |
| `myink_app` | api / worker | `NOBYPASSRLS`，受租户策略约束 |
| `myink_report` | api（仅 /admin 统计） | `BYPASSRLS` + 只授 `SELECT` + 默认事务只读 |

于是 api 与 worker 都拿不到建表能力：api 的 `ADMIN_DATABASE_URL` 指向 `myink_report`，
worker 里被显式置空（`env_file` 会把 `.env` 里的 owner 串注进去，所以必须显式压住）。

全新数据卷由 `docker/initdb/01-roles.sh` 一次建好三个角色。**已经在跑的库**不会重跑那个脚本，
要手工补 `myink_report`——先把同一口令写进 `.env`，再跑：

```bash
# 服务器 ~/myink 目录下（脚本随 docker-compose.yml 一起拷过去）
echo "MYINK_REPORT_PASSWORD=<强随机值>" >> ~/myink/.env
MYINK_REPORT_PASSWORD='<同一个值>' bash create-report-role.sh
```

验收：报表角色读得到全部租户的行，但写不进去任何东西。

```bash
sudo docker compose exec myink-pg psql -U myink_report -d myink -c 'select count(*) from projects'
sudo docker compose exec myink-pg psql -U myink_report -d myink -c 'create table t(i int)'   # 期望报错
```

> RLS 只覆盖带 `project_id` 的表（`db.py` 的 `enable_rls`）。`users` / `projects` 是租户根表，
> `invitations` / `feedback` / `short_creation_sessions` / `style_library_items` 等没有该列，
> 它们靠应用层的 `user_id` 归属校验，不由数据库兜底——改这些表的查询时要自己带上条件。

### 首次切非 root 容器：三个卷要 chown 一次

api 与 caddy 现在以 uid 10001 运行（两个 Dockerfile 末尾）。**镜像内新建的目录**属主已经对了，
但**已存在的命名卷**仍是 root，切换后 caddy 写不进 `/data`（证书存放处）会直接起不来。
上线前做一次：

```bash
for v in myink_caddy-data myink_caddy-config myink_feedback-data; do
    sudo docker run --rm -v "$v":/d alpine chown -R 10001:10001 /d
done
```

全新部署不用做：空卷会继承镜像目录的属主。

### 备份与恢复

`backup.sh` 做一次 `pg_dump` 并轮转保留最近 14 份，落在 `~/myink/backups`。装 cron：

```bash
# 在服务器上执行（17 分而不是整点：整点机器上别的东西也在跑）
mkdir -p ~/myink/backups
( crontab -l 2>/dev/null; \
  echo '17 3 * * * bash $HOME/myink/backup.sh >> $HOME/myink/backups/backup.log 2>&1' ) | crontab -
crontab -l   # 确认写进去了
# 装完等第一个触发点过了再看一眼日志，确认是真跑过而不是只写进了 crontab：
cat ~/myink/backups/backup.log
```

**恢复演练**——备份没验过就等于没有。恢复到库内另起的临时库，不要动 `myink`：

```bash
LATEST=$(ls -1t ~/myink/backups/myink-*.sql.gz | head -1)
sudo docker compose exec -T myink-pg psql -U myink -d postgres -c 'drop database if exists myink_restore_check'
sudo docker compose exec -T myink-pg psql -U myink -d postgres -c 'create database myink_restore_check'
gunzip -c "$LATEST" | sudo docker compose exec -T myink-pg psql -U myink -d myink_restore_check
# 两边策略数应当一样，说明 RLS 也跟着恢复了
sudo docker compose exec -T myink-pg psql -U myink -d myink -c 'select count(*) from pg_policies'
sudo docker compose exec -T myink-pg psql -U myink -d myink_restore_check -c 'select count(*) from pg_policies'
sudo docker compose exec -T myink-pg psql -U myink -d postgres -c 'drop database myink_restore_check'
```

备份和库在同一块盘上，挡不住整机故障，所以本机再留一份离机副本：

```bash
# 在**本机**执行（不是服务器）。服务器侧的 cron 继续每天出备份。
bash scripts/pull-backup.sh
# 默认拉服务器 ~/myink/backups 里所有 *.sql.gz 到 ~/myink-backups/，
# 落地后逐份 gzip -t 校验，本机按 KEEP（默认 14）轮转。
```

脚本只**读**服务器（rsync 同步 `*.sql.gz`），不在服务器上做任何事；本机轮转只删 `myink-`
开头的日常份，手工的一次性备份（`prod-*.sql.gz`）不删。

**本机这边也要挂个定时任务**，否则「这份副本没在跑」本身不会有人发现——注意 Mac 关机或睡眠时
不会执行，靠它兜底的前提是那台机器常开。

### 确认线上跑的是哪一版

构建时带上 revision，之后不必再比对镜像 ID：

```bash
GIT_REVISION=$(git rev-parse --short HEAD) docker compose build myink-api myink-caddy
sudo docker inspect myink-api --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
```

依赖版本同理钉在 `docker/constraints.txt`（整棵依赖树，含间接依赖）。**改了 `pyproject.toml`
的依赖必须重新生成**，否则新依赖不受约束；命令写在那个文件的头部注释里。

## 仍在后续范围

HTTPS 已由 Caddy 承担（`SITE_ADDRESS` 填域名即自动签发续期）；Caddy 之前若再挂 CDN 或云 LB，
必须配 Caddy 全局 `trusted_proxies` 并把客户端 IP 取值换成 `{client_ip}`，否则所有用户会塌进
同一个限流桶（见 `.env.example`）。此外还有：集中监控与告警（探活与告警渠道已定，见
[REMAINING-WORK.md](REMAINING-WORK.md) §2.2，**尚未在控制台配置**）、容量测试，以及两项已知的
结构性欠账——前端凭据从 localStorage 换成 HttpOnly Cookie、/admin 加 MFA。当前没有生产可用性或
真实小说质量的保证；演示应使用已验证的机制与测试结果描述能力。
