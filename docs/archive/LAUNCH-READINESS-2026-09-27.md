# 上线前检查报告

> **状态：已完成（归档）。** 当时发现的问题均已修复；§四「已知残留风险」与 §五「未能验证」已并入 [剩余待办](../REMAINING-WORK.md)，以那份为准。

2026-09-27。项目进入发布前最后检查：对部署配置、边缘层、认证边界、前端健壮性与文档一致性做了一轮取证式排查，**发现的阻断级与高风险问题已直接修复**，本文汇总修了什么、怎么验证的、上线前还剩哪些必须手工做的事，以及有意留作已知风险未动的部分。

结论：**没有阻断发布的问题残留**。已修复 13 项（其中 1 项是我在修复过程中自己弄坏的 CI，同轮修回）。上线前需要部署方手工设置的内容见第三节，**未验证项与残留风险都如实列出**，见第四、五节。

---

## 摘要

| # | 问题 | 严重度 | 状态 |
|---|------|--------|------|
| 1 | 全部基础设施口令硬编码在 `docker-compose.yml`，Redis 干脆没有口令 | 阻断 | 已修 |
| 2 | 建业务角色 `myink_app` 的初始化文件是 `.sql`，读不到环境变量，口令无法注入 | 阻断 | 已修 |
| 3 | 上面这次改名把 CI 弄坏了（`ci.yml` 仍在 `psql -f` 已被删除的 `.sql`） | 阻断 | 已修 |
| 4 | 边缘层缺安全响应头；请求体无体积上限 | 高 | 已修 |
| 5 | `/readyz` 公网可达，异常原文（可能含主机名、DSN）直接回给匿名调用方 | 高 | 已修 |
| 6 | `APP_ENV=prod` 时 `MODEL_CREDENTIAL_KEY` 缺失会静默回落到 `JWT_SECRET`（一把钥匙两用） | 高 | 已修 |
| 7 | 六个容器都用默认 `json-file` 日志驱动，**不轮转**，磁盘会被写满 | 高 | 已修 |
| 8 | 部署文档漏了「发邀请码」这一步，空库照文档走会在注册页卡死 | 高 | 已修 |
| 9 | README / DEPLOY 仍在描述**已退场的 Go 网关**，并承诺一个不存在的 Go 门禁 | 中 | 已修 |
| 10 | 生产环境渲染抛错会显示 React Router 自带英文开发页，**把错误堆栈摊在页面上** | 中 | 已修 |
| 11 | 登录页错误提示写死「请确认网关（:8080）已启动」，用户看不懂且已经不成立 | 中 | 已修 |
| 12 | 反馈附件下载：慢请求之后 `window.open` 被弹窗拦截器挡掉 | 中 | 已修 |
| 13 | 主题切换快于 IndexedDB 读盘时，blob URL 泄漏（单个最大 50MB） | 中 | 已修 |

---

## 一、验证结果

以下均为**真实执行**的结果，不是推断。

| 检查 | 命令 / 方式 | 结果 |
|---|---|---|
| Python 全量回归 | 隔离栈 `myink-test`（`docker-compose.test.yml`），先 `myink init --seed` 再 `EMBED_ENABLED=0 python -m pytest tests/ -q` | **1374 passed / 5 xfailed**，3 分 02 秒 |
| 前端 lint | `npm run lint` | 通过（仅既有 fast-refresh 警告，非本次引入） |
| 前端交互测试 | `npm test` | **53 文件 / 387 测试全过** |
| 前端真实类型闸 | `npm run build` | 成功（713 模块） |
| 契约漂移闸 | `myink contract export` + `git diff --exit-code -- spec/api-openapi.json` | 有 1 处新增导出，见下 |
| Compose 配置 | `docker compose config -q` | 通过 |
| 生产栈实况 | `curl -si http://localhost/{healthz,readyz}` | 6 容器全 healthy；两探针 200；`readyz` 报 `redis/db/worker 全 ok` |
| 安全响应头 | 同上，抓响应头 | 六个头齐全 |
| 附件落盘 / 反馈提交 / Redis 需口令 | 逐个实测 | 通过 |

