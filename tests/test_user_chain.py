"""账号级模型链：建书对话与文风提取走这条（此刻还没有书，拿不到 project_settings）。

不装 chain_stub —— make_chain/make_user_chain 在 default_provider 是测试桩时会短路，
那样就绕过了这里要验的路由逻辑。
"""

from __future__ import annotations

import uuid

from myink.api.routes_environment import EnvironmentBody, ModelConnectionBody, put_environment
from myink.db import ensure_user_environment
from myink.providers import make_user_chain


ensure_user_environment()


def _install(temp_user, routes: dict) -> str:
    cid = str(uuid.uuid4())
    put_environment(EnvironmentBody(
        model_connections=[ModelConnectionBody(
            id=cid, name="私有", protocol="openai",
            base_url="https://models.example.com/v1", model="novel-pro",
            api_key="k", input_price=3.5, output_price=8,
        )],
        model_routes={role: f"custom:{cid}" for role in routes},
    ), user_id=temp_user)
    return cid


def test_user_chain_uses_the_account_route_and_its_prices(temp_user):
    _install(temp_user, {"planner": None})
    chain = make_user_chain("planner", temp_user)
    assert chain.chain == ["novel-pro"]
    assert chain.prices == {"input": 3.5, "input_cache_hit": 3.5, "output": 8.0}


def test_user_chain_falls_back_from_planner_to_writer(temp_user):
    """用户只配了 writer：建书对话不该因为没配 planner 就变哑巴。"""
    _install(temp_user, {"writer": None})
    assert make_user_chain("planner", temp_user).chain == ["novel-pro"]


def test_user_chain_falls_back_from_extract_to_planner_then_writer(temp_user):
    _install(temp_user, {"writer": None})
    assert make_user_chain("extract", temp_user).chain == ["novel-pro"]


def test_user_chain_without_any_route_is_unconfigured(temp_user):
    assert make_user_chain("planner", temp_user).chain == ["unconfigured"]
