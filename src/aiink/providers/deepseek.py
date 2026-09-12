"""DeepSeek ModelProvider（OpenAI 兼容，§19.3）。

- JSON mode：`response_format={"type": "json_object"}`；
- 磁盘前缀缓存自动命中（同前缀 system 指令），价格差约 50 倍；
- 思考模式通过请求体参数切换（不再靠模型名，旧别名 2026-07-24 废弃）。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Callable

from openai import OpenAI

from aiink.config import settings
from aiink.providers.base import ModelProvider, ModelResponse

logger = logging.getLogger(__name__)

# 调用层兜底参数（§6.12）：指数退避重试 1s/2s/4s，上限 3 次
MAX_RETRIES = 3
BACKOFF_BASE = [1.0, 2.0, 4.0]


class DeepSeekProvider(ModelProvider):
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        # 模块加载不崩溃：key 留空也能 import（generate 时校验）；占位 key 满足 OpenAI client 构造
        self._api_key = api_key or settings.deepseek_api_key
        self._client = OpenAI(
            api_key=self._api_key or "sk-placeholder-not-configured",
            base_url=base_url or settings.deepseek_base_url,
            timeout=120.0,
            max_retries=0,  # 重试由本层控制（可观测、记日志）
        )

    def name(self) -> str:
        return "deepseek"

    @staticmethod
    def _request_kwargs(messages: list[dict], *, model_id: str,
                        max_tokens: int | None, temperature: float | None,
                        json_mode: bool, tools: list[dict] | None,
                        disable_thinking: bool) -> dict:
        kwargs: dict = {"model": model_id, "messages": messages}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if json_mode or tools or disable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        if tools:
            kwargs["tools"] = tools
        return kwargs

    def generate(self, messages: list[dict], *, model_id: str, max_tokens: int | None = None,
                 temperature: float | None = None, json_mode: bool = False,
                 tools: list[dict] | None = None,
                 disable_thinking: bool = False) -> ModelResponse:
        if not self._api_key:
            return ModelResponse(content="", model_id=model_id, error="DEEPSEEK_API_KEY 未配置")

        t0 = time.monotonic()
        # v4 思考模式默认开启：JSON / 工具轮 / 正文必须关闭，避免 reasoning 抢输出预算。
        kwargs = self._request_kwargs(
            messages, model_id=model_id, max_tokens=max_tokens,
            temperature=temperature, json_mode=json_mode, tools=tools,
            disable_thinking=disable_thinking,
        )

        last_error: str | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self._client.chat.completions.create(**kwargs)
                usage = resp.usage or type("U", (), {})()
                message = resp.choices[0].message
                content = message.content or ""
                # v4 思考模式默认开启，`thinking: disabled` 偶发不生效（§19.3）：
                # content 空或全空白但 reasoning_content 有内容时兜底——实测 json_mode
                # 最终轮偶发返回「全空白占位 content」（122 空格，`not content` 抓不住），
                # 避免下游 _parse_json("") 崩整章。reasoning 也空白 → 快速重试（瞬时输出
                # 异常，不 sleep 区别于网络退避），用尽后返回 error 触发 FallbackChain
                # 降级链（§6.10/§6.12 ① 模型降级链）——两档叠加治「两条模型同病」白给。
                # 注意：工具轮 content 空 + tool_calls 非空是正常情况（模型只输出工具
                # 调用不输出文本），不触发空白兜底。
                if not content.strip() and not getattr(message, "tool_calls", None):
                    reasoning = getattr(message, "reasoning_content", None) or ""
                    if reasoning.strip():
                        logger.warning("DeepSeek content 为空/空白，用 reasoning_content 兜底 (node/model=%s)", model_id)
                        content = reasoning
                    else:
                        if attempt < MAX_RETRIES:
                            logger.warning("DeepSeek 返回空白/空内容（attempt=%d/%d），快速重试",
                                           attempt, MAX_RETRIES)
                            continue
                        return ModelResponse(
                            content="", model_id=model_id,
                            error="DeepSeek 返回空白/空内容（thinking disabled 失效或输出异常）",
                            duration_ms=int((time.monotonic() - t0) * 1000))
                duration_ms = int((time.monotonic() - t0) * 1000)
                tool_calls = None
                if getattr(message, "tool_calls", None):
                    # arguments 是 JSON 字符串（OpenAI 兼容格式），解析失败容错为 {}
                    parsed = []
                    for tc in message.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except (json.JSONDecodeError, TypeError):
                            logger.warning("tool_calls.arguments 解析失败: %r", tc.function.arguments)
                            args = {}
                        parsed.append({"id": tc.id, "name": tc.function.name,
                                       "arguments": args if isinstance(args, dict) else {}})
                    tool_calls = parsed
                return ModelResponse(
                    content=content,
                    model_id=model_id,
                    input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                    cache_hit=bool(getattr(usage, "prompt_cache_hit_tokens", 0)),
                    duration_ms=duration_ms,
                    retry_count=attempt,
                    tool_calls=tool_calls,
                )
            except Exception as exc:
                last_error = str(exc)
                logger.warning("DeepSeek 调用失败(attempt=%d): %s", attempt, last_error)
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE[min(attempt, len(BACKOFF_BASE) - 1)])
        return ModelResponse(content="", model_id=model_id, error=last_error, duration_ms=int((time.monotonic() - t0) * 1000))

    def generate_stream(self, messages: list[dict], *, model_id: str,
                        on_delta: Callable[[str], None],
                        on_reset: Callable[[], None] | None = None,
                        max_tokens: int | None = None,
                        temperature: float | None = None, json_mode: bool = False,
                        tools: list[dict] | None = None,
                        disable_thinking: bool = False) -> ModelResponse:
        """OpenAI 兼容流式调用，最终仍聚合为 ModelResponse 供原校验链使用。"""
        if not self._api_key:
            return ModelResponse(content="", model_id=model_id, error="DEEPSEEK_API_KEY 未配置")

        t0 = time.monotonic()
        kwargs = self._request_kwargs(
            messages, model_id=model_id, max_tokens=max_tokens,
            temperature=temperature, json_mode=json_mode, tools=tools,
            disable_thinking=disable_thinking,
        )
        kwargs["stream"] = True
        # OpenAI 兼容协议在最后一个空 choices 帧返回完整 usage。
        kwargs["stream_options"] = {"include_usage": True}
        last_error: str | None = None

        for attempt in range(MAX_RETRIES + 1):
            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_parts: dict[int, dict[str, str]] = {}
            usage = None
            emitted = False
            try:
                stream = self._client.chat.completions.create(**kwargs)
                for chunk in stream:
                    if getattr(chunk, "usage", None) is not None:
                        usage = chunk.usage
                    if not getattr(chunk, "choices", None):
                        continue
                    delta = chunk.choices[0].delta
                    text = getattr(delta, "content", None) or ""
                    if text:
                        content_parts.append(text)
                        on_delta(text)
                        emitted = True
                    reasoning = getattr(delta, "reasoning_content", None) or ""
                    if reasoning:
                        reasoning_parts.append(reasoning)
                    for tc in (getattr(delta, "tool_calls", None) or []):
                        idx = int(getattr(tc, "index", 0) or 0)
                        row = tool_parts.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if getattr(tc, "id", None):
                            row["id"] += tc.id
                        fn = getattr(tc, "function", None)
                        if fn is not None:
                            row["name"] += getattr(fn, "name", None) or ""
                            row["arguments"] += getattr(fn, "arguments", None) or ""

                content = "".join(content_parts)
                tool_calls: list[dict] | None = None
                if tool_parts:
                    parsed_tools: list[dict] = []
                    for idx in sorted(tool_parts):
                        row = tool_parts[idx]
                        try:
                            args = json.loads(row["arguments"] or "{}")
                        except (json.JSONDecodeError, TypeError):
                            logger.warning("流式 tool_calls.arguments 解析失败: %r", row["arguments"])
                            args = {}
                        parsed_tools.append({
                            "id": row["id"], "name": row["name"],
                            "arguments": args if isinstance(args, dict) else {},
                        })
                    tool_calls = parsed_tools

                if not content.strip() and not tool_calls:
                    reasoning = "".join(reasoning_parts)
                    if reasoning.strip():
                        content = reasoning
                        on_delta(reasoning)
                        emitted = True
                    elif attempt < MAX_RETRIES:
                        if emitted and on_reset:
                            on_reset()
                        logger.warning("DeepSeek 流式返回空内容（attempt=%d/%d），快速重试",
                                       attempt, MAX_RETRIES)
                        continue
                    else:
                        return ModelResponse(
                            content="", model_id=model_id,
                            error="DeepSeek 流式返回空白/空内容",
                            duration_ms=int((time.monotonic() - t0) * 1000),
                        )
                usage = usage or type("U", (), {})()
                return ModelResponse(
                    content=content,
                    model_id=model_id,
                    input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                    cache_hit=bool(getattr(usage, "prompt_cache_hit_tokens", 0)),
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    retry_count=attempt,
                    tool_calls=tool_calls,
                )
            except Exception as exc:
                last_error = str(exc)
                logger.warning("DeepSeek 流式调用失败(attempt=%d): %s", attempt, last_error)
                if emitted and on_reset:
                    on_reset()
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE[min(attempt, len(BACKOFF_BASE) - 1)])
        return ModelResponse(
            content="", model_id=model_id, error=last_error,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
