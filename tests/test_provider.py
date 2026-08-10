"""ModelProvider 层单测（§19.3 思考模式兜底 + §6.10 降级链）。

无需真实 DeepSeek 调用：monkeypatch OpenAI client 的 create，验证：
- content 非空 → 原样透传（兜底不误伤正常路径）；
- content 空/全空白但 reasoning_content 有内容 → 兜底（v4 `thinking: disabled` 偶发不生效，
  §19.3 思考 token 仍产生，正文进 reasoning_content，否则下游 _parse_json("") 崩整章；
  实测 json_mode 最终轮偶发返回「全空白占位 content」，`not content` 抓不住）；
- 两者皆空 → error（触发 FallbackChain 降级重试，§6.12 ① 模型降级链）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from aiink.providers.base import ModelResponse
from aiink.providers.deepseek import DeepSeekProvider


def _fake_create(content: str = "", reasoning_content: str = ""):
    """构造模拟 OpenAI 响应的 create 函数（返回 usage/choices/message）。"""
    def create(**kwargs):
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                                prompt_cache_hit_tokens=0)
        message = SimpleNamespace(content=content or None,
                                  reasoning_content=reasoning_content or None,
                                  tool_calls=None)
        return SimpleNamespace(usage=usage,
                               choices=[SimpleNamespace(message=message)])
    return create


def _provider_with(create):
    p = DeepSeekProvider(api_key="test-key")
    p._client.chat.completions.create = create
    return p


def test_content_nonempty_passthrough():
    """content 非空：正常路径原样返回，不触发兜底。"""
    p = _provider_with(_fake_create(content='{"verdict": "pass"}'))
    resp: ModelResponse = p.generate([{"role": "user", "content": "x"}], model_id="deepseek-v4-flash")
    assert resp.error is None
    assert resp.content == '{"verdict": "pass"}'


def test_reasoning_content_fallback():
    """content 空 + reasoning_content 有值：兜底为 content（§19.3 v4 偶发思考模式）。"""
    p = _provider_with(_fake_create(content="", reasoning_content='思考过程... {"verdict": "pass"}'))
    resp: ModelResponse = p.generate([{"role": "user", "content": "x"}], model_id="deepseek-v4-flash")
    assert resp.error is None
    assert resp.content.startswith("思考过程")
    assert "verdict" in resp.content


def test_blank_content_falls_back():
    """content 全空白（json_mode 最终轮占位输出，122 空格）+ reasoning 有值：兜底。"""
    p = _provider_with(_fake_create(content=" " * 122, reasoning_content='思考... {"verdict": "pass"}'))
    resp: ModelResponse = p.generate([{"role": "user", "content": "x"}], model_id="deepseek-v4-flash")
    assert resp.error is None
    assert resp.content.startswith("思考")
    assert "verdict" in resp.content


def test_both_empty_returns_error():
    """content 与 reasoning_content 皆空：返回 error 触发 FallbackChain 降级重试（§6.12 ①）。"""
    p = _provider_with(_fake_create(content="", reasoning_content=""))
    resp: ModelResponse = p.generate([{"role": "user", "content": "x"}], model_id="deepseek-v4-flash")
    assert resp.error is not None
    assert "空白/空内容" in resp.error
