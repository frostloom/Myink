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

打开 http://localhost ，注册自己的账号。旧 `demo` 账号需管理员通过 `myink reset-password demo` 设置密码后才能访问其示例书，不存在公开默认密码。

如需让用户在项目设置中保存自定义模型 API Key，请在首次使用前设置稳定的
`MODEL_CREDENTIAL_KEY`。该值用于加密数据库中的模型密钥，部署后修改会使旧密钥无法解密；
未设置时会从 `JWT_SECRET` 派生，以兼容本地开发。设置页支持 OpenAI 兼容接口与
Anthropic Messages 原生接口，请按服务商要求填写包含版本前缀的基础地址。

| 本机地址 | 服务 |
|---|---|
| 127.0.0.1:80 / :443 | Caddy 边缘层：前端静态产物、SPA 回退、TLS，把 `/api/v1/*` 分给 Python、`/api/v1/tasks/*/events` 分给 Go |
| 127.0.0.1:5432 | PostgreSQL + pgvector |
| 127.0.0.1:6380 | Redis：限流、锁、心跳、SSE 事件 |
| 127.0.0.1:5672 | RabbitMQ：任务、延迟重投、死信 |
| 127.0.0.1:15672 | RabbitMQ 管理界面，演示账号 myink/myink |

Python API 的 8100 端口与 Go 网关的 8080 端口都仅在容器网络内开放（`expose`，不发布宿主机端口）。宿主机上唯一对外发布的是 Caddy：它按设计监听所有网卡的 80/443——那就是公网入口；PostgreSQL、Redis、RabbitMQ 只绑定回环地址。本机跑演示时 Caddy 对同局域网可达，要收口就配宿主防火墙，或把 compose 里 Caddy 的 `ports` 改成 `127.0.0.1:80:80` 这类形式。不要将这份演示配置原样开放到公网。

首次启动由 `docker/initdb/01-roles.sql` 创建非超级用户 `myink_app`；API 启动时运行 `myink init`，创建表、RLS 与必要补丁（默认不建账号、不建示例数据）；启动不再自动清理遗留表/列。单独升级认证字段可用 `myink auth-upgrade`，不重命名旧账号、不迁移作品归属。已有数据库升级目前使用幂等补丁，尚无完整的 Alembic 版本迁移链。

```bash
docker compose logs -f myink-api myink-worker myink-gateway myink-caddy
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

在不同终端运行 `myink-api`、`myink-worker`、`cd gateway && go run ./cmd/gateway`、`cd web && npm ci && npm run dev`。网关本机运行只需 `REDIS_ADDR`、`PYTHON_API_BASE`、`JWT_SECRET`（它不再连接 RabbitMQ）。本机连接 Compose RabbitMQ 使用 `.env.example` 中的 `amqp://myink:myink@localhost:5672/`；容器内使用服务名 `myink-rabbitmq`。不要混用 guest 凭据。

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

脚本依次执行 Python 语法检查、初始化、契约导出差异检查、Python 全量回归、Go vet/测试、前端 lint/交互测试/构建。模型和 embedding 使用替身，不产生真实模型费用。Go 的 SKIP 会被门禁判为失败。

改动 API 后先执行 `myink contract export` 并提交 `spec/api-openapi.json`，再运行检查；未提交的契约变化会被 `git diff --exit-code` 拦截，这是预期行为。

GitHub Actions 的 Python 和 Go job 均提供 RabbitMQ。PG 业务角色在 checkout 后通过 SQL 创建，避免服务容器早于 checkout 导致初始化脚本缺失。

国内镜像覆盖示例（只用于测试基础设施）：

```bash
PG_IMAGE=docker.m.daocloud.io/pgvector/pgvector:pg16 \
REDIS_IMAGE=docker.m.daocloud.io/library/redis:7-alpine \
RABBITMQ_IMAGE=docker.m.daocloud.io/library/rabbitmq:3.13-management \
SKIP_IMAGES=1 bash scripts/ci-local.sh
```

## 上下文与向量配置

`REQUEST_TOKEN_BUDGET=64000` 控制完整请求的估算输入上限，包含正文、提示词、记忆和工具 schema/返回。`RECALL_TOKEN_BUDGET=12000` 单独限制可选记忆的增量，不能充当整章正文预算。提示词另预留 1000 tokens 给纠错消息，write/audit 还按实际工具 schema 大小预留；发送前按模型注册表的上下文窗口减输出预留再次限制。估算不是精确 tokenizer，真实 usage 另行记录。超出完整请求上限时仍明确失败，不截断正文或硬约束。

预算覆盖章节规划、写作、抽取、审核及章节节点的模型调用。整书规划、批次复盘、全局审计等独立调用尚未统一到这一预算，不能宣称全系统所有请求均限制在 12k。

Compose 默认 `EMBED_ENABLED=0`，关闭向量腿但仍可使用关系与关键词召回。启用需将 Dockerfile 安装改为 `pip install .[ml]`，重建镜像，并给 API/worker 配置 `EMBED_ENABLED=1`、首次下载时 `EMBED_ALLOW_DOWNLOAD=1`，持久化模型缓存。本地 embedding 会额外占用内存与磁盘。开关只对新写入生效，存量事件的向量要另跑一次 `myink embed-backfill --level event`（事实用 `--level world`，`--project` 可限定单本）补建；否则向量腿索引为空，召回静默退化成纯关键词，`recall_stats.vector_status` 会显示 `enabled_but_empty`。该命令幂等，可重复执行。

## 切换公网入口（宿主已有 web 服务器时）

Caddy 要占用 80/443，宿主若已跑着 nginx，它会起不来。这一步**手工做**，不要脚本化：

1. **先确认那台 nginx 没有在服务别的站点**。有的话只删对应的 vhost 文件，别卸载 nginx 包。
2. 把 `docker-compose.yml` 里 `myink-caddy` 的 `ports` 临时改成 `"127.0.0.1:8081:80"`，`docker compose up -d --build myink-caddy`，用 `http://127.0.0.1:8081` 走一遍登录与生成，确认新入口自己是对的。
3. 再停 nginx（`systemctl stop nginx`，确认后 `systemctl disable nginx`），把 `ports` 改回 `"80:80"` / `"443:443"` / `"443:443/udp"`，`docker compose up -d myink-caddy`。
4. 域名解析指过来，`SITE_ADDRESS` 填域名（不带协议前缀），Caddy 自动申请续期证书；证书落在 `caddy-data` 卷里，**不要删这个卷**，否则重启会重签并可能撞 Let's Encrypt 速率限制。

回滚就是把 nginx 起回来、`ports` 改回 8081（第 1 步若删过 vhost，先把它恢复）：Caddy 与 Go 网关都不持有跨启动的业务状态。

## 仍需完成的生产工作

HTTPS 已由 Caddy 承担（`SITE_ADDRESS` 填域名即自动签发续期）；Caddy 之前若再挂 CDN 或云 LB，必须配 Caddy 全局 `trusted_proxies` 并把客户端 IP 取值换成 `{client_ip}`，否则所有用户会塌进同一个限流桶（见 `.env.example`）。模型凭据用户级数据库权限加固、版本化数据库迁移、备份与恢复演练、集中监控和容量测试仍在后续范围。当前没有生产可用性或真实小说质量的保证；演示应使用已验证的机制与测试结果描述能力。
