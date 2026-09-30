# 新人免费额度与平台内置模型密钥

> **状态：未做。** 设计已定、代码未写，两个待拍板问题见 [剩余待办](../REMAINING-WORK.md) 第 3 节。

状态：待评审，**未实现**
日期：2026-09-30

## 一、为什么做

现在 Myink 的模型密钥完全归用户：没配就是 `MissingModelProvider`（`providers/base.py:207`），报「请先在环境配置里添加模型连接」。新用户注册完第一件事就是去弄一个 API key，否则看不到产品能干什么。同时整套闸门的默认值都是「0 = 不限」，因为前提是「模型 Key 是用户自己的」（`config.py:77-80` 原话）。

要做的是：**部署方提供一套内置密钥兜底**，新用户开箱即用，但给终身免费额度，用完才要求配自己的 key。

已拍定的口径（2026-09-30）：

| 项 | 决定 |
| --- | --- |
| 「一次短篇」 | 点「确认，开写」（`POST /api/v1/short/creation/sessions/{id}/commit`）扣一次 |
| 「一次长篇」 | 建书（`POST /api/v1/projects`）扣一次；该书章节数上限 30 章 ← 与现状冲突，见 §六 |
| 额度是否重置 | **终身一次性**，不重置 |
| 构思／规划阶段的模型调用 | 不计入额度，但要有总量保护 |
| 内置密钥可选的模型 | 写死一个，用户不可挑 |

## 二、现状：两条互相独立的链路

### 2.1 凭据解析——已经有唯一收敛点

- 加解密：`providers/credentials.py:19 encrypt_api_key` / `:23 decrypt_api_key`，
  `Fernet(sha256("myink:model-credentials:" + MODEL_CREDENTIAL_KEY))`；密文落在
  `users.environment → models → __model_connections__[].api_key_encrypted`。
- **「override → provider」的唯一入口**：`providers/__init__.py:53 _chain_from_override(override, thinking)`。
  `:58` 解密，`:59` 解不出 key → `_no_model_chain`。
- 两个调用者：`make_chain(role, project_id, db)`（`:78`，作品级，路由取自 `_project_primary` `:155`）；
  `make_user_chain(role, user_id)`（`:101`，账号级——建书对话与文风提取发生在还没有书的时刻）。
- **兜底出口只有一个**：`_no_model_chain(thinking)`（`:47`）。全文件共 7 处调用它
  （`:59 :60 :68 :71 :86 :113 :116`），最终都汇到这一个函数。

这条结构决定了本方案能小改：**只动 `_no_model_chain` 一处，两个入口同时获得平台兜底。**

### 2.2 配额闸门——已经有原子实现

`src/myink/worker/gates.lua` 五项，语义都是「**0 = 不限**」（`:13-15` 注释 + `if max > 0` 判断）：

| 拒绝码 | Redis 键 | 上限来自 |
| --- | --- | --- |
| `QUOTA_EXCEEDED` | `rate:quota:{uid}:{date}` | `QUOTA_DAILY_CHAPTERS`（默认 0） |
| `BOOK_QUOTA_EXCEEDED` | `rate:bookquota:{uid}:{pid}:{date}` | `BOOK_QUOTA_DAILY_CHAPTERS`（默认 0） |
| `BOOK_CNT_EXCEEDED` | `rate:bookcnt:{uid}:{date}` | `BOOKS_PER_DAY`（默认 10，**生效中**） |
| `CONCURRENCY_LIMIT` | `rate:inflight:{uid}:{pid}` | 硬编码 `inflight > 0` |
| `DAILY_BUDGET_EXCEEDED` | `rate:cost:{date}` | `DAILY_BUDGET_YUAN`（默认 0） |

键名集中在 `worker/redis_client.py:56-73`，前缀 `rate:`。执行点在入队时（`worker/enqueue.py:68` → `_run_gates` `:132`）。

