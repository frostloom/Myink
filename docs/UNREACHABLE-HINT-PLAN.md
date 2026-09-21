# 不可达提示施工单：把「连不上」和「被拒绝」分开，并给一句可操作的出路

目标：当用户配置的模型服务（或 MCP 服务）因为**本部署所在网络**而不可达时，给他一句说清
原因的提示，并指向可自行部署的仓库地址；同时**不再把"密钥错""模型名错"也混进这句话里**。

配套阅读：本文是**施工单**。用户的原始诉求见 §十六「原始诉求」原文。

---

## 一、先摆事实：现在到底会发生什么

### 1.1 探针这条路——二分结构**已经在**，只是文案没分层

[`probe.py:114-117`](../src/myink/providers/probe.py#L114-L117)：

```python
except httpx.HTTPStatusError as exc:          # 上游回了非 2xx
    return False, ..., _status_error(exc, api_key)
except Exception as exc:                      # 压根没拿到响应
    return False, ..., _error_text(exc, api_key)
```

- 第一支 `_status_error`（[:47](../src/myink/providers/probe.py#L47)）**会把上游 body 带出来**
  ——"模型不存在 / 鉴权方式不对 / 额度用尽"都能看到。**这条已经做得很好，本次不动它。**
- 第二支 `_error_text`（[:43](../src/myink/providers/probe.py#L43)）**只有异常原文**：

  ```python
  return _sanitize(str(exc) or exc.__class__.__name__, api_key)
  ```

  这就是要改的地方。而**连接层失败恰恰是大陆网络环境下最常见的一类**，却最不好懂。

`list_models`（[:70-84](../src/myink/providers/probe.py#L70-L84)）是同样的两分支结构，同样要改。

### 1.2 生成期这条路——**完全另一条**，而且问题比文案严重得多

用户不是在"点测试"时才用模型，**真正跑起来失败**发生在
[`deepseek.py:180-185`](../src/myink/providers/deepseek.py#L180-L185)：

```python
except Exception as exc:
    last_error = str(exc)
    logger.warning("DeepSeek 调用失败(attempt=%d): %s", attempt, last_error)
    if attempt < MAX_RETRIES:
        time.sleep(BACKOFF_BASE[min(attempt, len(BACKOFF_BASE) - 1)])
return ModelResponse(content="", model_id=model_id, error=last_error, ...)
```

三个事实：

1. **它不抛异常**，返回 `ModelResponse(error=<异常原文>)`。
2. 常量是 `MAX_RETRIES = 3`、`BACKOFF_BASE = [1.0, 2.0, 4.0]`、`timeout=120.0`
   （[:28-29](../src/myink/providers/deepseek.py#L28-L29)、[:83](../src/myink/providers/deepseek.py#L83)）。
   面对一个**不可达**的主机，最坏耗时 = 4 次 × 120s 超时 + (1+2+4)s 退避 ≈ **487 秒，超过 8 分钟**。
   `ConnectTimeout` 每次都会实实在在地等满 120 秒。
3. **对连接层失败重试三次毫无意义**——主机不可达不会因为等 1 秒就可达。这 8 分钟是纯浪费。

`resp.error` 随后被 **10 处以上**当字符串消费，链路完全一致：
[`book_setup.py:35-36`](../src/myink/book_setup.py#L35-L36)、
[`style_extract.py:115-116`](../src/myink/style_extract.py#L115-L116)、
[`batch_graph.py:150-151`](../src/myink/workflow/batch_graph.py#L150-L151)、
[`nodes.py:193`](../src/myink/workflow/nodes.py#L193) …

**这带来一个好消息**：`last_error = str(exc)` 是**所有生成期模型错误的唯一漏斗**（流式版本在
[:307-313](../src/myink/providers/deepseek.py#L307-L313) 同形）。在这一处做分类，
**下游十几处调用点一行都不用改**。

### 1.3 分类边界已经被 httpx 定义好了——实测确认

在容器里跑了一遍 `httpx 0.28.1` 的异常树：

```
TransportError                                    ← 「没拿到合法 HTTP 响应」的精确边界
├── NetworkError          → CloseError / ConnectError / ReadError / WriteError
├── ProtocolError         → LocalProtocolError / RemoteProtocolError
├── ProxyError
├── TimeoutException      → ConnectTimeout / PoolTimeout / ReadTimeout / WriteTimeout
└── UnsupportedProtocol

判定抽样（实测）:
  ConnectError / ConnectTimeout / ReadTimeout / RemoteProtocolError
  ProxyError / TLS 失败(ConnectError 包 SSLError)     → 全是 TransportError
  HTTPStatusError（上游回了 401/404/402）              → False  ✅ 正是我们要的分界
  InvalidURL（URL 写坏）                               → False  ✅
```

**结论：`isinstance(exc, httpx.TransportError)` 就是"连不上"的判据**，不需要自己列举。
比按 IP、按域名、按国家猜要准得多——而且它天然免疫 §1.4 那种情况。

**一个边界情形**：`UnsupportedProtocol`（用户把 URL 写成 `ftp://`）也是 `TransportError`，
但那是**他自己配错了**，不是网络不可达。归类时要单独摘出来（见 §五）。

### 1.4 守卫放行 ≠ 能连上（上一轮已实测的坑）

`api.openai.com` 在污染 DNS 下解析到 `31.13.90.19`（Facebook AS32934）。这个地址是
**全球可路由的**，所以 `_assert_host_allowed` 会**放行**它，然后请求真的发出去、连到错误的
主机、TLS 对不上。

所以：**出站守卫拦不住 DNS 污染，只能拦私网地址**。用户会看到"保存成功"，然后在探针/生成
阶段以 `ConnectError` 的形式失败。这正是本次要补的那句话的场景。

### 1.5 MCP 那条路——现在**检测不出来**（本次不做，见附录）

mcp SDK 把所有协议层失败折叠成 `CancelledError`，`_fetch_remote`
（[`rankings.py:224-228`](../src/myink/integrations/rankings.py#L224-L228)）只能报一句
"扫榜请求被取消"，**分不出"端点根本不存在（405 静态站）"和"网络抖动"**。
要让它也走这套提示，得先在 `McpClient` 层把底层异常捞出来——那是独立的一块工作。

---

## 二、关键设计决定

| 问题 | 决定 | 理由 |
|---|---|---|
| 分类判据 | `isinstance(exc, httpx.TransportError)` | §1.3 实测：它精确等于「没拿到合法 HTTP 响应」 |
| 分类代码放哪 | 新模块 `src/myink/providers/errors.py` | `probe.py`（测试）与 `deepseek.py`（生成）**两条路都要用**，不能各写一份 |
| 提示怎么传出去 | **拼进错误字符串**，不新增结构化字段 | 全链路的 error 都是字符串（探针 schema、`ModelResponse.error`、`agent_runs.error`、SSE）。新增字段要改十几处，收益不成比例 |
| 仓库地址哪来 | `settings.self_host_url`（`.env` 的 `SELF_HOST_URL`），**留空则不显示这句** | 本地部署时必须能关掉——见 §三 |
| 链接怎么渲染 | 第一版**纯文本**，不新增组件、不做可点链接 | 前端目前**没有任何打开外链的先例**（实测 grep 零命中）。引入第一个会连带样式 + `rel` 安全决策，与本次目标无关 |
| 连接层失败要不要重试 | **不重试**（见 §八，需你定） | 不可达不会因为等 1 秒就可达；现在是 4×120s ≈ 8 分钟纯浪费 |
| MCP 那半 | **不做** | §1.5，且扫榜已搁置 |

---

## 三、一句必须避开的废话

如果 Myink 就跑在用户自己机器上，"请到 GitHub 部署到本地"是**自相矛盾**的。

所以这句话：
- 主语句是**「本部署」**，不是「你」：
  > 本部署所在网络无法访问该服务。
- 自部署指引**由配置项控制**，`SELF_HOST_URL` 留空即整句不出现——本地部署的 `.env` 留空。

---

## 四、Phase 1 · 共享分类器（新文件）

`src/myink/providers/errors.py`：

```python
"""provider 错误分类：把「本部署连不上」和「上游拒绝了你」分开。

判据用 httpx.TransportError —— 它精确等于「请求没拿到合法 HTTP 响应」，
涵盖 DNS/TLS/连接/读超时/代理/协议错误（见 docs/UNREACHABLE-HINT-PLAN.md §1.3 实测）。
上游回非 2xx 不算（那是 HTTPStatusError，自带可诊断的 body）。
"""

def is_unreachable(exc: Exception) -> bool:
    """本部署够不到该地址 → 不是用户密钥/模型名的错。"""
    if isinstance(exc, httpx.UnsupportedProtocol):
        return False        # URL scheme 写错，是配置错误不是网络不可达
    return isinstance(exc, httpx.TransportError)


def unreachable_hint() -> str:
    """给用户的一句话；SELF_HOST_URL 为空时只汇报原因，不推销自部署。"""
    msg = "本部署所在网络无法访问该服务（连接失败）"
    url = (settings.self_host_url or "").strip()
    if url:
        msg += f"。可在你可控的网络中自行部署后使用：{url}"
    return msg
```

**要点**：
- **不要**在文案里写"网络问题"四个字。写"本部署所在网络无法访问该服务"——主语句是
  「本部署」，这样它在大陆 ECS 上成立，拿到境外跑也成立（那时就不会出现这句话）。
- 异常类名要不要带上？建议带一个短的（`ConnectTimeout` / `ConnectError`），便于用户搜索，
  但**不要把 `str(exc)` 原文拼进去**——它可能含 URL、IP、甚至（脱敏前的）密钥。

---

## 五、Phase 2 · 探针接上

改 [`probe.py`](../src/myink/providers/probe.py) 两处（`test_connection` 的 :116-117、
`list_models` 的 :80-81），把 `_error_text` 换成：

```python
def _error_text(exc: Exception, api_key: str) -> str:
    if is_unreachable(exc):
        return _sanitize(unreachable_hint(), api_key)
    return _sanitize(str(exc) or exc.__class__.__name__, api_key)
```

**注意 `_MAX_ERROR_CHARS = 300`（[:18](../src/myink/providers/probe.py#L18)）**：
"本部署所在网络无法访问该服务（连接失败：ConnectTimeout）。可在你可控的网络中自行部署后使用：
https://github.com/zlx05/Myink" 约 80-90 字，**放得下**，不用改 cap。但如果将来 URL 变长要留意。

**`_status_error` 一行都不动**——上游回 401/402/404 的路径现在是对的。

---

## 六、Phase 3 · 生成期接上（单点改动）

改 [`deepseek.py`](../src/myink/providers/deepseek.py) 的两处 `last_error = str(exc)`
（:181 非流式、:308 附近流式）为：

```python
last_error = unreachable_hint() if is_unreachable(exc) else str(exc)
```

**下游十几处 `if resp.error:` 全部自动受益，一行不用改**（§1.2）。

这是本次改动里性价比最高的一处——它会同时改善：建书方案、整书大纲、章节计划、正文生成、
批量生成、refine、全局审计……**所有**会打模型的路径。

---

## 七、Phase 4 · 前端

几乎不用动：

- 模型连接的探针错误已经渲染在 [`EnvironmentPage.tsx:437-444`](../web/src/pages/EnvironmentPage.tsx#L437-L444)
  的 `connMsg` 里；扫榜的在 [:528-530](../web/src/pages/EnvironmentPage.tsx#L528-L530) 的 `rankProbe.text` 里。
  **字符串换了，UI 自动跟上。**
- **唯一要检查的**：`styles.saveMsg` / `probeStatus` 的容器**会不会把长文本挤爆或截断**
  （现在错误文案通常很短，加上自部署指引后会变长）。要真起前端看一眼——不许凭想象判定。
- **不做可点链接**（§二）。若以后要做，记得加 `rel="noreferrer"`。

---

## 八、Phase 5 · 连接层失败不重试（**需你定，可独立跳过**）

现在 [`deepseek.py:183`](../src/myink/providers/deepseek.py#L183) 对**所有**异常一视同仁地退避重试。
对 `ConnectError` / `ConnectTimeout` 这类，重试是纯浪费——最坏 8 分钟（§1.2）。

改法是循环体内提前跳出：

```python
except Exception as exc:
    last_error = ...
    if is_unreachable(exc):
        break          # 主机不可达，重试没有意义，立刻让用户看到原因
    if attempt < MAX_RETRIES:
        time.sleep(BACKOFF_BASE[...])
```

**收益**：不可达时从 ~8 分钟降到 ~120 秒（一次超时就够）。
**代价 / 风险**：这是个**行为变化**，会影响所有 provider（含中转/网关抖动）。
如果中转偶发 `RemoteProtocolError` 且重试真能救回来，就会被这次改动牺牲掉。

**折中方案**（若担心上面那条）：只对 `ConnectError` / `ConnectTimeout` / DNS 失败 fail-fast，
`RemoteProtocolError` / `ReadTimeout` 保留重试——**"主机都握不上手"和"握上手了但聊崩了"是两回事**。

> 这一条独立于提示文案。就算不做，Phase 1-3 的提示照样成立。建议**分开落地**，便于回滚。

---

## 九、Phase 6 · 配置

| 位置 | 改动 |
|---|---|
| [config.py](../src/myink/config.py) rankings 段附近 | 加 `self_host_url: str = field(default_factory=lambda: _env("SELF_HOST_URL", "") or "")` |
| [.env](../.env) | 加 `SELF_HOST_URL=https://github.com/zlx05/Myink`（**部署在 ECS 时**） |
| [.env.example](../.env.example) | 加上键 + 注释说明"本地部署留空即不显示自部署指引" |
| 本地开发 | `.env` 里留空 |

**仓库地址现状（已核实）**：`https://github.com/zlx05/Myink`，**public**。
本地 remote 原先指向旧名 `git@github.com:zlx05/ai-ink.git`（靠 GitHub 301 兜着），
**已于 2026-09-21 改为 `git@github.com:zlx05/Myink.git` 并验证连通**。
改名前的真实隐患：一旦 `zlx05` 名下新建一个叫 `ai-ink` 的仓库，301 失效，
`git push` 会静默推到那个新仓库。现已消除。
（当时本地有 14 笔未推送提交，与本次改动无关。）

---

## 十、测试

现有：[`tests/test_model_probe.py`](../tests/test_model_probe.py)、
[`tests/test_environment_routes.py`](../tests/test_environment_routes.py)。

**新增（对 `errors.py`，纯函数，最好测）**：

1. `is_unreachable` 的真值表——把 §1.3 实测的那批类**逐个断言**：
   `ConnectError` / `ConnectTimeout` / `ReadTimeout` / `RemoteProtocolError` / `ProxyError` → `True`；
   `HTTPStatusError` / `InvalidURL` / `UnsupportedProtocol` → `False`。
   **`UnsupportedProtocol` 那条必须有用例**——它是唯一会被判据误伤的边界。
2. `unreachable_hint()`：`self_host_url` 为空 → **不含 URL**（这是防止本地部署出现废话的守卫）；
   非空 → 含 URL。用 `monkeypatch` 改 settings。
3. `_error_text` 分层：喂一个 `ConnectError` → 得到提示文案；喂一个普通 `ValueError` → 得到原文
   （**保证非连接类失败不被改写**）。
4. **脱敏不回归**：密钥出现在异常文本里时仍被 `***` 替换（`_sanitize`，[:37-40](../src/myink/providers/probe.py#L37-L40)）。

**新增（对生成期）**：

5. `deepseek.py` 返回的 `ModelResponse.error`：mock transport 抛 `ConnectError` →
   `error` 是提示文案而非 `str(exc)`；抛 `HTTPStatusError` → **不受影响**。
   （这条最好用 `httpx.MockTransport` 打，别碰真网络。）

**若做 Phase 5**：

6. 不可达 → 只尝试 1 次（断言调用次数），且总耗时不随 `MAX_RETRIES` 增长。
7. `RemoteProtocolError`（若选折中方案）→ 仍然重试 `MAX_RETRIES` 次。

---

## 十一、回归面（**不该**被碰到）

- `_status_error` / `_body_detail`（有响应的路径，现在是对的）。
- `_assert_host_allowed`（本次完全不碰守卫）。
- `resp.error` 的十几处消费点（Phase 3 靠"单点漏斗"避免碰它们）。
- `WebSearch`… 无关。**工作树里正在进行的 SSE 改动**（`routes_sse.py` / `test_sse.py` 及
  若干未提交文件）与本次无关，不碰。
- 扫榜相关的一切（已搁置）。

---

## 十二、风险

| 风险 | 影响 | 处置 |
|---|---|---|
| 把配置错误误报成"网络不可达" | 用户查错方向 | `UnsupportedProtocol` / `InvalidURL` 明确排除，并有测试钉住 |
| 提示文案太长撑爆 UI | 版面 | Phase 4 必须**真起前端**看；不许凭想象 |
| Phase 5 牺牲中转抖动的自愈 | 偶发失败变硬失败 | 分开落地；或只对 Connect 类 fail-fast |
| `SELF_HOST_URL` 配错/仓库改名 | 指向 404 | 地址进配置而非硬编码；remote 顺手改名 |
| 文案在本地部署出现 | 自相矛盾 | 留空即不显示 + 测试用例 2 钉死 |

---

## 十三、落地顺序

```
Phase 1  errors.py 分类器 + 测试        ← 纯函数，先立住判据
   ↓
Phase 2  探针接上（probe.py 两处）      ← 起后端填个污染地址就能看到效果
   ↓
Phase 3  生成期接上（deepseek.py 两处） ← 收益最大，下游零改动
   ↓
Phase 4  前端目视检查（真起前端）
   ↓
Phase 6  配置（SELF_HOST_URL）+ remote 改名
   ↓
Phase 5  不重试（独立一笔，可跳过/可回滚）
```

Phase 1-3 是一个原子批次；Phase 5 单独一笔提交，便于回滚。

---

## 十四、待你确认

1. **Phase 5（连接层不重试）做不做？** 做的话是全 fail-fast 还是只对 Connect 类？
   见 §八——收益是 8 分钟 → 2 分钟，代价是可能牺牲中转抖动的自愈。
2. **`SELF_HOST_URL` 要不要真的配上？** 也就是说：ECS 上跑的时候，你想让用户看到
   "可在你可控的网络中自行部署"这句吗？还是只要"本部署所在网络无法访问该服务"这一句诊断就够了？
   （见 §三——前者在面试场景是加分还是减分，是你的判断。）
3. **异常类名带不带？** 建议带短的（`ConnectTimeout`），便于搜索。

---

## 附：MCP 那半为什么这次不做

用户的诉求里提到了"比如刚才说的 mcp"。但这半现在**技术上做不到**：

mcp SDK 把协议层失败统一折叠成 `CancelledError`（上一轮已实测：喂两个完全不同的死 URL，
拿到的错误**逐字节相同**）。所以 `_fetch_remote` 现在分不出"端点不存在"和"网络抖动"——
想分类就得先在 [`mcp.py`](../src/myink/integrations/mcp.py) 层把底层异常捞出来，
可能要给 `McpClient` 包一层异常翻译。

加上扫榜功能本身已搁置（[`docs/RANKINGS-MCP-SWAP-PLAN.md`](RANKINGS-MCP-SWAP-PLAN.md)），
**建议等你想捡起扫榜时和换源一起做**。届时这半可以直接复用本次的 `errors.py`。

---

## 附二：原始诉求（原文留档）

> 当用户使用了因为网络问题而不可达的服务之后，比如刚才你说的 mcp，比如刚才说的国外模型，
> 检测到了之后都会提醒用户由于网络问题而不可达，如果需要的话可以到 github 上面我的这个
> 项目仓库地址去部署到本地使用。

本文与原文的三处偏离，均已在上文说明理由：① 不叫"网络问题"而叫"本部署所在网络无法访问"
（§一）；② 统一提示会把密钥错/模型名错也误导进来，故改为分层（§1.1、§十二）；
③ 自部署指引由配置控制，避免本地部署时自相矛盾（§三）。
