# 短篇建书 v2 + 文风库模块 + 短篇工作台收口 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把短篇建书改成「聊天 → 服务端判定齐备 → 冒出开始建书 → 弹出可编辑方案卡 → 确认即开写」的三段式，把文风独立成顶层模块（与环境配置/主题同级），长短篇建书改为选文风标签，短篇工作台去掉长篇残留的右栏，并修掉上一轮遗留的 M-1 ~ M-10。

**Architecture:** 后端只做三件事——补一个 `PATCH /style-library/{item_id}`、把文风解析抽成共享函数供短篇 `commit` 与长篇建书两处调用、改写 `SYSTEM_SHORT_CREATION` 提示词。建书状态机（`ready`）与 `commit` 端点形状**完全不变**：三段式是纯前端呈现。短篇「确认即开写」由前端在 `commit` 成功后紧接着调既有的 `POST /projects/{id}/short/generate`，不入队逻辑不搬到后端。扫榜只拆「MCP 探针」这一条线，`integrations/mcp.py` 原样保留。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 / PostgreSQL(pgvector, RLS) / pytest；React 19 / react-router 7 / vitest 4 / oxlint / CSS Modules。

**Spec:** `docs/superpowers/specs/2026-09-24-short-creation-v2-design.md`

## Global Constraints

- **只改短篇。** 长篇本轮唯一的改动是建书第①步多一个「文风（可选）」下拉；长篇的设定页 / 大纲页 / 工作台一行不动。
- **`integrations/mcp.py` 不删**（`McpClient` / `McpError` 保留，以后接别的 MCP 工具）。只拆扫榜那条 MCP 线：配置字段 `mcp_url`、探针端点 `POST /environment/test-rankings`、前端地址输入与按钮。
- **`spec/api-openapi.json` 必须与 `app.openapi()` 字节一致**（`tests/test_api_contract.py`）。任何改了路径/体形状的后端任务，**在提交前的最后一步**跑 `myink contract export` 并把它一起提交。
- **后端验证口径**：先 `source .local/env-test.sh`，用 conda `aiink` 的解释器（`$MYINK_PY`）。集成测试需要隔离的 PostgreSQL/Redis/RabbitMQ（`myink-auth-test` 栈）。
- **前端真类型闸是 `npm run build`（`tsc -b && vite build`），不是 `npx tsc --noEmit`**（后者对着 solution 式 tsconfig 是假绿）。
- **禁止 `git add .`**：`.superpowers/` 与 `gateway/` 未被 `.gitignore` 覆盖。一律显式路径 stage，提交前核 `git diff --cached --name-status`。
- **公开侧去痕**：README / docs / 代码注释 / commit message 里不得出现「面试」「interview」，也不得出现参照对象的项目名；参照 `inkos/` 源码时只在本地读，不把它的名字写进仓库。
- **后端不新增文件。**
- 每个任务末尾提交，并按用户授权 `git push` 到 `origin/main`。
- 短篇形态参数与后端同规：章数 1–10、每章字数 1000–8000、全篇 ≤ 20000 字。

## Review Focus

以下五类输入/失败模式在 spec 里被隐含，但没有一个任务的测试会自然覆盖；每个任务在自己的步骤里把对应测试写进去。

1. **文风档案的键值形状五花八门。** 内置预设、提取草稿、统计层（`sentence_len_dist` 是嵌套 dict、`frequent_words` 是字符串数组）都会进同一个渲染器。渲染器遇到非预期类型既不能崩，也不能丢掉用户没碰过的键。
2. **在已确认过的旧会话上打开 `/short/new`。** `data.session.status !== 'active'` 时，状态机不能把「开始建书」选项或方案卡摆出来，也不能让用户误以为还能再写一篇。
3. **确认后入队失败。** 书已建、方案已落，但 `POST /projects/{id}/short/generate` 因 429/502/网络失败——用户必须能在工作台重试，而不是卡在一个既没在写又没入口的状态。
4. **中文输入法组合态下的 Enter。** 拼音候选未上屏时按 Enter 是选词，不是发送。
5. **长篇建书不传 `style_item_id`**（老客户端、或走题材包 `primary_id`）时，`project_settings` 的行为必须与今天逐字节一致。

---

## 文件结构

**后端改动（无新增文件）**

| 文件 | 责任 |
| --- | --- |
| `src/myink/config.py` | 去掉 `rankings_mcp_url` 设置项 |
| `src/myink/environment.py` | 扫榜默认值与合并逻辑去掉 `mcp_url` |
| `src/myink/api/routes_environment.py` | `RankingsBody` 去 `mcp_url`；删探针端点 |
| `src/myink/api/schemas.py` | 删 `RankingsProbeOut` |
| `src/myink/api/routes_style_library.py` | 新增 `PATCH /style-library/{item_id}` |
| `src/myink/api/routes_style.py` | 新增 `resolve_style_selection`（文风解析唯一实现） |
| `src/myink/api/routes_book.py` | `CreateProjectBody.style_item_id` + 建书时落文风 |
| `src/myink/api/routes_short_creation.py` | 改用共享解析函数；`commit` 第 4 步加会话存在守卫；`reset` 连带删孤儿草稿书 |
| `src/myink/short/creation.py` | `_known` 加 `math.isfinite` 守卫 + 文本字段只收 `str` |
| `src/myink/workflow/prompts.py` | `SYSTEM_SHORT_CREATION` 从问卷机改成合作者 |
| `src/myink/api/routes_admin.py` | 新增 `GET /admin/users/{user_id}`；`overview` 加归属过滤 |
| `.env.example` / `docs/DEPLOY.md` | 配置去行 / 部署补一行 |
| `spec/api-openapi.json` | 每次后端形状变更后重导出 |

**前端改动**

| 文件 | 责任 |
| --- | --- |
| `web/src/pages/StyleLibraryPage.tsx` + `.module.css` + `.test.tsx`（新增） | 文风库顶层页：列表 + 编辑 + 粘文章提取 |
| `web/src/router.tsx` | 加 `/styles` |
| `web/src/components/ProjectRail.tsx` | 全局设置分区加「文风库」 |
| `web/src/lib/styleLibraryApi.ts` | 加 `patch` |
| `web/src/pages/EnvironmentPage.tsx` + `.test.tsx` | 扫榜区去 MCP |
| `web/src/pages/ShortCreationPage.tsx` + `.module.css` + `.test.tsx` | 三段式 + 回车发送 + 去内联导入 |
| `web/src/pages/NewProjectPage.tsx` + `.test.tsx` | 第①步文风下拉 |
| `web/src/pages/WorkspacePage.tsx` + `.module.css` + `.test.tsx` | 短篇去右栏 + 状态带 + 续写触发迁移 + 审稿并中栏 |
| `web/src/pages/admin/UserDetail.tsx` | 改用 `getUser`，404 显示「用户不存在」 |
| `web/src/lib/api.ts` / `lib/adminApi.ts` / `types.ts` | 删 `testRankings`、加 `getUser`、类型增删 |

## 任务总览

| # | 工作块 | 交付物 |
| --- | --- | --- |
| 1 | 扫榜去 MCP | 后端删字段与探针端点 + 契约重导出 |
| 2 | 扫榜去 MCP | 前端扫榜区去 MCP |
| 3 | 文风库 | `PATCH /style-library/{item_id}` |
| 4 | 文风库 | `styleLibraryApi.patch` + 类型 |
| 5 | 文风库 | `StyleLibraryPage` 组件与样式 |
| 6 | 文风库 | 路由 + 左栏入口 |
| 7 | 文风库 | `StyleLibraryPage` 测试 |
| 8 | 建书选文风 | 抽 `resolve_style_selection` 并让短篇 `commit` 改用它（纯重构） |
| 9 | 建书选文风 | `CreateProjectBody.style_item_id` + 大类建书落文风 + 契约 |
| 10 | 建书选文风 | `NewProjectPage` 文风下拉 |
| 11 | 建书选文风 | `ShortCreationPage` 去内联导入，只留选择器 |
| 12 | 三段式 | `SYSTEM_SHORT_CREATION` 改写 |
| 13 | 三段式 | `ShortCreationPage` 状态机（含回车发送、选项、确认即开写） |
| 14 | 工作台收口 | 短篇去右栏 + 状态带 + 续写触发迁移 + 审稿并中栏 |
| 15 | 遗留缺陷 | M-8 `GenerationPanel` 依赖警告 |
| 16 | 遗留缺陷 | M-1 端点级测试补真 RED |
| 17 | 遗留缺陷 | M-2 / M-4 `_known` 数值与文本守卫 |
| 18 | 遗留缺陷 | M-3 `commit` 会话存在守卫 |
| 19 | 遗留缺陷 | M-6 `reset` 连带删孤儿草稿书 |
| 20 | 遗留缺陷 | M-7 `GET /admin/users/{user_id}` 全链路 + 契约 |
| 21 | 遗留缺陷 | M-9 `overview` 归属过滤 |
| 22 | 遗留缺陷 | M-10 部署文档补一行 |

M-5（`plan_warning` 到了工作台被丢弃）在任务 14 里落地。

---

### Task 1: 扫榜后端去掉 MCP 字段与探针端点

**Files:**
- Modify: `src/myink/config.py:131-132`
- Modify: `src/myink/environment.py:18,31-33`
- Modify: `src/myink/api/routes_environment.py:18,36,50-51,61-63,170-189`
- Modify: `src/myink/api/schemas.py:284-289`
- Modify: `tests/test_environment_routes.py:35,45-46,56,146-149,221-237`
- Modify: `.env.example`
- Regenerate: `spec/api-openapi.json`

**Interfaces:**
- Consumes: 无（本任务独立）
- Produces: `get_environment()["rankings"]` 只剩 `{"enabled","timeout","limit"}`（任务 2 的前端类型要与此对齐）。`POST /api/v1/environment/test-rankings` 与 `RankingsProbeOut` 从此不存在。

- [ ] **Step 1: 把测试改成断言「没有 mcp_url」**

`tests/test_environment_routes.py` 四处改动：

`test_environment_roundtrip_models_and_rankings`（:30-63）——删掉 :35 那一行，payload 去掉 `mcp_url`，:56 改成断言它不在：

```python
def test_environment_roundtrip_models_and_rankings(temp_user):
    empty = get_environment(user_id=temp_user)
    assert empty["model_routes"] == {}
    assert empty["model_connections"] == []
    assert empty["thinking_enabled"] is False
    assert empty["rankings"]["enabled"] is True
    assert "mcp_url" not in empty["rankings"]

    cid = str(uuid.uuid4())
    out = put_environment(EnvironmentBody(
        model_connections=[ModelConnectionBody(
            id=cid, name="私有 OpenAI", protocol="openai",
            base_url="https://models.example.com/v1/", model="novel-pro",
            api_key="secret-value",
        )],
        model_routes={"writer": f"custom:{cid}"},
        rankings={"enabled": False, "timeout": 8, "limit": 5},
    ), user_id=temp_user)

    assert out["model_routes"] == {"writer": f"custom:{cid}"}
    assert out["model_connections"] == [{
        "id": cid, "name": "私有 OpenAI", "protocol": "openai",
        "base_url": "https://models.example.com/v1", "model": "novel-pro",
        "input_price": None, "output_price": None, "has_api_key": True,
    }]
    assert out["rankings"] == {"enabled": False, "timeout": 8, "limit": 5}

    with new_session() as db:
        stored = db.get(User, uuid.UUID(temp_user)).environment
        encrypted = stored["models"][CONNECTIONS_KEY][cid]["api_key_encrypted"]
    assert decrypt_api_key(encrypted) == "secret-value"
```

删掉 `test_environment_save_rejects_non_global_rankings_url`（:146-149）整个函数——没有用户可控 URL 了，这条校验随之消失。

删掉 `test_rankings_probe_reports_tools`（:221-237）整个函数。

- [ ] **Step 2: 跑测试，确认它红**

```bash
source .local/env-test.sh
"$MYINK_PY" -m pytest tests/test_environment_routes.py -q
```

Expected: FAIL。`test_environment_roundtrip_models_and_rankings` 在 `assert "mcp_url" not in empty["rankings"]` 上失败（现在 `mcp_url` 还在）。若 `RankingsProbeBody` 的删除让文件无法 import，那是下一步的事。

- [ ] **Step 3: 后端实现**

`src/myink/config.py` 删掉这两行：

```python
    rankings_mcp_url: str = field(default_factory=lambda: _env(
        "RANKINGS_MCP_URL", "https://daosearch.io/api/mcp") or "https://daosearch.io/api/mcp")
```