**账号级**（没有排队任务的对话／文风提取）：`model_admission.py:90 generate_account_model()`，
Redis `rate:account-model:calls:{uid}:{day}`，上限 `ACCOUNT_MODEL_CALLS_DAILY=60`（`config.py:88`，**默认就生效**），
另有单用户租约（`ACCOUNT_MODEL_BUSY`）与共享日成本桶 `rate:cost`。

拒绝路径统一：`GateError(code)` → `api/main.py:91` → **429 `{"error": CODE}`**。
`{"error": ...}` 这个信封是前端 `GATE_CODES` 命中中文文案的前提，`routes_book.py:190` 的注释专门交代过
（用 `HTTPException` 会被包成 `{"detail": ...}`，文案就丢了）。

**结论：构思阶段的「总量保护」已经存在，不用新做**（`ACCOUNT_MODEL_CALLS_DAILY=60`
就是防「刷对话」那一条）。真正缺的只有三样：平台密钥、终身计数、把成本桶从 0 打开。

## 三、设计

### 3.1 平台内置密钥（新增，结构上不可见）

`config.py` 新增字段，沿用 `_env("UPPER_SNAKE", default)` 的写法和 `dataclass(frozen=True)`：

| 字段 | env | 默认 |
| --- | --- | --- |
| `platform_model_api_key` | `PLATFORM_MODEL_API_KEY` | `""` |
| `platform_model_base_url` | `PLATFORM_MODEL_BASE_URL` | `""` |
| `platform_model_name` | `PLATFORM_MODEL_NAME` | `""` |
| `platform_model_protocol` | `PLATFORM_MODEL_PROTOCOL` | `"openai"` |
| `platform_short_quota` | `PLATFORM_SHORT_QUOTA` | `10` |
| `platform_long_quota` | `PLATFORM_LONG_QUOTA` | `3` |

落点在 `providers/__init__.py`：

```
_no_model_chain(thinking)              # 保持函数名，改内部
    if default_provider is not _BUILTIN_PROVIDER:      # 测试桩短路，原样保留
        return FallbackChain(default_provider, ["stub"], ...)
    chain = _platform_chain(thinking)                  # 新增
    return chain if chain is not None \
        else FallbackChain(_UNCONFIGURED, ["unconfigured"], ...)
```

新增 `_platform_chain(thinking)`：读 `settings` 里那四项，任一缺失就返回 `None`（回落现状）。
**它不走 `decrypt_api_key`**——平台 key 是进程配置里的明文，不是库里的密文，走解密那条路纯属绕远。

为避免与 `_chain_from_override` 重复那段「protocol → provider」判断，
把 `:62-68` 抽成 `_provider_for(protocol, api_key, base_url)`，两边共用。

**「不显示在前端」是结构性的，不是靠隐藏**：平台 key 从不写入 `users.environment`，
而 `GET /environment` 只回 `public_connections(用户自己的连接)`（`environment.py:52 load_environment`）。
这条不变式要守住，防止以后有人图省事把平台 key 塞进 `environment`。

### 3.2 终身额度计数：落在 DB 两列

`users` 表加：

- `platform_short_used INTEGER NOT NULL DEFAULT 0`
- `platform_long_used INTEGER NOT NULL DEFAULT 0`

三条理由都要留着，免得后人「优化」掉：

1. **不能放 Redis。** 现有 `rate:*` 键全是日桶（`EXPIRE 86400`），终身额度不能过期；
   塞进同一命名空间迟早踩错。
2. **不能放 `users.environment` JSON。** 那个 JSON 的语义是「模型连接」，
   `load_environment` 有对外契约；而且并发写整个 JSON 会互相覆盖。
3. **不需要新表。** 判定条件只有「有没有自备 key」「是不是 admin」，没有维度可查。
   逐次明细已经有 `agent_runs`（`models/runs.py:77` 带 `cost_est`）。

