# 剩余待办

2026-09-30。本文是**唯一的剩余工作量清单**，把散在三处的未完成事项合成一份：

- [公网部署前检查](archive/PUBLIC-DEPLOYMENT-CHECKLIST.md)（2026-09-19）的「上线阻断项」
- [上线前检查报告](archive/LAUNCH-READINESS-2026-09-27.md) §四「已知残留风险」、§五「未能验证」
- [内置平台密钥与免费额度方案](todo/PLATFORM-KEY-QUOTA-PLAN.md)（2026-09-30，设计已定、未实现）

上面三份是当时的快照，保留作历史记录；**结论以本文为准**（§0 列出了其中已经过期的两条）。
每条都标了实测证据或明确标注「未验证」。

## 文档怎么放

- `docs/` 根 —— 还需要看的参考文档（`AUTH.md` / `ADMIN.md` / `DEPLOY.md` / `DEMO.md` /
  `PROD-CREDENTIALS.md` / `SHORT-FORM.md`），以及**本文**。
- `docs/archive/` —— 已完成的施工单、验收记录与检查报告。都**没有删**，每份顶部标了状态；
  里面的结论是当时的，不再更新。
- `docs/todo/` —— 未做方案的详细文档。三份，由本文汇总跟踪：
  - [内置平台密钥与免费额度方案](todo/PLATFORM-KEY-QUOTA-PLAN.md) —— 见本文 §3
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

## 1. 还没上线的代码（最紧的一条）

**短篇建书改成多会话 + 自动落点**：本地已完成、已用 headless Chrome 端到端验证，但**未提交、未推送、未部署**。

实测证据：线上 `myink-api` 容器内 `grep -c "_latest_active"` = `0`；运行中的 `myink-api:local` 镜像构建于 2026-09-29 23:47，早于这笔改动。仓库 HEAD = `origin/main` = `79c945a`。

待提交的 9 个文件：

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
| `docker-compose.yml` | worker 去掉 `container_name`、改 `deploy.replicas: 2`（已单独上线，见 §2.9） |

上线步骤（服务器 `~/myink` 没有源码、不是 git 仓库）：本地 `docker build` → `save`/`load` 传到服务器 → `docker compose up -d myink-api myink-worker`。注意 `docker-compose.yml` 已经在服务器上单独生效过（worker 副本数），**本地这份要一起传过去**，否则两个 worker 会在下次 `up` 时缩回一个。

---

## 2. 生产环境安全与运维

按「真出事时的后果」排序，不按文档里的原始顺序。

### 2.1 备份没有定时，也没演练过（唯一会真的丢数据）

服务器 `~/myink/backups/` 里只有**一个**文件：`prod-before-zlx-migrate-20260929180025.sql.gz`，13 KB，2026-09-29 手工跑的迁移前备份。**没有定时任务**——`crontab -l` 只有腾讯云自己的 agent。

也就是说，线上作品数据的唯一副本就是 PostgreSQL 数据卷本身。磁盘坏一块就全没了。那个备份也**从没做过恢复演练**，[公网部署前检查](archive/PUBLIC-DEPLOYMENT-CHECKLIST.md) 里那句「备份没有做恢复演练，不等于已验证灾难恢复」仍然成立。

- 要做：`pg_dump` 定时化（每天一次 + 保留 N 份）→ **真恢复到临时库验一遍** → 备份文件拉离服务器（同机备份挡不住整机故障）。
- 成本：最低。半天以内。

### 2.2 没有监控告警

`/readyz` 存在，刚验过返回 `{"status":"ok","checks":{"redis":"ok","db":"ok","worker":"ok"}}`，但**没有任何东西在轮询它**。

代价：API 500 暴增、worker 死掉、磁盘写满、证书续期失败——全都不会有人知道，等用户来告诉你。磁盘现在 8.8G/40G（24%），还早。

- 起步做法：外部探活服务轮询 `/readyz`（顺带覆盖「整机挂掉」）+ 一条磁盘阈值 + 一条证书到期提醒。
- 成本：一小时。

### 2.3 DB 最小权限：运行进程同时握着绕过 RLS 的钥匙

**问题**：每个 api / worker 进程**同时**持有两把数据库连接。`DATABASE_URL` 用 `myink_app`（NOBYPASSRLS，受行级安全策略管），`ADMIN_DATABASE_URL` 用 `myink`（表属主，BYPASSRLS）。

