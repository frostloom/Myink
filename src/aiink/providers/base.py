"""ModelProvider 抽象 + 模型注册表 + 降级链（plan.md §6.10 / §19.3）。

- 模型注册表：model_id → 上下文窗口 / 输出上限 / 成本档 / 能力标记；
- 降级链：每个 role 配 fallback（主 → 备 → 全局默认），失败自动降级不中断写作；
- 成本估算：cost_est = 输入token×(命中?命中价:未命中价) + 输出token×输出价。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# ---- DeepSeek V4 官方价格（¥/百万 token，§19.3 核对 2026-08-05）----
# 缓存命中输入价 ≈ 未命中 1/50
DEEPSEEK_PRICES: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {"input": 1.0, "input_cache_hit": 0.02, "output": 2.0},
    "deepseek-v4-pro": {"input": 2.0, "input_cache_hit": 0.04, "output": 8.0},
}


@dataclass(frozen=True)
class ModelSpec:
    """模型注册表一项（§6.10）。"""

    model_id: str
    context_window: int
    max_output: int
    capabilities: frozenset[str] = frozenset({"llm", "json"})


MODEL_REGISTRY: dict[str, ModelSpec] = {
    "deepseek-v4-flash": ModelSpec("deepseek-v4-flash", 1_000_000, 384_000, frozenset({"llm", "json"})),
    "deepseek-v4-pro": ModelSpec("deepseek-v4-pro", 1_000_000, 384_000, frozenset({"llm", "json"})),
}


@dataclass
class ModelResponse:
    """一次 LLM 调用结果（§6.8 agent_runs 全字段的数据来源）。"""

    content: str
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0  # 思考 token 计入输出（§19.3）
    cache_hit: bool = False
    duration_ms: int = 0
    retry_count: int = 0
    degraded: bool = False
    error: str | None = None
    # 工具调用（§10 只读查证工具）：[{id, name, arguments(dict)}]，None = 本轮无工具调用
    tool_calls: list[dict] | None = None

    @property
    def cost_est(self) -> float:
        """成本估算（¥）。"""
        prices = DEEPSEEK_PRICES.get(self.model_id)
        if prices is None:
            return 0.0
        in_price = prices["input_cache_hit"] if self.cache_hit else prices["input"]
        return (self.input_tokens * in_price + self.output_tokens * prices["output"]) / 1_000_000


class ModelProvider(ABC):
    """模型提供方抽象：可切换 / 降级（§3 已收敛决策）。"""

    @abstractmethod
    def generate(self, messages: list[dict], *, model_id: str, max_tokens: int | None = None,
                 temperature: float | None = None, json_mode: bool = False,
                 tools: list[dict] | None = None,
                 disable_thinking: bool = False) -> ModelResponse:
        ...

    @abstractmethod
    def name(self) -> str:
        ...


class FallbackChain:
    """降级链：主 → 备 → 全局默认（§6.10/§6.12 调用层）。"""

    def __init__(self, provider: ModelProvider, chain: list[str]):
        self.provider = provider
        self.chain = chain

    def generate(self, messages: list[dict], *, json_mode: bool = False, max_tokens: int | None = None,
                 temperature: float | None = None, tools: list[dict] | None = None,
                 disable_thinking: bool = False) -> ModelResponse:
        last_error: str | None = None
        for i, model_id in enumerate(self.chain):
            try:
                resp = self.provider.generate(
                    messages, model_id=model_id, max_tokens=max_tokens,
                    temperature=temperature, json_mode=json_mode, tools=tools,
                    disable_thinking=disable_thinking,
                )
                if resp.error is None:
                    resp.degraded = i > 0
                    return resp
                last_error = resp.error
            except Exception as exc:  # 网络 / 超时 / 5xx → 试下一个
                last_error = str(exc)
        return ModelResponse(content="", model_id=self.chain[-1], error=last_error)


# 可配置角色（§6.10）：仅这些 role 允许项目级 model_routes 覆盖主模型；
# audit/revise/L1 固定默认链（设置端点 PUT 同样按此校验，本表是 make_chain 的兜底闸）。
CONFIGURABLE_ROLES: frozenset[str] = frozenset({"planner", "writer", "validator_l2", "extract"})


# 默认路由表（§6.10）：role → 模型链（主 → 备）
DEFAULT_ROUTES: dict[str, list[str]] = {
    "planner": ["deepseek-v4-flash", "deepseek-v4-pro"],   # 规划/校验强模型
    "writer": ["deepseek-v4-flash", "deepseek-v4-pro"],
    "validator_l2": ["deepseek-v4-flash", "deepseek-v4-pro"],
    "audit": ["deepseek-v4-flash", "deepseek-v4-pro"],     # 审核中枢：语义判断 + 路由决策（§6.5）
    "extract": ["deepseek-v4-flash"],                      # 便宜快模型（抽取）
}
