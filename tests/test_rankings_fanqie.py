"""番茄榜单取数测试（integrations/fanqie.py）。全离线：假的 httpx.AsyncClient 按 side_type 分派。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from myink.integrations import fanqie
from myink.integrations.fanqie import _BASE, FanqieError


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeAsyncClient:
    """假 httpx.AsyncClient：按 params["side_type"] 取预置响应。"""

    def __init__(self, responses, *, timeout=None, headers=None):
        self.responses = responses
        self.timeout = timeout
        self.headers = headers
        self.requests: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        self.requests.append({"url": url, "params": dict(params or {})})
        item = self.responses[params["side_type"]]
        if callable(item):
            item = item()
        if isinstance(item, BaseException):
            raise item
        return item


def _install(monkeypatch, responses) -> list[FakeAsyncClient]:
    """把 fanqie.httpx 换成假模块，返回捕获到的 client 实例。"""
    seen: list[FakeAsyncClient] = []

    class Client(FakeAsyncClient):
        def __init__(self, *, timeout=None, headers=None):
            super().__init__(responses, timeout=timeout, headers=headers)
            seen.append(self)

    monkeypatch.setattr(fanqie, "httpx", SimpleNamespace(AsyncClient=Client))
    return seen


def _payload(*items) -> dict:
    return {"code": 0, "message": "success", "data": {"result": list(items)}}


def _book(name: str, **extra) -> dict:
    return {"book_id": "1", "book_name": name, "author": "作者", "hot": 1234, **extra}


# ---- 两个榜的合并与归一 ----


def test_two_boards_merge_hot_first_then_dark_horse(monkeypatch):
    seen = _install(monkeypatch, {
        10: FakeResponse(_payload(_book("甲"), _book("乙"))),
        13: FakeResponse(_payload(_book("丙"))),
    })
    rows = asyncio.run(fanqie.fetch_all(timeout=7))

    assert [r["title"] for r in rows] == ["甲", "乙", "丙"], "热门榜在前、黑马榜在后"
    assert [r["rank"] for r in rows] == [1, 2, 1], "rank 是榜内名次，两榜各自从 1 起"
    assert [r["tags"][0] for r in rows] == ["热门榜", "热门榜", "黑马榜"], "tags 首位是榜名"
    assert all(set(r) == {"rank", "title", "author", "tags", "hot"} for r in rows)

    assert len(seen) == 1, "两个榜复用同一个 client"
    assert [r["params"]["side_type"] for r in seen[0].requests] == [10, 13]
    assert all(r["url"] == _BASE for r in seen[0].requests)
    assert seen[0].requests[0]["params"] == {"aid": 13, "limit": 30, "offset": 0, "side_type": 10}
    assert seen[0].requests[1]["params"]["side_type"] == 13
    assert seen[0].timeout == 7, "timeout 透传"
    assert "User-Agent" in (seen[0].headers or {})


def test_category_v2_preferred_then_category_then_board_only(monkeypatch):
    _install(monkeypatch, {
        10: FakeResponse(_payload(
            _book("甲", category_v2=["玄幻", "热血"], category="忽略我"),
            _book("乙", category="都市,异能"),
            _book("丙", category_v2=[], category="科幻"),
            _book("丁"),
        )),
        13: FakeResponse(_payload()),
    })
    rows = asyncio.run(fanqie.fetch_all(timeout=10))

    assert rows[0]["tags"] == ["热门榜", "玄幻", "热血"], "category_v2 优先"
    assert rows[1]["tags"] == ["热门榜", "都市", "异能"], "缺 category_v2 回落 category 并按逗号切"
    assert rows[2]["tags"] == ["热门榜", "科幻"], "空 category_v2 同样回落"
    assert rows[3]["tags"] == ["热门榜"], "两者皆无 → 只剩榜名"


@pytest.mark.parametrize(("raw", "label"), [
    (12345678, "热度 1235万"),
    (10000, "热度 1万"),
    (9999, "热度 9999"),
    (0, "热度 0"),
    (None, ""),
    ("abc", ""),
    ("8765", "热度 8765"),
])
def test_heat_label(monkeypatch, raw, label):
    _install(monkeypatch, {
        10: FakeResponse(_payload(_book("甲", hot=raw))),
        13: FakeResponse(_payload()),
    })
    assert asyncio.run(fanqie.fetch_all(timeout=10))[0]["hot"] == label


# ---- 降级：单榜失败 / 两榜皆空 / 形状不符 ----


def test_single_board_http_error_drops_only_that_board(monkeypatch):
    _install(monkeypatch, {
        10: FakeResponse(None, status_code=502),
        13: FakeResponse(_payload(_book("丙"))),
    })
    rows = asyncio.run(fanqie.fetch_all(timeout=10))
    assert [r["title"] for r in rows] == ["丙"]
    assert rows[0]["tags"][0] == "黑马榜"


def test_single_board_network_error_drops_only_that_board(monkeypatch):
    _install(monkeypatch, {
        10: RuntimeError("connection reset"),
        13: FakeResponse(_payload(_book("丙"))),
    })
    assert [r["title"] for r in asyncio.run(fanqie.fetch_all(timeout=10))] == ["丙"]


def test_single_board_empty_result_drops_only_that_board(monkeypatch):
    _install(monkeypatch, {10: FakeResponse(_payload()), 13: FakeResponse(_payload(_book("丙")))})
    assert [r["title"] for r in asyncio.run(fanqie.fetch_all(timeout=10))] == ["丙"]


def test_both_boards_fail_raises_with_both_reasons(monkeypatch):
    _install(monkeypatch, {
        10: FakeResponse(None, status_code=500),
        13: RuntimeError("timeout"),
    })
    with pytest.raises(FanqieError) as exc:
        asyncio.run(fanqie.fetch_all(timeout=10))
    assert "番茄榜单不可用" in str(exc.value)
    assert "热门榜" in str(exc.value) and "黑马榜" in str(exc.value), "两榜原因都要带上"


def test_both_boards_empty_raises(monkeypatch):
    _install(monkeypatch, {10: FakeResponse(_payload()), 13: FakeResponse(_payload())})
    with pytest.raises(FanqieError, match="返回空"):
        asyncio.run(fanqie.fetch_all(timeout=10))


@pytest.mark.parametrize("payload", [
    {"code": 0, "message": "invalid client", "data": None},   # aid 非法：HTTP 200 但无 result
    {"code": 0, "message": "invalid client"},                  # 连 data 都没有
    {"code": 0, "data": {"result": "oops"}},                   # result 不是 list
    [],                                                        # 顶层形状就不对
])
def test_malformed_payload_is_a_failure_not_a_crash(monkeypatch, payload):
    _install(monkeypatch, {10: FakeResponse(payload), 13: FakeResponse(payload)})
    with pytest.raises(FanqieError):
        asyncio.run(fanqie.fetch_all(timeout=10))


def test_missing_fields_and_non_dict_items_do_not_crash(monkeypatch):
    _install(monkeypatch, {
        10: FakeResponse(_payload({}, "字符串不是条目", _book("戊"))),
        13: FakeResponse(_payload()),
    })
    rows = asyncio.run(fanqie.fetch_all(timeout=10))

    assert len(rows) == 2, "非 dict 条目跳过"
    assert rows[0] == {"rank": 1, "title": None, "author": None, "tags": ["热门榜"], "hot": ""}
    assert rows[1]["rank"] == 3, "rank 按原始下标，不因跳过而重排"


# ---- 与 sanitize 的接缝 ----


def test_rows_survive_sanitize_with_board_name_first(monkeypatch):
    from myink.integrations.rankings import sanitize

    _install(monkeypatch, {
        10: FakeResponse(_payload(_book("甲", category_v2=["玄幻"], hot=12345678))),
        13: FakeResponse(_payload(_book("丙", category_v2=["言情"], hot=999))),
    })
    items = sanitize(asyncio.run(fanqie.fetch_all(timeout=10)), limit=10)
    assert items == [
        {"title": "甲", "rank": 1, "author": "作者", "hot": "热度 1235万", "tags": ["热门榜", "玄幻"]},
        {"title": "丙", "rank": 1, "author": "作者", "hot": "热度 999", "tags": ["黑马榜", "言情"]},
    ]
