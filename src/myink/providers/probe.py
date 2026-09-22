"""模型连接探针：拉取可用模型列表 + 联通性测试（设置页「添加网络模型」闭环）。

刻意不复用 ``ModelProvider.generate``：真实 provider 内含 3 次退避重试与 120s 超时，
探针要的是「端点 + 鉴权 + 模型可达」的快速判定，单次请求、20s 超时即可。
两个函数都返回结构化结果而非抛异常，失败信息脱敏后由调用方原样透传给前端。
"""

from __future__ import annotations

import time

import httpx

from myink.config import settings
from myink.providers.errors import format_provider_error
from myink.providers.anthropic import _messages_url, _models_url

PROBE_TIMEOUT = 20.0
_ANTHROPIC_VERSION = "2023-06-01"
_PING = [{"role": "user", "content": "ping"}]

Protocol = str  # "openai" | "anthropic"（路由层已用 Literal 收敛）


def _headers(protocol: Protocol, api_key: str) -> dict[str, str]:
    if protocol == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": _ANTHROPIC_VERSION}
    return {"Authorization": f"Bearer {api_key}"}


def _chat_url(protocol: Protocol, base_url: str) -> str:
    # OpenAI 兼容与 SDK 一致：base_url 原样拼接（用户需自带 /v1）
    if protocol == "anthropic":
        return _messages_url(base_url)
    return base_url.rstrip("/") + "/chat/completions"


def _error_text(exc: Exception, api_key: str) -> str:
    return format_provider_error(exc, api_key=api_key, self_host_url=settings.self_host_url)


def _status_error(exc: httpx.HTTPStatusError, api_key: str) -> str:
    return _error_text(exc, api_key)


def list_models(protocol: Protocol, base_url: str, api_key: str) -> tuple[list[str], str | None]:
    """拉取可用模型 id（去重排序）。返回 (models, error)，error 非空时 models 为空。"""
    url = _models_url(base_url) if protocol == "anthropic" else base_url.rstrip("/") + "/models"
    try:
        with httpx.Client(timeout=PROBE_TIMEOUT) as client:
            resp = client.get(url, headers=_headers(protocol, api_key))
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return [], _status_error(exc, api_key)
    except Exception as exc:
        return [], _error_text(exc, api_key)
    rows = data.get("data") if isinstance(data, dict) else None
    ids = [str(row["id"]) for row in rows or [] if isinstance(row, dict) and row.get("id")]
    return sorted(dict.fromkeys(ids)), None


def _reply_text(protocol: Protocol, data: dict) -> str:
    """取 2xx 响应体里的 ping 回显文本（形状不合规时返回空串/抛给调用方兜底）。"""
    if protocol == "anthropic":
        return "".join(block.get("text", "") for block in data.get("content") or []
                       if isinstance(block, dict))
    choices = data.get("choices") or [{}]
    first = choices[0] if isinstance(choices[0], dict) else {}
    return (first.get("message") or {}).get("content") or ""


def test_connection(protocol: Protocol, base_url: str, api_key: str,
                    model: str) -> tuple[bool, int, str | None, str | None]:
    """发一条 max_tokens=16 的 ping 判定端点/鉴权/模型可达。返回 (ok, latency_ms, reply, error)。"""
    started = time.monotonic()
    try:
        with httpx.Client(timeout=PROBE_TIMEOUT) as client:
            resp = client.post(
                _chat_url(protocol, base_url), headers=_headers(protocol, api_key),
                json={"model": model, "max_tokens": 16, "messages": _PING},
            )
            resp.raise_for_status()
            data = resp.json()
            # 2xx 但不是 JSON 对象（误配到返回数组/字符串的端点）也走「不连通 + 可诊断」，
            # 否则 data.get 抛 AttributeError 逃出探针 → 路由 500，前端只看到「服务器错误」。
            if not isinstance(data, dict):
                raise ValueError(f"响应不是 JSON 对象: {data}")
            reply = _reply_text(protocol, data)
    except httpx.HTTPStatusError as exc:
        return False, int((time.monotonic() - started) * 1000), None, _status_error(exc, api_key)
    except Exception as exc:
        return False, int((time.monotonic() - started) * 1000), None, _error_text(exc, api_key)
    return True, int((time.monotonic() - started) * 1000), (reply or "").strip()[:200] or None, None