租户隔离的最后一道防线是 RLS，而**同一进程里就放着绕开它的钥匙**。RLS 防的是「写错的查询」，不防「拿管理员连接去查的代码」。api 进程一旦被攻破（SSRF 打进内网、依赖投毒、任何 RCE），攻击者可以直接用管理员连接读全表，所有用户的隔离等于不存在。[上线前检查报告](archive/LAUNCH-READINESS-2026-09-27.md) §四 那句「数据库管理员不属于 RLS 能防御的攻击者」说的正是这个；`routes_admin.py` 的跨用户报表就走这条连接。

- 要做：迁移抽成跑完即退的一次性 job，只它拿管理员连接；运行时 api/worker 只留 `myink_app`；管理面板的只读报表另建最小权限角色。
- 代价：属结构性改动，管理面板目前靠 admin 连接跑跨用户查询。**注意 [上线前检查报告](archive/LAUNCH-READINESS-2026-09-27.md) §三 的提醒**：PG 角色类变更只对全新数据卷首启生效，已有数据卷要手工 `ALTER ROLE`。

### 2.4 防撞库只有 IP 维度，两个方向都会出问题

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

### 2.6 镜像与依赖版本全都没锁

`pyproject.toml` 里依赖都是区间（`sqlalchemy>=2.0` 这种），今天构建和下周构建拿到的是不同版本；镜像 tag 是 `myink-api:local`，不指向任何 commit。也**没有**任何扫描（pip-audit / trivy 之类）。

- 要做：加锁文件（`uv.lock` / `pip-compile`）、镜像 tag 带上 commit、CI 里加一轮依赖与镜像扫描。

### 2.7 容器以 root 运行，且无资源上限

`Dockerfile` 与 `caddy/Dockerfile` 都没有 `USER`，都是 root；`docker-compose.yml` 里没有任何 `mem_limit` / `cpus`（2026-09-30 新加的 `deploy: replicas` 只管副本数）。

眼下不危险（两个 worker 各 108 MB、整个栈才用掉约 1.8 GB / 3.7 GB），但**没有任何上限**：哪天 `EMBED_ENABLED` 打开，每份 worker 要再加约 2 GB（bge-m3），无约束地乘上去。

### 2.8 管理面板没有 MFA

`/admin` 只有密码。这是全站唯一能跨用户读数据的地方，也是单点；管理员账号目前只有一个。

### 2.9 worker 副本数（2026-09-30 已做，留档）

服务器 worker 从 1 份加到 **2 份**，因为已经有不止一个用户，而消费循环是 `prefetch=1` + 单线程（`worker/consumer.py`），一个进程同时只跑一个任务，多一本书就得排队等。

- 改法：`docker-compose.yml` 里去掉 `container_name: myink-worker`（与副本数互斥），加 `deploy: replicas: 2`。**没有用 `--scale`**，因为它不落盘，下次 `docker compose up -d` 会缩回一份。
- 多实例安全性已核查：锁按资源分（`lock:task:{id}` / `lock:book:{pid}`），重复投递由 `process()` 先重查锁与 DB 状态兜住。
- 实测：两个 worker_id 不同、`queue:tasks` 消费者数 1 → 2、`/readyz` 的 worker 项仍 `ok`、各占 108.3 MiB。
- **不会提速的场景**：同一本书。`rate:inflight:{uid}:{pid}` 的 `inflight > 0` 硬检查加 `lock:book:{pid}` 把同书任务串行——这是有意的。
- 注意：本地 dev 也会起两份（仓库只有一份 compose，没有 dev/prod 分叉）。
- 与 §3 的耦合：多一个 worker 会让单个用户在共享的 `rate:cost` 桶上花得更快。当前 `DAILY_BUDGET_YUAN=0`（不限）且 Key 是用户自己的，所以现在没有账单风险；**§3 落地时必须同时给这个桶设上限**。

---

## 3. 内置平台密钥与免费额度（设计已定，未实现）

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

### 3.4 待拍板

