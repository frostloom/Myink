"""Append-only, credential-free run provenance for packaged business images."""
from hashlib import sha256
import json
import math
import re
from typing import Any
from myink.admin_observability import scrub_text

_CONFIG_FIELDS = ('request_token_budget', 'recall_token_budget', 'max_revisions', 'max_patches',
                  'max_replans', 'max_tool_calls', 'audit_interval', 'chapter_reflexion_interval',
                  'platform_model_name', 'platform_model_protocol', 'embed_model_name', 'embed_enabled')


def _identifier(value):
    return value if (isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value)
                     and scrub_text(value) == value) else None


def run_provenance(settings) -> dict[str, Any]:
    """Identifiers describe this invocation, never populate old rows.

    Digest keys use `_id` because the existing credential scrubber redacts `_hash`.
    The Pi projection maps them back to the public snapshot hash fields.
    """
    config = {key: getattr(settings, key, None) for key in _CONFIG_FIELDS}
    encoded = json.dumps(config, sort_keys=True, separators=(',', ':'), allow_nan=False)
    complete_config = getattr(settings, 'observation_config_id', None)
    if not isinstance(complete_config, str) or not re.fullmatch(r'[0-9a-f]{64}', complete_config):
        complete_config = None
    generation = getattr(settings, 'deployment_generation', None)
    try:
        images = json.loads(getattr(settings, 'deployment_image_ids', '') or '{}')
        if (not isinstance(images, dict) or len(images) > 8
                or any(not _identifier(k) or not _identifier(v) for k, v in images.items())):
            images = {}
    except (TypeError, ValueError):
        images = {}
    return dict(version=1, deployment_id=_identifier(getattr(settings, 'deployment_id', None)),
                generation=generation if type(generation) is int and generation > 0 else None,
                owner=_identifier(getattr(settings, 'deployment_owner', None)),
                image_ids=images or None, commit_sha=_identifier(getattr(settings, 'deployment_commit_sha', None)),
                schema_id=_identifier(getattr(settings, 'observation_schema_id', None)),
                settings_id=sha256(encoded.encode()).hexdigest(), config_id=complete_config,
                prompt_id=_identifier(getattr(settings, 'observation_prompt_id', None)),
                rubric_id=_identifier(getattr(settings, 'observation_rubric_id', None)),
                data_id=_identifier(getattr(settings, 'observation_data_id', None)))


def run_measurement(resp) -> dict[str, Any]:
    from myink.providers.prices import lookup_prices
    prices = resp.prices if resp.prices is not None else lookup_prices(resp.model_id)
    tokens = (resp.input_tokens, resp.output_tokens)
    usage_known = (resp.usage_complete and not resp.error
                   and all(type(v) is int and v >= 0 for v in tokens) and resp.input_tokens > 0
                   and (not (resp.content or resp.tool_calls) or resp.output_tokens > 0))
    prices_known = (isinstance(prices, dict)
                    and all(type(prices.get(key)) in (int, float) and math.isfinite(prices[key])
                            and prices[key] >= 0 for key in ('input', 'input_cache_hit', 'output')))
    known_cost = (usage_known and prices_known
                  and type(resp.cost_est) in (int, float) and math.isfinite(resp.cost_est) and resp.cost_est >= 0)
    return dict(version=1, kind='model', model_id=resp.model_id, cost=known_cost,
                latency=type(resp.duration_ms) in (int, float) and math.isfinite(resp.duration_ms)
                and resp.duration_ms >= 0,
                pricing_id=sha256(json.dumps(prices, sort_keys=True).encode()).hexdigest() if prices_known else None)
