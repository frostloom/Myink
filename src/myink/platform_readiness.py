"""Local readiness for effective platform routes; never probes a vendor."""
from urllib.parse import urlsplit
import ipaddress

from fastapi import HTTPException
from pydantic import BaseModel

from myink.platform_configuration import PLATFORM_ROLES, resolve_connection
from myink.providers.credentials import decrypt_api_key


class PlatformNotReady(Exception):
    """Public failures deliberately contain no administrator diagnostics."""


class ReadinessCheck(BaseModel):
    role: str
    ready: bool
    reason: str | None


class ReadinessOut(BaseModel):
    ready: bool
    checks: list[ReadinessCheck]


def _connection_reason(record, *, deployment=False):
    from myink.api.routes_settings import _clean_base_url, _unsafe_address
    if record is None:
        return 'model_unconfigured'
    if record.get('protocol') not in {'openai', 'anthropic'}:
        return 'protocol_invalid'
    model = record.get('model', '')
    if not isinstance(model, str) or not model.strip() or len(model) > 160:
        return 'model_invalid'
    try:
        url = _clean_base_url(record.get('base_url', ''))
        parsed = urlsplit(url)
        host = parsed.hostname
        parsed.port
        if not host or any(char.isspace() or ord(char) < 33 for char in url):
            return 'address_invalid'
        if host.rstrip('.').lower() == 'localhost' or host.lower().endswith('.localhost'):
            return 'address_invalid'
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass  # Static check only: saving/probing applies the DNS address guard.
        else:
            if _unsafe_address(host):
                return 'address_invalid'
    except (ValueError, TypeError, AttributeError, HTTPException):
        return 'address_invalid'
    key = record.get('api_key', '') if deployment else decrypt_api_key(str(record.get('api_key_encrypted', '')))
    if not key or not key.strip():
        return 'credential_unavailable'
    return None


def readiness(*, roles=None, selections=None, config=None):
    """Diagnostics contain fixed reasons only, never URLs, credentials or errors."""
    from myink.config import settings
    from myink.platform_configuration import load_configuration
    config = load_configuration() if config is None else config
    from myink.user_defaults import platform_defaults
    defaults_reason = None
    try:
        platform_defaults(config)
    except PlatformNotReady:
        defaults_reason = 'defaults_invalid'
    checks = []
    for role in sorted(PLATFORM_ROLES if roles is None else roles):
        record = resolve_connection(role, selections, config)
        deployment = record is None and config['version'] == 0
        if deployment:
            record = {'protocol': settings.platform_model_protocol,
                'model': settings.platform_model_name, 'base_url': settings.platform_model_base_url,
                'api_key': settings.platform_model_api_key}
        reason = defaults_reason or _connection_reason(record, deployment=deployment)
        checks.append({'role': role, 'ready': reason is None, 'reason': reason})
    return {'ready': all(check['ready'] for check in checks), 'checks': checks}


def require_ready(roles, *, selections=None, config=None):
    # Preserve the existing concrete dependency-injection seam for test providers.
    from myink import providers
    if providers.default_provider is not providers._BUILTIN_PROVIDER:
        return
    if not readiness(roles=roles, selections=selections, config=config)['ready']:
        raise PlatformNotReady()


def require_operation_ready(operation, user_id):
    from myink import providers
    if providers.default_provider is not providers._BUILTIN_PROVIDER:
        return
    from myink.environment import packed_models
    from myink.providers.connections import unpack_model_settings
    roles = {'short_generate': ('writer', 'audit'), 'short_commit': ('planner',)}.get(operation, PLATFORM_ROLES)
    selections, _ = unpack_model_settings(packed_models(user_id))
    require_ready(roles, selections=selections)