> **契约为何有差异**：本次给 `/readyz` 加了 docstring（说明它公网可达、只回 ok/fail），OpenAPI 因此多一行 `description`。按项目约定「改 API 后先导出并提交 spec」，`spec/api-openapi.json` 的这次变更必须与代码同批提交，否则 CI 的漂移闸会红。

---

## 二、修复清单

### 部署与凭据（1、2、3、7）

- `docker-compose.yml`：全部口令参数化为 `${VAR:-原值}`。**默认值就是改动前的值**，所以本机开发栈与测试栈行为完全不变；公网只需在 `.env` 覆盖。Redis 从「无口令」改为 `requirepass`，健康检查改为带鉴权探测。
- `docker/initdb/01-roles.sql` → **`docker/initdb/01-roles.sh`**：SQL 初始化文件无法读取环境变量，业务角色 `myink_app` 的口令没法注入。新脚本用 `psql -v` 传参，且无论被**执行**还是被 **source**（git 未跟踪可执行位，两种都可能发生）都会在失败时响亮退出。
- `.github/workflows/ci.yml`：上一项改名把 CI 弄坏了——`ci.yml` 仍在跑 `psql -f docker/initdb/01-roles.sql`。已改为调用同一份脚本，并补齐 `PGHOST/PGPASSWORD/...`（CI 里数据库在另一个容器，不补就连不上）。
- 六个服务统一加日志轮转（`max-size: 10m` / `max-file: 3`）。

### 边缘层与探针（4、5）

- `caddy/Caddyfile`：补 `Strict-Transport-Security` / `X-Content-Type-Options` / `X-Frame-Options` / `Referrer-Policy` / `Permissions-Policy`，以及 CSP 的 `frame-ancestors 'none'; base-uri 'self'; object-src 'none'`；请求体加 `max_size 500MB`。
  - **完整 CSP 有意留白**：需要给内联的主题启动脚本算 hash，还要放开 `blob:`（用户上传的媒体背景）。贸然上完整 CSP 会直接白屏，所以只加了不可能破坏 SPA 的那几条，并在文件里写明原因。
- `src/myink/api/main.py`：`/readyz` 经 Caddy 公网可达，原先把异常原文回给调用方（可能含主机名、DSN）。改为对外只回 `ok`/`fail`，细节进 logger。

### 配置校验（6）

- `src/myink/config.py`：新增第二道生产闸——`APP_ENV=prod` 且未显式设 `MODEL_CREDENTIAL_KEY` 时**拒绝启动**。原行为是静默回落到 `JWT_SECRET` 派生密钥，等于加密密钥和签名密钥共用一把（见 `docs/PROD-CREDENTIALS.md` §1）。已确认 `is_prod()` 只影响这两条校验，不改变其它运行时行为。

### 文档一致性（8、9）

- `docs/DEPLOY.md`：补上 `docker compose exec myink-api myink create-invite`——**空库没有任何可用账号**，照原文档会在注册页卡死且看不出原因；同时修正端口表（SSE 已不由 Go 提供）、口令引用与 initdb 脚本名。
- `README.md` / `docs/DEPLOY.md`：删除 Go 网关相关描述。`76925c9 refactor: Go 网关退场，SSE 退回 Python 单一进程` 是刻意的架构变更，但那次提交漏改了这两份文档（`gateway/` 目录如今只剩构建缓存，CI 也没有 Go job），于是 README 的技术栈表还在写「网关 | Go / Gin」，部署文档还在承诺「Go vet/测试」门禁。
- `.env.example`：顶部加「公网部署必须改的三处」，并新增基础设施口令一节，标注 **PG / RabbitMQ 口令只在空数据卷首启生效**、口令须用 URL 安全字符。

### 前端健壮性（10–13）

| 文件 | 修复 |
|---|---|
| `web/src/router.tsx` | 新增中文兜底错误页（`errorElement`）。原先渲染期抛错会命中 React Router 内置开发页，把英文报错与**完整堆栈**渲染进用户页面。兜底页给「刷新」与「回到首页」两个出口——若出错的正是当前路由，只刷新会陷在同一地址上出不来 |
| `web/src/pages/LoginPage.tsx` | 「无法连接服务，请确认网关（:8080）已启动」→「无法连接服务，请检查网络后重试」 |
| `web/src/components/FeedbackWidget.tsx` | ① 附件下载改为**先同步 `window.open` 再 fetch**，否则慢请求之后弹窗会被浏览器拦截；② 反馈面板补 Tab 焦点陷阱（照抄项目既有 `ShortCreationPage` 的实现） |
| `web/src/context/ThemeContext.tsx` | 加序号守卫。连着切主题预设时两次 IndexedDB 读盘会交错，后一次把前一次新建的 blob URL 顶掉、再没人撤销——单个最大 50MB，切几次就吃掉几百 MB |

