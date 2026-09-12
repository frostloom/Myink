"""Provider for user-configured OpenAI-compatible chat completion endpoints."""

from __future__ import annotations

from aiink.providers.deepseek import DeepSeekProvider


class OpenAICompatibleProvider(DeepSeekProvider):
    def __init__(self, *, api_key: str, base_url: str):
        super().__init__(api_key=api_key, base_url=base_url)

    def name(self) -> str:
        return "openai-compatible"

    @staticmethod
    def _request_kwargs(messages: list[dict], *, model_id: str,
                        max_tokens: int | None, temperature: float | None,
                        json_mode: bool, tools: list[dict] | None,
                        disable_thinking: bool) -> dict:
        kwargs = DeepSeekProvider._request_kwargs(
            messages, model_id=model_id, max_tokens=max_tokens,
            temperature=temperature, json_mode=json_mode, tools=tools,
            disable_thinking=disable_thinking,
        )
        # ``thinking`` is a DeepSeek extension and breaks standard OpenAI servers.
        kwargs.pop("extra_body", None)
        return kwargs
