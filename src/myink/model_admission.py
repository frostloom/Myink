"""Admission for account-level model calls that have no queued task.

Reserve estimated spending in the existing global daily cost bucket before I/O.
Successful metered calls reconcile their reservation; missing usage, failures and
process crashes conservatively retain it. These estimates are not provider bills.
"""

from __future__ import annotations

from datetime import date
import json
import logging
import math
import threading
import uuid

from myink.config import settings
from myink.providers.base import FallbackChain, MissingModelProvider, ModelResponse
from myink.providers.prices import lookup_prices
from myink.worker.enqueue import EnqueueUnavailable, GateError
from myink.worker.redis_client import cost_key, get_redis

logger = logging.getLogger(__name__)
_KEY_PREFIX = "rate:account-model:"
# Both supported protocols currently allow one request plus three retries.
_ATTEMPTS = 4
_BUCKET_TTL = 172800

_ADMIT = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 'ACCOUNT_MODEL_BUSY' end
local calls = tonumber(redis.call('GET', KEYS[2]) or '0')
if calls >= tonumber(ARGV[2]) then return 'ACCOUNT_MODEL_QUOTA_EXCEEDED' end
local cost = tonumber(redis.call('GET', KEYS[3]) or '0')
if cost + tonumber(ARGV[3]) > tonumber(ARGV[4]) then
  return 'DAILY_BUDGET_EXCEEDED'
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[5])
redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], ARGV[6])
redis.call('INCRBYFLOAT', KEYS[3], ARGV[3])
redis.call('EXPIRE', KEYS[3], ARGV[6])
redis.call('SET', KEYS[4], ARGV[3], 'EX', ARGV[6])
return 'OK'
"""

_RENEW = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('EXPIRE', KEYS[1], ARGV[2])
"""

_FINISH = """
local reserved = redis.call('GET', KEYS[3])
if reserved then
  -- A missing bucket must not be recreated with a negative adjustment.
  if redis.call('EXISTS', KEYS[2]) == 1 then
    redis.call('INCRBYFLOAT', KEYS[2], tonumber(ARGV[2]) - tonumber(reserved))
  else
    redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
  end
  redis.call('DEL', KEYS[3])
end
if redis.call('GET', KEYS[1]) == ARGV[1] then redis.call('DEL', KEYS[1]) end
return 1
"""


def _reservation(chain: FallbackChain, messages: list[dict], max_tokens: int) -> tuple[float, bool]:
    # UTF-8 bytes plus envelope allowance is deliberately more conservative than
    # the UI's character heuristic, including Chinese and custom tokenizers.
    input_bound = len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + 1024
    per_attempt = 0.0
    known = True
    for model in chain.chain:
        prices = chain.prices if chain.prices is not None else lookup_prices(model)
        if prices is None:
            known = False
            per_attempt += settings.account_model_unknown_cost
            continue
        values = [float(prices[key]) for key in ("input", "input_cache_hit", "output")]
        if not all(math.isfinite(value) and value >= 0 for value in values):
            raise ValueError("invalid model prices")
        per_attempt += (input_bound * max(values[:2]) + max_tokens * values[2]) / 1_000_000
    return per_attempt * _ATTEMPTS, known


def generate_account_model(chain: FallbackChain, *, user_id, messages: list[dict],
                           max_tokens: int, **kwargs) -> ModelResponse:
    """One account call: a bounded owner lease, daily call quota and cost reserve.

    Admission fails closed. Finalization failure leaves the conservative charge
    and bounded lease in place, while allowing the caller to persist its response.
    """
    # This concrete provider performs no external I/O; a configuration error must
    # not consume everyone's budget. Unknown real models still require admission.
    if chain.providers and all(type(provider) is MissingModelProvider for provider in chain.providers):
        return chain.generate(messages, max_tokens=max_tokens, **kwargs)

    owner = uuid.uuid4().hex
    day = date.today().isoformat()
    lock = f"{_KEY_PREFIX}inflight:{user_id}"
    quota = f"{_KEY_PREFIX}calls:{user_id}:{day}"
    receipt = f"{_KEY_PREFIX}reservation:{owner}"
    cost = cost_key(day)
    try:
        if not user_id or not chain.chain or max_tokens <= 0:
            raise ValueError("account model call requires owner, model and output bound")
        reserved, known_prices = _reservation(chain, messages, max_tokens)
        if not math.isfinite(reserved) or reserved < 0:
            raise ValueError("invalid model cost reservation")
        r = get_redis()
        result = r.eval(_ADMIT, 4, lock, quota, cost, receipt, owner,
                        settings.account_model_calls_daily, reserved, settings.daily_budget,
                        settings.account_model_lease_seconds, _BUCKET_TTL)
    except Exception as exc:
        raise EnqueueUnavailable("account_model_admission") from exc
    if result != "OK":
        if result in {"ACCOUNT_MODEL_BUSY", "ACCOUNT_MODEL_QUOTA_EXCEEDED", "DAILY_BUDGET_EXCEEDED"}:
            raise GateError(result)
        raise EnqueueUnavailable("account_model_admission_result")

    stopped = threading.Event()
    lease_seconds = settings.account_model_lease_seconds

    def renew_lease() -> None:
        while not stopped.wait(lease_seconds / 3):
            try:
                if not r.eval(_RENEW, 1, lock, owner, lease_seconds):
                    return  # Expired or replaced: never renew another owner's lease.
            except Exception:
                logger.warning("Account model lease renewal unavailable owner=%s", owner,
                               exc_info=True)

    heartbeat = threading.Thread(target=renew_lease, name="account-model-lease", daemon=True)
    charge = reserved
    try:
        heartbeat.start()
        response = chain.generate(messages, max_tokens=max_tokens, **kwargs)
        actual = response.cost_est
        if math.isfinite(actual) and actual >= 0:
            charge = max(reserved, actual)
            if known_prices and not response.error and not response.degraded and (
                response.input_tokens > 0 and response.output_tokens > 0
            ):
                # Earlier retries may have been billed without returning usage.
                charge = actual + min(response.retry_count, _ATTEMPTS - 1) * reserved / _ATTEMPTS
        return response
    finally:
        stopped.set()
        if heartbeat.is_alive():
            heartbeat.join(timeout=1)
        try:
            r.eval(_FINISH, 3, lock, cost, receipt, owner, charge, _BUCKET_TTL)
        except Exception:
            logger.warning("Account model finalization unavailable; reservation retained owner=%s", owner,
                           exc_info=True)
