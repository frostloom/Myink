# 扫榜换源施工单：摘掉 daosearch，接入 fanqie-rank-mcp

配套阅读：本文是**施工单**（改哪里、按什么顺序）。设计口径与降级语义见
[`src/myink/integrations/rankings.py`](../src/myink/integrations/rankings.py) 顶部 docstring 与
[`docs/PUBLIC-DEPLOYMENT-CHECKLIST.md`](PUBLIC-DEPLOYMENT-CHECKLIST.md)。

---

## 一、背景：现在这个为什么必须换

`RANKINGS_MCP_URL` 默认指向 `https://daosearch.io/api/mcp`。2026-09-21 实测：

```
POST /api/mcp  →  405   allow: GET, HEAD
GET  /api/mcp  →  404   （返回的是站点自己的 HTML）
GET  /          →  200
```

**不是"服务挂了"，是"这条路结构上走不通"**：MCP Streamable HTTP 只有 POST 一种进法
（`McpClient` 也是 `streamablehttp_client(url)`），而该地址根本不接受 POST。域名活着，
但它现在是个静态内容站。

后果：扫榜**恒灭**——面板永远显示"外部榜单不可用"，永远给内置【示例】数据。
`_fetch_remote` 的降级逻辑本身是对的，不用改；要换的是**源**。

---

## 二、换上去的这个（已实测可用）

