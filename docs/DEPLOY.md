# Ai Ink 一键启动（Docker Compose，阶段 5 首切）

一条命令拉起全部服务，访问 **http://localhost:8080** 即可：前端页面 + API + SSE 全部同源（网关静态托管 `web/dist`）。

## 前置

- Docker Desktop 运行中（Windows：托盘图标为 Running）
- 根目录已有 `.env`（没有则 `copy .env.example .env`，填 `DEEPSEEK_API_KEY`；**不填也能启动看界面，生成章节才需要**）
- **如之前用手工 `docker run` 起过 `aiink-pg` / `aiink-redis`**，先停掉并删除（compose 接管同名容器，端口 5432/6380 冲突）：
  ```bash
  docker stop aiink-pg aiink-redis && docker rm aiink-pg aiink-redis
  ```

## 一键启动

```bash
# 首次：构建镜像（慢，一次性：npm ci + vite build + go build + pip install，约 10~20 分钟）
docker compose build

# 启动全部服务（含自动初始化：建库角色 + aiink init 建表/RLS/seed）
docker compose up -d

# 访问
open http://localhost:8080        # 登录账号：demo（无密码，seed 自动创建）
```

启动后等待约 30~60 秒（首次初始化建表 + seed），`docker compose ps` 看到全部 `Up (healthy)` 即可用。

## 端口

| 端口 | 服务 | 说明 |
|---|---|---|
| **8080** | aiink-gateway | **唯一入口**：前端页面 + `/api/v1/*` + SSE |
| 5432 | aiink-pg | PostgreSQL + pgvector（仅本机可连） |
| 6380 | aiink-redis | Redis 队列（避开外部 rag-redis 的 6379） |
| 8100 | aiink-api | Python API（仅容器网络内，不映射到本机） |
| — | aiink-worker | 队列消费进程（无端口） |

## 常用命令

```bash
docker compose ps                    # 状态
docker compose logs -f aiink-api     # 看初始化日志（aiink init → uvicorn）
docker compose logs -f aiink-gateway # 网关日志（请求转发）
docker compose down                  # 停止（数据保留在 pgdata volume）
docker compose up -d --build         # 改了代码后重建
docker compose down -v               # 停止并清空数据库（回到全新状态，慎用）
```

## 两种用法

1. **全量一键**（上面的命令）：全部服务进容器，适合演示/交付。
2. **只起基础设施**，Python/前端本地直跑（开发热更新）：
   ```bash
   docker compose up -d aiink-pg aiink-redis
   # 然后本地：
   python -m pip install -e . && aiink init
   aiink-api & aiink-worker &        # 或分别开两个终端
   cd gateway && go run ./cmd/gateway
   cd web && npm run dev             # 前端热更新，http://localhost:5173
   ```

## 常见问题

- **`name conflicts with an existing container`**：旧手工容器未删，见「前置」。
- **端口被占（5432/6380）**：`netstat -ano | findstr :5432` 找占用进程，或确认旧的 `aiink-pg`/`aiink-redis` 容器已停止。
- **构建失败：`Read timed out` / `dial tcp ... connection refused`**：docker.io / pypi / npm / golang 官方源在国内直连不稳。compose 里已按国内环境覆盖镜像源（`docker-compose.yml` build args：daocloud 基础镜像 + 阿里云 pip + npmmirror + goproxy.cn）——**境外网络可删除这些 args 用官方源**。
- **镜像构建极慢**：pip 装 torch/sentence-transformers 等大依赖首次需数分钟到十几分钟；Dockerfile 已用 buildkit cache mount 让已下载 wheel 跨 build 复用，中断重跑不重下。
- **登录后项目库为空**：等 `docker compose logs -f aiink-api` 里 `aiink init` 完成（seed 写入《九州问天》+ 示例书），约 30~60 秒；也可 `docker compose restart aiink-api` 重跑（幂等）。
- **生成任务一直 pending / 报错**：`docker compose logs -f aiink-worker` 看 worker 是否消费；`.env` 的 `DEEPSEEK_API_KEY` 是否有效。
- **向量能力（bge-m3）默认关闭**：Docker 镜像默认**不装 torch/sentence-transformers**（依赖拆到 `[ml]` extras，torch ~2GB 且国内镜像源下载易抖）；`EMBED_ENABLED=0` 时 embedder 延迟导入、完全不加载，纯关系链路可跑通演示（§6.12 降级）。需要向量：Dockerfile 的 `pip install .` 改 `pip install .[ml]` 重构建，并把 `EMBED_ENABLED=1`、`EMBED_ALLOW_DOWNLOAD=1` 加进 compose 的 api/worker 环境变量，挂 volume 缓存模型（`~/.cache/huggingface`）。

## 初始化都做了什么（为什么能幂等重跑）

`aiink-api` 容器启动时先执行 `aiink init`：
1. `CREATE EXTENSION vector` + `Base.metadata.create_all` 建表（幂等）
2. 补齐唯一约束 / 组合索引 / HNSW / 候选 kind / 全局审计报告表 / 章节版本表（幂等）
3. `enable_row_level_security()`：全表 FORCE RLS + 租户策略
4. seed：demo 用户（`demo`）+ 《九州问天》作品 + 示例书

PG 首次初始化时挂载的 `docker/initdb/01-roles.sql` 建业务角色 `aiink_app`（NOBYPASSRLS，受 RLS 约束）+ `public` schema 建表权（langgraph checkpointer `saver.setup()` 用应用连接建内部表，PG15+ public 默认对 PUBLIC 无 CREATE）+ 默认权限（未来建表自动授 DML）。

## 跑测试（注意 compose worker 会抢 Redis 队列）

本地 Python 全量回归依赖 Docker 的 `aiink-pg`/`aiink-redis`，但 **compose 的 `aiink-worker` 正消费同一个 Redis 队列**，会抢掉测试入队的任务导致 worker/多进程用例断言失败。跑测试前先停掉它：

```bash
docker compose stop aiink-worker   # 跑完测试再 docker compose up -d aiink-worker 恢复
python -m pytest tests/ -q          # 期望 314 passed + 5 xfailed
cd gateway && go test ./...
```
