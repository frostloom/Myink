"""模型提供方（§6.10 模型路由 + §6.12 调用层兜底）。"""

import uuid

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


def make_chain(role: str, project_id=None, db=None) -> FallbackChain:
    """按 role 建降级链（§6.10 默认分层；project_settings.model_routes 每项目可覆盖）。

    project_id 非空时读该书 model_routes[role]（可配置角色 = planner/writer/validator_l2/
    extract，§6.10；audit/revise/L1 不可覆盖走默认链）：命中合法模型 → 该书主模型置链首，
    默认链其余去重兜底；未配置/非法模型 → 默认链。db 复用调用方已开的租户会话（读一次
    project_settings），避免每次建链多连；project_id 为 None 时纯默认，零 DB 访问。
    """
    route = DEFAULT_ROUTES.get(role, DEFAULT_ROUTES["extract"])
    override = _project_primary(role, project_id, db) if project_id is not None else None
    if override is None:
        return FallbackChain(default_provider, route)
    chain = [override] + [m for m in route if m != override]
    return FallbackChain(default_provider, chain)


def _project_primary(role: str, project_id, db) -> str | None:
    """读 project_settings.model_routes[role] 的主模型；无 settings / 未配置 / 非法 id → None。

    providers 是底层模块，懒导入 memory.repository 防 providers↔repository 依赖环。
    """
    from aiink.memory.repository import get_settings  # 懒导入防环
    from aiink.db import tenant_session

    pid = uuid.UUID(str(project_id))
    if db is None:
        with tenant_session(str(pid)) as s:
            st = get_settings(s, pid)
    else:
        st = get_settings(db, pid)
    if st is None:
        return None
    override = (st.model_routes or {}).get(role)
    return override if override in MODEL_REGISTRY else None


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