`src/myink/environment.py` 的 `default_rankings()` 去掉 `"mcp_url": settings.rankings_mcp_url,` 一项；`merge_rankings` 去掉这四行：

```python
    mcp_url = raw.get("mcp_url")
    if isinstance(mcp_url, str) and mcp_url.strip():
        base["mcp_url"] = mcp_url.strip()
```

（存量用户环境 JSON 里残留的 `mcp_url` 键会被自然忽略，不做迁移。）

`src/myink/api/routes_environment.py`：

- :18 的 import 去掉 `RankingsProbeOut`（`McpClient, McpError` 的 import 也一并删——本文件不再用；**模块本身保留**）。
- `RankingsBody`（:33-37）去掉 `mcp_url: str | None = None`。
- `_validate_rankings`（:59-63）去掉整个 `if body.mcp_url is not None:` 分支。
- 删掉 `RankingsProbeBody`（:50-51）与 `POST /environment/test-rankings` 端点（:170-189，含 `@router.post` 装饰器与函数体）。
- 删完检查 `asyncio` 与 `settings` 这两个 import 是否变成未使用——是则删。

`src/myink/api/schemas.py` 删掉：

```python
class RankingsProbeOut(BaseModel):
    ...
```

`.env.example` 删掉 `RANKINGS_MCP_URL=...` 行及其上方的 MCP 注释行；`RANKINGS_ENABLED` / `RANKINGS_TIMEOUT` / `RANKINGS_LIMIT` / `RANKINGS_CACHE_TTL` 保留。

- [ ] **Step 4: 跑测试，确认它绿**

```bash
"$MYINK_PY" -m pytest tests/test_environment_routes.py tests/test_rankings_mcp.py -q
```

Expected: PASS。`test_rankings_mcp.py` 一并跑：它测的是 `McpClient` 与榜单服务（都还在），一个用例都不该受影响。

若 `routes_environment.py` 里还有别处引用 `McpClient`，改成别的探针时不要顺手删——`integrations/mcp.py` 保留。

- [ ] **Step 5: 重导出契约并跑契约测试**

```bash
"$MYINK_PY" -m myink contract export
"$MYINK_PY" -m pytest tests/test_api_contract.py -q
```

Expected: PASS。`spec/api-openapi.json` 里 `test-rankings` 路径消失。

- [ ] **Step 6: 全量后端回归 + 提交 + 推送**

```bash
"$MYINK_PY" -m pytest tests/ -q
git status --short
git add src/myink/config.py src/myink/environment.py src/myink/api/routes_environment.py \
        src/myink/api/schemas.py tests/test_environment_routes.py .env.example spec/api-openapi.json
git diff --cached --name-status
git commit -m "refactor: 扫榜配置去掉已废弃的 MCP 探针（客户端保留待接其他 MCP 工具）"
git push
```

Expected: 全套测试绿；`git diff --cached --name-status` 只有上面六个路径；push 成功。

---

### Task 2: 前端扫榜区去掉 MCP

**Files:**
- Modify: `web/src/types.ts:403-434`
- Modify: `web/src/lib/api.ts:321-322`（删 `testRankings`）与 :412 附近把扫榜说成 MCP Client 的注释
- Modify: `web/src/pages/EnvironmentPage.tsx:44-48,67,263-320,474-556`
- Modify: `web/src/pages/EnvironmentPage.test.tsx:19-27,176-199`

**Interfaces:**
- Consumes: 任务 1 的端点已不存在；`get_environment` 的 `rankings` 只有三个键。
- Produces: `RankingsConfig` = `{enabled, timeout, limit}`（无 `mcp_url`）。

- [ ] **Step 1: 改测试**

`web/src/pages/EnvironmentPage.test.tsx` 的 `emptyEnv`（:19-27）里 `rankings` 改成：

```ts
    rankings: { enabled: true, timeout: 10, limit: 10 },
```

把 `'saves rankings config and tests MCP connectivity'`（:176-199）整条替换成一条只测保存的用例：

```tsx
  it('saves the rankings config without any MCP field', async () => {
    renderPage()
    const timeout = await screen.findByLabelText('扫榜超时（秒）')
    fireEvent.change(timeout, { target: { value: '8' } })
    fireEvent.click(screen.getByRole('button', { name: '保存扫榜配置' }))
    await waitFor(() => expect(api.updateEnvironment).toHaveBeenCalled())
    expect(vi.mocked(api.updateEnvironment).mock.calls[0][0]).toEqual({
      rankings: { enabled: true, timeout: 8, limit: 10 },
    })
  })

  it('has no MCP address input or probe button', async () => {
    renderPage()
    await screen.findByRole('heading', { name: '扫榜' })
    expect(screen.queryByLabelText('MCP 地址')).toBeNull()
    expect(screen.queryByRole('button', { name: '测试 MCP 连接' })).toBeNull()
  })
```

（`renderPage` 与现有用例同款；标签文案以本任务第 3 步实现里的 `aria-label` 为准。若现有用例用的是别的挂载 helper，沿用现有的。）

- [ ] **Step 2: 跑测试，确认它红**

```bash
cd web && npm test -- src/pages/EnvironmentPage.test.tsx
```

Expected: FAIL——`扫榜超时（秒）` 这个 label 现在还不叫这个名字（或者说：`保存扫榜配置` 的载荷里还带 `mcp_url`），且 `MCP 地址` 输入框仍然存在。

- [ ] **Step 3: 前端实现**

`web/src/types.ts`：

```ts
export interface RankingsConfig {
  enabled: boolean
  timeout: number
  limit: number
}

export interface RankingsConfigInput {
  enabled?: boolean
  timeout?: number
  limit?: number
}
```

删掉 `RankingsProbeRequest` 与 `RankingsProbeResult` 两个接口（:425-434）。若 `EnvironmentSettings` 别处引用了它们，一并清掉。

`web/src/lib/api.ts` 删掉 `testRankings`（:321-322），并把 :412 附近那条把扫榜描述成 MCP Client 的注释改成如实描述（数据来自番茄榜单，不进记忆层）。

`web/src/pages/EnvironmentPage.tsx`：

- `EMPTY_RANKINGS` 改成 `{ enabled: true, timeout: 10, limit: 10 }`。
- 删 `rankProbe` 状态、`testRankings` 调用函数、`saveRankings` 里的 URL 校验分支（现在只校验超时/条数的数值区间）。
- 渲染区：`<h2>扫榜</h2>` 保留；删 `<h3>MCP 服务</h3>` 分隔、`MCP 地址` 输入框、`测试 MCP 连接` 按钮与 `rankProbe.text`。超时输入加 `aria-label="扫榜超时（秒）"`。说明文案改成「数据来自番茄榜单，只作建书前灵感，不进记忆层。」
- 保存按钮文案保持「保存扫榜配置」，`rankMsg` 保留。

- [ ] **Step 4: 跑测试与类型闸**

```bash
cd web && npm test -- src/pages/EnvironmentPage.test.tsx && npm run lint && npm run build
```

Expected: PASS / 无 error / 构建成功。`npm run build` 是真正的类型闸——`RankingsProbeResult` 的残留引用会在这里暴露。

- [ ] **Step 5: 提交 + 推送**

```bash
git add web/src/types.ts web/src/lib/api.ts web/src/pages/EnvironmentPage.tsx \
        web/src/pages/EnvironmentPage.test.tsx
git diff --cached --name-status
git commit -m "refactor: 环境配置的扫榜区去掉 MCP 地址与探针按钮"
git push
```

---

### Task 3: `PATCH /style-library/{item_id}`

**Files:**
- Modify: `src/myink/api/routes_style_library.py`
- Modify: `src/myink/api/schemas.py`（新增 `StyleLibraryPatchBody`）
- Modify: `tests/test_style_library.py`
- Regenerate: `spec/api-openapi.json`

**Interfaces:**
- Consumes: 现有 `POST ""` 里的重名检查（409 `NAME_TAKEN`）与 `name.strip()` 为空 → 400。
- Produces: `PATCH /api/v1/style-library/{item_id}`，体 `{"name"?: str, "note"?: str}`，返回与 `POST` 同形状的 item。任务 4 的前端 `patch` 依赖它。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_style_library.py` 末尾：

```python
def test_patch_renames_and_edits_note(temp_user):
    created = client.post("/api/v1/style-library",
                          json={"name": "渡口冷白描", "profile": {"pov": "限知"}, "sample_chars": 10},
                          headers=identity_headers(temp_user))
    item_id = created.json()["id"]
    out = client.patch(f"/api/v1/style-library/{item_id}",
                       json={"name": "渡口白描", "note": "冷、短句"},
                       headers=identity_headers(temp_user))
    assert out.status_code == 200, out.text
    assert out.json()["name"] == "渡口白描"
    assert out.json()["note"] == "冷、短句"
    items = client.get("/api/v1/style-library", headers=identity_headers(temp_user)).json()["items"]
    assert [i["name"] for i in items if not i["builtin"]] == ["渡口白描"]


def test_patch_rejects_a_duplicate_name(temp_user):
    body = {"name": "渡口冷白描", "profile": {"pov": "限知"}, "sample_chars": 10}
    client.post("/api/v1/style-library", json=body, headers=identity_headers(temp_user))
    second = client.post("/api/v1/style-library",
                         json={**body, "name": "另一档"}, headers=identity_headers(temp_user))
    again = client.patch(f"/api/v1/style-library/{second.json()['id']}", json={"name": "渡口冷白描"},
                         headers=identity_headers(temp_user))
    assert again.status_code == 409
    assert again.json()["detail"] == "NAME_TAKEN"


def test_patch_rejects_a_blank_name_and_a_stranger(temp_user):
    created = client.post("/api/v1/style-library",
                          json={"name": "渡口", "profile": {}, "sample_chars": 0},
                          headers=identity_headers(temp_user))
    item_id = created.json()["id"]
    assert client.patch(f"/api/v1/style-library/{item_id}", json={"name": "   "},
                        headers=identity_headers(temp_user)).status_code == 400
    assert client.patch("/api/v1/style-library/builtin:xianxia-jiuzhou", json={"name": "改内置"},
                        headers=identity_headers(temp_user)).status_code == 404
    assert client.patch(f"/api/v1/style-library/{uuid.uuid4()}", json={"name": "别人的"},
                        headers=identity_headers(temp_user)).status_code == 404


def test_patch_only_touches_the_supplied_fields(temp_user):
    created = client.post("/api/v1/style-library",
                          json={"name": "渡口", "profile": {"pov": "限知"},
                                "note": "原备注", "sample_chars": 42},
                          headers=identity_headers(temp_user))
    item_id = created.json()["id"]
    out = client.patch(f"/api/v1/style-library/{item_id}", json={"name": "渡口二"},
                       headers=identity_headers(temp_user))
    assert out.status_code == 200, out.text
    assert out.json()["note"] == "原备注", "没传的字段不动"
    assert out.json()["profile"] == {"pov": "限知"}, "档案不随重命名被清空"
    assert out.json()["sample_chars"] == 42
```

- [ ] **Step 2: 跑测试，确认它红**

```bash
source .local/env-test.sh
"$MYINK_PY" -m pytest tests/test_style_library.py -q -k patch
```

Expected: FAIL / 4 条都是 405 Method Not Allowed（路由还没有 PATCH）。

- [ ] **Step 3: 实现**

`src/myink/api/schemas.py` 加：

```python
class StyleLibraryPatchBody(BaseModel):
    """改名 / 改备注。没传的字段不动（None 与「没传」区分开）。"""

    name: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=200)
```

`src/myink/api/routes_style_library.py` 加端点（沿用本文件既有的 `self._item_out` / 重名查询写法；下面是等价逻辑）：

```python
@router.patch("/{item_id}", response_model=StyleLibraryItemOut)
def patch_item(item_id: str, body: StyleLibraryPatchBody,
               user_id: str = Depends(require_user)) -> dict:
    uid = uuid.UUID(user_id)
    try:
        target = uuid.UUID(item_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="NOT_FOUND") from None
    with new_session() as db:
        item = db.scalar(select(StyleLibraryItem).where(
            StyleLibraryItem.id == target, StyleLibraryItem.user_id == uid))
        if item is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="文风名不能为空")
            taken = db.scalar(select(StyleLibraryItem.id).where(
                StyleLibraryItem.user_id == uid, StyleLibraryItem.name == name,
                StyleLibraryItem.id != item.id))
            if taken is not None:
                raise HTTPException(status_code=409, detail="NAME_TAKEN")
            item.name = name
        if body.note is not None:
            item.note = body.note.strip()
        db.commit()
        return _item_out(item)