---

## 三、上线前需要手工完成

1. **部署机的 `.env`**：`APP_ENV=prod` + 强随机 `JWT_SECRET` 与 `MODEL_CREDENTIAL_KEY`（`openssl rand -base64 48`）+ 四个基础设施口令。
2. ⚠️ **PG 与 RabbitMQ 的口令只在全新数据卷首启生效**。已有数据卷必须重建卷或手工 `ALTER ROLE`；Redis 口令每次启动都读，随时可改。
3. **提交时必须带上 `spec/api-openapi.json`**（原因见第一节注），以及 `docker/initdb/01-roles.sh` 的新增与 `01-roles.sql` 的删除。
4. 不要用 `git add .`：`gateway/`、`docs/superpowers/` 等未跟踪且未被 `.gitignore` 覆盖，会被一起卷进提交。

---

## 四、已知残留风险（本次有意未改）

| 项 | 说明 | 为何不动 |
|---|---|---|
| 管理端报表用超级用户连接 | `src/myink/api/routes_admin.py:48-56` 的报表会话走 `ADMIN_DATABASE_URL`（表 owner 超级用户，绕过 RLS） | 只读且管理员门禁。根治需新建 BYPASSRLS 报表角色，属 DDL 变更——**只对全新数据卷生效**，且与线上已有数据卷纠缠，上线前动它风险大于收益 |
| 没有 Alembic 迁移链 | 建表唯一来源是 `create_all` + 幂等 `myink init` 补丁 | 项目既定设计（`plan.md` §17.2 明确），非本次引入 |
| git 历史含两个 39MB `gateway/bin/gateway.exe` | pack 共 112.8MB，其中约 78MB 是这两个二进制 | 体积问题，非泄密。清理需改写 git 历史（破坏性操作），留待你决定 |
| 死配置残留 | `config.py` 的 `worker_stream` / `worker_group` 无人读取；`scripts/ci-local.sh:21` 导出的 `REDIS_ADDR` 也是 Go 时代遗物 | 均为既有死代码，按「不删既有死代码除非明确要求」处理 |
| `AGENTS.md` 第 26 行仍要求 `go vet ./...` | 该文件是你手写的协作规则，且当前**未被 git 跟踪**；`gateway/` 已无源码 | 属于你在维护的文件，未擅自改动 |
| 文档中的真实标识 | `docs/archive/ADMIN-ACCEPTANCE-2026-09-19.md` 含真实用户名与 UUID；提交元数据为个人邮箱 | 公网发布前你可决定是否处理 |

---

## 五、未能验证的部分

如实列出，**不将其记作通过**：

1. **浏览器级视觉验收**：项目内没有 Playwright / Puppeteer，无法自动化截图或做视觉回归。前端改动只经单测（jsdom）与 `npm run build` 验证，**未在真实浏览器里逐屏走查**。建议上线前用 Chrome / Edge 手工过一遍：登录 → 任一带灯泡的页面 → 提交带图/视频的反馈 → `/admin` 的「反馈」页签可见并标记已解决；以及主题页上传 MP4 后的动态背景与文字可读性。
2. **公网新数据卷的首次启动**：本机是已有数据卷，PG / RabbitMQ 口令的「首启生效」路径无法在本机完整复现（init 脚本本身已在一次性卷上单独验证过会按预期建角色）。**首次在生产机 `up` 之前，请确认 `.env` 已填好**——填晚了就得重建卷。
3. **CI 远端实际运行**：本轮只做了本地等价验证（`scripts/ci-local.sh` 的各项门禁逐条手工执行）。真实 GitHub Actions 的运行结果以推送后的 CI 为准。
4. **Go 相关门禁**：Go 网关已退场，不再适用。
