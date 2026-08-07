"""模型提供方（§6.10 模型路由 + §6.12 调用层兜底）。"""

from aiink.providers.base import (
    DEFAULT_ROUTES,
    MODEL_REGISTRY,
    DEEPSEEK_PRICES,
    FallbackChain,
    ModelProvider,
    ModelResponse,
    ModelSpec,
)
from aiink.providers.deepseek import DeepSeekProvider

# 默认单例：DeepSeek 主模型（v4-flash 默认，降级链到 v4-pro）
default_provider = DeepSeekProvider()


def make_chain(role: str) -> FallbackChain:
    """按 role 建降级链（§6.10 默认分层；project_settings.model_routes 前端可覆盖）。"""
    route = DEFAULT_ROUTES.get(role, DEFAULT_ROUTES["extract"])
    return FallbackChain(default_provider, route)


__all__ = [
    "DEFAULT_ROUTES",
    "MODEL_REGISTRY",
    "DEEPSEEK_PRICES",
    "FallbackChain",
    "ModelProvider",
    "ModelResponse",
    "ModelSpec",
    "DeepSeekProvider",
    "default_provider",
    "make_chain",
]
