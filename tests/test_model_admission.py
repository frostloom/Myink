"""Account calls share atomic Redis admission; only provider I/O is replaced."""

from dataclasses import replace
from datetime import date
import time
import uuid

import pytest

from myink.providers.base import FallbackChain, ModelProvider, ModelResponse
from myink.worker.enqueue import EnqueueUnavailable, GateError


class Provider(ModelProvider):
    def __init__(self, callback=None, response=None):
        self.callback = callback
        self.response = response or ModelResponse("ok", "deepseek-v4-flash", 100, 200)

    def name(self):
        return "test-provider"

    def generate(self, messages, **kwargs):
        if self.callback:
            self.callback()
        return self.response


@pytest.mark.parametrize("operation", ["dialogue", "style"])
def test_account_dialogue_does_not_bypass_admission(monkeypatch, operation):
    """Deleting dialogue admission would let an exhausted account call the provider."""
    from myink import book_setup, providers, style_extract
    from myink.worker.redis_client import get_redis

    uid = str(uuid.uuid4())
    key = f"rate:account-model:inflight:{uid}"
    r = get_redis()
    r.set(key, "another-call", ex=30)
    monkeypatch.setattr(providers, "make_user_chain", lambda *args: FallbackChain(
        Provider(), ["deepseek-v4-flash"]))
    try:
        with pytest.raises(GateError, match="ACCOUNT_MODEL_BUSY"):
            if operation == "dialogue":
                book_setup.generate_short_creation_turn([], {}, user_id=uid)
            else:
                style_extract.extract_style_profile(["样本正文。"], {}, user_id=uid)
    finally:
        r.delete(key)


@pytest.fixture
def admission(monkeypatch):
    import myink.model_admission as module
    from myink.worker.redis_client import get_redis

    r = get_redis()
    prefix = f"test:account-admission:{uuid.uuid4()}:"
    monkeypatch.setattr(module, "cost_key", lambda day: prefix + "cost:" + day)
    monkeypatch.setattr(module, "_KEY_PREFIX", prefix)
    monkeypatch.setattr(module, "settings", replace(
        module.settings, account_model_calls_daily=2, daily_budget=10))
    try:
        yield module, r, prefix
    finally:
        keys = list(r.scan_iter(prefix + "*"))
        if keys:
            r.delete(*keys)


def call(module, provider=None, user="alice", model="deepseek-v4-flash"):
    return module.generate_account_model(
        FallbackChain(provider or Provider(), [model]), user_id=user,
        messages=[{"role": "user", "content": "hello"}], max_tokens=1000,
        json_mode=True)


def test_unconfigured_model_never_consumes_shared_budget(admission, monkeypatch):
    from myink.providers.base import MissingModelProvider
    module, r, prefix = admission
    chain = FallbackChain(MissingModelProvider(), ["unconfigured"])
    for _ in range(3):
        result = module.generate_account_model(chain, user_id="no-model", messages=[], max_tokens=10)
        assert "环境配置" in result.error
    assert list(r.scan_iter(prefix + "*")) == []
    def unavailable():
        raise RuntimeError("offline")
    monkeypatch.setattr(module, "get_redis", unavailable)
    result = module.generate_account_model(chain, user_id="no-model", messages=[], max_tokens=10)
    assert "环境配置" in result.error


def test_concurrent_calls_for_same_account_never_reach_provider(admission):
    module, r, prefix = admission
    blocked = []

    def competing_request():
        with pytest.raises(GateError, match="ACCOUNT_MODEL_BUSY"):
            call(module)
        blocked.append(True)

    assert call(module, Provider(callback=competing_request)).content == "ok"
    assert blocked == [True]
    assert call(module).content == "ok"  # The original lease was released.
    with pytest.raises(GateError, match="ACCOUNT_MODEL_QUOTA_EXCEEDED"):
        call(module)


def test_shared_budget_reservation_reconciles_actual_cost(admission):
    module, r, prefix = admission
    key = module.cost_key(date.today().isoformat())
    r.set(key, "0.5")
    during = []
    response = call(module, Provider(callback=lambda: during.append(float(r.get(key)))))
    assert during[0] > 0.5009
    assert float(r.get(key)) == pytest.approx(0.5009)
    assert response.cost_est == pytest.approx(0.0009)


def test_global_budget_blocks_another_account_before_model_io(admission, monkeypatch):
    module, r, prefix = admission
    monkeypatch.setattr(module, "settings", replace(module.settings, daily_budget=0.025))

    def competing_account():
        with pytest.raises(GateError, match="DAILY_BUDGET_EXCEEDED"):
            call(module, user="bob")

    assert call(module, Provider(callback=competing_account)).content == "ok"