```

（`_item_out` 是本文件已有的私有序列化函数；`uuid` / `select` / `HTTPException` / `Depends` / `require_user` 都已在 import 里。）

- [ ] **Step 4: 跑测试，确认它绿**

```bash
"$MYINK_PY" -m pytest tests/test_style_library.py -q
```

Expected: PASS（本文件全部用例）。

- [ ] **Step 5: 契约 + 全量 + 提交 + 推送**

```bash
"$MYINK_PY" -m myink contract export
"$MYINK_PY" -m pytest tests/ -q
git add src/myink/api/routes_style_library.py src/myink/api/schemas.py \
        tests/test_style_library.py spec/api-openapi.json
git diff --cached --name-status
git commit -m "feat: 文风库支持改名与改备注"
git push
```

---

### Task 4: 前端 `styleLibraryApi.patch` 与类型

**Files:**
- Modify: `web/src/lib/styleLibraryApi.ts`

**Interfaces:**
- Consumes: 任务 3 的端点。
- Produces: `styleLibraryApi.patch(token, id, body)`，`body: {name?: string; note?: string}` → `Promise<StyleLibraryItem>`。任务 5 与 7 依赖它。

- [ ] **Step 1: 写失败测试**

新建 `web/src/lib/styleLibraryApi.test.ts`：

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { styleLibraryApi } from './styleLibraryApi'

const request = vi.fn()
vi.mock('./api', () => ({ request: (...args: unknown[]) => request(...args) }))

describe('styleLibraryApi', () => {
  beforeEach(() => request.mockReset())

  it('patches a rename through the item path', async () => {
    request.mockResolvedValue({ id: 'abc', name: '渡口白描', builtin: false })
    await styleLibraryApi.patch('tok', 'abc', { name: '渡口白描' })
    expect(request).toHaveBeenCalledWith('PATCH', '/style-library/abc', { name: '渡口白描' })
  })
})
```

（若本仓库的 `lib/*.ts` 现有测试是别的 mock 形状——例如 `lib/api.short.test.ts` 那样 spy 在 `api` 对象上——沿用现有那种写法，别为此引入第二种风格。）

- [ ] **Step 2: 跑测试，确认它红**

```bash
cd web && npm test -- src/lib/styleLibraryApi.test.ts
```

Expected: FAIL——`styleLibraryApi.patch is not a function`。

- [ ] **Step 3: 实现**

`web/src/lib/styleLibraryApi.ts` 的 `styleLibraryApi` 对象里加：

```ts
  patch: (token: string, id: string, body: { name?: string; note?: string }) =>
    request<StyleLibraryItem>('PATCH', `/style-library/${id}`, body, token),
```

（`token` 位置与参数形状照本文件其他方法：`request` 的签名以 `lib/api.ts` 为准，`lib/*Api.ts` 的路径**不带** `/api/v1` 前缀。）

- [ ] **Step 4: 跑测试与类型闸**

```bash
cd web && npm test -- src/lib/styleLibraryApi.test.ts && npm run build
```

Expected: PASS / 构建成功。

- [ ] **Step 5: 提交 + 推送**

```bash
git add web/src/lib/styleLibraryApi.ts web/src/lib/styleLibraryApi.test.ts
git commit -m "feat: 文风库 API 客户端补上改名接口"
git push
```

---

### Task 5: `StyleLibraryPage` 组件与样式

**Files:**
- Create: `web/src/pages/StyleLibraryPage.tsx`
- Create: `web/src/pages/StyleLibraryPage.module.css`

**Interfaces:**
- Consumes: `styleLibraryApi.list/extract/save/patch/remove`、`StyleLibraryItem`、`StyleDraft`。
- Produces: `export default function StyleLibraryPage()`（任务 6 挂路由，任务 7 写测试）。渲染时必须有这些可测的锚点：`role="list"` 的文风列表、`aria-label="文风名"`、`aria-label="备注"`、`aria-label="粘贴文章"`、`aria-label="提取文风"`、`aria-label="保存文风"`、`aria-label="重命名"`、`aria-label="删除文风"`、以及档案区每个键的 `aria-label={键名}`。

页面版式照 `AppearancePage`：`div.wrap` + `<ProjectRail>` + `main.main` + `h1` 标题 + 返回链接。左列列表（内置在前、我的在后，与后端返回顺序一致），右列详情/编辑。

档案编辑器是**通用键值**渲染，规则固定三条：

```tsx
/** 档案里每个键按值的形状给一种控件；嵌套对象只读展示（那是统计层的中间结果，不该手改）。 */
function ProfileField({ label, value, onChange }: {
  label: string; value: unknown; onChange: (next: unknown) => void
}) {
  if (Array.isArray(value) && value.every((v) => typeof v === 'string')) {
    return (
      <label>
        <span>{label}</span>
        <textarea className="input" rows={3} aria-label={label} value={value.join('\n')}
                  onChange={(e) => onChange(e.target.value.split('\n').filter((line) => line.trim() !== ''))} />
      </label>
    )
  }
  if (typeof value === 'number') {
    return (
      <label>
        <span>{label}</span>
        <input className="input" type="number" aria-label={label} value={value}
               onChange={(e) => onChange(e.target.value === '' ? 0 : Number(e.target.value))} />
      </label>
    )
  }
  if (typeof value === 'string') {
    return (
      <label>
        <span>{label}</span>
        <textarea className="input" rows={2} aria-label={label} value={value}
                  onChange={(e) => onChange(e.target.value)} />
      </label>
    )
  }
  return (
    <div className={styles.readonly}>
      <span>{label}</span>
      <code>{JSON.stringify(value)}</code>
    </div>
  )
}
```

- `profile` 用 `Record<string, unknown>` 存；`onChange` 只替换那一个键（`{...profile, [key]: next}`），**不碰别的键**。
- 保存按钮在「我的」项上，调 `patch(token, id, {name, note})`；档案改动走 `save`（新建）或 `patch`（既然 `PATCH` 不收 `profile`，改档案要另走一条：把档案一并放进新建流的 `save`；对已有项，档案编辑只在「我的」项上启用，保存时用 `save` 的兄弟路径——**本任务采用的做法是：档案编辑只对新建流开放，已有项只允许改名与改备注，避免为改档案再开一个端点**）。这条要写进组件顶部注释。
- `删除文风` 二次确认用 `window.confirm`；`item.builtin || !item.removable` 的项不渲染删除按钮。
- 新建区：`粘贴文章` textarea → `提取文风` 按钮 → 提取出的草稿用同一个 `ProfileField` 渲染（可改）→ `文风名` 输入 → `保存文风`。`draft.extract_error` 存在时在草稿上方渲染 `role="alert"` 的降级提示。

**写法约定：** `<summary>` 里的嵌套 dict 用 `.readonly` 样式；`ProfileField` 的每个控件都要 `aria-label`（键名），否则任务 7 的测试没有稳定锚点。

- [ ] **Step 1: 建 `.module.css`**

```css
.page { height: 100%; display: flex; }
.wrap { flex: 1; min-width: 0; display: grid; grid-template-columns: minmax(180px, 260px) minmax(0, 1fr); gap: 16px; height: 100%; min-height: 0; }
.list { display: flex; flex-direction: column; gap: 4px; min-height: 0; overflow-y: auto; }
.groupTitle { font-size: 0.8em; opacity: 0.7; margin-top: 8px; }
.item { text-align: left; padding: 6px 8px; border-radius: 8px; border: 1px solid transparent; background: none; cursor: pointer; }
.itemOn { border-color: var(--accent, #66f); }
.detail { display: flex; flex-direction: column; gap: 8px; min-height: 0; overflow-y: auto; }
.detail label { display: flex; flex-direction: column; gap: 2px; font-size: 0.85em; }
.readonly { display: flex; flex-direction: column; gap: 2px; font-size: 0.85em; opacity: 0.8; }
.readonly code { font-size: 0.9em; word-break: break-all; }
.actions { display: flex; gap: 8px; }
.newBox { display: flex; flex-direction: column; gap: 6px; padding: 8px; border: 1px solid var(--line, #ddd); border-radius: 8px; }
@media (max-width: 900px) { .wrap { grid-template-columns: minmax(0, 1fr); } }
```

- [ ] **Step 2: 写页面组件**

`web/src/pages/StyleLibraryPage.tsx`，结构如下（`ProfileField` 如上）：

```tsx
/** 账号级文风库：内置 4 套只读可复制，我的档可新建/改名/改备注/删除。
 *
 * 档案形状沿用 StyleProfile（与 project_settings.style_profile 同构），库里取出来直接
 * 写进书，不需要转换。已有项只允许改名与改备注——档案改动只走新建流，避免为改档案
 * 再开一个端点。
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { useGuest } from '../hooks/useGuest'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import { styleLibraryApi, type StyleLibraryItem } from '../lib/styleLibraryApi'
import type { Project } from '../types'
import styles from './StyleLibraryPage.module.css'

export default function StyleLibraryPage() {
  const { session, logout } = useAuth()
  const guest = useGuest()
  const token = session?.token ?? ''
  const [projects, setProjects] = useState<Project[]>([])
  const [items, setItems] = useState<StyleLibraryItem[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [note, setNote] = useState('')
  const [newOpen, setNewOpen] = useState(false)
  const [sampleText, setSampleText] = useState('')
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  // ... 其余实现照上面 InterFace 里列出的行为与锚点
}
```

（列表分「内置」「我的」两组；选中项把 `name` / `note` 灌进编辑态；`run` 包装器与 `ShortCreationPage.tsx:110-120` 同款；`guest` 时 `projects` 置空。`ProfileField` 定义在同文件下部。）

- [ ] **Step 3: 自查**

```bash
cd web && npm run lint && npm run build
```

Expected: 无 error、构建成功。若 `oxlint` 报 `react-hooks/exhaustive-deps`，按依赖补齐，不加 disable 注释。

- [ ] **Step 4: 提交 + 推送**

```bash
git add web/src/pages/StyleLibraryPage.tsx web/src/pages/StyleLibraryPage.module.css
git commit -m "feat: 新增文风库页面（列表 + 编辑 + 粘文章提取）"
git push
```

---

### Task 6: 文风库入路由与左栏

**Files:**
- Modify: `web/src/router.tsx:13-21`（import）与 `:82-84`（路由）
- Modify: `web/src/components/ProjectRail.tsx:88-103`
- Modify: `web/src/components/ProjectRail.test.tsx`

**Interfaces:**
- Consumes: 任务 5 的默认导出。
- Produces: `/styles` 路由；左栏全局设置分区里的「文风库」链接。

- [ ] **Step 1: 写失败测试**

`web/src/components/ProjectRail.test.tsx` 补一条（沿用本文件现有的挂载与内存路由写法）：

```tsx
  it('links to the style library from the global settings section', async () => {
    renderRail('/environment')
    expect(await screen.findByRole('link', { name: '文风库' })).toHaveAttribute('href', '/styles')
  })
```

（`renderRail` 是现有 helper 的名字占位——用本文件真实 helper。若尚无该 helper，就在 `createMemoryRouter` 的 routes 里补 `{ path: '/styles', element: <div/> }`，因为 `NavLink` 在无匹配路由时会抛错。）

- [ ] **Step 2: 跑测试，确认它红**

```bash
cd web && npm test -- src/components/ProjectRail.test.tsx
```

Expected: FAIL——找不到「文风库」链接。

- [ ] **Step 3: 实现**

`web/src/router.tsx` 加 import 与路由：

```tsx
import StyleLibraryPage from './pages/StyleLibraryPage'
```

```tsx
      { path: '/styles', element: <StyleLibraryPage /> },
```

放在 `{ path: '/theme', element: <AppearancePage /> },` 旁。

`web/src/components/ProjectRail.tsx` 的全局设置分区（`:88-103`，与环境配置、主题同级）加：

```tsx
        <NavLink to="/styles" className={({ isActive }) => isActive ? `${styles.item} ${styles.on}` : styles.item}>
          文风库
        </NavLink>
```

（`styles.item` / `styles.on` 用该分区现有的类名——环境配置那两条是怎么写的，就照抄。）

- [ ] **Step 4: 跑测试与类型闸**

```bash
cd web && npm test -- src/components/ProjectRail.test.tsx && npm run build
```

Expected: PASS / 构建成功。

- [ ] **Step 5: 提交 + 推送**

```bash
git add web/src/router.tsx web/src/components/ProjectRail.tsx web/src/components/ProjectRail.test.tsx
git commit -m "feat: 文风库进左栏全局设置并挂上 /styles 路由"
git push
```

---

### Task 7: `StyleLibraryPage` 测试

**Files:**
- Create: `web/src/pages/StyleLibraryPage.test.tsx`

