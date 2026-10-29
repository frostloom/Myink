"""Private guest credentials and domain-separated, normalized IP ledger keys."""
import hashlib
import hmac
import ipaddress

from myink.config import settings


def _digest(domain: str, value: str) -> str:
    # Auth configuration is checked at the HTTP boundary, and here for non-HTTP users.
    if len(settings.jwt_secret.encode()) < 32:
        raise ValueError('AUTH_SECRET_NOT_CONFIGURED')
    return hmac.new(settings.jwt_secret.encode(), (domain + '\0' + value).encode(), hashlib.sha256).hexdigest()


def ip_key(raw: str) -> str:
    if not isinstance(raw, str) or '%' in raw:
        raise ValueError('INVALID_CLIENT_IP')
    address = ipaddress.ip_address(raw.strip())
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return _digest('myink:guest:ip:v1', str(address))


def recovery_digest(secret: str) -> str:
    return _digest('myink:guest:recovery:v1', secret)
