# 模型连接错误与可见反馈 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if the user chooses delegated execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让模型列表、连接测试与真实写作失败都返回安全、可操作的错误，并让模型连接页的操作反馈不受滚动位置影响。

**Architecture:** 一个无网络副作用的错误格式化模块复用现有字符串契约，分别接入探针、OpenAI 兼容和 Anthropic 同步/流式出口。模型连接页使用小型视口通知与字段定位，不改全站布局、不建立全站通知服务。

**Tech Stack:** Python、httpx、现有 OpenAI SDK；React 19、TypeScript、CSS Modules、Vitest、Testing Library。不新增依赖。

**Spec:** `docs/superpowers/specs/2026-09-22-provider-errors-design.md`。本计划和设计必须一起阅读。

状态：用户已认可，三个任务的代码已实现；下列代码块保留为原计划，最终以源文件及验收记录为准。

## 实施验收记录（2026-09-22）

- 任务 1：`b7d88ad`，相关测试 65 项通过，Python 全量 959 passed / 5 xfailed；[CI 三项成功](https://github.com/frostloom/Myink/actions/runs/35741711007)。
- 任务 2：`b4556be`，相关测试 28 项通过，Python 全量 965 passed / 5 xfailed；[CI 三项成功](https://github.com/frostloom/Myink/actions/runs/35743467331)。
- 任务 3 与最终修正：交互测试 10 项通过；前端全量 251 项通过，lint/build 成功；Python 全量 969 passed / 5 xfailed。最终 CI 以 GitHub 对应提交 SHA 的结果为准。
- 独立复核发现两项 Important，均已通过新增测试 RED→GREEN 修复：非对象 JSON 不再提前截断测试密钥；通知区域已滚动时新增/更新消息会回到可见位置。未遗留未处理的重要问题。
- 无头 Edge 实测：长页面等待后错误仍在视口；不同连接错误保留；375px 下通知长文无横向溢出；通知区滚到底后新错误仍可见；Escape 关闭恢复焦点；首个错误字段定位；保存失败保留草稿；关闭不重发、手动重试只请求一次。全部 API 请求受控拦截，未调用付费模型。
- 小屏验收仅覆盖本次通知组件；原页面的桌面最小宽度仍存在，不将本次结果表述为全站移动适配完成。
- 沿用既有 6 条前端 lint warning、>500kB chunk warning，以及故意测试 HS512 错误算法时的短测试密钥 warning，没有把警告冒充不存在。
- 未重建正式 API/worker/Caddy；源码提交不等于正式容器已经更新。
- 执行调整：后续任务可在前一 CI 运行时实施，但前一 CI 成功前不再推送；前端异常测试按实际 status/code/body 契约修正；按用户要求保留执行记录与 worktree，不做删除清理。

## Global Constraints

- 不改变登录、租户隔离、数据库结构、队列路由、模型选择、重试次数、退避、降级顺序或流式 reset 语义。
- Jev、局部修订、短篇、榜单换源各自独立，不捆绑实施。
- 不新增幼稚、重复或显而易见的说明。必要的操作指引、格式约束和风险说明可以常驻，文字保持简短。
- 保留必要弹窗和通知；本次模型连接操作使用非模态通知。建书阻断弹窗在建书目标中完成，不在此处扩展。
- 错误最终最多 300 字符；已知 API Key 脱敏先于截断；网络错误不输出底层 URL、IP、请求头或异常原文。
- `SELF_HOST_URL` 默认空字符串，仅连接建立失败可附加；只接受无用户名密码的 HTTP(S) URL，不主动访问它。
- 优先复用现有 React、CSS Modules、设计变量和弹窗模式；不更换框架、字体或整页布局，不新增无关视觉效果。
- 不修改 `.env`、不删除容器/卷、不使用 `down -v`、`prune`、数据库清理或 Git 强制覆盖。
- 不纳入已有未跟踪的 `AGENTS.md`、`docs/BACKLOG.md`、`docs/team-workflow.md`、`gateway/`。
- 每个独立目标验证后提交、推送，核对该 SHA 的 GitHub CI；未运行、跳过或被阻塞的检查不能写成通过。

## Review Focus

1. SDK 外层统一成连接错误，但底层实际是读超时或地址配置问题：任务 1 用真实 SDK 包装异常验证具体原因优先。
2. cause 链循环、超深或含无关异常：任务 1 限深防环；不把普通 ValueError 的 cause 当成网络根因。
3. 密钥跨过截断边界，上游状态正文包含密钥：任务 1 先脱敏再截断，状态码放在诊断前端。
4. 流式已输出正文后断线：任务 2 验证调用次数、退避与 reset 不变，返回和日志均不泄密。
5. 发起探针后滚动、另一连接同时失败、关闭提示后重试：任务 3 保留不同连接的反馈、可键盘关闭、不丢表单、不重复发送。

## 文件边界与交付顺序

| 任务 | 文件 | 职责 |
|---|---|---|
| 1 | `src/myink/providers/errors.py`（新） | 类型分类、安全格式化、状态正文提取 |
| 1 | `src/myink/providers/probe.py`、`src/myink/config.py`、`.env.example` | 接入探针、可选部署指引配置 |
| 1 | `tests/test_provider_errors.py`（新）、`tests/test_model_probe.py` | 分类、脱敏、探针行为 |
| 2 | `src/myink/providers/deepseek.py`、`src/myink/providers/anthropic.py` | 四个真实调用出口接入 |
| 2 | `tests/test_provider_error_integration.py`（新） | SDK/HTTP 调用、日志、重试和流式回归 |
| 3 | `web/src/components/ConnectionNotices.tsx`、同名 `.module.css`、`.test.tsx`（新） | 仅连接页消费的可关闭通知 |
| 3 | `web/src/pages/EnvironmentPage.tsx`、`.test.tsx`、`SettingsPage.module.css` | 结果接入、字段错误定位 |

三个任务各自形成可验证的小提交。按任务顺序推进，避免后续推送取消上一目标的 CI。现有 CI 只监听 main push 和 PR：若执行时使用 worktree 分支，应在审核与本地验证后按既有用户授权进行非强制集成，或使用 PR 触发；不能把无人触发的分支推送当成 CI 已通过。

## 验证环境

执行前按 `superpowers:using-git-worktrees` 建立隔离工作区；复制本计划与设计，不复制用户未跟踪文件。端口和服务不会被 worktree 隔离：不得并发跑使用相同资源的完整测试。

本机已核实的测试资源是 `myink-auth-test-postgres-1`（15432）、`myink-auth-test-redis-1`（16380）、`myink-auth-test-rabbitmq-1`（15673）。启动或初始化前重新 inspect，确保不是正式服务；不依赖上一轮测试状态。只启动/停止这些已确认的测试容器，不移除它们和卷。

Python 命令运行前，在当前 PowerShell 进程设置：

```powershell
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:DATABASE_URL='postgresql+psycopg://myink_app:myink@127.0.0.1:15432/myink'
$env:ADMIN_DATABASE_URL='postgresql+psycopg://myink:myink@127.0.0.1:15432/myink'
$env:REDIS_URL='redis://127.0.0.1:16380/0'
$env:AMQP_URL='amqp://myink:myink@127.0.0.1:15673/'
$env:APP_ENV='test'
$env:EMBED_ENABLED='0'
$env:RANKINGS_ENABLED='0'
$env:JWT_SECRET='test-jwt-secret-at-least-32-bytes-long'
```

不要在正式数据库运行 `tests/conftest.py` 的 fixture。本文中的新测试不调用付费模型。

---

### Task 1: 共享错误格式化与探针

**Interfaces:**

- Produces: `format_provider_error(exc: Exception, *, api_key: str, self_host_url: str = "") -> str`。
- Consumes: 现有 `httpx` 和 `openai` 公共异常类型；`Settings.self_host_url: str`。
- `list_models` 和 `test_connection` 参数与返回 tuple 保持不变。

- [ ] **1. 写类型分类、SDK 包装和安全边界的失败测试。** 新建 `tests/test_provider_errors.py`，从以下测试开始；HTTP 库矩阵用真实已安装类型，不自己定义同名伪异常：

```python
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
```

- [ ] **2. 执行 RED。** `python -m pytest tests/test_provider_errors.py -q -p no:cacheprovider`。应因新模块不存在失败，不因数据库指向错误或测试依赖缺失而宣称 RED 完成。

- [ ] **3. 实现共享模块。** 下面是具体边界算法；将现有 `probe._body_detail` 移到此模块为 `_body_detail`，保留 JSON `error.message/error/message/detail/msg` 与纯文本提取顺序。`_status_text` 读不到流式正文时使用安全的异常说明，不读取网络流、不新增请求。

```python
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
```

`_MESSAGES.get` 的默认表达式仍会求值，但不输出网络异常原文。无需加入复杂异常反射或依据错误文字猜测地区。

- [ ] **4. 接入配置与探针，写真实 transport 测试。** `Settings` 增加 `self_host_url: str = field(default_factory=lambda: _env("SELF_HOST_URL", "") or "")`；`.env.example` 增加 `SELF_HOST_URL=` 与一行“可选自部署说明地址，仅模型连接失败时展示”。不更改真实 `.env`。

删除 `probe.py` 内已移出的 `_body_detail` 与重复的 `_sanitize`、上限常量；保留两个内部包装方法以最小化出口差异：

```python
from myink.config import settings
from myink.providers.errors import format_provider_error


def _error_text(exc: Exception, api_key: str) -> str:
    return format_provider_error(exc, api_key=api_key, self_host_url=settings.self_host_url)


def _status_error(exc: httpx.HTTPStatusError, api_key: str) -> str:
    return _error_text(exc, api_key)
```

在已有 `test_probe_error_redacts_api_key` 中保留“不含 secret”断言，把必须出现 `***` 的旧断言改为 `assert "未能连接模型服务" in error`：网络原文完全不输出也是正确脱敏。新增以下矩阵，使用当前文件的 `_patch_client`：

```python
@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
@pytest.mark.parametrize("operation", ["models", "test"])
def test_connection_failure_is_actionable(monkeypatch, protocol, operation):
    def handler(request):
        raise httpx.ConnectError("private host sk-secret", request=request)
    _patch_client(monkeypatch, handler)
    if operation == "models":
        models, error = probe.list_models(protocol, "https://example.test/v1", "sk-secret")
        assert models == []
    else:
        ok, latency, reply, error = probe.test_connection(protocol, "https://example.test/v1", "sk-secret", "test")
        assert not ok and latency >= 0 and reply is None
    assert "未能连接模型服务" in error
    assert "private host" not in error and "sk-secret" not in error
```

为该文件补 `import pytest`。保留现有成功、响应体与非对象 JSON 的全部测试。

- [ ] **5. GREEN 与提交。** 运行新文件、`tests/test_model_probe.py`、`tests/test_environment_routes.py`，随后 Python 全量；运行 `git diff --check`。只暂存任务 1 文件与本设计/计划，提交 `feat: explain model probe failures safely`。推送并核对该 SHA 的三项 CI；记录实际结果后进入任务 2。

### Task 2: 真实写作的同步、流式出口一致化

**Interfaces:** 消费任务 1 的 `format_provider_error` 和 `settings.self_host_url`；`ModelResponse` 类型和 provider 构造参数不变。`OpenAICompatibleProvider` 继承 DeepSeek 实现，不另加一条错误路径。

- [ ] **1. 写四路径失败测试。** 新建 `tests/test_provider_error_integration.py`：

```python
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIConnectionError

from myink.providers import anthropic, deepseek


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
@pytest.mark.parametrize("stream", [False, True])
def test_generation_error_is_safe_and_retry_count_unchanged(monkeypatch, caplog, kind, stream):
    module = deepseek if kind == "openai" else anthropic
    cls = deepseek.DeepSeekProvider if kind == "openai" else anthropic.AnthropicProvider
    provider = cls(api_key="sk-secret", base_url="https://example.test")
    provider._client.close()
    req = httpx.Request("POST", "https://example.test")
    exc = httpx.ConnectError("private host sk-secret", request=req)
    if kind == "openai":
        wrapped = APIConnectionError(request=req)
        wrapped.__cause__ = exc
        exc = wrapped
    fail = Mock(side_effect=exc)
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fail)), post=fail, stream=fail,
    )
    sleep = Mock()
    monkeypatch.setattr(module.time, "sleep", sleep)
    resets = Mock()
    kwargs = {"model_id": "test-model"}
    with caplog.at_level("WARNING", logger=module.__name__):
        if stream:
            result = provider.generate_stream([{"role": "user", "content": "test"}], on_delta=Mock(), on_reset=resets, **kwargs)
        else:
            result = provider.generate([{"role": "user", "content": "test"}], **kwargs)
    assert "未能连接模型服务" in result.error
    assert "sk-secret" not in result.error + caplog.text
    assert "private host" not in result.error + caplog.text
    assert fail.call_count == 4
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0, 4.0]
    assert resets.call_count == 0
```

再加入真实“已输出然后断线”测试，避免仅在 create 前抛异常的假覆盖：

```python
@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_partial_stream_still_resets_on_each_failure(monkeypatch, kind):
    module = deepseek if kind == "openai" else anthropic
    cls = deepseek.DeepSeekProvider if kind == "openai" else anthropic.AnthropicProvider
    provider = cls(api_key="sk-secret", base_url="https://example.test")
    provider._client.close()
    error = httpx.ReadError("sk-secret private host")

    def chunks():
        delta = SimpleNamespace(content="正文", reasoning_content=None, reasoning_details=None, tool_calls=None)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)
        raise error

    def lines():
        yield 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"正文"}}'
        raise error

    @contextmanager
    def stream_response(*args, **kwargs):
        yield SimpleNamespace(raise_for_status=lambda: None, iter_lines=lines)

    create = Mock(side_effect=lambda **kwargs: chunks())
    stream = Mock(side_effect=stream_response)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), stream=stream)
    monkeypatch.setattr(module.time, "sleep", Mock())
    resets, deltas = Mock(), Mock()
    result = provider.generate_stream([{"role":"user", "content":"test"}], model_id="test", on_delta=deltas, on_reset=resets)
    assert resets.call_count == 4 and deltas.call_count == 4
    assert (create if kind == "openai" else stream).call_count == 4
    assert "模型通信中断" in result.error and "sk-secret" not in result.error
```

若实际流式接口读取更多公开 chunk 字段，按当前 `generate_stream` 补齐测试值；不得为了让假对象通过改动生产流式逻辑。

- [ ] **2. 执行 RED。** `python -m pytest tests/test_provider_error_integration.py -q -p no:cacheprovider`，确认失败原因是旧错误内容/日志，而非未适配 mock。

- [ ] **3. 四个出口仅替换字符串生成。** 在两个 provider 模块中导入配置和共享 formatter；将同步与流式 `except Exception as exc` 的 `last_error = str(exc)` 改成：

```python
last_error = format_provider_error(
    exc, api_key=self._api_key, self_host_url=settings.self_host_url,
)
```

原 warning 保持记录 `last_error`，不加 `exc_info=True`。其余循环、计时、请求参数、fallback、reset 代码不动。检查 `rg -n 'last_error =|logger.warning' src/myink/providers/deepseek.py src/myink/providers/anthropic.py`，应恰好四个格式化出口。

- [ ] **4. GREEN、回归与提交。** 运行新测试、`tests/test_custom_providers.py`、`tests/test_streaming.py`、`tests/test_model_probe.py` 和 Python 全量，原有降级顺序测试不能删除或降格。审核 diff 后只提交任务 2 文件：`fix: sanitize model generation failures consistently`，推送并核对同一 SHA 的三项 CI。

### Task 3: 模型连接页可见反馈与必要指引

**Interfaces:**

- 新组件 `ConnectionNotices({items, onDismiss})`，`items: ConnectionNotice[]`，`onDismiss(id: string): void`。
- `ConnectionNotice = { id: string; tone: 'error' | 'ok'; text: string; returnFocus: HTMLElement | null }`。
- 页面 `notify(id, tone, text)` 以操作对象 id 更新本对象反馈，不覆盖别的连接；通知没有“自动重试”。
- API 请求/返回类型不变。字段 `name | base_url | model | api_key` 的校验错误定位到本卡片。

**前端审查结论：** 当前 React/CSS Modules 无通用通知依赖；连接错误在卡片与保存行，异步结束时用户可能已经滚动离开。沿用现有文字、边框与主题变量；通知背景采用不透明 `--surface-2`，避免文字与后方内容重叠。保留 API Key 留空保留等必要指引，不添加欢迎、教学或部署推广段落。

- [ ] **1. 写通知与页面行为失败测试。** `ConnectionNotices.test.tsx`：

```tsx
// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ConnectionNotices } from './ConnectionNotices'

afterEach(cleanup)

it('keeps errors from separate connections without taking focus', () => {
  const trigger = document.createElement('button')
  document.body.append(trigger)
  trigger.focus()
  const dismiss = vi.fn()
  render(<ConnectionNotices items={[
    { id: 'a', tone: 'error', text: '连接 A：请求超时', returnFocus: trigger },
    { id: 'b', tone: 'error', text: '连接 B：额度不足', returnFocus: trigger },
  ]} onDismiss={dismiss} />)
  expect(screen.getAllByRole('alert')).toHaveLength(2)
  expect(document.activeElement).toBe(trigger)
  const close = screen.getAllByRole('button', { name: '关闭通知' })[0]
  close.focus()
  fireEvent.keyDown(close, { key: 'Escape' })
  expect(dismiss).toHaveBeenCalledExactlyOnceWith('a')
  expect(document.activeElement).toBe(trigger)
  trigger.remove()
})
```

在 `EnvironmentPage.test.tsx` 使用现有 `emptyEnv/renderPage/api` 测试 setup，加失败保存测试：

```tsx
it('keeps the draft and presents failed saves in the notification region', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue({ ...emptyEnv, model_connections: [{
    id: 'test', name: '连接 A', protocol: 'openai', base_url: 'https://example.test/v1',
    model: 'writer', has_api_key: true,
  }] })
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.updateEnvironment).mockRejectedValue(new Error('保存失败'))
  renderPage()
  const name = await screen.findByLabelText('连接名称')
  fireEvent.change(name, { target: { value: '新名称' } })
  fireEvent.click(screen.getByRole('button', { name: '保存连接与路由' }))
  const notice = await screen.findByRole('alert')
  expect(notice.textContent).toContain('保存失败')
  expect(screen.getByRole('region', { name: '模型连接通知' }).contains(notice)).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '关闭通知' }))
  expect((name as HTMLInputElement).value).toBe('新名称')
  expect(api.updateEnvironment).toHaveBeenCalledTimes(1)
})
```

现有缺字段测试改为断言 `document.activeElement === screen.getByLabelText('连接名称')`、`aria-invalid="true"`、关联错误包含“连接名称”，保留 API 未调用断言。成功探针测试保留模型列表与耗时断言；新增 `mockResolvedValue({ok:false,models:[],error:'服务拒绝'})` 和 `testConnection` reject 两种返回，均断言通知区可见错误且关闭不再请求。

- [ ] **2. 执行 RED。** 在 `web` 运行 `npm test -- src/components/ConnectionNotices.test.tsx src/pages/EnvironmentPage.test.tsx`。

- [ ] **3. 实现非模态通知组件。** 不注册全局 Escape，不移动输入焦点；仅当用户在通知里操作关闭时恢复到仍存在且可用的触发控件：

```tsx
import { createPortal } from 'react-dom'
import styles from './ConnectionNotices.module.css'

export type ConnectionNotice = {
  id: string
  tone: 'error' | 'ok'
  text: string
  returnFocus: HTMLElement | null
}

export function ConnectionNotices({ items, onDismiss }: {
  items: ConnectionNotice[]
  onDismiss: (id: string) => void
}) {
  return createPortal(
    <section className={styles.region} aria-label="模型连接通知">
      {items.map((item) => (
        <div className={styles.notice} key={item.id} data-tone={item.tone}
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return
            event.stopPropagation()
            onDismiss(item.id)
            if (item.returnFocus?.isConnected) item.returnFocus.focus()
          }}>
          <div role={item.tone === 'error' ? 'alert' : 'status'} aria-atomic="true">{item.text}</div>
          <button type="button" className="btn btn-quiet" aria-label="关闭通知"
            onClick={() => {
              onDismiss(item.id)
              if (item.returnFocus?.isConnected) item.returnFocus.focus()
            }}>关闭</button>
        </div>
      ))}
    </section>, document.body,
  )
}
```

```css
.region {
  position: fixed;
  z-index: 900; /* 高于正文，低于现有 GuestPromptDialog 的 1000 */
  inset-inline-end: max(16px, env(safe-area-inset-right));
  bottom: max(16px, env(safe-area-inset-bottom));
  width: min(26rem, calc(100vw - 32px));
  max-height: 45dvh;
  overflow-y: auto;
  display: grid;
  gap: 8px;
}
.notice {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--line-strong);
  border-inline-start: 3px solid var(--success);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--ink);
  box-shadow: var(--shadow-soft);
  font-size: var(--text-body);
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.notice[data-tone='error'] { border-inline-start-color: var(--error); }
.notice > div { flex: 1; min-width: 0; }
.notice > button { flex: none; }
```

通知均不自动消失。新通知追加到可见区域顶端，避免队列底部不可见；同连接的后续操作更新原条目。关闭按钮沿用 `.btn` focus-visible，实际浏览器验证样式和焦点。

- [ ] **4. 页面接入通知。** 导入新组件与类型；新增状态和方法：

```tsx
const [notices, setNotices] = useState<ConnectionNotice[]>([])

function notify(id: string, tone: 'error' | 'ok', text: string, returnFocus: HTMLElement | null) {
  setNotices((previous) => [
    { id, tone, text, returnFocus }, ...previous.filter((item) => item.id !== id),
  ])
}
```

在页面根 JSX 渲染 `<ConnectionNotices items={notices} onDismiss={(id) => setNotices((items) => items.filter((item) => item.id !== id))} />`。每个 async handler 在请求前捕获 `const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null`，避免等待结束后错误地记录用户新焦点。

`fetchModels` 和 `runTest` 的成功/业务失败分支分别添加如下调用，保留原 `setProbes`：

```tsx
// fetchModels 中拿到 res 后
notify(`probe:${draft.id}`, res.ok ? 'ok' : 'error',
  `${draft.name.trim() || '模型连接'}：${res.ok ? `已获取 ${res.models.length} 个模型` : (res.error ?? '获取模型列表失败')}`,
  returnFocus)

// runTest 中拿到 res 后
notify(`probe:${draft.id}`, res.ok ? 'ok' : 'error',
  `${draft.name.trim() || '模型连接'}：${res.ok ? `连接正常 · ${res.latency_ms} ms` : (res.error ?? '连接测试失败')}`,
  returnFocus)
```

两个 catch 分别用 `formatApiError(err, '获取模型列表失败')` / `formatApiError(err, '连接测试失败')` 调用 `notify`，并保留卡片状态。通知承担 live region，卡片原状态不再重复朗读；测试使用 `within(screen.getByRole('region', {name:'模型连接通知'}))` 定位通知，避免双处展示造成模糊查询。

`saveRoutes` 的请求失败分支用 `notify('save', 'error', formatApiError(err), returnFocus)`；成功用 `notify('save', 'ok', '模型连接与路由已保存', returnFocus)`，不弹模态框。MCP 保存/测试保持原状。

- [ ] **5. 校验定位与必要指引。** 新增字段错误状态，用稳定 id 和 ref 绑定，不以 CSS 选择器拼接用户输入：

```tsx
type ConnectionField = 'name' | 'base_url' | 'model' | 'api_key'
type FieldProblem = { key: string; text: string } | null
const [fieldProblem, setFieldProblem] = useState<FieldProblem>(null)
const fieldRefs = useRef(new Map<string, HTMLInputElement>())

function rejectField(id: string, field: ConnectionField, text: string) {
  const key = `${id}:${field}`
  setFieldProblem({ key, text })
  setBusy(null)
  fieldRefs.current.get(key)?.focus()
  fieldRefs.current.get(key)?.scrollIntoView({ block: 'center', behavior: 'auto' })
  return false
}

function fieldAttributes(id: string, field: ConnectionField) {
  const key = `${id}:${field}`
  return {
    ref: (element: HTMLInputElement | null) => {
      if (element) fieldRefs.current.set(key, element)
      else fieldRefs.current.delete(key)
    },
    'aria-invalid': fieldProblem?.key === key || undefined,
    'aria-describedby': fieldProblem?.key === key ? `error-${key}` : undefined,
  }
}

function fieldMessage(id: string, field: ConnectionField) {
  const key = `${id}:${field}`
  return fieldProblem?.key === key
    ? <span id={`error-${key}`} className={styles.fieldError}>{fieldProblem.text}</span>
    : null
}
```

补 `useRef` import。对四个 input 分别 spread `fieldAttributes(connection.id, 'name'/'base_url'/'model'/'api_key')` 并在对应 input 后渲染 `fieldMessage`；名称输入用小容器包裹错误使协议下拉不被挤开。CSS `.fieldError { color: var(--ink); font-size: var(--text-small); line-height: 1.5; }`，错误 input 使用现有边框语义色，不靠低对比红色小字承担信息。

`saveRoutes` 原 missing 汇总改为按 name/base_url/model 依次 `rejectField`，URL 解析失败指向 base_url，密钥缺失指向 api_key；`probeReady` 的三个校验对应 base_url/model/api_key。示例替换：

```tsx
if (!name) return rejectField(draft.id, 'name', '请填写连接名称')
if (!baseUrl) return rejectField(draft.id, 'base_url', '请填写请求地址')
if (!model) return rejectField(draft.id, 'model', '请填写模型 id')
```

进入保存/探针前 `setFieldProblem(null)`；修改对应字段时清掉它的旧错误。去掉仅由模型操作消费的旧 `connMsg` 状态和保存行消息，`rankMsg` 不动。保留“已保存，留空即保留”、实际字段格式/风险说明；不因“常驻”而删除。测试环境 `scrollIntoView` 通过 spy 替身断言调用，不冒充真实滚动。

- [ ] **6. GREEN 与真实浏览器验收。** `web` 运行 `npm run lint`、`npm test`、`npm run build`。用开发预览与受控 API 错误做下列验证，不向真实付费模型发送请求：

| 场景 | 操作 | 预期 |
|---|---|---|
| 长页面 | 配置多条连接，发起请求后滚到底部再返回失败 | 错误在当前视口显示，可关闭 |
| 并发失败 | 两条连接分别失败 | 两条反馈都保留，含连接名 |
| 小屏长文 | 375px 宽度、300 字错误、长无空格地址 | 不横向溢出，关闭按钮可见，区域内可滚动 |
| 键盘 | Tab 到通知关闭按钮，按 Escape | 只关闭本条，焦点返回有效触发控件 |
| 字段缺失 | 保存时第一条连接缺名称 | 滚动并聚焦名称，错误关联字段，不调用保存 API |
| 草稿 | 改名后保存失败，关闭通知再手动保存 | 未填内容不丢，关闭不触发请求，每次手动操作仅请求一次 |

实际浏览器能力不可用时明确记录未验证，并保留验收闸门；jsdom 不提供布局测量，不能代替上述视觉检查。新的错误反馈不涉及模态，因此此目标不新造焦点陷阱；建书对话框的完整焦点约束在对应计划落实。

- [ ] **7. 回归、审核、提交、推送。** 运行 Python 全量（确认 UI 接入不需要 API 契约变化），检查 staged 只含本任务文件。提交 `feat: keep model connection feedback visible`，推送并核对该 SHA 的三个 CI job。独立复核全部任务的安全与交互边界后才能把本目标标为完成。

## 计划自审与记录要求

- [x] 设计覆盖：共享分类、探针、两类 provider 四出口、可选配置、可见反馈、必要指引、脱敏、重试不变均有归属；建书弹窗/全站设计明确排除。
- [x] 接口核对：只新增 formatter 与局部通知组件，不变更 ModelResponse、API 响应、队列与租户字段。
- [x] Review Focus 五项分别落在任务 1、2、3 的测试与浏览器清单。
- [x] 路径核对：基于 `a6f0cf2` 当前代码结构；旧 Go 目录与旧计划行号不是修改依据。
- [ ] 执行时每任务记录 RED 命令与原因、GREEN 计数、跳过/警告、commit SHA、CI URL/结论。
- [ ] 最终记录正式容器是否部署了本目标；未重建部署不能把源码完成说成线上生效。