**Interfaces:**
- Consumes: 任务 5 的组件与锚点；任务 4 的 `patch`。
- Produces: 无（测试是终点）。

- [ ] **Step 1: 写测试**

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import StyleLibraryPage from './StyleLibraryPage'
import { styleLibraryApi } from '../lib/styleLibraryApi'

vi.mock('../lib/api', () => ({ api: { listProjects: vi.fn().mockResolvedValue([]) } }))
vi.mock('../lib/styleLibraryApi', () => ({
  styleLibraryApi: { list: vi.fn(), extract: vi.fn(), save: vi.fn(), patch: vi.fn(), remove: vi.fn() },
}))
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ session: { token: 'tok' }, logout: vi.fn() }) }))
vi.mock('../hooks/useGuest', () => ({ useGuest: () => false }))

const BUILTIN = {
  id: 'builtin:xianxia-jiuzhou', name: '九州问天', builtin: true, removable: false,
  profile: { pov: '第三人称限知', forbidden: ['网络流行语'] }, note: '', sample_chars: 0,
  created_at: null,
}

beforeEach(() => {
  vi.mocked(styleLibraryApi.list).mockReset()
  vi.mocked(styleLibraryApi.extract).mockReset()
  vi.mocked(styleLibraryApi.save).mockReset()
  vi.mocked(styleLibraryApi.patch).mockReset()
})

function renderPage() {
  return render(<MemoryRouter><StyleLibraryPage /></MemoryRouter>)
}

describe('StyleLibraryPage', () => {
  it('lists the builtins first and renders their profile keys as editable fields', async () => {
    vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [BUILTIN] })
    renderPage()
    const entry = await screen.findByRole('button', { name: '九州问天' })
    fireEvent.click(entry)
    expect(await screen.findByLabelText('pov')).toHaveValue('第三人称限知')
    expect(await screen.findByLabelText('forbidden')).toHaveValue('网络流行语')
  })

  it('hides the delete action for a builtin', async () => {
    vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [BUILTIN] })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '九州问天' }))
    expect(screen.queryByRole('button', { name: '删除文风' })).toBeNull()
  })

  it('extracts a sample, lets the user name it, and saves it into the list', async () => {
    vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [] })
    vi.mocked(styleLibraryApi.extract).mockResolvedValue({
      draft: { pov: '第一人称', extract_error: '模型这一趟没成功' },
    })
    vi.mocked(styleLibraryApi.save).mockResolvedValue({
      id: 'new-1', name: '渡口白描', builtin: false, removable: true,
      profile: { pov: '第一人称' }, note: '', sample_chars: 12, created_at: '2026-09-24',
    })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '新建文风' }))
    fireEvent.change(screen.getByLabelText('粘贴文章'), { target: { value: '渡口的老人守着最后一班船。' } })
    fireEvent.click(screen.getByRole('button', { name: '提取文风' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('模型这一趟没成功')
    fireEvent.change(screen.getByLabelText('文风名'), { target: { value: '渡口白描' } })
    fireEvent.click(screen.getByRole('button', { name: '保存文风' }))
    await waitFor(() => expect(styleLibraryApi.save).toHaveBeenCalled())
    expect(vi.mocked(styleLibraryApi.save).mock.calls[0][1]).toMatchObject({
      name: '渡口白描', profile: { pov: '第一人称' },
    })
    expect(await screen.findByRole('button', { name: '渡口白描' })).toBeInTheDocument()
  })

  it('renames my own item through patch without touching its profile', async () => {
    const mine = { ...BUILTIN, id: 'mine-1', name: '旧名', builtin: false, removable: true }
    vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [mine] })
    vi.mocked(styleLibraryApi.patch).mockResolvedValue({ ...mine, name: '新名' })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '旧名' }))
    fireEvent.change(screen.getByLabelText('文风名'), { target: { value: '新名' } })
    fireEvent.click(screen.getByRole('button', { name: '重命名' }))
    await waitFor(() => expect(styleLibraryApi.patch).toHaveBeenCalledWith(
      'tok', 'mine-1', { name: '新名', note: '' }))
  })
})
```

**注意**：这里把「提取草稿里没被用户碰过的键」当成第 4 条 Review Focus 的落点——`profile` 断言的 `{pov: '第一人称'}` 里**不含** `extract_error`（它是瞬态诊断键，不该进 `save`）；如果实现把整份 draft 原样交出去，这条断言会红。

- [ ] **Step 2: 跑测试，确认它红**

```bash
cd web && npm test -- src/pages/StyleLibraryPage.test.tsx
```

Expected: FAIL。任务 5 的组件此时还没实现 `新建文风` / `重命名` 这些按钮的 `aria-label`（或者干脆还没有组件）。逐条把实现补齐到测试要的样子。

- [ ] **Step 3: 补实现使测试通过**

在本任务的步骤里改 `StyleLibraryPage.tsx`：加 `新建文风` 按钮、`重命名` 按钮、`删除文风` 按钮、`保存文风` 按钮，并在保存时把 `extract_error` 从 `profile` 里剔掉：

```tsx
  const { extract_error: _omit, ...profileForSave } = draft ?? {}
```

（`extract_error` 只用于页面上的降级提示，不落库——这条与后端 `PUT /style-projects` 剔除瞬态键的口径一致。）

- [ ] **Step 4: 跑测试与类型闸**

```bash
cd web && npm test -- src/pages/StyleLibraryPage.test.tsx && npm run lint && npm run build
```

Expected: PASS / 无 error / 构建成功。

- [ ] **Step 5: 提交 + 推送**

```bash
git add web/src/pages/StyleLibraryPage.test.tsx web/src/pages/StyleLibraryPage.tsx
git commit -m "test: 文风库页面的列表、提取、改名与内置保护"
git push
```

---

### Task 8: 抽出共享的文风解析函数（纯重构）

**Files:**
- Modify: `src/myink/api/routes_style.py`（新增 `resolve_style_selection`）
- Modify: `src/myink/api/routes_short_creation.py:130-153`（`_style_for` 改为转发）与 `:232-240`
- Modify: `tests/test_style_profile.py`（新增单元测试）

**Interfaces:**
- Consumes: `StyleLibraryItem`、`STYLE_PRESETS`。
- Produces: `resolve_style_selection(db, uid: uuid.UUID, item_id: str) -> tuple[dict, str | None, str]`，语义与今天 `_style_for` 完全一致（内置 key → `skill_pack=key`；库 item → `skill_pack=None`；查不到 → `HTTPException(404, "NOT_FOUND")`）。任务 9 的长篇建书依赖它。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_style_profile.py`：

```python
def test_resolve_style_selection_prefers_builtin_then_library(temp_user):
    from myink.api.routes_style import resolve_style_selection
    from myink.db import new_session
    from myink.models import StyleLibraryItem
    import uuid as _uuid

    with new_session() as db:
        uid = _uuid.UUID(temp_user)
        profile, skill_pack, name = resolve_style_selection(db, uid, "builtin:xianxia-jiuzhou")
        assert skill_pack == "xianxia-jiuzhou", "内置项 id 同时当 skill_pack 标记"
        assert name == "九州问天"
        item = StyleLibraryItem(user_id=uid, name="渡口白描", profile={"pov": "限知"}, sample_chars=10)
        db.add(item)
        db.commit()
        profile, skill_pack, name = resolve_style_selection(db, uid, str(item.id))
        assert profile == {"pov": "限知"}
        assert skill_pack is None
        assert name == "渡口白描"


def test_resolve_style_selection_404s_on_garbage(temp_user):
    from fastapi import HTTPException
    from myink.api.routes_style import resolve_style_selection
    from myink.db import new_session
    import uuid as _uuid
    import pytest as _pytest

    with new_session() as db:
        for bad in ("builtin:nope", "not-a-uuid", str(_uuid.uuid4())):
            with _pytest.raises(HTTPException) as exc:
                resolve_style_selection(db, _uuid.UUID(temp_user), bad)
            assert exc.value.status_code == 404
```

- [ ] **Step 2: 跑测试，确认它红**

```bash
source .local/env-test.sh
"$MYINK_PY" -m pytest tests/test_style_profile.py -q -k resolve
```

Expected: FAIL——`ImportError: cannot import name 'resolve_style_selection'`。

- [ ] **Step 3: 实现**

把 `routes_short_creation.py` 的 `_style_for` 函数体原样搬进 `routes_style.py`，改名并加公开 docstring：

```python
def resolve_style_selection(db, uid: uuid.UUID, item_id: str) -> tuple[dict, str | None, str]:
    """选择器的值 → (style_profile, skill_pack, 展示名)。短篇建书与长篇建书共用这一份。

    `builtin:<preset id>` 是内置预设（id 同时当 skill_pack 标记，与「题材包导入」同口径）；
    其他按文风库 item id 处理，且**只查自己名下的**——查不到给 404，不区分「不存在」与
    「是别人的」，免得拿 404/403 的差别当探测别人的库。
    """
    preset = next((p for p in STYLE_PRESETS
                   if item_id.startswith("builtin:") and p["id"] == item_id[len("builtin:"):]), None)
    if preset is not None:
        return dict(preset["style_profile"]), preset["id"], str(preset["name"])
    if item_id.startswith("builtin:"):
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    try:
        target = uuid.UUID(item_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="NOT_FOUND") from None
    item = db.scalar(select(StyleLibraryItem).where(
        StyleLibraryItem.id == target, StyleLibraryItem.user_id == uid))
    if item is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return dict(item.profile), None, item.name
```

`routes_style.py` 需要补 import：`from sqlalchemy import select` 与 `from myink.models import ProjectSettings, StyleLibraryItem`。

`routes_short_creation.py` 删掉 `_style_for` 整个函数，把 :233 的调用改成：

```python
            profile, skill_pack, style_name = resolve_style_selection(tdb, uid, style_item_id)
```

并在文件头部加 `from myink.api.routes_style import resolve_style_selection`。

**行为必须逐字节不变**——这是纯重构，任务 8 不许有任何可观测的行为变化。

- [ ] **Step 4: 跑测试，确认它绿（含回归）**

```bash
"$MYINK_PY" -m pytest tests/test_style_profile.py tests/test_short_creation.py tests/test_short_routes.py tests/test_style_library.py -q
```

Expected: PASS。短篇 `commit` 的既有用例一条都不许翻。

- [ ] **Step 5: 提交 + 推送**

```bash
git add src/myink/api/routes_style.py src/myink/api/routes_short_creation.py tests/test_style_profile.py
git diff --cached --name-status
git commit -m "refactor: 文风解析抽成共享函数，短篇建书与长篇建书同源"
git push
```

---

### Task 9: 长篇建书时选文风

**Files:**
- Modify: `src/myink/api/routes_book.py:111-129`（`CreateProjectBody`）与 `:277-299`（`create_project`）
- Modify: `tests/test_project_creation.py`
- Regenerate: `spec/api-openapi.json`