def test_unknown_model_and_failed_call_keep_nonzero_reservation(admission):
    module, r, prefix = admission
    key = module.cost_key(date.today().isoformat())
    call(module, model="custom-unknown")
    initial = float(r.get(key))
    assert initial > 0
    response = call(module, Provider(response=ModelResponse("", "unknown", error="timeout")))
    assert response.error == "timeout"
    assert float(r.get(key)) > initial


def test_expired_owner_does_not_release_a_new_lease(admission):
    module, r, prefix = admission

    def replace_lease():
        r.set(prefix + "inflight:alice", "new-owner", ex=30)

    call(module, Provider(callback=replace_lease))
    assert r.get(prefix + "inflight:alice") == "new-owner"
    assert 0 < r.ttl(prefix + "inflight:alice") <= 30


def test_redis_failure_is_closed_before_provider(admission, monkeypatch):
    module, r, prefix = admission

    def unavailable():
        raise ConnectionError("test unavailable")

    def forbidden():
        pytest.fail("Provider called without admission")

    monkeypatch.setattr(module, "get_redis", unavailable)
    with pytest.raises(EnqueueUnavailable):
        call(module, Provider(callback=forbidden))


def test_success_after_retry_retains_allowance_for_unknown_attempts(admission):
    module, r, prefix = admission
    key = module.cost_key(date.today().isoformat())
    reserved = []
    response = ModelResponse("ok", "deepseek-v4-flash", 100, 200, retry_count=2)
    call(module, Provider(response=response, callback=lambda: reserved.append(float(r.get(key)))))
    assert float(r.get(key)) == pytest.approx(0.0009 + reserved[0] / 2)


def test_settlement_failure_keeps_reservation_and_bounded_lease(admission, monkeypatch):
    module, r, prefix = admission
    key = module.cost_key(date.today().isoformat())
    reserved = []

    class FailsAtSettlement:
        def eval(self, script, *args):
            if script == module._FINISH:
                raise ConnectionError("settlement unavailable")
            return r.eval(script, *args)

    monkeypatch.setattr(module, "get_redis", lambda: FailsAtSettlement())
    response = call(module, Provider(callback=lambda: reserved.append(float(r.get(key)))))
    assert response.content == "ok"  # Caller can still persist usage into agent_runs.
    assert float(r.get(key)) == reserved[0]
    assert 0 < r.ttl(prefix + "inflight:alice") <= 900


def test_unknown_price_configuration_cannot_disable_reservation(monkeypatch):
    from myink.config import Settings

    for value in ("nan", "inf", "0", "-1"):
        monkeypatch.setenv("ACCOUNT_MODEL_UNKNOWN_COST_YUAN", value)
        with pytest.raises(ValueError, match="ACCOUNT_MODEL_UNKNOWN_COST_YUAN"):
            Settings().validate()


@pytest.mark.parametrize("input_tokens,output_tokens", [(100, 0), (0, 200)])
def test_partial_usage_retains_full_reservation(admission, input_tokens, output_tokens):
    module, r, prefix = admission
    key = module.cost_key(date.today().isoformat())
    reserved = []
    response = ModelResponse("ok", "deepseek-v4-flash", input_tokens, output_tokens)
    call(module, Provider(response=response, callback=lambda: reserved.append(float(r.get(key)))))
    assert float(r.get(key)) == reserved[0]


def test_slow_provider_keeps_lease_across_expiration_periods(admission, monkeypatch):
    module, r, prefix = admission
    monkeypatch.setattr(module, "settings", replace(module.settings, account_model_lease_seconds=1))
    rejected = []

    def slow_provider():
        time.sleep(1.3)
        with pytest.raises(GateError, match="ACCOUNT_MODEL_BUSY"):
            call(module)
        rejected.append(True)

    assert call(module, Provider(callback=slow_provider)).content == "ok"
    assert rejected == [True]
    assert r.exists(prefix + "inflight:alice") == 0


def test_heartbeat_does_not_renew_a_replacement_owner(admission, monkeypatch):
    module, r, prefix = admission
    monkeypatch.setattr(module, "settings", replace(module.settings, account_model_lease_seconds=1))
    key = prefix + "inflight:alice"

    def replacement_owner():
        r.set(key, "new-owner", ex=5)
        time.sleep(1.2)

    call(module, Provider(callback=replacement_owner))
    assert r.get(key) == "new-owner"
    assert 3000 < r.pttl(key) < 4500