**原子性靠复用已有的 `User` 行锁**：短篇 `routes_short_creation.py:290`、
长篇 `routes_book.py:283`，两处都是 `select(User.id).where(...).with_for_update()`。
读-判-增在同一事务内闭环，没有第二个并发窗口——不需要 Lua，也不需要 advisory lock。

迁移：`db.ensure_platform_quota()` + `_upgrade_platform_quota(conn)`，
仿 `ensure_user_tier`（`db.py:214`）与 `ensure_user_environment`（`db.py:274`），
在 `cli.py` 的 `init()` 里插一行 `1.566/3`。
（本仓库的硬规矩：`create_all` 只建新表、不 ALTER 已存在的表，凡是加列必须显式写幂等升级函数。）

### 3.3 扣减与拦截

判据「这个用户走不走平台密钥」：`environment.packed_models(uid)`（`environment.py:46`）
为空 → 没有自备连接 → 用平台 key、受额度限制；非空 → 不受限、也不计数。
`role == "admin"` 直接豁免（否则自己没法测）。

**短篇** —— `routes_short_creation.py:262 commit()`：在 `:290` 的行锁内扣减。
扣减位置要放在 `_create_project_row`（`:295`）**之后**、`db.commit()`（`:303`）**之前**。
放后面是有意的：建书那一步会抛 `BookCountExceeded`（`:299` 捕获后 return），
扣减在它后面，整个事务一起回滚，额度不会被建书失败白白吃掉。

**长篇** —— `routes_book.py:260 create_project()`：同样在 `:283` 的行锁内，同法扣减。

⚠️ 扣减**不能写进 `_create_project_row`**：那个函数被两条动线共用
（长篇 `routes_book.py:296`、短篇 commit `routes_short_creation.py:295`），
必须靠 `form` 分叉、写在两个调用点。这正是它自己 docstring（`:204-209`）警告过的
「两条动线各写一份就会有两种上限口径，对话建书能绕开表单建书的闸门」。

### 3.4 拒绝与前端引导

新码 `PLATFORM_QUOTA_EXCEEDED`，沿用 429 + `{"error": code}` 信封
（直接照抄 `_book_cnt_response`，`routes_book.py:195`）。

`web/src/lib/apiError.ts:5` 的 `GATE_CODES` 加一行，文案直接说结论和下一步动作——
按既有约定**不写灰色小字说明**：

```
PLATFORM_QUOTA_EXCEEDED: '免费额度已用完，去配置自己的密钥',
```

引导入口是 `/environment`（`EnvironmentPage.tsx`，`router.tsx:107`）。
注意 `SettingsPage` 是「本书创作设置」，不是密钥入口，别引导错。

### 3.5 成本护栏（不打开就有真实的账单风险）

`QUOTA_DAILY_CHAPTERS=0` / `DAILY_BUDGET_YUAN=0` 这两个默认值成立的前提是
「模型 Key 是用户自己的，写多少章由用户付费」（`config.py:77-80`）。
一旦有平台密钥，这个前提没了，而 `rate:cost` 是**全体用户共用一个桶**
（`.env.example:58` 明写「注意是全体用户共用一个桶」）。

所以：

- 部署时 `DAILY_BUDGET_YUAN` 必须设成正数（建议先 20，观察一周再调）；
- `config.validate()` 加一条 fail-closed：
  `is_prod() and platform_model_api_key and daily_budget <= 0` → 拒绝启动。
  与 `:179` 拒绝空 `MODEL_CREDENTIAL_KEY` 是同一手法——漏配要响亮，不能静默降级。

## 四、改动的文件