**Interfaces:**
- Consumes: 任务 8 的 `resolve_style_selection(db, uid, item_id)`。
- Produces: `POST /api/v1/projects` 收可选 `style_item_id: str | null`；给了就把它解析后写进同事务的 `project_settings.style_profile` / `skill_pack`。任务 10 的前端依赖它。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_project_creation.py`（沿用该文件现有的 `client` / `identity_headers` / `ensure_*` 惯例）：

```python
def test_create_project_writes_the_chosen_builtin_style(temp_user):
    resp = client.post("/api/v1/projects",
                       json={"title": "带文风的书", "style_item_id": "builtin:xianxia-jiuzhou"},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 200, resp.text
    pid = resp.json()["id"]
    with new_session() as db:
        st = db.scalar(select(ProjectSettings).where(ProjectSettings.project_id == uuid.UUID(pid)))
    assert st.skill_pack == "xianxia-jiuzhou"
    assert st.style_profile, "内置预设的档案要真写进去"


def test_create_project_without_style_item_id_keeps_settings_empty(temp_user):
    resp = client.post("/api/v1/projects", json={"title": "不带文风的书"},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 200, resp.text
    pid = resp.json()["id"]
    with new_session() as db:
        st = db.scalar(select(ProjectSettings).where(ProjectSettings.project_id == uuid.UUID(pid)))
    assert st is not None
    assert not st.style_profile and not st.skill_pack, "不传文风时与今天逐字节一致"


def test_create_project_rejects_a_stranger_style_item_id(temp_user):
    resp = client.post("/api/v1/projects",
                       json={"title": "坏文风的书", "style_item_id": str(uuid.uuid4())},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "NOT_FOUND"
```

- [ ] **Step 2: 跑测试，确认它红**

```bash
source .local/env-test.sh
"$MYINK_PY" -m pytest tests/test_project_creation.py -q -k style_item
```

Expected: FAIL。第一条：`style_item_id` 被 pydantic 忽略（`CreateProjectBody` 没有这个字段），`st.skill_pack` 是 NULL；第三条：返回 200 而不是 404。

- [ ] **Step 3: 实现**

`src/myink/api/routes_book.py`：

`CreateProjectBody` 加字段：

```python
    # 建书时选的文风（可选）。`builtin:<preset id>` 走内置预设，其他按账号文风库的 item id。
    # 传了就在同一事务里解析并写 project_settings；解析不到 → 404（与短篇建书同一份实现）。
    style_item_id: str | None = None
```

`create_project` 里，在 `_create_project_row` 之后、`db.commit()` 之前插入（注意 `_create_project_row` 内部已 `set_config('app.tenant_id', ...)`，所以这一段查询在 RLS 下可见）：

```python
        style_item_id = (body.style_item_id or "").strip()
        if style_item_id:
            profile, skill_pack, _name = resolve_style_selection(db, uid, style_item_id)
            db.flush()
            settings_row = db.scalar(select(ProjectSettings).where(
                ProjectSettings.project_id == project.id))
            settings_row.style_profile = profile
            settings_row.skill_pack = skill_pack
```

文件头加 `from myink.api.routes_style import resolve_style_selection`。

**注意**：`BookCountExceeded` 分支会 return，那时 `project` 未定义——上面的代码必须放在 `try/except` 之后。

- [ ] **Step 4: 跑测试，确认它绿（含回归）**

```bash
"$MYINK_PY" -m pytest tests/test_project_creation.py tests/test_outline.py tests/test_genre_packs.py -q
```

Expected: PASS。走题材包（`primary_id`）的既有用例必须一条都不翻——这是 Review Focus 第 5 条的落点。

- [ ] **Step 5: 契约 + 全量 + 提交 + 推送**

```bash
"$MYINK_PY" -m myink contract export
"$MYINK_PY" -m pytest tests/ -q
git add src/myink/api/routes_book.py tests/test_project_creation.py spec/api-openapi.json
git diff --cached --name-status
git commit -m "feat: 长篇建书可以选文风标签，与短篇共用同一份解析"
git push
```

---

### Task 10: 长篇建书页的文风下拉

**Files:**
- Modify: `web/src/types.ts:518`（`CreateProjectBody`）
- Modify: `web/src/pages/NewProjectPage.tsx`
- Modify: `web/src/pages/NewProjectPage.test.tsx`

**Interfaces:**
- Consumes: 任务 9 的 `style_item_id`；`styleLibraryApi.list`。
- Produces: `CreateProjectBody.style_item_id?: string | null`；第①步出现 `aria-label="文风"` 的 `<select>`。

- [ ] **Step 1: 写失败测试**

追加到 `web/src/pages/NewProjectPage.test.tsx`：

```tsx
  it('submits the selected style item id with the project', async () => {
    vi.mocked(styleLibraryApi.list).mockResolvedValue({
      items: [
        { id: 'builtin:xianxia-jiuzhou', name: '九州问天', builtin: true, removable: false,
          profile: {}, note: '', sample_chars: 0, created_at: null },
        { id: 'mine-1', name: '渡口白描', builtin: false, removable: true,
          profile: {}, note: '', sample_chars: 10, created_at: '2026-09-24' },
      ],
    })
    // ... 沿用本文件现有的「填完第①步 → 提交」helper
    fireEvent.change(await screen.findByLabelText('文风'), { target: { value: 'mine-1' } })
    await submitStepOne()
    expect(vi.mocked(api.createProject).mock.calls[0][0].style_item_id).toBe('mine-1')
  })

  it('lists the builtin style before mine with their origin marked', async () => {
    vi.mocked(styleLibraryApi.list).mockResolvedValue({
      items: [
        { id: 'builtin:xianxia-jiuzhou', name: '九州问天', builtin: true, removable: false,
          profile: {}, note: '', sample_chars: 0, created_at: null },
        { id: 'mine-1', name: '渡口白描', builtin: false, removable: true,
          profile: {}, note: '', sample_chars: 10, created_at: '2026-09-24' },
      ],
    })
    // ... 挂载后
    const select = await screen.findByLabelText('文风')
    expect(Array.from(select.querySelectorAll('option')).map((o) => o.textContent)).toEqual([
      '不指定', '九州问天（内置）', '渡口白描（我的）',
    ])
  })
```

（`styleLibraryApi.list` 的 mock 加进本文件顶部的 `vi.mock` 里。）

- [ ] **Step 2: 跑测试，确认它红**

```bash
cd web && npm test -- src/pages/NewProjectPage.test.tsx
```

Expected: FAIL——找不到 `文风` 这个 label。

- [ ] **Step 3: 实现**

`web/src/types.ts` 的 `CreateProjectBody` 加：

```ts
  style_item_id?: string | null
```

`web/src/pages/NewProjectPage.tsx`：

- 顶部加 `import { styleLibraryApi, type StyleLibraryItem } from '../lib/styleLibraryApi'`。
- state 加 `const [styleItems, setStyleItems] = useState<StyleLibraryItem[]>([])` 与 `const [styleItemId, setStyleItemId] = useState('')`。
- 挂载 effect 里取列表（拿不到就当空）：

```tsx
  useEffect(() => {
    styleLibraryApi.list(token).then((out) => setStyleItems(out.items)).catch(() => setStyleItems([]))
  }, [token])
```

（`token` 用本文件已有的会话 token 变量名。）

- 提交载荷（:273-287）加一行：

```tsx
        style_item_id: styleItemId || null,
```

- 渲染：在第①步的题材 `<details>` 块（:661-666）之后加：

```tsx
            <label className={styles.field}>
              <span className={styles.fieldLabel}>文风（可选）</span>
              <select className="input" aria-label="文风" value={styleItemId}
                      disabled={busy === 'restore' || pid !== null}
                      onChange={(e) => setStyleItemId(e.target.value)}>
                <option value="">不指定</option>
                {styleItems.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}{item.builtin ? '（内置）' : '（我的）'}
                  </option>
                ))}
              </select>
            </label>
```

- [ ] **Step 4: 跑测试与类型闸**

```bash
cd web && npm test -- src/pages/NewProjectPage.test.tsx && npm run lint && npm run build
```

Expected: PASS / 无 error / 构建成功。

- [ ] **Step 5: 提交 + 推送**

```bash
git add web/src/types.ts web/src/pages/NewProjectPage.tsx web/src/pages/NewProjectPage.test.tsx
git commit -m "feat: 长篇建书第①步加文风下拉"
git push
```

---

### Task 11: 短篇建书页去掉内联导入

**Files:**
- Modify: `web/src/pages/ShortCreationPage.tsx`（删 :74-78、:152-168、:180-181、:252-283）
- Modify: `web/src/pages/ShortCreationPage.module.css`（删 `.import*`）
- Modify: `web/src/pages/ShortCreationPage.test.tsx`

**Interfaces:**
- Consumes: `styleLibraryApi.list`（只为填选择器）。
- Produces: 文风行只剩 `<select aria-label="文风">` + `<Link to="/styles">`。任务 13 在这份骨架上做三段式。

- [ ] **Step 1: 写失败测试**

在 `web/src/pages/ShortCreationPage.test.tsx` 里把原来的导入用例改写：

```tsx
  it('offers the style selector and a link to the library, with no inline import', async () => {
    renderPage()
    expect(await screen.findByLabelText('文风')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '去文风库添加' })).toHaveAttribute('href', '/styles')
    expect(screen.queryByRole('button', { name: '导入文章存成我的文风' })).toBeNull()
    expect(screen.queryByLabelText('粘贴文章')).toBeNull()
  })
```

- [ ] **Step 2: 跑测试，确认它红**

```bash
cd web && npm test -- src/pages/ShortCreationPage.test.tsx
```

Expected: FAIL——「去文风库添加」链接不存在。

- [ ] **Step 3: 实现**

`ShortCreationPage.tsx`：

- 删 state：`importOpen` / `importText` / `importDraft` / `importName`。
- 删 `extractStyle` / `saveStyle` 两个函数。
- 删 `extractError` 常量（:181）与方案卡里 :252-283 的整块（`<small>` 提示 + 导入按钮 + 展开区）。
- 把 :252 的 `<small>` 换成：

```tsx
        <small>文风在确认时定下来，之后没有换的入口。</small>
        <Link to="/styles">去文风库添加</Link>
```

- `styleItems` 的加载保留（选择器要它）；`styleLibraryApi` 的 `extract`/`save` 不再被引用，但 API 对象整体 import 保留即可。

`ShortCreationPage.module.css` 删掉 `.import`、`.import label`、`.import small` 三条规则。

- [ ] **Step 4: 跑测试与类型闸**

```bash
cd web && npm test -- src/pages/ShortCreationPage.test.tsx && npm run lint && npm run build
```

Expected: PASS / 无 error / 构建成功（未使用的 import 会被 `npm run build` 或 `oxlint` 抓到，按提示清掉）。

- [ ] **Step 5: 提交 + 推送**

```bash
git add web/src/pages/ShortCreationPage.tsx web/src/pages/ShortCreationPage.module.css \
        web/src/pages/ShortCreationPage.test.tsx
git commit -m "refactor: 短篇建书页去掉内联导入，改为选文风标签"
git push
```

---

### Task 12: 改写 `SYSTEM_SHORT_CREATION`

**Files:**
- Modify: `src/myink/workflow/prompts.py:940-1010`（`SYSTEM_SHORT_CREATION`）
- Modify: `tests/test_prompts.py`

**Interfaces:**
- Consumes: `short_creation_messages(history, card)` 的签名与「喂全历史 + 当前卡」的行为**不变**。
- Produces: 系统提示里含有两个标志串「直接回答」与「一明确就填满」，任务 13 前面没有别的消费者。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_prompts.py`：

```python
def test_short_creation_prompt_is_a_collaborator_not_a_questionnaire():
    from myink.workflow.prompts import SYSTEM_SHORT_CREATION
    assert "直接回答" in SYSTEM_SHORT_CREATION
    assert "填满" in SYSTEM_SHORT_CREATION
    assert "一回合只问一个" not in SYSTEM_SHORT_CREATION, "问卷机口径必须删掉"


def test_short_creation_messages_feed_the_whole_history_and_the_current_card():
    from myink.workflow.prompts import short_creation_messages
    messages = short_creation_messages(
        [{"role": "user", "content": "第一句"}, {"role": "assistant", "content": "第二句"}],
        {"working_title": "渡口"})
    assert messages[0]["role"] == "system"
    joined = " ".join(m["content"] for m in messages)
    assert "第一句" in joined and "第二句" in joined, "全历史都要在"
    assert "渡口" in joined, "当前卡要带上"
```

（第二条测试若与本文件已有的 `short_creation_messages` 用例重复，就用已有的那条，只补第一条。）

- [ ] **Step 2: 跑测试，确认它红**

```bash
source .local/env-test.sh
"$MYINK_PY" -m pytest tests/test_prompts.py -q -k short_creation_prompt
```

Expected: FAIL——`"直接回答" in SYSTEM_SHORT_CREATION` 为假（现提示词没有这个口径）。

- [ ] **Step 3: 实现**

改写 `SYSTEM_SHORT_CREATION` 的正文（保持「只输出 JSON、两个键 `reply` / `card`」的契约与卡字段清单不动，只换协作方式）：

```python
SYSTEM_SHORT_CREATION = """你在和作者一起把一篇短篇聊成形。你是合作者，不是填表机。

怎么说话：
1. 普通讨论**直接回答**。作者问「这个题材行不行」「你觉得哪个更好」这类问题，就正常答，
   不要每轮都反问，也不要为了凑回合数去追问细节。
2. 只有「题材」「主角压力」「核心冲突」这三样太空的时候，才问**一个**最关键的。
3. 这三样一明确，就把卡**填满**——包括你自己拟的 2–8 字暂定名、默认章数与每章字数。
   不要在文字里再把方案复述一遍等作者二次确认：卡就是方案。
4. 作者说「就这样」「开写」「确认」这类话，立刻把卡填满。
5. 结尾可以带一句「想开始就说一声，或者直接改卡」这样的可选提示，不要每轮都问同一个问题。

不许做的：
- 不承诺已经建书或已经开写（建书由作者点确认触发）。
- 不用 markdown 表格或标题。
- 卡里留空的字段 = 这轮没有新信息，系统会保留作者已经写好的值。

只输出 JSON：{"reply": "...", "card": {...}}。card 的键只有：
working_title / genre / direction / protagonist_pressure / conflict_core / emotional_payoff / plot_sketch
/chapter_count / chars_per_chapter。"""
```