1. **「30 章」与长篇现状冲突。** 现状长篇章数区间是 **50–1000**（`workflow/outline.py:8` 的 `CHAPTER_COUNT_MIN = 50`，`routes_book.py:81 _check_form_chapter_count()` 在用）。免费额度建的长篇若要 30 章封顶，就得为这类书放开区间。请确认「后续章节数量定到 30 章」是不是「免费建的长篇最多写 30 章」。
2. **豁免范围**：`role=admin` 建议永久豁免（否则自己没法测）。`tier=vip` 要不要也豁免？

### 3.5 改动的文件

| 文件 | 改动 |
|---|---|
| `src/myink/config.py` | 6 个平台字段 + `validate()` 那条 fail-closed |
| `src/myink/providers/__init__.py` | 抽 `_provider_for`；新增 `_platform_chain`；改 `_no_model_chain` |
| `src/myink/models/project.py` | `User` 加两列 |
| `src/myink/db.py` | `ensure_platform_quota()` + `_upgrade_platform_quota()` |
| `src/myink/cli.py` | `init()` 里插一行升级调用 |
| `src/myink/api/routes_short_creation.py` | commit 里扣减 |
| `src/myink/api/routes_book.py` | create_project 里扣减 |
| `web/src/lib/apiError.ts` | `GATE_CODES` 加一行 |
| `.env.example` | 新增 6 个 env 的说明与示例值 |

### 3.6 明确不做

不新建按维度的用量表；不动 `gates.lua` 与 `rate:*` 的语义（现有五项一并不改）；不给平台 key 做加密落库；不在页面常驻显示剩余次数；不动短篇/长篇的生成管道。

详细施工口径见 [PLATFORM-KEY-QUOTA-PLAN.md](todo/PLATFORM-KEY-QUOTA-PLAN.md)。

---

## 4. 其他已知残留（低优先）

| 项 | 说明 |
|---|---|
| 短篇页有一条过期注释 | `web/src/pages/ShortCreationPage.tsx:131` 的注释还写着「重新开始」，但控件已经改名成「新建会话」 |
| 文档里有真实标识 | `docs/archive/ADMIN-ACCEPTANCE-2026-09-19.md` 含真实用户名与 UUID；提交元数据是个人邮箱。公网发布前可决定是否处理 |
| git 历史含两个 39MB 二进制 | `gateway/bin/gateway.exe`，pack 共约 113MB 其中约 78MB 是这两个。属体积问题、非泄密；清理需改写历史（破坏性），留待决定 |
| 死配置残留 | `config.py` 的 `worker_stream` / `worker_group` 无人读取；`scripts/ci-local.sh:21` 导出的 `REDIS_ADDR` 是 Go 时代遗物。按「不删既有死代码除非明确要求」处理 |
| `AGENTS.md` 第 26 行仍要求 `go vet ./...` | Go 网关已退场，`gateway/` 只剩构建缓存。该文件是手写的协作规则且未被 git 跟踪 |
| 没有 Alembic 迁移链 | 建表唯一来源是 `create_all` + 幂等 `myink init` 补丁。**项目既定设计**，非缺陷 |
| 两条待手工核对的旧门禁 | `docs/superpowers/specs/` 下两份带日期的规格说明未标注现状；本地过期分支 / stash 未清理 |

---

## 5. 未验证 / 已知限制（不能算通过）

1. **浏览器级视觉验收不完整。** 项目内没有 Playwright / Puppeteer，除下列一条外，前端改动仍只经单测（jsdom）与 `npm run build` 验证，**没有在真实浏览器里逐屏走查**。
   例外：2026-09-30 的短篇会话改动用 headless Chrome + CDP 真跑过两个场景（重进页面落到新会话、连按刷新不堆空会话）并做了 390px 窄屏核查。其余页面（主题页上传 MP4 后的动态背景可读性、带灯牌页面的反馈流程、`/admin` 反馈页签）仍未走查。
2. **生产机首次启动路径未复现。** PG / RabbitMQ 口令的「只在全新数据卷首启生效」在本机（已有数据卷）无法完整复现。**线上已于 2026-09-29 首次启动成功，此项对当前部署不再适用**；但将来换机或重建卷时要重新走一遍 §三。
3. **没有生产容量 / 负载测试。** 两个 worker 是照着「4 vCPU / 3.7 GB / 当前闲置」的判断加的，没有压测支撑。真正并发上量后要回头看队列深度（`rabbitmqctl list_queues`）再决定是否继续加。
4. **真实小说质量没有评测结论。** 现有的是机制与测试结果，不是可用性或文笔保证。
