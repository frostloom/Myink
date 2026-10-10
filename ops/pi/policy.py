"""Trusted, fixed-schema configuration. Monetary rates are CNY per million tokens."""
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
import json
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Policy:
    schema_version: int
    live_enabled: bool
    server_daily_enabled: bool
    model: str
    protocol: str
    base_url: str
    max_attempts: int
    budget_microyuan: int
    timeout_seconds: int
    max_body_bytes: int
    input_token_bound: int
    input_bound_source: str
    input_bound_calibrated: bool
    max_tokens: int
    price_source: str
    prices: dict
    grace_seconds: int
    soft_production_files: int
    soft_production_lines: int
    hard_tracked_files: int
    hard_production_lines: int
    protected_paths: list[str]
    high_risk_types: list[str]


def rate(value):
    if not isinstance(value, str):
        raise ValueError('price must be a Decimal string')
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError('invalid price') from None
    if not result.is_finite() or result < 0:
        raise ValueError('invalid price')
    return result


def load_policy(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate policy field')
            result[key] = value
        return result
    data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs)
    if not isinstance(data, dict) or set(data) != {f.name for f in fields(Policy)}:
        raise ValueError('unsupported policy schema')
    p = Policy(**data)
    if type(p.schema_version) is not int or p.schema_version != 1:
        raise ValueError('unsupported policy version')
    for key in ('live_enabled', 'server_daily_enabled', 'input_bound_calibrated'):
        if type(getattr(p, key)) is not bool:
            raise ValueError('invalid policy flag')
    limits = dict(max_attempts=100, budget_microyuan=10000000, timeout_seconds=120,
                  grace_seconds=900, soft_production_files=3, soft_production_lines=150,
                  hard_tracked_files=8, hard_production_lines=300, max_body_bytes=1048576, input_token_bound=1000000, max_tokens=1000000)
    for key, maximum in limits.items():
        value = getattr(p, key)
        if type(value) is not int or not 0 < value <= maximum:
            raise ValueError('invalid policy limit')
    for key in ('model', 'input_bound_source', 'price_source'):
        if not isinstance(getattr(p, key), str) or not getattr(p, key).strip():
            raise ValueError('missing trusted source')
    if (not isinstance(p.base_url, str) or any(c.isspace() or ord(c) < 32 for c in p.base_url)
            or any(c in p.base_url for c in ('?', '#', '\\', '%'))):
        raise ValueError('ambiguous provider endpoint')
    url = urlsplit(p.base_url)
    safe_path = (url.path in ('', '/') or
                 (re.fullmatch(r'/[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*', url.path)
                  and all(segment not in ('.', '..') for segment in url.path.split('/')[1:])))
    if p.protocol != 'anthropic' or url.scheme != 'https' or not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment or not safe_path:
        raise ValueError('unsupported provider endpoint')
    if not isinstance(p.prices, dict) or set(p.prices) != {'input', 'output', 'cache_read', 'cache_write'}:
        raise ValueError('invalid price dimensions')
    for key, value in p.prices.items():
        if value is not None:
            rate(value)
        elif key != 'cache_write':
            raise ValueError('missing required price')
    required = {'ops/pi', '.github', 'AGENTS.md', '.agents', '.codex', 'docs/team-workflow.md'}
    if (not isinstance(p.protected_paths, list) or any(not isinstance(v, str) for v in p.protected_paths)
            or not required.issubset(p.protected_paths)
            or any(not isinstance(v, str) or not v or '\\' in v or ':' in v
                   or any(part in ('', '.', '..') for part in v.split('/')) for v in p.protected_paths)
            or p.soft_production_files > p.hard_tracked_files
            or p.soft_production_lines > p.hard_production_lines):
        raise ValueError('invalid plan policy')
    risky = {'schema', 'authentication', 'billing', 'external_api', 'infrastructure', 'deployment', 'policy'}
    if (not isinstance(p.high_risk_types, list) or any(not isinstance(v, str) for v in p.high_risk_types)
            or not risky.issubset(p.high_risk_types)):
        raise ValueError('invalid high risk policy')
    return p