（保留文件里原有的卡字段说明、JSON 输出契约与「用中文」要求；上面是把它们一并写全的版本，实现时以现有文本为准，只替换「说话方式」那部分。）

- [ ] **Step 4: 跑测试，确认它绿（含回归）**

```bash
"$MYINK_PY" -m pytest tests/test_prompts.py tests/test_short_creation.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交 + 推送**

```bash
git add src/myink/workflow/prompts.py tests/test_prompts.py
git commit -m "feat: 短篇建书提示词从问卷机改成合作者"
git push
```

---

### Task 13: 短篇建书页三段式

**Files:**
- Modify: `web/src/pages/ShortCreationPage.tsx`
- Modify: `web/src/pages/ShortCreationPage.module.css`
- Modify: `web/src/pages/ShortCreationPage.test.tsx`

**Interfaces:**
- Consumes: `data.ready`（服务端算好的，不改契约）、`shortCreationApi.commit`、`api.generateShort(projectId)`。
- Produces: 三段式页面。`navigate('/projects/'+id, {state:{beginShortWriting:true, planWarning}})` 这个握手形状**不变**——任务 14 在工作台消费它。

- [ ] **Step 1: 写失败测试**

替换 `ShortCreationPage.test.tsx` 的建书用例：

```tsx
  it('keeps the card hidden until the server says it is ready', async () => {
    vi.mocked(shortCreationApi.get).mockResolvedValue({
      session: { id: 's1', status: 'active', card: {}, style_item_id: null, style_name: null, book_id: null },
      messages: [], ready: false,
    })
    renderPage()
    expect(await screen.findByLabelText('对助手说')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '开始建书' })).toBeNull()
    expect(screen.queryByLabelText('暂定名')).toBeNull()
  })

  it('shows the start option when ready, then the card, then commits and enqueues in order', async () => {
    vi.mocked(shortCreationApi.get).mockResolvedValue({
      session: { id: 's1', status: 'active', card: { working_title: '渡口' },
                 style_item_id: null, style_name: null, book_id: null },
      messages: [], ready: true,
    })
    vi.mocked(shortCreationApi.commit).mockResolvedValue({
      project_id: 'p1', lengths_compressed: false, plan_warning: null, style_name: null,
    })
    vi.mocked(api.generateShort).mockResolvedValue({ task_id: 't1' })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '开始建书' }))
    expect(await screen.findByLabelText('暂定名')).toHaveValue('渡口')

    const order: string[] = []
    vi.mocked(shortCreationApi.commit).mockImplementation(async () => {
      order.push('commit')
      return { project_id: 'p1', lengths_compressed: false, plan_warning: null, style_name: null }
    })
    vi.mocked(api.generateShort).mockImplementation(async () => {
      order.push('generate')
      return { task_id: 't1' }
    })
    fireEvent.click(screen.getByRole('button', { name: '确认，开写' }))
    await waitFor(() => expect(order).toEqual(['commit', 'generate']))
    expect(mockNavigate).toHaveBeenCalledWith('/projects/p1',
      { state: { beginShortWriting: true, planWarning: null } })
  })

  it('sends on Enter and leaves Shift+Enter to insert a newline', async () => {
    vi.mocked(shortCreationApi.get).mockResolvedValue({
      session: { id: 's1', status: 'active', card: {}, style_item_id: null, style_name: null, book_id: null },
      messages: [], ready: false,
    })
    vi.mocked(shortCreationApi.send).mockResolvedValue({
      session: { id: 's1', status: 'active', card: {}, style_item_id: null, style_name: null, book_id: null },
      messages: [], ready: false,
    })
    renderPage()
    const box = await screen.findByLabelText('对助手说')
    fireEvent.change(box, { target: { value: '一个渡口的故事' } })
    fireEvent.keyDown(box, { key: 'Enter', shiftKey: false })
    await waitFor(() => expect(shortCreationApi.send).toHaveBeenCalledWith('tok', '一个渡口的故事', {}))
    fireEvent.change(box, { target: { value: '第二句' } })
    fireEvent.keyDown(box, { key: 'Enter', shiftKey: true })
    expect(shortCreationApi.send).toHaveBeenCalledTimes(1)
  })

  it('does not send on an Enter that is only committing an IME composition', async () => {
    // ... 同一挂载流程
    fireEvent.change(box, { target: { value: '渡口' } })
    const event = createEvent.keyDown(box, { key: 'Enter' })
    Object.defineProperty(event, 'isComposing', { value: true })
    fireEvent(box, event)
    expect(shortCreationApi.send).not.toHaveBeenCalled()
  })
```

（`mockNavigate` 来自本文件顶部对 `react-router-dom` 的 `useNavigate` mock——本文件若用 `MemoryRouter` 真实导航，就断言 `window.location`/路由落点，或把 `useNavigate` 单独 mock 出来。沿用本文件现有做法。）

- [ ] **Step 2: 跑测试，确认它红**

```bash
cd web && npm test -- src/pages/ShortCreationPage.test.tsx
```

Expected: FAIL——「开始建书」按钮不存在；`keyDown Enter` 不触发 `send`。

- [ ] **Step 3: 实现**

`ShortCreationPage.tsx` 的改动：

1. 加 `cardOpen` 状态（点「开始建书」后为真），并在 `data.ready` 变回 false 时关掉它：

```tsx
  useEffect(() => { if (!data?.ready) setCardOpen(false) }, [data?.ready])
```

2. 输入框改成 `onKeyDown`：

```tsx
  const onKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) return
    // 中文输入法组合态里的 Enter 是「选词上屏」，不是发送。
    if (event.nativeEvent.isComposing) return
    event.preventDefault()
    sendDraft()
  }
```

把 `submit` 拆成 `sendDraft()`（无 event）+ 一个仅用于按钮点击的包装。`<textarea>` 保留在 `<form onSubmit>` 里（回车被 `preventDefault` 后由 `sendDraft` 负责，`发送` 按钮走 `onSubmit`）。

3. `committed`（`data.session.status !== 'active'`）时：不摆「开始建书」，不摆方案卡，只留已有的提示条（:284-291）。

4. 对话流末尾，`data.ready && !committed && !cardOpen` 时插一条可点的条：

```tsx
          {data.ready && !committed && !cardOpen && (
            <button type="button" className={`btn btn-primary ${styles.option}`}
                    onClick={() => setCardOpen(true)}>
              开始建书
            </button>
          )}
```

5. 方案卡由常驻 `aside` 改成 `cardOpen && (...)` 才渲染（内容沿用现有 JSX，含 FIELDS / 章数 / 每章字数 / 压缩提示 / 文风选择器）。

6. `confirm()` 改成 `commit` 成功后紧接着入队，入队失败不丢书也不卡死：

```tsx
  const confirm = () => {
    if (committed) return
    void run(async () => {
      const out = await shortCreationApi.commit(token, card as Record<string, unknown>, styleItemId || null)
      let enqueueFailed = false
      try {
        await api.generateShort(out.project_id)
      } catch {
        enqueueFailed = true
      }
      navigate(`/projects/${out.project_id}`, {
        state: { beginShortWriting: !enqueueFailed, planWarning: out.plan_warning },
      })
    }, '确认失败，请重试')
  }
```

（`beginShortWriting` 为假时，任务 14 的工作台就不自动开写，只显示状态带上的重试入口——这正是 Review Focus 第 3 条的落点。）

7. `.module.css` 加 `.option { align-self: flex-start; }`。

- [ ] **Step 4: 跑测试与类型闸**

```bash
cd web && npm test -- src/pages/ShortCreationPage.test.tsx && npm run lint && npm run build
```

Expected: PASS / 无 error / 构建成功。

- [ ] **Step 5: 提交 + 推送**

```bash
git add web/src/pages/ShortCreationPage.tsx web/src/pages/ShortCreationPage.module.css \
        web/src/pages/ShortCreationPage.test.tsx
git commit -m "feat: 短篇建书三段式——聊到齐备才冒开始建书，确认即开写"
git push
```

---

### Task 14: 短篇工作台去右栏 + 状态带 + 续写迁移 + 审稿并中栏

**Files:**
- Modify: `web/src/pages/WorkspacePage.tsx`（`:66-83` 与短篇分支 `:796-839`）
- Modify: `web/src/pages/WorkspacePage.module.css`
- Modify: `web/src/pages/WorkspacePage.test.tsx`
- Modify: `web/src/components/GenerationPanel.tsx`（只删短篇自动开写那段）

**Interfaces:**
- Consumes: `handover.beginShortWriting` / `handover.planWarning`（任务 13 的握手形状不变）、`api.generateShort`、`task.retry`、`ShortStoryPanel`。
- Produces: 短篇下不渲染 `aside.right`；中间栏顶部一条 `role="status"` 状态带；`ShortStoryPanel` 移到中间栏整篇正文下方、默认折叠。

- [ ] **Step 1: 写失败测试**

`WorkspacePage.test.tsx` 补：

```tsx
  it('renders no right column for a short book, and a status band instead', async () => {
    renderShortWorkspace()
    expect(await screen.findByRole('status')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '章节流转' })).toBeNull()
    expect(screen.queryByRole('heading', { name: '短篇审稿' })).toBeNull()
    expect(screen.queryByText('生成与重写')).toBeNull()
  })

  it('shows the plan warning on the short status band', async () => {
    renderShortWorkspace({ planWarning: '每章字数已按全篇上限归一' })
    expect(await screen.findByRole('status')).toHaveTextContent('每章字数已按全篇上限归一')
  })

  it('auto-starts the short generation once on handover', async () => {
    renderShortWorkspace({ beginShortWriting: true })
    await waitFor(() => expect(api.generateShort).toHaveBeenCalledWith('p1'))
    expect(api.generateShort).toHaveBeenCalledTimes(1)
  })

  it('does not auto-start when the enqueue already failed at commit time', async () => {
    renderShortWorkspace({ beginShortWriting: false })
    await Promise.resolve()
    expect(api.generateShort).not.toHaveBeenCalled()
  })

  it('keeps the long-form right column unchanged', async () => {
    renderLongWorkspace()
    expect(await screen.findByRole('heading', { name: '章节流转' })).toBeInTheDocument()
  })
```

（`renderShortWorkspace` / `renderLongWorkspace` 是本文件现有挂载 helper 的形态——用现有的，只加 `state` 参数。`WorkspacePage.test.tsx:415` 那条「`form: undefined` → 长篇」的既有用例必须保持绿。）

- [ ] **Step 2: 跑测试，确认它红**

```bash
cd web && npm test -- src/pages/WorkspacePage.test.tsx
```

Expected: FAIL——短篇下 `role="status"` 不存在（现在右下角摆的是 `ShortStoryPanel`）。

- [ ] **Step 3: 实现**

`WorkspacePage.tsx`：

1. 短篇的续写触发搬到本页自己的 effect（原先靠 `GenerationPanel` 的 `autoStartShort`）。`handedOver` / `shortStarted` 用组件内 ref，并与现有的「抹 `history.state` 标记」合成同一个 effect，顺序显式：

```tsx
  const shortStarted = useRef(false)
  useEffect(() => {
    if (isShortBook && handover.beginShortWriting && !shortStarted.current && activeTaskId === null) {
      shortStarted.current = true
      void api.generateShort(projectId).then((resp) => handleTaskStart(resp.task_id)).catch(() => {
        setShortStartFailed(true)   // 失败时状态带给重试，不静默吞掉
      })
    }
    if (handover.planWarning || handover.beginShortWriting) {
      navigate(location.pathname, { replace: true, state: { planWarning: handover.planWarning ?? null } })
    }
  }, [isShortBook, handover.beginShortWriting, handover.planWarning, activeTaskId, projectId])
```

（`handleTaskStart` 是现成的 :306 那段；`projectId` / `isShortBook` / `handover` / `navigate` / `location` 都是本页已有的。）

2. 短篇分支的 `aside.right` 整块不渲染：

```tsx
        {!isShortBook && (
          <aside className={styles.right}>
            {/* 长篇的 GenerationPanel / TaskTimeline / AuditPanel / CandidatePanel / LessonsPanel 原样 */}
          </aside>
        )}
```

3. 中间栏顶部加状态带（`role="status"`），四态；`plan_warning` 在这里渲染（M-5）：

```tsx
        {isShortBook && (
          <div className={styles.band} role="status">
            {shortStatus}
            {handover.planWarning && <span className={styles.bandWarn}>{handover.planWarning}</span>}
            {shortStartFailed && (
              <button type="button" className="btn btn-quiet" onClick={retryShort}>重试</button>
            )}
          </div>
        )}
