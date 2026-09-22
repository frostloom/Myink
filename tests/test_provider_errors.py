import importlib

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from myink.providers.errors import format_provider_error


HTTP_MODULES = [httpx]
try:
    HTTP_MODULES.append(importlib.import_module("httpx2"))
except ModuleNotFoundError:
    pass


@pytest.mark.parametrize("module", HTTP_MODULES)
@pytest.mark.parametrize("name,expected", [
    ("ConnectError", "未能连接模型服务"),
    ("ConnectTimeout", "未能连接模型服务"),
    ("ProxyError", "未能连接模型服务"),
    ("ReadTimeout", "模型请求超时"),
    ("WriteTimeout", "模型请求超时"),
    ("PoolTimeout", "等待可用连接超时"),
    ("InvalidURL", "模型连接配置无效"),
    ("UnsupportedProtocol", "模型连接配置无效"),
    ("LocalProtocolError", "模型连接配置无效"),
    ("ReadError", "模型通信中断"),
    ("WriteError", "模型通信中断"),
    ("CloseError", "模型通信中断"),
    ("RemoteProtocolError", "模型通信中断"),
])
def test_real_transport_types(module, name, expected):
    exc = getattr(module, name)("https://private.invalid/sk-secret")
    result = format_provider_error(exc, api_key="sk-secret")
    assert expected in result
    assert "private.invalid" not in result
    assert "sk-secret" not in result


@pytest.mark.parametrize("module", HTTP_MODULES)
@pytest.mark.parametrize("name,expected", [
    ("ReadTimeout", "模型请求超时"),
    ("InvalidURL", "模型连接配置无效"),
    ("ConnectError", "未能连接模型服务"),
])
def test_sdk_wrapper_uses_specific_cause(module, name, expected):
    exc = APIConnectionError(request=httpx.Request("POST", "https://example.test"))
    exc.__cause__ = getattr(module, name)("secret")
    assert expected in format_provider_error(exc, api_key="secret")


def test_sdk_defaults_and_cyclic_cause():
    req = httpx.Request("POST", "https://example.test")
    exc = APIConnectionError(request=req)
    middle = RuntimeError("opaque")
    exc.__cause__ = middle
    middle.__cause__ = exc
    assert "未能连接模型服务" in format_provider_error(exc, api_key="")
    assert "模型请求超时" in format_provider_error(APITimeoutError(req), api_key="")
    for _ in range(30):
        outer = RuntimeError("opaque")
        outer.__cause__ = middle
        middle = outer
    exc.__cause__ = middle
    assert "未能连接模型服务" in format_provider_error(exc, api_key="")
    value_error = ValueError("invalid JSON")
    value_error.__cause__ = httpx.ConnectError("irrelevant")
    assert format_provider_error(value_error, api_key="") == "invalid JSON"


@pytest.mark.parametrize("status", [401, 402, 404, 429, 500, 503])
@pytest.mark.parametrize("sdk", [False, True])
def test_status_preserves_reason_without_network_hint(status, sdk):
    req = httpx.Request("POST", "https://example.test")
    response = httpx.Response(status, request=req, json={"error": {"message": "quota sk-secret"}})
    exc = (APIStatusError("denied", response=response, body=response.json()) if sdk
           else httpx.HTTPStatusError("denied", request=req, response=response))
    result = format_provider_error(exc, api_key="sk-secret", self_host_url="https://docs.test/deploy")
    assert str(status) in result and "quota ***" in result
    assert "sk-secret" not in result and "docs.test" not in result


@pytest.mark.parametrize("url", ["", "javascript:alert(1)", "ftp://example.test", "https://user:pass@example.test", "https://", "https://[bad", "https://example.test:bad", "https://example.test/\nsecret"])
def test_invalid_guidance_omitted(url):
    result = format_provider_error(httpx.ConnectError("private"), api_key="", self_host_url=url)
    assert "自部署" not in result


def test_guidance_and_redaction_before_limit():
    result = format_provider_error(httpx.ConnectError("private"), api_key="", self_host_url="https://docs.test/deploy")
    assert "https://docs.test/deploy" in result
    secret = "sk-secret-value"
    result = format_provider_error(ValueError("x" * 295 + secret), api_key=secret)
    assert len(result) <= 300 and "sk-" not in result and "***" in result
    assert format_provider_error(ValueError(), api_key="") == "ValueError"