[wengchengjian/fanqie-rank-mcp](https://github.com/wengchengjian/fanqie-rank-mcp)，番茄小说榜单。

**用 Myink 真实 `McpClient` 跑通过**：`list_tools` → 4 个工具；`get_ranking` → 真实书名/作者；
Myink 自己的 `sanitize()` 字段能对上。

| 项 | 实测值 |
|---|---|
| 常驻内存 | **45 MiB**（限 256 MiB 下能起，CPU 0.31%） |
| 依赖 | `mcp>=1.0.0` + `httpx>=0.27.0` —— **Myink 镜像里已有**（实测 mcp 1.30.0 / httpx 0.28.1） |
| 代码体积 | tarball 19 KB，生产用到 4 个 `.py` |
| 浏览器 / OCR | **无**，纯 httpx + 正则 |

### 工具契约（实测 dump）

```
list_rankings()                      → [{"title":"男频阅读榜","items":[{"id":"1_2_1141","name":"西方奇幻"}, ...]}, ...]
                                      共 4 组：男频阅读榜 / 男频新书榜 / 女频阅读榜 / 女频新书榜
get_ranking(ranking_id, limit=30, …) → {"ranking_id","count","books":[{"id","rank","title","author","synopsis","cover"}]}
                                       ranking_id 必填，形如 "1_2_1141"（gender_rankMold_categoryId）
get_book_detail(book_id)             → 简介 + 免费章节列表
get_chapter_content(chapter_id)      → 章节正文
```

Myink 只需要前两个；后两个（书详情/章节正文）用不到，且它们的 cookie 逻辑也用不上。

---

## 三、三个拦路虎（**动手前必须先解决，否则方案不成立**）

### 拦路虎 1：出站守卫会拒绝内网 sidecar 地址 —— 这轮新发现，最硬的一个

`_assert_host_allowed`（[routes_settings.py:94-115](../src/myink/api/routes_settings.py#L94-L115)）
只放行**全球可路由**地址，内网与回环**一律拒绝**（`_unsafe_address` 判据是 `not ip.is_global`，
[routes_settings.py:78-91](../src/myink/api/routes_settings.py#L78-L91)）。注释写得很明确：

> 原先私有段与回环**刻意放行**，为的是本地推理服务（如 127.0.0.1:11434 Ollama）；
> 现已确认本部署不用本地模型，改为一律拒绝

而这个守卫**已经覆盖扫榜地址**：[routes_environment.py:65](../src/myink/api/routes_environment.py#L65)
的 `_validate_rankings` 里就调了它。

**冲突点**：sidecar 在 compose 网络内的地址是 `http://myink-rankings-mcp:8765/mcp`，
解析到 `172.x.x.x`；`127.0.0.1` 同理。两种都被拒。

**而且不是"只有手动改才撞"**：`default_rankings()`（[environment.py:15-23](../src/myink/environment.py#L15-L23)）
会把 `.env` 的值当成表单初值下发，环境页 `load()` 直接 `setRankings(env.rankings)`；
前端保存时**总是**发送 `mcp_url`（[EnvironmentPage.tsx:251](../web/src/pages/EnvironmentPage.tsx#L251)）。
于是：**只要 `.env` 指向内网 sidecar，任何用户点一下"保存扫榜配置"就会 400「请求地址指向内网/保留地址，已拒绝」。**

注意 `.env` 默认值本身**不走**守卫（`_default_client_factory` 直接用 `settings.rankings_mcp_url`），
所以"能用"和"能存"是分叉的——这种分叉比直接报错更难查。

**两个修法**（需要你选，见 §八）：

- **A1｜运维预设白名单**：给守卫加一个可选形参 `allow_host`，
  `_validate_rankings` 与扫榜探针传 `urlsplit(settings.rankings_mcp_url).hostname`。
  host 与运维预设**完全相等**才跳检查 → 用户仍不能凭空填 `169.254.169.254`，
  但运维自己声明的那台能用。**推荐**——保住了 SSRF 防线，也不废掉 per-user 覆盖机制。
- **A2｜扫榜地址收归只读**：环境页里 `mcp_url` 不再可编辑（运维配置），用户只能改
  `ranking_id` / `limit` / `timeout`。零守卫改动，最小。代价是多账号不能再各自指向不同榜单服务。

### 拦路虎 2：上游**没有 LICENSE** —— 这轮新发现

```
license: None      stars: 5      pushed: 2026-05-18      archived: False
```

GitHub 上没有任何 LICENSE 文件，等于**保留所有权利**。严格讲，把它的代码复制进 Myink 仓库
是没有授权的。Myink 是**面试作品**，会被人翻代码，这一条会被问到。

同时它也没有 PyPI 包、没有 Docker 镜像（`pypi.org/pypi/fanqie-rank-mcp/json` → 404），
所以没有"依赖它而不复制它"的干净路径。

**可选处理**：① 给作者提 issue 要一个 MIT/Apache 授权（5 star 的小 repo，可能性不低）；
② 换一个带 license 的实现（但上一轮已确认没有更轻的，托管选项也不存在）；
③ 自己实现榜单拉取（见 §九 附二）；④ 接受风险并注明来源。
**这是你的决定，计划里不替你定。**

### 拦路虎 3：工具发现 + 参数错配 → **静默垃圾**（比现在更危险）

两个缺陷叠加：

1. `_find_tool`（[rankings.py:139-150](../src/myink/integrations/rankings.py#L139-L150)）按名字含
   `"rank"` 模糊匹配。当前 server 的工具集里，`list_rankings` 会被选中。
2. `_TOOL_ARGS`（[rankings.py:49-52](../src/myink/integrations/rankings.py#L49-L52)）按 **source**（`qidian`）
   给参，不是按 tool。而调用处是 `_TOOL_ARGS.get(st.rankings_source, {})`
   （[rankings.py:212](../src/myink/integrations/rankings.py#L212)）——`source=qidian` 那套
   `{"type":"hotsales","genre":"overall"}` 是 **DaoSearch 的词汇**，与番茄毫无关系。

结果：调用 `list_rankings({type:"hotsales",...})` → FastMCP **静默忽略**多余实参 → 成功返回分组列表
→ `_extract_rows` 看到顶层 list，每项是 `{"title":"男频阅读榜","items":[...]}` → `sanitize` 取 `title`
→ 得到 **4 本名叫「男频阅读榜」「男频新书榜」「女频阅读榜」「女频新书榜」的书**，
`source="remote"`、**无 error**、**无降级横幅**。

**面板看起来是好的，内容是垃圾。** 上一轮已用 `probe3.py` 复现。

修法见 §六：工具按名钉死 + 参数按 tool 映射 + **无映射即降级**（不要 `{}` 兜底）。

---

## 四、验收目标

1. 扫榜面板拿到**真实番茄榜单**（书名/作者/排名来自番茄，非【示例】），`source=remote`。
2. daosearch 相关的默认值、参数表、文案、文档**全部清除**，仓库里搜不到。
3. `_find_tool` / `_TOOL_ARGS` 的静默垃圾路径**被测试钉死**：参数对不上时降级，绝不返回分类名当书名。
4. 环境页保存扫榜配置**不再 400**（按 §八 选定方案）。
5. 2核4G 上：新增常驻内存 **≤ 60 MiB**，**零新增 Python 依赖**，**不新增镜像**。
6. 全量测试（对齐 CI：`EMBED_ENABLED=0`）全绿。
7. ECS 上实测番茄可达（见 Phase 0）。

---

## 五、Phase 0 · ECS 预检（**先做这个，一天内能出结论**）

整个方案的前置条件：**阿里云机房 IP 会不会被番茄拦**。带宽内网都不一样，本地测不出来。

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H 'User-Agent: Mozilla/5.0' https://fanqienovel.com/rank
```

- `200` → 通，继续 Phase 1。
- `403` / 超时 / 挑战页 → **机房 IP 被封，MCP 方案在 ECS 上作废**。此时要么挂出站代理，要么走 §九 附二。

顺带确认出站到 `fanqienovel.com` 没被安全组/出站策略挡（`PUBLIC-DEPLOYMENT-CHECKLIST.md:27`
提过出站守卫只针对**用户填的**地址，`.env` 默认值不受限，但机房层面的出站策略要单独确认）。

---

## 六、Phase 1 · 落地 sidecar

### 6.1 目录与文件

新增 `rankings-mcp/`（对齐 `caddy/`、`gateway/` 的"每服务一个顶层目录"惯例）：

```
rankings-mcp/
  a_bogus.py      ← vendor（番茄签名算法，14 KB）
  api.py          ← vendor（榜单拉取）
  pua_map.py      ← vendor（章节正文的 PUA 字符映射；Myink 用不到，但 api.py 会 import）
  server.py       ← vendor（FastMCP 工具定义）
  serve.py        ← 新写（见下）
  UPSTREAM.md     ← 来源、commit、日期、license 状态（拦路虎 2 的处置结论）
```

**不要给 `rankings-mcp/` 单独写 Dockerfile，也不要装依赖**：Myink 镜像里
`mcp 1.30.0` + `httpx 0.28.1` 已经在了（实测确认），直接复用 `myink-api:local` 镜像 +
只读挂载这几个文件即可。这是"零新增镜像、零新增依赖"的落地方式。

### 6.2 `serve.py`（新写，约 20 行）

把 stdio 的 FastMCP 改成 Streamable HTTP。**必须设 `transport_security`**：

```python
# FastMCP 1.30 默认开 DNS rebinding 保护，跨容器按服务名访问时 Host 头不在白名单
# → 直接 421 Misdirected Request。这是上一轮踩过的坑，不是可选项。
mcp.settings.host = "0.0.0.0"
mcp.settings.port = 8765
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["myink-rankings-mcp:8765", "127.0.0.1:8765", "localhost:8765"],
    allowed_origins=[],
)
mcp.run(transport="streamable-http")
```

`allowed_origins` **不要**写成 `["*"]`——上一轮验证时为了省事填的 `*`，生产不该留。

注意 `server.py` 用 `from api import ...` 的相对式导入，`serve.py` 需要
`sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` 才能 import 到兄弟模块。

### 6.3 compose 新增服务

```yaml
  myink-rankings-mcp:
    image: myink-api:local
    container_name: myink-rankings-mcp
    volumes:
      - ./rankings-mcp:/srv:ro
    command: ["python", "/srv/serve.py"]
    expose:
      - "8765"          # 只给 compose 网络内部，绝不 publish 到宿主/公网
    healthcheck:
      test: ["CMD", "python", "-c", "import socket;socket.create_connection(('127.0.0.1',8765),2)"]
      interval: 5s
      timeout: 5s
      retries: 30
    restart: unless-stopped
```

**安全要点**：这是**未鉴权的番茄代理**，必须 `expose` 而非 `ports`，且不能进 Caddy 路由表。
它跑的是第三方代码（见拦路虎 2），`/srv` 只读挂载，容器内不需要任何 Myink 密钥 —— 所以
**不要给它 `env_file: .env`**。

然后给 `myink-api` 加依赖，避免冷启动竞态（扫榜失败**只在成功时**写缓存，
[rankings.py:196-197](../src/myink/integrations/rankings.py#L196-L197)；而前端挂载即预热
[RankingsPanel.tsx:37-45](../web/src/components/RankingsPanel.tsx#L37-L45)，
sidecar 没起来的第一屏会假降级，用户不点刷新就一直看着【示例】数据）：

```yaml
    depends_on:
      myink-rankings-mcp:
        condition: service_healthy
```

`myink-worker` 那组 `RANKINGS_*` 环境变量是**残留**（扫榜只在 API 侧调用，worker 不注入生成节点
——见 [docker-compose.yml:137](../docker-compose.yml#L137) 的注释），不必加依赖，顺手可以把那两行删掉。

---

## 七、Phase 2 · 配置模型改造

现在 `source`（`qidian`/`community`）是 **DaoSearch 的词汇**，换源后完全失去意义。
而番茄需要的是 `ranking_id`。**把 `source` 换成 `ranking_id`**。

| 位置 | 现在 | 改成 |
|---|---|---|
| [config.py:126-127](../src/myink/config.py#L126-L127) | `https://daosearch.io/api/mcp` | `http://myink-rankings-mcp:8765/mcp` |
| [config.py:131](../src/myink/config.py#L131) | `rankings_source="qidian"` | `rankings_ranking_id="1_2_1141"`（男频阅读榜·西方奇幻） |
| [config.py:133](../src/myink/config.py#L133) | `rankings_tool=""` | `rankings_tool="get_ranking"`（**默认钉死，不靠模糊匹配**） |
| [.env:47-56](../.env#L47-L56) | 同上 | 同上，注释一并改写 |
| [docker-compose.yml:104-106](../docker-compose.yml#L104-L106) | 同上 | 同上 |
| [environment.py:15-23, 26-48, 93-119](../src/myink/environment.py#L15) | `source` | `ranking_id` |
| [schemas.py:263-269](../src/myink/api/schemas.py#L263-L269) | `RankingsConfigOut.source` | `ranking_id` |
| [routes_environment.py:74-78](../src/myink/api/routes_environment.py#L74-L78) | 校验 `source` ≤32 | 校验 `ranking_id` 形如 `\d+_\d+_\d+` |
| [types.ts:372-388](../web/src/types.ts#L372-L388) | `source` | `ranking_id` |
| [EnvironmentPage.tsx:40-47, 472, 500](../web/src/pages/EnvironmentPage.tsx#L40-L47) | `source` 输入框 | `ranking_id` 输入框 + 改 placeholder |

**旧数据安全**：`merge_rankings` 对未知键是忽略 + 回落默认（[environment.py:26-48](../src/myink/environment.py#L26-L48)），
所以已存库的 `{source:"qidian"}` 会自然失效并落到新默认，**不需要数据迁移**。

`rankings_cache_ttl` 不在用户可改范围内（`rankings_view_for_user` 固定取进程值，
[environment.py:117](../src/myink/environment.py#L117)），不用动。

---

## 八、Phase 3 · 修静默垃圾（拦路虎 3）

三处改动，都在 [rankings.py](../src/myink/integrations/rankings.py)：

1. **删掉 `_TOOL_ARGS`**（:49-52），换成按 **tool** 取参的纯函数：

   ```python
   def _tool_args(tool: str, st) -> dict[str, Any] | None:
       """按工具名给参；返回 None 表示「这个工具我们没有参数约定」→ 调用方必须降级。"""
       if tool == "get_ranking":
           return {"ranking_id": st.rankings_ranking_id, "limit": st.rankings_limit}
       return None
   ```

2. **调用处（:212）改为**：

   ```python
   args = _tool_args(tool, st)
   if args is None:
       return RankingsResult(
           source="sample",
           error=f"工具 {tool} 无参数映射（预期 get_ranking）",
           items=_SAMPLE_ITEMS,
       )
   raw = await client.call_tool(tool, args)
   ```

   **关键**：绝不用 `{}` 兜底。`{}` 兜底正是静默垃圾的成因——调用成功，返回的却是别的东西。

3. **`sanitize` 加一道防线**：`_extract_rows` 现在会把「有 `title` 的单个 dict」当一条记录
   （[rankings.py:96-97](../src/myink/integrations/rankings.py#L96-L97)），这正是分组对象被误当书的原因。
   加一条：**若顶层是 list 且每项都是「有 `items` 列表、无 `rank`」的形状，视为分组容器 → 返回 `[]`**
   （→ 降级），而不是把组名当书名。这是兜底，防将来换榜单服务时重演。

   番茄的 `get_ranking` 返回 `{"books":[...]}`，`books` 已在 `_extract_rows` 的键集合里
   （[rankings.py:93](../src/myink/integrations/rankings.py#L93)），不受影响。

4. **顺手修文案**：`except asyncio.CancelledError` 现在报"扫榜请求被取消"
   （[rankings.py:224-228](../src/myink/integrations/rankings.py#L224-L228)）。mcp SDK 会把
   **连接失败**也折叠成 `CancelledError`，所以 sidecar 挂掉时用户会看到一句和事实无关的话。
   改成「扫榜服务不可达（连接失败或被取消）」。这是小改动，但它是唯一会让运维误判的文案。

### Phase 3 的验收（必须钉成测试）

- 工具返回分组列表 → **降级**，绝不产出 4 条假书。
- `RANKINGS_TOOL` 指向一个无映射的工具 → **降级**，且**不发起调用**。
- 真实 `get_ranking` 返回 → 正常出书名。

---

## 九、Phase 4 · 守卫例外（按 §三 选定的方案落地）

**若选 A1**：给 `_assert_host_allowed` 加可选形参（**不要改它的默认语义**，它还被模型连接
三条路径用着：[routes_settings.py:145, 243, 256](../src/myink/api/routes_settings.py#L145)）：

```python
def _assert_host_allowed(base_url: str, *, allow_host: str | None = None) -> None:
    host = urlsplit(base_url).hostname
    if not host:
        raise HTTPException(status_code=400, detail="请求地址缺少主机名")
    if allow_host and host == allow_host:
        return   # 运维在 .env 里显式声明的扫榜 sidecar，非用户可自选
    ...
```

调用点传 `allow_host=urlsplit(settings.rankings_mcp_url).hostname` ——
[routes_environment.py:65](../src/myink/api/routes_environment.py#L65)（保存）与扫榜探针
[routes_environment.py:162-188](../src/myink/api/routes_environment.py#L162-L188) 两条路径都要传，
否则又是"探针拦、保存不拦"那种分叉（守卫 docstring 自己警告过这一点）。

**若选 A2**：环境页 `mcp_url` 改只读展示，`_validate_rankings` 忽略 `body.mcp_url`。

新增测试：用户填 `169.254.169.254` / `100.100.100.200` / 任意内网段 **仍然 400**；
填 `.env` 声明的那个 host **放行**。

---

## 十、Phase 5 · 前端

- [EnvironmentPage.tsx:40-47](../web/src/pages/EnvironmentPage.tsx#L40-L47) `EMPTY_RANKINGS`：
  `mcp_url` 换默认值、`source` → `ranking_id`；:472 placeholder 同步；:500 那个"来源（source）"
  标签改成"榜单 ID"。
- [EnvironmentPage.test.tsx:24](../web/src/pages/EnvironmentPage.test.tsx#L24) 的 fixture 同步。
- **`RankingsPanel.tsx` 基本不用改**——它只读 `source`（remote/sample）、`items[].{rank,title,author,tags,hot}`，
  与榜单服务无关。唯一视觉变化见下。
- **注意标签/热度会是大片空白**：番茄 `get_ranking` 只给 `rank/title/author/synopsis/cover`，
  **没有 `tags` 也没有 `hot`**。`sanitize` 的 allowlist 只放行 `{rank,title,author,tags,tag,hot}`
  （[rankings.py:43](../src/myink/integrations/rankings.py#L43)），所以真实榜单每一行的右侧
  （`tagsText` / `hotText`，[RankingsPanel.tsx:94-97](../web/src/components/RankingsPanel.tsx#L94-L97)）
  会全是空的，而内置样例数据是有标签的——看起来会比现在的"降级态"更朴素。

  三个选项，**建议本次选 ①**：
  1. **接受空白**，面板照常（不增加注入面，改动为零）；
  2. 把 `rank` 合成 `hot`（如"热榜 3"），右侧至少有东西——纯展示，零风险；
  3. 新增 `synopsis` 进 allowlist 并 cap 到 ~100 字。**不建议**：这会扩大 prompt 注入面，
     而 `sanitize` 的整条设计就是为了不让外部字段原样流出去。

- `web/src/lib/rankings.ts` 的 `sourceLabel`/`sourceTone` 处理的是 remote/sample，
  **与本次换源无关，不要动**（容易被误改）。

---

## 十一、Phase 6 · 测试

改动集中在 [tests/test_rankings_mcp.py](../tests/test_rankings_mcp.py)：

| 现有测试 | 处理 |
|---|---|
| `FakeSettings`（:42-51）`rankings_source="qidian"` | → `rankings_ranking_id` / `rankings_tool="get_ranking"` |
| `test_find_tool_rank_substring_and_source_priority`（:253-261） | 保留，但 fixture 工具名改成番茄的；**新增一条**：`list_rankings` 与 `get_ranking` 同时存在时，`RANKINGS_TOOL=get_ranking` 必须选中 `get_ranking` |
| `test_service_remote_returns_sanitized_items`（:277-291） | :291 那行断言的是 Daosearch 的 `{"type":"hotsales","genre":"overall"}` → 改成 `{"ranking_id":..., "limit":...}` |
| `test_service_no_tool_found_degrades_to_sample`（:350） | 保留 |

**新增**（对应 Phase 3 验收）：

1. `test_grouped_list_degrades_not_garbage` —— 喂真实的 `list_rankings` 输出（4 个分组），
   断言 `source == "sample"` **且** `len(items) == len(_SAMPLE_ITEMS)`，
   并显式断言**没有任何一条 title 是「男频阅读榜」**。这条是把静默垃圾钉死的核心测试。
2. `test_tool_without_args_degrades_without_calling` —— 工具名有、但无参数映射 → 降级，
   且 `fake.tool_calls == []`（**没发起调用**）。
3. `test_get_ranking_real_payload_maps_fields` —— 用实测的真实 payload
   （`{"ranking_id","count","books":[{"id","rank","title","author","synopsis","cover"}]}`）
   断言 sanitize 后 `rank/title/author` 正确、无多余键。
4. 守卫测试（Phase 4）：内网地址仍然 400 / 运维声明的 host 放行。

`tests/conftest.py:15` 的 `RANKINGS_ENABLED=0` 保持不变。

---

## 十二、Phase 7 · 清尾

仓库内 `daosearch` 的**全部**残留（`grep -rn daosearch`）：

```
docker-compose.yml:106, 139
web/src/pages/EnvironmentPage.tsx:42, 472
web/src/pages/EnvironmentPage.test.tsx:24
src/myink/config.py:127
```

文档侧：

- [config.py:121-124](../src/myink/config.py#L121-L124) 与 [.env:47-49](../.env#L47-L49) 的注释
  还写着"MCP 扫榜（plan.md §10）…拉取**起点**外部榜单"——起点已不成立，改写为番茄，并说明
  数据源是自托管 sidecar。
- [PUBLIC-DEPLOYMENT-CHECKLIST.md:27](PUBLIC-DEPLOYMENT-CHECKLIST.md#L27) 的"自定义模型/MCP 地址"
  一行要补一句：扫榜 sidecar 走的是**运维预设白名单**例外（或按 A2 说明地址已只读），
  并说明该容器只 `expose` 未 `publish`。
- [docs/DEPLOY.md](DEPLOY.md) 加 sidecar 的说明（首次 `docker compose up` 会自动带上，
  但升级时要注意 `rankings-mcp/` 是新目录）。
- `rankings-mcp/UPSTREAM.md` 记录来源、commit、拉取日期、license 处置结论。

---

## 十三、回归面（这些**不该**被这次改动碰到）

- `sanitize` 的 allowlist 语义与 `_SAMPLE_ITEMS` 的降级路径（换源不改降级设计）。
- `RankingsService` 的 TTL 缓存与 `_user_services` 的 per-user 分流。
- `web/src/lib/rankings.ts`（remote/sample 映射，与扫榜源无关）。
- `routes_rankings.py`（`GET /api/v1/rankings` 的形状不变）。
- 模型连接的守卫语义（Phase 4 只加可选形参，默认行为逐字不变）。
- **工作树里正在进行的 SSE 改动**（`src/myink/api/routes_sse.py`、`tests/test_sse.py` 等未提交文件）
  ——本次完全不碰。

---

## 十四、风险

| 风险 | 影响 | 处置 |
|---|---|---|
| **ECS 机房 IP 被番茄拦** | 方案作废 | Phase 0 先测，再决定要不要开工 |
| **上游无 LICENSE** | 面试作品的法律瑕疵 | §三 拦路虎 2，你定 |
| **`a_bogus` 是番茄的私有签名算法** | 番茄改算法 → 榜单接口 401/参数错误 | 这是它能"无浏览器"的代价。`get_chapter_content` 那条路更脆（要 cookie），好在我们不用 |
| 第三方代码进内网 | 供应链 | `expose` 不 `publish`、`/srv` 只读、不给 `env_file`、钉住 commit |
| 守卫例外削弱 SSRF 防线 | 内网可达面变大 | A1 只放行"与运维预设 host 全等"的地址，不放开任意内网 |
| 冷启动竞态 | 首屏假降级 | healthcheck + `depends_on: service_healthy` |
| 分组名被当书名 | 面板显示垃圾而不报错 | Phase 3 三重防护 + 核心测试 |

---

## 十五、落地顺序

```
Phase 0  ECS 预检（机房 IP）           ← 决定方案成不成立，先做
   ↓  通了才往下
§三 拦路虎 2 决策（LICENSE）           ← 决定能不能 vendor，可并行
   ↓
Phase 1  vendor + serve.py + sidecar   ← 起来了就能手工 curl 验证
Phase 2  配置模型（source→ranking_id）
Phase 3  修静默垃圾                    ← 必须带测试，这是最危险的一处
Phase 4  守卫例外（A1 或 A2）
Phase 5  前端
Phase 6  测试全绿
Phase 7  清尾 + 文档
```

**Phase 2 与 Phase 3 必须同批落地**：只改配置不改参数映射，会立刻从"端点死掉"变成
"静默垃圾"；只改参数映射不改配置，`source=qidian` 仍在。两者是一个原子改动。

---

## 十六、待你确认

1. **守卫用 A1（运维白名单）还是 A2（地址只读）？** 见 §三 拦路虎 1。
2. **LICENSE 怎么处置？** 提 issue 要授权 / 换实现 / 自己写 / 接受风险，见 §三 拦路虎 2。
3. **右侧标签栏空白接受吗？** 见 §十，建议选 ①（接受）或 ②（用 rank 合成热度）。
4. **默认榜单选哪个？** 建议 `1_2_1141`（男频阅读榜 · 西方奇幻）。若要女频或新书榜，改
   `RANKINGS_RANKING_ID` 即可；要不要在环境页做成下拉（需要多打一次 `list_rankings`）？

---

## 附一：这次计划**不**做的事

- 不做 `list_rankings` → 选榜 → `get_ranking` 的**两级编排**（那就得改 `_fetch_remote` 的
  "一次调用"模型，并把榜单分类也做成可选项）。本次用「配置里钉一个 `ranking_id`」绕开。
- 不接 `get_book_detail` / `get_chapter_content`（用不到，且后者要 cookie，更脆）。
- 不改 `McpClient`（它是通用的，换源不该动它）。
- 不动短篇相关的一切。

## 附二：我发现的更轻的一条路（供你决定要不要改方向）

如果 §三 的 LICENSE 与守卫两个拦路虎让你觉得代价过高，有一条**明显更简单**的路：

番茄的 `/rank` 页面是**纯 HTML，不需要签名、不需要 cookie**（实测 `HTTP 200`，80 KB，
且 server 自己的 `fetch_leaderboards()` 就是解这个页面的 HTML，不用 `a_bogus`）。
只有 `get_ranking` 那条 JSON 接口才需要签名。

也就是说：**只读榜单页 HTML** 的话，可以完全不引入 MCP、不引入 sidecar、不引入第三方代码——
一个 ~50 行的 `httpx + 正则` 模块就够，Myink 已有的 `sanitize` 直接复用。代价是：
放弃"Myink 是 MCP Client"这个设计口径（docstring 里明确写过），以及榜单粒度可能比 JSON 接口粗。

**这与你说的"接入这个 MCP"方向不同，所以我只列在这里，没有写进计划。** 你要是想改走这条，
我重写一份。