```

`shortStatus` 由现有任务状态推：无任务 → 「还没开始写」；进行中 → 「正在写整篇」；终态成功 → 「写完了」；终态失败 → 「写失败了」+ 重试按钮。重试入口两条：`activeTaskId === null` 时 `api.generateShort(projectId)`，否则 `task.retry`。

4. 审稿结论并进中间栏：把 `ShortStoryPanel runs={visibleTaskRuns}` 放到整篇正文下方，用 `<details>` 默认折叠、有报告才渲染：

```tsx
        {isShortBook && hasShortReview && (
          <details className={styles.review}>
            <summary>审稿结论</summary>
            <ShortStoryPanel runs={visibleTaskRuns} />
          </details>
        )}
```

`hasShortReview` 用 `visibleTaskRuns.some((r) => r.node === 'short_review')`。

5. `GenerationPanel.tsx` 删掉 `autoStartShort` 相关的 prop、`handedOver` ref 与那段 effect（:44-56），以及短篇分支里不再需要的 `isShort` 分支。**长篇的分支一行不动。** 删 `autoStartShort` 后若 `form` prop 仍有长篇用途，保留。

6. `.module.css` 加 `.band`（细条、`role="status"` 的一行）、`.bandWarn`、`.review`。

- [ ] **Step 4: 跑测试与类型闸**

```bash
cd web && npm test -- src/pages/WorkspacePage.test.tsx && npm run lint && npm run build
```

Expected: PASS / 无 error / 构建成功。长篇那条回归用例（`form: undefined` → 长篇）必须仍绿。

- [ ] **Step 5: 提交 + 推送**

```bash
git add web/src/pages/WorkspacePage.tsx web/src/pages/WorkspacePage.module.css \
        web/src/pages/WorkspacePage.test.tsx web/src/components/GenerationPanel.tsx
git commit -m "feat: 短篇工作台去掉长篇残留的右栏，改细状态带并接住方案提示"
git push
```

---

### Task 15: M-8 `GenerationPanel` 依赖警告

**Files:**
- Modify: `web/src/components/GenerationPanel.tsx`

**Interfaces:**
- Consumes: 任务 14 已删掉短篇的自动开写 effect。
- Produces: 无（lint 干净）。

- [ ] **Step 1: 复现警告**

```bash
cd web && npm run lint 2>&1 | grep -n "exhaustive-deps" || echo "no warning"
```

Expected: 任务 14 之后若那段 effect 已删，这里可能已经没有警告。**若没有警告，本任务无事可做**——把这条记进 ledger 的 Ruling，跳过其余步骤，不留空提交。

- [ ] **Step 2: 写一个能抓住重构回归的测试**

即使警告消失，也把「面板只在自己该跑的时候跑一次」钉成行为测试（追加到 `GenerationPanel` 的既有测试文件；若无，新建 `web/src/components/GenerationPanel.test.tsx`）：

```tsx
  it('does not auto-start anything on its own for a long book', async () => {
    render(<GenerationPanel projectId="p1" chapters={[]} selectedChapter={null} form="long"
                            onTaskStart={vi.fn()} />)
    await Promise.resolve()
    expect(api.generateShort).not.toHaveBeenCalled()
  })
```

- [ ] **Step 3: 跑测试，确认它绿**

```bash
cd web && npm test -- src/components/GenerationPanel.test.tsx
```

Expected: PASS。这条一开始就该绿——它是钉住「短篇自动开写已搬走」的回归网，不是 RED→GREEN 的新功能。**在 ledger 里写明它是回归网而非新行为的 RED。**

- [ ] **Step 4: 提交 + 推送**

```bash
git add web/src/components/GenerationPanel.tsx web/src/components/GenerationPanel.test.tsx
git commit -m "test: 钉住生成面板不再自行触发短篇生成"
git push
```

---

### Task 16: M-1 端点级测试补真 RED

**Files:**
- Modify: `tests/test_short_creation.py`

**Interfaces:**
- Consumes: `POST /short/creation/messages` 的合并语义（`merge_model_card` 的「空串 = 这轮没给」）。
- Produces: 一条**删掉实现就会红**的端点级用例。

- [ ] **Step 1: 写测试并确认它在今天还能靠**

现有 stub 的卡省略了 `working_title`，所以「模型返回空串时保留用户旧值」这条逻辑删掉也照样绿。改成卡**带** `working_title`，模型返回空串：

```python
def test_an_empty_model_field_keeps_what_the_user_already_wrote(_STUB_TURN):
    """模型在某个字段上回空串 = 这轮没新信息，不能把用户填好的暂定名冲掉。

    这条是端点级的：只测 creation.merge_model_card 会在 handler 那层漏掉（比如 handler
    改成了先 card_patch 再合并），所以必须走 POST /messages。
    """
    client.post("/api/v1/short/creation/messages",
                json={"content": "渡口，冷白描", "card": {"working_title": "渡口"}},
                headers=identity_headers(_STUB_TURN))
    out = client.post("/api/v1/short/creation/messages",
                      json={"content": "接着说说环境", "card": {"working_title": "渡口"}},
                      headers=identity_headers(_STUB_TURN)).json()
    assert out["session"]["card"]["working_title"] == "渡口", "空串不该覆盖用户已写的值"
```

其中 `_STUB_TURN` 的 provider stub 要**显式**在 card 里带上 `working_title: ""`。若现有 stub 的 payload 形状是模块级常量，就加一个本用例专用的 stub 或 `monkeypatch` 覆盖。

- [ ] **Step 2: 验证它确实会红**

临时把 `src/myink/short/creation.py` 的 `merge_model_card` 改成「空串也覆盖」（一行），跑：

```bash
source .local/env-test.sh
"$MYINK_PY" -m pytest tests/test_short_creation.py -q -k empty_model_field
```

Expected: FAIL。**看到红之后立刻把那一行改回去。**

- [ ] **Step 3: 确认它绿且实现未被改动**

```bash
git diff --stat src/myink/short/creation.py   # 必须为空
"$MYINK_PY" -m pytest tests/test_short_creation.py -q
```

Expected: `git diff --stat` 无输出；全套 PASS。

- [ ] **Step 4: 提交 + 推送**

```bash
git add tests/test_short_creation.py
git commit -m "test: 补一条真会红的端点级用例，钉住空串不覆盖用户输入"
git push
```

---

### Task 17: M-2 / M-4 `_known` 的数值与文本守卫

**Files:**
- Modify: `src/myink/short/creation.py`（`_known`）
- Modify: `tests/test_short_creation.py`（或 `tests/test_short_parse.py`）

**Interfaces:**
- Consumes: 无。
- Produces: `_known` 丢非有限浮点、丢文本字段上的非字符串、丢数字位上的非数字。

- [ ] **Step 1: 写失败测试**

```python
def test_non_finite_numbers_are_ignored_not_fatal():
    """Infinity / NaN / 1e400 经 int() 会抛 OverflowError 或 ValueError → 端点 500。"""
    from myink.short.creation import merge_model_card
    for bad in (float("inf"), float("-inf"), float("nan"), 1e400):
        out = merge_model_card({"chapter_count": 5}, {"chapter_count": bad})
        assert out["chapter_count"] == 5, f"{bad!r} 应当被当作「没给」"


def test_numbers_never_land_in_text_fields():
    """数字写进 working_title 会让 Project(title=<int>) 崩成 500。"""
    from myink.short.creation import merge_model_card
    out = merge_model_card({}, {"working_title": 42, "genre": {"x": 1}})
    assert "working_title" not in out and "genre" not in out
