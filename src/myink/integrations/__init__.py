"""外部集成（plan.md §10）：扫榜能力 + MCP 客户端。

- `fanqie.py`：番茄榜单取数（所有 httpx 调用隔离在此）；
- `rankings.py`：扫榜域封装（sanitize + 缓存 + 降级），对外暴露 `fetch_rankings`
  （async，API）。扫榜已整体前移至建书前的灵感工具，不再有 sync 图节点入口。
- `mcp.py`：MCP 协议客户端薄封装（所有 mcp SDK import 的隔离点）。扫榜不再经它取数，
  留作后续接其他 MCP 工具的入口。
"""

from myink.integrations.rankings import fetch_rankings

__all__ = ["fetch_rankings"]
