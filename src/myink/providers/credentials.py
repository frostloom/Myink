"""Encrypt project-scoped model credentials before storing them in settings JSON."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from myink.config import settings

_MODEL_NAMESPACE = "model-credentials"
_MFA_NAMESPACE = "mfa"


def _cipher(namespace: str = _MODEL_NAMESPACE) -> Fernet:
    """按用途分域的 Fernet 实例。

    ``namespace`` 参与密钥派生，所以模型密钥与 TOTP 密钥互不可解——一处密文泄露不会连带
    另一处。默认值就是原来写死的那一段，**存量模型密钥密文照旧解得开**（派生式一字未改）。
    """
    secret = settings.model_credential_key or settings.jwt_secret
    digest = hashlib.sha256(f"myink:{namespace}:{secret}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_api_key(value: str) -> str:
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_api_key(value: str) -> str | None:
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError):
        return None


def encrypt_totp_secret(value: str) -> str:
    return _cipher(_MFA_NAMESPACE).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_totp_secret(value: str | None) -> str | None:
    """解不出就返回 ``None``——调用方据此拒绝，不能退化成「没有密钥 = 不校验」。"""
    if not value:
        return None
    try:
        return _cipher(_MFA_NAMESPACE).decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError):
        return None