```

（`merge_model_card` 的名字以 `creation.py` 实现为准——它调用 `_known`。若签名是 `merge_model_card(base, patch)` 之外的形状，照真实签名写。）

- [ ] **Step 2: 跑测试，确认它红**

```bash
source .local/env-test.sh
"$MYINK_PY" -m pytest tests/test_short_creation.py -q -k "non_finite or numbers_never"
```

Expected: FAIL——`inf` 那条抛 `OverflowError`；`working_title: 42` 那条现在会写进去（`42` 是 `int`，落进了 `out[key]`）。

- [ ] **Step 3: 实现**

`src/myink/short/creation.py` 顶部加 `import math`，`_known` 改成：

```python
def _known(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for key, value in raw.items():
        if key not in ShortCreationCard.model_fields:
            continue
        if isinstance(value, bool):          # bool 是 int 的子类，先挡掉
            continue
        if isinstance(value, str):
            text = value.strip()
            if key in _NUMBER_FIELDS:
                try:
                    out[key] = int(float(text))
                except (ValueError, OverflowError):
                    continue                 # 数字位上的垃圾/空串：宁可不改，也不写进去
                continue
            out[key] = text
            continue
        if isinstance(value, (int, float)):
            # 只有数字位收数字；文本位收数字会让 Project(title=<int>) 在建书时崩。
            if key not in _NUMBER_FIELDS:
                continue
            if not math.isfinite(value):     # Infinity / NaN / 1e400 都当「没给」
                continue
            out[key] = int(value)
    return out
```

（与现有实现相比的三处差异：`math.isfinite` 守卫、数值分支加 `key not in _NUMBER_FIELDS` 的早退、字符串数字分支的 `except` 补上 `OverflowError`。）

- [ ] **Step 4: 跑测试，确认它绿（含回归）**

```bash
"$MYINK_PY" -m pytest tests/test_short_creation.py tests/test_short_parse.py tests/test_short_form.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交 + 推送**

```bash
git add src/myink/short/creation.py tests/test_short_creation.py
git commit -m "fix: 方案卡丢弃非有限数字，文本位不再收数字"
git push
```

---

### Task 18: M-3 `commit` 的会话存在守卫

**Files:**
- Modify: `src/myink/api/routes_short_creation.py`（commit 的第 4 步）
- Modify: `tests/test_short_creation.py`

**Interfaces:**
- Consumes: 无。
- Produces: 会话在步骤 1 与步骤 4 之间被删掉时，`commit` 跳过状态写回并**照常返回成功**（书与方案已落）。

- [ ] **Step 1: 写失败测试**

```python
def test_commit_survives_a_session_deleted_midway(monkeypatch):
    """第 1 步锁住会话后、第 4 步写回前，会话被 DELETE 掉——不能 AttributeError 崩成 500。

    书和逐章方案已经落了，这条动线的语义是「成功」——用户回到工作台就能开写。
    """
    import myink.api.routes_short_creation as mod
    from myink.models import ShortCreationSession
    from sqlalchemy import delete as sa_delete

    original = mod._book._short_outline_draft
    def sabotage(*args, **kwargs):
        with new_session() as db:
            db.execute(sa_delete(ShortCreationMessage))
            db.execute(sa_delete(ShortCreationSession))
            db.commit()
        return original(*args, **kwargs)
    monkeypatch.setattr(mod._book, "_short_outline_draft", sabotage)

    resp = client.post("/api/v1/short/creation/commit",
                       json={"card": FULL_CARD}, headers=identity_headers(temp_user))
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"]
```

（`FULL_CARD` 用本文件已有的那张填满的卡常量；`new_session` / `ShortCreationMessage` 按需 import。）

- [ ] **Step 2: 跑测试，确认它红**

```bash
source .local/env-test.sh
"$MYINK_PY" -m pytest tests/test_short_creation.py -q -k deleted_midway
```

Expected: FAIL——`AttributeError: 'NoneType' object has no attribute 'status'`，HTTP 500。

- [ ] **Step 3: 实现**

`routes_short_creation.py` 的第 4 步（:243-252）加守卫：

```python
    # 4) 会话收尾。会话可能在步骤 1 之后被 DELETE /short/creation 删掉——
    # 书与方案已经落了，这一段的语义是「成功」，不能因为收尾写不回去就报 500。
    with new_session() as db:
        session = db.scalar(select(ShortCreationSession)
                            .where(ShortCreationSession.user_id == uid))
        if session is not None:
            session.status = "committed"
            session.book_id = pid
            if style_item_id:
                session.style_item_id = style_item_id
                session.style_name = style_name
        db.commit()
```

（保留该处现有的字段写入集合——上面是本次读到的字段，实现时以文件里真实的第 4 步内容为准，只加 `if session is not None:` 与一级缩进。）

- [ ] **Step 4: 跑测试，确认它绿（含回归）**

```bash
"$MYINK_PY" -m pytest tests/test_short_creation.py tests/test_short_routes.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交 + 推送**

```bash
git add src/myink/api/routes_short_creation.py tests/test_short_creation.py
git commit -m "fix: 建书确认时会话若已被删，收尾跳过状态写回而不报错"
git push
```

---

### Task 19: M-6 `reset` 连带删掉孤儿草稿书

**Files:**
- Modify: `src/myink/api/routes_short_creation.py:117-127`（`reset_session`）
- Modify: `tests/test_short_creation.py`

**Interfaces:**
- Consumes: `Project` / `Task` / `Chapter` 模型。
- Produces: 会话的 `book_id` 指向一本「当日创建 + 无任务」的书时，`DELETE /short/creation` 连带删它。

- [ ] **Step 1: 写失败测试**

```python
def test_reset_removes_todays_orphan_draft_book(temp_user):
    """commit 中途失败会留下一本当日建的草稿书，而它已经吃掉了当日额度。

    重置这段对话时应当把它带走。有任务的书不动——用户可能已经在写了。
    """
    # 1) 建会话 + 一本当日草稿书，把 book_id 指过去
    # 2) DELETE /api/v1/short/creation
    # 3) 断言那本书没了
    ...


def test_reset_keeps_a_book_that_already_has_tasks(temp_user):
    ...  # 同一流程，但先插一行 Task(project_id=pid)，断言书还在
```

（两步的具体搭法照 `tests/test_short_creation.py` 现有用例——它已经有建会话与建书的 helper。）

- [ ] **Step 2: 跑测试，确认它红**

```bash
source .local/env-test.sh
"$MYINK_PY" -m pytest tests/test_short_creation.py -q -k orphan
```

Expected: FAIL——重置后那本书还在。

- [ ] **Step 3: 实现**

```python
@router.delete("", response_model=OkOut)
def reset_session(user_id: str = Depends(require_user)) -> dict:
    uid = uuid.UUID(user_id)
    with new_session() as db:
        session = _session(db, uid)
        if session is not None:
            # 上次 commit 中途失败会留下一本当日的草稿书，而它已经吃掉了当日建书额度。
            # 只有「当日创建 + 一个任务都没有」才带走——宁可漏删，也不误删正在写的书。
            if session.book_id is not None:
                book = db.scalar(select(Project).where(
                    Project.id == session.book_id,
                    Project.user_id == uid,
                    Project.creation_status == "draft",
                    Project.created_at >= func.date_trunc("day", func.now()),
                    ~select(Task.id).where(Task.project_id == Project.id).exists(),
                    ~select(Chapter.id).where(Chapter.project_id == Project.id).exists(),
                ))
                if book is not None:
                    db.delete(book)
            db.execute(sa_delete(ShortCreationMessage)
                       .where(ShortCreationMessage.session_id == session.id))
            db.delete(session)
        db.commit()
    return {"ok": True}
```

需要补 import `func`、`Project`、`Task`、`Chapter`、`select`（按文件现有 import 情况增删）。

- [ ] **Step 4: 跑测试，确认它绿（含回归）**

```bash
"$MYINK_PY" -m pytest tests/test_short_creation.py tests/test_project_delete.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交 + 推送**

```bash
git add src/myink/api/routes_short_creation.py tests/test_short_creation.py
git commit -m "fix: 重置建书对话时带走当日失败留下的孤儿草稿书"
git push
```

---

### Task 20: M-7 管理面板的 `GET /admin/users/{user_id}`

**Files:**
- Modify: `src/myink/api/routes_admin.py`（新增端点，抽出 `_user_statement()`）
- Modify: `src/myink/api/admin_schemas.py`（若 `AdminUser` 需要复用，不改形状）
- Modify: `tests/test_admin.py`
- Modify: `web/src/lib/adminApi.ts`
- Modify: `web/src/pages/admin/UserDetail.tsx`
- Regenerate: `spec/api-openapi.json`

**Interfaces:**
- Consumes: `users()` 列表里那套 `run_owner` / `_count` / `_word_count` 指标列。
- Produces: `GET /api/v1/admin/users/{user_id}` → `AdminUser`；查不到 404 `NOT_FOUND`。前端 `adminApi.getUser(token, userId, signal)`。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_admin.py`：

```python
def test_admin_user_detail_returns_one_user(admin_client, temp_user):
    resp = admin_client.get(f"/api/v1/admin/users/{temp_user}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == temp_user
    assert body["username"]
    assert "metrics" in body


def test_admin_user_detail_404s_on_an_unknown_id(admin_client):
    resp = admin_client.get(f"/api/v1/admin/users/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "NOT_FOUND"
```

（`admin_client` / `temp_user` 用本文件现有 fixture 的名字。）

- [ ] **Step 2: 跑测试，确认它红**

```bash
source .local/env-test.sh
"$MYINK_PY" -m pytest tests/test_admin.py -q -k user_detail
```

Expected: FAIL——404（路径不存在，`/admin/users/{user_id}` 被 `*` 兜底或直接 404）。

- [ ] **Step 3: 实现**

`routes_admin.py`：把 `users()` 里那段 `select(...)` 抽成模块级函数，两处共用：

```python
def _user_statement():
    owned = select(Project.id).where(Project.user_id == User.id).correlate(User)
    run_owner = or_(AgentRun.project_id.in_(owned),
                    and_(AgentRun.project_id.is_(None), AgentRun.user_id == User.id))
    return select(User.id, User.username, User.tier, User.role,
                  _count(Task, Task.project_id.in_(
                      select(Project.id).where(Project.user_id == User.id))).label("task_count"),
                  *_metric_columns(run_owner),
                  *_task_average_columns(lambda pt: pt.c.project_id.in_(
                      select(Project.id).where(Project.user_id == User.id))))
```

（实现时照抄 `users()` 里现有的列清单，只是把它搬进函数——**列顺序与别名一个都不许动**，否则列表页与详情页的口径会分叉。）

```python
@router.get("/users/{user_id}", response_model=AdminUser, name="admin.user")
def user_detail(db: DB, user_id: uuid.UUID):
    row = db.execute(_user_statement().where(User.id == user_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "NOT_FOUND")
    return _nested_metrics(row)
```

`users()` 改成 `_user_statement()` + 既有的搜索/分页/`_page`。

- [ ] **Step 4: 跑测试，确认它绿（含回归）**

```bash
"$MYINK_PY" -m pytest tests/test_admin.py tests/test_admin_analytics.py tests/test_admin_observability.py -q
```

Expected: PASS。列表页的既有断言必须一条都不翻——这是「抽函数不改口径」的证明。

- [ ] **Step 5: 契约 + 前端**

```bash
"$MYINK_PY" -m myink contract export
```

`web/src/lib/adminApi.ts` 加：

```ts
  getUser: (token: string, userId: string, signal?: AbortSignal) =>
    request<AdminUser>('GET', `/admin/users/${userId}`, undefined, token, signal),
```

（参数形状照本文件已有的 `getTask` / `getRun`。）

`web/src/pages/admin/UserDetail.tsx` 改 `loadUser`：

```tsx
  const loadUser = useCallback(async (signal: AbortSignal) => {
    try {
      return { items: [await adminApi.getUser(token, userId, signal)] }
    } catch (reason) {
      // 未知 id 要显示「用户不存在」，不能靠 404 的英文码。
      if (reason instanceof ApiError && reason.status === 404) {
        throw new ApiError(404, '用户不存在', reason.body)
      }
      throw reason
    }
  }, [token, userId])
```

（`formatErrorText` 对含中文的 code 直接透传，所以 `'用户不存在'` 会原样显示。`ApiError` 从 `lib/api` import。）

前端测试：`web/src/pages/admin/UserDetail.test.tsx`（无则新建）补一条「未知 id 显示用户不存在」，mock `adminApi.getUser` 抛 `new ApiError(404, 'NOT_FOUND', {})`，断言页面出现「用户不存在」。

- [ ] **Step 6: 跑前端测试与类型闸 + 提交 + 推送**

```bash
cd web && npm test -- src/pages/admin/UserDetail.test.tsx && npm run lint && npm run build
cd .. && git add src/myink/api/routes_admin.py tests/test_admin.py spec/api-openapi.json \
        web/src/lib/adminApi.ts web/src/pages/admin/UserDetail.tsx \
        web/src/pages/admin/UserDetail.test.tsx
git diff --cached --name-status
git commit -m "feat: 管理面板补用户详情端点，未知 id 给 404"
git push
```

---

### Task 21: M-9 `overview` 的归属过滤

**Files:**
- Modify: `src/myink/api/routes_admin.py`（`overview` 与模块常量）
- Modify: `tests/test_admin.py`

**Interfaces:**
- Consumes: `_metric_columns(*conditions)`。
- Produces: `/admin/overview` 的全局指标等于各用户之和（去掉无归属的孤儿 `agent_runs`）。

**Ruling（本任务实现时遵守）：** spec 里写的是「加 `owner.is_not(None)` 条件」，那需要给 `_metric_columns` 的子查询加一个 `Project` 外连接。改用**等价的子查询谓词**，不需要 join：

```python
# 归属口径：有书（书还在）或 无书但有账号。与 /admin/users 列表的行内条件同源，
# 所以全局合计恰好等于各用户之和（包括「project 被删但 user_id 还在」这类孤儿行）。
_ATTRIBUTED_RUN = or_(AgentRun.project_id.in_(select(Project.id)),
                      AgentRun.user_id.is_not(None))
```

与 spec 字面写法的差别只在于「project 存在但其 `user_id` 为 NULL」这一种情形（代码里不存在这种行）。记进 ledger。

- [ ] **Step 1: 写失败测试**

```python
def test_overview_metrics_match_the_sum_of_the_users(admin_client, temp_user, temp_project):
    """全局花费必须等于各用户之和：孤儿 agent_runs（project 被删、user_id 也没了）不算。"""
    # 造三行：真项目上的一行、只有 user_id 的一行、以及一行两者都没有的孤儿
    ...
    total = admin_client.get("/api/v1/admin/overview").json()["metrics"]
    listed = admin_client.get("/api/v1/admin/users", params={"limit": 100}).json()["items"]
    assert total["cost_est"] == pytest.approx(sum(u["metrics"]["cost_est"] for u in listed))
    assert total["run_count"] == sum(u["metrics"]["run_count"] for u in listed)
```

- [ ] **Step 2: 跑测试，确认它红**

```bash
source .local/env-test.sh
"$MYINK_PY" -m pytest tests/test_admin.py -q -k sum_of_the_users
```

Expected: FAIL——全局 `run_count` / `cost_est` 比各用户之和多（孤儿行被算进去了）。

- [ ] **Step 3: 实现**

加模块常量 `_ATTRIBUTED_RUN`（如上），`overview` 改成：

```python
    metrics = db.execute(select(*_metric_columns(_ATTRIBUTED_RUN))).mappings().one()
```

- [ ] **Step 4: 跑测试，确认它绿（含回归）**

```bash
"$MYINK_PY" -m pytest tests/test_admin.py tests/test_admin_observability.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交 + 推送**

```bash
git add src/myink/api/routes_admin.py tests/test_admin.py
git commit -m "fix: 管理面板全局花费与各用户之和口径对齐，剔除无归属调用"
git push
```

---

### Task 22: M-10 部署文档补一行

**Files:**
- Modify: `docs/DEPLOY.md`

**Interfaces:**
- Consumes: 无。
- Produces: 无。

- [ ] **Step 1: 加说明**

在 `docs/DEPLOY.md` 的升级/迁移小节里加一行（位置贴着现有的 `myink init` 说明）：

```markdown
- 若环境早于 `dbb62e9` 建过 `style_library_items`：那一版缺 `note` 列与 `(user_id, name)` 唯一约束，
  `create_all` 不会补这两样。一次性执行 `DROP TABLE style_library_items;` 再 `myink init` 重建即可
  （表里只有用户自建的文风档，重建会清空它们）。
```

- [ ] **Step 2: 提交 + 推送**

```bash
git add docs/DEPLOY.md
git commit -m "docs: 部署说明补 style_library_items 的一次性重建"
git push
```

---

## 收尾（全部任务完成后）

1. **全量验证**

```bash
source .local/env-test.sh
"$MYINK_PY" -m pytest tests/ -q
cd web && npm run lint && npm test && npm run build
```

2. **手工 E2E（浏览器只能用 Chrome / Edge）**——spec §验证 的四条：环境配置扫榜区无 MCP；文风库新建（粘文章 → 提取 → 命名 → 保存）、改名、删除、内置不可删；短篇建书三段式（回车发送、Shift+Enter 换行、聊到齐备冒选项、点开卡改字段选文风、确认直接开写并落工作台、右栏没有那三块、状态带能重试）；长篇建书选文风后「创作设置」页看到的就是那个档案。以及管理面板用户详情页手改一个不存在的 id → 显示「用户不存在」。

3. **收尾决定交给用户**：全部 commit 已推送（本次已获授权），但 PR / 合并 / 发布仍按 `AGENTS.md` 默认口径另问一次。
