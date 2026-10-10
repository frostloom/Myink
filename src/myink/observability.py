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
                config_id=sha256(encoded.encode()).hexdigest(),
                prompt_id=_identifier(getattr(settings, 'observation_prompt_id', None)),
                rubric_id=_identifier(getattr(settings, 'observation_rubric_id', None)),
                data_id=_identifier(getattr(settings, 'observation_data_id', None)))


def run_measurement(resp) -> dict[str, Any]:
    from myink.providers.prices import lookup_prices
    prices = resp.prices if resp.prices is not None else lookup_prices(resp.model_id)
    known_cost = (prices is not None and resp.usage_complete
                  and type(resp.cost_est) in (int, float) and math.isfinite(resp.cost_est))
    return dict(version=1, model_id=resp.model_id, cost=known_cost,
                latency=type(resp.duration_ms) in (int, float) and math.isfinite(resp.duration_ms)
                and resp.duration_ms >= 0,
                pricing_id=sha256(json.dumps(prices, sort_keys=True).encode()).hexdigest() if prices else None)
