"""DeepSeek ModelProvider（OpenAI 兼容，§19.3）。

- JSON mode：`response_format={"type": "json_object"}`；
- 磁盘前缀缓存自动命中（同前缀 system 指令），价格差约 50 倍；
- 思考模式通过请求体参数切换（不再靠模型名，旧别名 2026-07-24 废弃）。
"""

from __future__ import annotations

import json
import logging
import time

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

    def generate(self, messages: list[dict], *, model_id: str, max_tokens: int | None = None,
                 temperature: float | None = None, json_mode: bool = False,
                 tools: list[dict] | None = None,
                 disable_thinking: bool = False) -> ModelResponse:
        if not self._api_key:
            return ModelResponse(content="", model_id=model_id, error="DEEPSEEK_API_KEY 未配置")

        t0 = time.monotonic()
        kwargs: dict = {"model": model_id, "messages": messages}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if json_mode or tools or disable_thinking:
            # v4 思考模式默认开启：思考 token 会让 content 变空（正文进 reasoning_content）
            # 且破坏 JSON 结构（§19.3）。JSON mode / 工具轮 / 纯文本正文一律关思考——
            # 本项目结构化输出（extract/plan/audit）与长文正文（write/revise）都是确定性
            # 产物，不需要思考（§6.9 单遍生成）；工具循环要重建 assistant tool_calls
            # 消息回传，thinking 开着会产生 reasoning_content，下轮不回传会 400。
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        if tools:
            kwargs["tools"] = tools

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
