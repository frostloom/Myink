"""粗粒度限流（网关退役后由 Python 接管）。

两层，对应网关原有的两个限流器：

- :class:`GlobalRateLimit` —— 进程内令牌桶，等价 ``limiter.Middleware``。防外部刷接口。
- :func:`auth_rate_limit` —— 按客户端 IP 分桶的登录/注册/改密限流，等价 ``AuthRateLimit``。

细粒度配额/并发/日成本仍然走 ``gates.lua``（§13），不在这里——那是按用户计账，
这里的两个纯粹是防滥用的。uvicorn 目前单进程（``main.py`` 的 ``uvicorn.run`` 没有
``workers=``），所以进程内桶与网关的行为一致；将来加 ``workers=`` 会让额度翻倍。
"""

from __future__ import annotations

import hashlib
import ipaddress
import time

from fastapi import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from myink.config import settings
from myink.worker.redis_client import get_redis

# 窗口与上限原先与网关 auth.go 的 `EXPIRE ... 60` / `n > 20` 同源。写成模块常量而不是
# 配置项，是因为当初要两端逐字对齐；网关退场后仍是常量——这两条不该随手调。
AUTH_RATE_WINDOW = 60
AUTH_RATE_MAX = 20

# 沿用网关 auth.go 的内联脚本（键名与窗口不变）：切流时在途计数直接接续，
# 不会给暴力破解留一个「计数清零」的缝。
_AUTH_WINDOW_LUA = (
    "local n=redis.call('INCR',KEYS[1]); "
    "if n==1 then redis.call('EXPIRE',KEYS[1],60) end; "
    "return n"
)


class ApiError(Exception):
    """带 ``{"error": CODE}`` 信封的 HTTP 错误。

    FastAPI 的 ``HTTPException`` 渲染成 ``{"detail": ...}``，而前端只认 ``error`` 键
    （见 ``web/src/lib/apiError.ts`` 的 ``GATE_CODES``），所以网关时代的错误码必须走这条路。
    """

    def __init__(self, status_code: int, code: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.headers = headers or {}


def client_ip(request: Request) -> str:
    """客户端地址，取自边缘盖章的 ``X-Myink-Client-IP``；没有则退回直连地址。

    客户端自己伪造这个头没用：Caddy 用 ``header_up``（是「设置」不是「追加」）覆盖写入，
    伪造值会被抹掉。Python 不对宿主发布端口，这个头只可能来自边缘。

    ⚠️ 若将来在 Caddy 前面再挂一层（CDN），``{http.request.remote.host}`` 会变成那层的
    地址，**所有用户塌进同一个限流桶**。正确改法是 Caddy 全局 ``trusted_proxies`` +
    ``{client_ip}``，不是在这里加环境变量。
    """
    raw = request.headers.get("x-myink-client-ip", "").strip()
    if raw:
        try:
            ipaddress.ip_address(raw)
            return raw
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def auth_rate_limit(request: Request) -> None:
    """登录/注册/改密的按 IP 限流（FastAPI 依赖，挂在三条路由上）。

    Redis 不可用时失败关闭（503）：这个限流器挡的是密码爆破，放行等于敞开。
    """
    key = "rate:auth:" + hashlib.sha256(client_ip(request).encode()).hexdigest()
    try:
        count = get_redis().eval(_AUTH_WINDOW_LUA, 1, key)
    except Exception:
        raise ApiError(503, "auth_unavailable")
    if not isinstance(count, int) or isinstance(count, bool) or count > AUTH_RATE_MAX:
        raise ApiError(429, "auth_rate_limited", {"Retry-After": str(AUTH_RATE_WINDOW)})


class GlobalRateLimit:
    """纯 ASGI 令牌桶。

    刻意不用 ``BaseHTTPMiddleware``：那个在路由之后才跑，而且会经手响应体——本服务要接
    SSE，缓冲响应体意味着事件攒到最后一次性吐出。纯 ASGI 只在请求进门时插一句，不碰 body。

    桶是单实例的（一个中间件对象一个桶），因此限的是**整个进程**的总速率，与网关一致。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._tokens = float(settings.rate_burst)
        self._updated = time.monotonic()

    def _allow(self) -> bool:
        # 每次请求都现读配置：测试要把额度抬到无穷大，而桶是在导入期构造的。
        rate, burst = float(settings.rate_per_sec), float(settings.rate_burst)
        now = time.monotonic()
        self._tokens = min(burst, self._tokens + (now - self._updated) * rate)
        self._updated = now
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._allow():
            await self.app(scope, receive, send)
            return
        body = b'{"error":"rate_limited"}'
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