| 文件 | 改动 |
| --- | --- |
| `src/myink/config.py` | 6 个平台字段 + `validate()` 那条 fail-closed |
| `src/myink/providers/__init__.py` | 抽 `_provider_for`；新增 `_platform_chain`；改 `_no_model_chain` |
| `src/myink/models/project.py` | `User` 加两列 |
| `src/myink/db.py` | `ensure_platform_quota()` + `_upgrade_platform_quota()` |
| `src/myink/cli.py` | init 里插 `1.566/3` |
| `src/myink/api/routes_short_creation.py` | commit 里扣减 |
| `src/myink/api/routes_book.py` | create_project 里扣减 |
| `web/src/lib/apiError.ts` | `GATE_CODES` 加一行 |
| `.env.example` | 新增 6 个 env 的说明与示例值 |

## 五、明确不做

- 不新建「用户用量表」；不引入任何按维度的历史统计。
- 不动 `gates.lua`、不动 `rate:*` 键的语义（现有五项一并不改）。
- 不给平台 key 做加密落库——它是进程配置，加密只会掩盖「它不该进 `users.environment`」这条不变式。
- 不在页面上常驻显示剩余次数；只在被拒时给明确文案加引导入口。
- 不动短篇/长篇的生成管道本身。

## 六、需要拍板的两点

1. **「30 章」与长篇现状冲突。** 现状长篇章数区间是 **50–1000**
   （`workflow/outline.py:8 CHAPTER_COUNT_MIN = 50`，`routes_book.py:81 _check_form_chapter_count()` 在用）。
   免费额度建的长篇若要 30 章封顶，就得为这类书放开区间（例如平台额度建的书走 1–30）。
   要确认「后续章节数量定到30章」是不是「免费建的长篇最多写 30 章」这个意思。
2. **豁免范围。** 建议 `role=admin` 永久豁免。`tier=vip` 要不要也豁免？

## 七、验证方案

分四层，前两层必须做，后两层按节奏来：

1. **单测（容器 pytest）**
   - 新增 `tests/test_platform_key_quota.py`：额度计数、平台回落、admin 豁免、429 码。
   - `tests/test_short_creation.py`：commit 扣减一次、重复 commit 不重复扣、超额 429。
   - `tests/test_book_setup.py`：建书扣减（该文件 `:171` 已有 `BOOK_CNT_EXCEEDED` 的先例可仿）。
   - 迁移测试仿 `tests/test_short_creation_migration.py` 的写法
     （临时 schema + 只回滚事务 + 跑两遍验幂等）。
   - 跑法用容器配方（宿主没 Python）：
     `docker run --rm --network myink-test_default -v $PWD:/repo -w /repo myink-api:pytest python -m pytest tests/ -q`，
     环境变量要带 `ADMIN_DATABASE_URL`，否则 `ensure_*` 会回落到本机默认而连不上。
2. **迁移在真库上过一遍**：dev 库跑 `myink init`，确认两个新列出现、存量用户为 0、二次运行幂等。
3. **浏览器真跑**：vite dev + headless Chrome，走完「新用户 → 无 key → 建短篇 → 第 11 次被拒」，
   确认文案与引导入口真的出现。
4. **线上**：先在 dev 栈验完再上服务器；上线沿用「本地 build 镜像 → save/load → up -d」，
   并把 `DAILY_BUDGET_YUAN` 与 `PLATFORM_MODEL_*` 写进服务器 `.env`。

## 八、风险

- **账单**：这是唯一有真金白银风险的一条。护栏是 §3.5 的 `DAILY_BUDGET_YUAN` + fail-closed 校验，
  两者缺一不可——只设额度不设成本桶，一个人刷 30 章长篇照样能把当天额度花穿。
- **平台 key 泄露**：结构性规避（§3.1 末段）。要防的是以后有人把平台 key 塞进 `users.environment`。
- **额度计数与建书事务的边界**：短篇 commit 在第一个事务提交后还有「出方案」一步（`:306-323`），
  那一步失败会 502 而额度可能已经扣掉。实现时要确认扣减到底落在哪一步之后，
  是接受这次扣减（书已经建出来了，重按复用 `session.book_id`）还是回退；这条留到动手时定。
