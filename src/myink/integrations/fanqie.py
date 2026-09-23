"""番茄榜单取数：纯 HTTP GET（无 MCP、无鉴权、无签名）。

**所有 httpx 调用收敛在本文件**（对齐 mcp.py 的隔离思路）。外部数据不可信：本模块
只负责「拉 + 归一到 sanitize 认识的原始行」，字段清洗与上限由 rankings.sanitize
这个唯一信任边界负责。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api-lf.fanqiesdk.com/api/novel/channel/homepage/rank/rank_list/v2/"
_AID = 13
# 服务端固定每榜返回 30 条，limit 参数被忽略；offset 是真偏移。
_PAGE = 30
_BOARDS = ((10, "热门榜"), (13, "黑马榜"))
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


class FanqieError(Exception):
    """榜单接口不可用（网络失败 / 响应形状不符 / 两榜皆空）。调用方据此降级样例。"""


def _heat_label(value: Any) -> str:
    try:
        heat = int(value)
    except (TypeError, ValueError):
        return ""
    return f"热度 {heat / 10000:.0f}万" if heat >= 10000 else f"热度 {heat}"


def _board_rows(payload: Any, label: str) -> list[dict[str, Any]]:
    """单个榜的响应 → sanitize 认识的原始行。形状不符返回 []，不抛。"""
    if not isinstance(payload, dict):
        return []
    result = (payload.get("data") or {}).get("result")
    if not isinstance(result, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(result):
        if not isinstance(item, dict):
            continue
        tags = item.get("category_v2")
        if not isinstance(tags, list) or not tags:
            tags = [c for c in str(item.get("category") or "").split(",") if c]
        rows.append({
            "rank": index + 1,
            "title": item.get("book_name"),
            "author": item.get("author"),
            "tags": [label, *tags],
            "hot": _heat_label(item.get("hot")),
        })
    return rows


async def _fetch_board(client: httpx.AsyncClient, side_type: int, label: str) -> list[dict[str, Any]]:
    resp = await client.get(_BASE, params={
        "aid": _AID, "limit": _PAGE, "offset": 0, "side_type": side_type,
    })
    resp.raise_for_status()
    return _board_rows(resp.json(), label)


async def fetch_all(*, timeout: float) -> list[dict[str, Any]]:
    """两个榜各拉一页，热门榜在前、黑马榜在后。

    单榜失败只丢该榜；两榜都拿不到数据才抛 FanqieError（上层降级样例）。
    """
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": _USER_AGENT}) as client:
        for side_type, label in _BOARDS:
            try:
                rows += await _fetch_board(client, side_type, label)
            except Exception as exc:  # noqa: BLE001 - 外部接口不可信，逐榜降级
                logger.info("番茄榜取数失败（%s/%s）: %s", label, side_type, exc)
                errors.append(f"{label}: {exc}")
    if not rows:
        raise FanqieError("番茄榜单不可用" + (f"（{'；'.join(errors)}）" if errors else "（返回空）"))
    return rows
