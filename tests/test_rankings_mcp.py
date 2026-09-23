"""扫榜灵感模块测试（plan.md §10：番茄榜单 → sanitize → 建书前灵感工具 → 降级）。全离线：stub/注入，不触外网。

覆盖：
- McpClient：text 块拼平 / is_error / 无文本 / structuredContent 回退 / list_tools 归一（stub 会话鸭子类型）；
  扫榜不再走它取数（取数在 integrations/fanqie.py），客户端保留作后续接其他 MCP 工具的入口；
- sanitize：allowlist / 剥控制字符 / 字段与条数 cap / 非 dict / 无 title 丢弃 / JSON 文本输入；
- RankingsService：禁用 / TTL 缓存命中与过期 / refresh 绕过 / 榜单不可用降级 / 无有效项降级 / remote 归一；
- facade fetch_rankings：无 pid 全局入口形状（source/tool/fetched_at/error/items）；
- API：全局 /api/v1/rankings 端点 → 200 形状（RankingsOut）+ refresh 透传；缺失身份 → 403 fail closed。
  扫榜已整体前移至建书前——不注入任何生成节点（plan_messages / 图节点不再拉榜单）。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import identity_headers
from myink.api.main import app
from myink.db import new_session
from myink.integrations import fetch_rankings as facade_fetch_rankings
from myink.integrations.fanqie import FanqieError
from myink.integrations.mcp import McpClient, McpError
from myink.integrations.rankings import (
    RankingsService,
    _SAMPLE_ITEMS,
    sanitize,
)
from myink.models import User

client = TestClient(app)

# ---- 测试 stub ----


@dataclass
class FakeSettings:
    """RankingsService 注入的最小 settings（只用得到这些字段）。"""

    rankings_enabled: bool = True
    rankings_cache_ttl: float = 3600
    rankings_limit: int = 10
    rankings_timeout: int = 10


class FakeFetcher:
    """鸭子类型 fanqie.fetch_all（fetcher 注入）。"""

    def __init__(self, rows: object):
        self.rows = rows
        self.calls = 0
        self.timeouts: list[float] = []

    async def __call__(self, *, timeout):
        self.calls += 1
        self.timeouts.append(timeout)
        if isinstance(self.rows, BaseException):
            raise self.rows
        return self.rows


def _make_clock():
    t = [0.0]
    return (lambda: t[0]), t


def _service(fake, *, enabled=True, ttl=3600, limit=10, clock=None):
    st = FakeSettings(enabled, ttl, limit)
    svc = RankingsService(settings_obj=st, fetcher=fake, clock=clock or (lambda: 0.0))
    return svc, st, fake


class StubSession:
    """鸭子类型 mcp ClientSession：async 上下文管理 + initialize/list_tools/call_tool。"""

    def __init__(self, tools=None, call_result=None, call_exc=None):
        self.tools = tools or []
        self.call_result = call_result
        self.call_exc = call_exc
        self.initialized = False
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def initialize(self):
        self.initialized = True

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name=t) for t in self.tools])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.call_exc:
            raise self.call_exc
        return self.call_result


def _stub_client(session):
    async def factory():
        return session

    return McpClient("http://fake", timeout_s=1, session_factory=factory)


# ---- McpClient（stub 会话鸭子类型）----


def test_mcp_call_tool_flattens_text_blocks_and_initializes():
    session = StubSession(
        call_result=SimpleNamespace(
            isError=False,
            content=[
                SimpleNamespace(type="text", text="line1"),
                SimpleNamespace(type="text", text=""),
                SimpleNamespace(type="text", text="line2"),
            ],
        ),
    )

    async def go():
        async with _stub_client(session) as c:
            text = await c.call_tool("rank", {})
            tools = await c.list_tools()
            return text, tools

    text, tools = asyncio.run(go())
    assert session.initialized, "__aenter__ 应完成 initialize() 握手"
    assert session.calls == [("rank", {})]
    assert text == "line1\nline2", "text 块拼平、空块跳过"
    assert tools == []


def test_mcp_list_tools_normalizes_names():
    session = StubSession(tools=["qidian_rank", "web_search"])

    async def go():
        async with _stub_client(session) as c:
            return await c.list_tools()

    assert asyncio.run(go()) == ["qidian_rank", "web_search"]


def test_mcp_call_tool_is_error_raises():
    session = StubSession(call_result=SimpleNamespace(
        isError=True, content=[SimpleNamespace(type="text", text="boom")]))

    async def go():
        async with _stub_client(session) as c:
            await c.call_tool("rank", {})

    with pytest.raises(McpError, match="工具返回错误"):
        asyncio.run(go())


def test_mcp_call_tool_no_text_raises():
    session = StubSession(call_result=SimpleNamespace(isError=False, content=[]))

    async def go():
        async with _stub_client(session) as c:
            await c.call_tool("rank", {})

    with pytest.raises(McpError, match="为空"):
        asyncio.run(go())


def test_mcp_call_tool_structured_content_fallback():
    session = StubSession(call_result=SimpleNamespace(
        isError=False, content=[], structuredContent={"items": [1, 2]}))

    async def go():
        async with _stub_client(session) as c:
            return await c.call_tool("rank", {})

    assert asyncio.run(go()) == json.dumps({"items": [1, 2]}, ensure_ascii=False)


# ---- sanitize（allowlist / 剥控制字符 / cap / 丢弃）----


def test_sanitize_allowlist_and_normalizes():
    raw = {
        "items": [
            {"rank": 1, "title": "甲", "author": "张三", "tags": ["仙侠", "无敌"], "hot": "1.2万",
             "evil_key": "注入"},
            {"rank": "2", "title": "  乙\n乙  ", "author": None, "tag": "玄幻"},
            {"not_title": True},
        ]
    }
    items = sanitize(raw, limit=10)
    assert items[0] == {"rank": 1, "title": "甲", "author": "张三", "tags": ["仙侠", "无敌"], "hot": "1.2万"}
    assert "evil_key" not in items[0], "未知键丢弃（防注入）"
    assert items[1]["title"] == "乙 乙", "剥控制字符 + 压缩空白"
    assert items[1]["tags"] == ["玄幻"], "tags 缺失回退单 tag"
    assert len(items) == 2, "无 title 项丢弃"


def test_sanitize_accepts_json_string_input():
    """上游返回 JSON 文本时 sanitize 必须能解析（MCP 工具路径即为此形态）。"""
    raw = '[{"rank":1,"title":"甲","tags":["仙侠"],"evil":"x"},{"rank":2,"title":"乙"}]'
    items = sanitize(raw, limit=10)
    assert items == [{"rank": 1, "title": "甲", "tags": ["仙侠"]}, {"rank": 2, "title": "乙"}]


def test_sanitize_non_json_text_returns_empty():
    assert sanitize("工具错误文案：服务器内部错误", limit=10) == []
    assert sanitize(12345, limit=10) == []


def test_sanitize_control_chars_stripped():
    raw = [{"rank": 1, "title": "甲\x00\x1f乙\r\n", "author": "张\x07三", "hot": "12\x01万"}]
    items = sanitize(raw, limit=10)
    assert items[0]["title"] == "甲乙", "\x00/\x1f/\r 剥掉，\n 随后被 split 折叠"
    assert items[0]["author"] == "张三"
    assert items[0]["hot"] == "12万"


def test_sanitize_limit_caps():
    raw = [{"rank": i, "title": f"书{i}"} for i in range(1, 20)]
    items = sanitize(raw, limit=5)
    assert len(items) == 5
    assert items[-1]["rank"] == 5


def test_sanitize_missing_rank_backfills_by_position():
    raw = [{"title": "甲"}, {"rank": 99, "title": "乙"}]
    items = sanitize(raw, limit=10)
    assert [i["rank"] for i in items] == [1, 99], "缺 rank 按出现顺序补"


# ---- RankingsService：禁用 / 缓存 / 降级 / remote ----


def test_service_disabled_returns_sample_without_fetch():
    fake = FakeFetcher([])
    svc, st, _ = _service(fake, enabled=False)
    result = asyncio.run(svc.fetch())
    assert result.source == "sample"
    assert result.error == "RANKINGS_ENABLED=0 已禁用扫榜"
    assert result.items == _SAMPLE_ITEMS
    assert fake.calls == 0, "禁用不触上游"


def test_service_remote_returns_sanitized_items():
    fake = FakeFetcher([
        {"rank": 1, "title": "甲", "author": "张", "tags": ["热门榜", "仙侠"], "hot": "热度 1万", "evil": "x"},
        {"rank": 2, "title": "乙"},
    ])
    svc, st, _ = _service(fake)
    result = asyncio.run(svc.fetch())
    assert result.source == "remote"
    assert result.tool == "fanqie"
    assert result.fetched_at is not None
    assert result.items == [
        {"rank": 1, "title": "甲", "author": "张", "tags": ["热门榜", "仙侠"], "hot": "热度 1万"},
        {"rank": 2, "title": "乙"},
    ]
    assert fake.timeouts == [10], "超时取自 settings.rankings_timeout"


@pytest.mark.parametrize("wrapper", [lambda x: x, lambda x: {"items": x}, lambda x: json.dumps(x)])
def test_categories_in_mixed_results_are_not_books(wrapper):
    group = {"title": "男频阅读榜", "items": [{"id": "1_2_1141", "name": "西方奇幻"}]}
    assert sanitize(wrapper([group, {**group, "rank": 1}, {"title": "真实书", "author": "作者"}]), limit=10) == [
        {"title": "真实书", "author": "作者", "rank": 1}]


def test_single_category_container_is_not_expanded_into_books():
    assert sanitize({"title": "分类", "items": [{"title": "子分类"}]}, limit=10) == []


def test_invalid_categories_are_not_cached_as_remote_success():
    fake = FakeFetcher([{"title": "男频阅读榜", "items": []}])
    svc, _, _ = _service(fake)
    assert asyncio.run(svc.fetch()).source == "sample"
    fake.rows = [{"title": "真实书"}]
    assert asyncio.run(svc.fetch()).items[0]["title"] == "真实书"
    assert fake.calls == 2


def test_service_caches_within_ttl_and_refresh_bypasses():
    fake = FakeFetcher([{"rank": 1, "title": "甲"}])
    clock, t = _make_clock()
    svc, st, _ = _service(fake, clock=clock)

    r1 = asyncio.run(svc.fetch())
    assert r1.source == "remote"
    assert fake.calls == 1
    # TTL 内第二次不重打上游
    asyncio.run(svc.fetch())
    assert fake.calls == 1, "TTL 内缓存命中，不重复打上游"

    asyncio.run(svc.fetch(refresh=True))
    assert fake.calls == 2, "refresh=True 绕过缓存重拉"


def test_service_ttl_expiry_refetches():
    fake = FakeFetcher([{"rank": 1, "title": "甲"}])
    clock, t = _make_clock()
    svc, st, _ = _service(fake, ttl=100, clock=clock)

    asyncio.run(svc.fetch())
    assert fake.calls == 1
    t[0] = 100.0  # TTL 到点
    asyncio.run(svc.fetch())
    assert fake.calls == 2, "TTL 过期重新拉取"


def test_service_fanqie_error_degrades_to_sample():
    fake = FakeFetcher(FanqieError("番茄榜单不可用（热门榜: 连接超时）"))
    svc, st, _ = _service(fake)
    result = asyncio.run(svc.fetch())
    assert result.source == "sample"
    assert result.items == _SAMPLE_ITEMS
    assert "连接超时" in (result.error or "")


def test_service_unexpected_error_degrades_to_sample():
    fake = FakeFetcher(RuntimeError("神秘错误"))
    svc, st, _ = _service(fake)
    result = asyncio.run(svc.fetch())
    assert result.source == "sample"
    assert "神秘错误" in (result.error or "")


def test_service_cancelled_error_degrades_to_sample():
    # 请求挂起被取消时抛 CancelledError——BaseException，不是 Exception，
    # `except Exception` 捕不住；不加这条会直接炸图节点（真实 bug）。
    fake = FakeFetcher(asyncio.CancelledError("cancelled"))
    svc, st, _ = _service(fake)
    result = asyncio.run(svc.fetch())
    assert result.source == "sample"
    assert result.items == _SAMPLE_ITEMS
    assert "连接失败或被取消" in (result.error or "")


def test_service_no_valid_items_degrades_to_sample():
    fake = FakeFetcher([{"foo": 1}])
    svc, st, _ = _service(fake)
    result = asyncio.run(svc.fetch())
    assert result.source == "sample"
    assert "无有效项" in (result.error or "")


# ---- facade fetch_rankings（全局无 pid 入口）----


def test_facade_fetch_rankings_shape(monkeypatch):
    fake = FakeFetcher([{"rank": 1, "title": "甲"}])
    svc, st, _ = _service(fake)
    monkeypatch.setattr("myink.integrations.rankings._service", svc)
    result = asyncio.run(facade_fetch_rankings())
    assert set(result) == {"source", "tool", "fetched_at", "error", "items"}
    assert result["source"] == "remote"
    assert result["tool"] == "fanqie"
    assert result["items"][0]["title"] == "甲"


# ---- API 端点（TestClient + 身份头 / 越权矩阵）----


def _demo_user_id() -> uuid.UUID:
    with new_session() as db:
        u = db.query(User).filter(User.username == "demo").first()
        assert u is not None, "请先运行 `myink init --seed`（demo 用户未建）"
        return u.id


def _h(uid: str | uuid.UUID | None) -> dict:
    """请求头：真 HS256 Bearer（None → 不带，测 fail closed）。"""
    return identity_headers(uid)


def test_rankings_endpoint_200_shape(monkeypatch):
    async def fake(refresh=False, user_id=None):
        return {"source": "remote", "tool": "fanqie",
                "fetched_at": "2026-01-01T00:00:00+00:00", "error": None,
                "items": [{"rank": 1, "title": "甲", "author": "张", "tags": ["热门榜", "仙侠"], "hot": "热度 1万"}]}

    monkeypatch.setattr("myink.api.routes_rankings.fetch_rankings", fake)
    resp = client.get("/api/v1/rankings", headers=_h(_demo_user_id()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "remote"
    assert body["items"][0] == {"rank": 1, "title": "甲", "author": "张", "tags": ["热门榜", "仙侠"], "hot": "热度 1万"}


def test_rankings_endpoint_refresh_param_passed(monkeypatch):
    seen: list[bool] = []

    async def fake(refresh=False, user_id=None):
        seen.append(refresh)
        return {"source": "sample", "tool": "", "fetched_at": None, "error": "已禁用", "items": []}

    monkeypatch.setattr("myink.api.routes_rankings.fetch_rankings", fake)
    resp = client.get("/api/v1/rankings?refresh=true", headers=_h(_demo_user_id()))
    assert resp.status_code == 200
    assert seen == [True]


def test_rankings_endpoint_ownership():
    """身份断言（current_user fail closed，全局端点无项目归属）：缺失身份 → 403。"""
    assert client.get("/api/v1/rankings").status_code == 403
