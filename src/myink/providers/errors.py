"""Safe, bounded diagnostics shared by model probes and generation."""

from __future__ import annotations

import importlib
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError

_HTTP_MODULES = [httpx]
try:
    _HTTP_MODULES.append(importlib.import_module("httpx2"))
except ModuleNotFoundError as exc:
    if exc.name != "httpx2":
        raise


def _types(*names: str) -> tuple[type, ...]:
    return tuple(getattr(module, name) for module in _HTTP_MODULES for name in names)


_RULES = (
    (_types("ConnectError", "ConnectTimeout", "ProxyError"), "connection"),
    (_types("PoolTimeout"), "pool"),
    (_types("ReadTimeout", "WriteTimeout", "TimeoutException"), "timeout"),
    (_types("InvalidURL", "UnsupportedProtocol", "LocalProtocolError"), "config"),
    (_types("ReadError", "WriteError", "CloseError", "RemoteProtocolError"), "interrupted"),
)
_STATUS_TYPES = _types("HTTPStatusError") + (APIStatusError,)
_MESSAGES = {
    "connection": "未能连接模型服务，请检查服务地址、代理和部署网络。",
    "timeout": "模型请求超时，服务可能响应较慢，请稍后重试。",
    "pool": "等待可用连接超时，请稍后重试。",
    "config": "模型连接配置无效，请检查服务地址、协议和请求配置。",
    "interrupted": "模型通信中断或响应协议异常，请稍后重试。",
}


def _kind(exc: BaseException) -> str | None:
    for types, category in _RULES:
        if isinstance(exc, types):
            return category
    return None


def _category(exc: Exception) -> str | None:
    if not isinstance(exc, APIConnectionError):
        return _kind(exc)
    cause = exc.__cause__
    seen = {id(exc)}
    for _ in range(16):
        if cause is None or id(cause) in seen:
            break
        seen.add(id(cause))
        category = _kind(cause)
        if category:
            return category
        cause = cause.__cause__
    return "timeout" if isinstance(exc, APITimeoutError) else "connection"


def _guidance_url(raw: str) -> str:
    if any(ord(char) < 33 for char in raw):
        return ""
    try:
        parsed = urlsplit(raw)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            return ""
        parsed.port
    except ValueError:
        return ""
    return raw


def _body_detail(resp: httpx.Response) -> str:
    try:
        payload = resp.json()
    except Exception:
        return (resp.text or "").strip()
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str):
            return err
        for key in ("message", "detail", "msg"):
            if payload.get(key):
                return str(payload[key])
    return str(payload)


def _status_text(exc: Exception) -> str:
    response = exc.response
    try:
        detail = _body_detail(response)
    except Exception:
        detail = str(exc) or type(exc).__name__
    return f"模型服务返回 HTTP {response.status_code}：{detail}"


def format_provider_error(exc: Exception, *, api_key: str, self_host_url: str = "") -> str:
    if isinstance(exc, _STATUS_TYPES):
        text = _status_text(exc)
    else:
        category = _category(exc)
        text = _MESSAGES.get(category, str(exc) or type(exc).__name__)
        if category == "connection":
            url = _guidance_url(self_host_url)
            suffix = f" 自部署说明：{url}" if url else ""
            if len(text + suffix) <= 300:
                text += suffix
    if api_key:
        text = text.replace(api_key, "***")
    return text[:300]
