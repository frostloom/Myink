"""Local account authentication plus the private-API identity boundary.

Python verifies the bearer token itself on every business route. It used to trust the
``X-Myink-User`` header because a private Go gateway overwrote that header after
validating the token -- but Python already owns the user table, so asking a second
process "is this session still valid?" on every request was a redundant network hop.
"""

from __future__ import annotations

import re
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from myink.api.ratelimit import (account_auth_cleared, account_auth_failed, account_auth_guard,
                                 auth_rate_limit, mfa_cleared, mfa_failed, mfa_guard)
from myink.api.schemas import (AuthResponse, AuthSessionOut, MfaChallengeOut, MfaCodeRequest,
                               MfaEnrollOut, MfaStatusOut, MfaVerifyRequest, OkOut)
from myink.config import settings
from myink.db import new_session
from myink.invitations import (
    InvitationRejected,
    consume_invitation,
    validate_invitation,
)
from myink.models import Project, User
from myink.passwords import hash_password, validate_password, verify_password
from myink.providers.credentials import decrypt_totp_secret, encrypt_totp_secret

router = APIRouter(prefix="/api/v1", tags=["auth"])

_ALG = "HS256"
_ISS = "myink"
# 第二因子挑战令牌用**另一个 issuer**。这样 `_decode_token`（要求 issuer=myink，见 `_ISS`）
# 一行都不用改：挑战令牌天然过不了受保护路由，线上已发的 access token 也不会因此失效。
# 比在 access token 上加 `purpose` 声明好——那条路要么改热路径校验，要么让存量 token 全失效。
_MFA_ISS = "myink-mfa"
_MFA_CHALLENGE_TTL = 300
_TOTP_ISSUER = "Myink"
_USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,64}$", re.ASCII)
_bearer = HTTPBearer(auto_error=False)
_password_slots = threading.BoundedSemaphore(2)
_DUMMY_PASSWORD_HASH = (
    "scrypt$131072$8$1$QOHzV10bCrbhDBCpJPmR2w==$"
    "a_WQOqXzp3DVUmCttce2HN7PyXB-JU1i5MnWF_6dgrzYDt8pY_TK0Jr1d1kYlv6VQOT8zsIMCSEmFEfvrb46jw=="
)


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="INVALID_CREDENTIALS",
        headers={"Cache-Control": "no-store"},
    )


def _mfa_invalid() -> HTTPException:
    """第二因子验不过。密码错与这一步分开报：前端在第二步说「验证码不正确」才讲得通。

    「码错」「码过期」「挑战票过期」仍然统一回这一个码——区分它们等于告诉攻击者密码对没对。
    """
    return HTTPException(
        status_code=401,
        detail="MFA_INVALID",
        headers={"Cache-Control": "no-store"},
    )


def require_auth_configuration() -> None:
    """Fail closed unless HS256 has at least a 256-bit configured secret."""
    if len(settings.jwt_secret.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=503,
            detail="AUTH_SECRET_NOT_CONFIGURED",
            headers={"Cache-Control": "no-store"},
        )


def normalize_username(username: str) -> str:
    """Trim and ASCII-lower a username, then enforce its canonical alphabet."""
    trimmed = username.strip()
    if not trimmed.isascii():
        raise ValueError("用户名必须是 ASCII")
    canonical = trimmed.lower()
    if not _USERNAME_RE.fullmatch(canonical):
        raise ValueError("用户名必须为 3–64 位 ASCII 字母、数字、下划线或短横线")
    return canonical


@contextmanager
def _password_capacity():
    """Cap concurrent ~128 MiB scrypt operations and fail fast when saturated."""
    if not _password_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="AUTH_CAPACITY_EXCEEDED",
            headers={"Cache-Control": "no-store", "Retry-After": "1"},
        )
    try:
        yield
    finally:
        _password_slots.release()


def create_access_token(
    user_id: uuid.UUID,
    tier: str = "normal",
    auth_version: int = 1,
) -> str:
    """Create a strict, short-lived account token."""
    require_auth_configuration()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iss": _ISS,
            "tier": tier,
            "ver": auth_version,
            "iat": now,
            "exp": now + timedelta(seconds=settings.jwt_ttl),
        },
        settings.jwt_secret,
        algorithm=_ALG,
    )


def current_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> _AuthenticatedUser:
    """Fully verified identity; tier/role/auth_version come fresh from the DB."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _invalid_credentials()
    user = _load_identity(_decode_token(credentials.credentials))
    if user is None:
        raise _invalid_credentials()
    return user


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str | None:
    """Caller id, or ``None`` when the request carried no credentials at all.

    Only the "no credentials" case returns ``None``, so callers keep their fail-closed
    branch (empty list / 403). A token that is present but invalid, expired or revoked
    is a 401 -- which is what the browser needs in order to notice it must sign in again.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    return str(current_identity(credentials).id)


def require_user(user_id: str | None = Depends(current_user)) -> str:
    if not user_id:
        raise HTTPException(status_code=403, detail="缺失身份（未携带已认证用户）")
    try:
        uuid.UUID(user_id)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=403, detail="身份非法")
    return user_id


def require_owner(project_id: str, user_id: str | None = Depends(current_user)) -> None:
    if not user_id:
        raise HTTPException(status_code=403, detail="缺失身份（未携带已认证用户）")
    try:
        owner = uuid.UUID(user_id)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=403, detail="身份非法")
    try:
        project_uuid = uuid.UUID(project_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"项目 id 非法: {project_id}")
    with new_session() as db:
        project = db.get(Project, project_uuid)
        if project is None:
            raise HTTPException(status_code=404, detail="项目不存在")
        if project.user_id != owner:
            raise HTTPException(status_code=403, detail="无权访问该项目")


class _RegisterRequest(BaseModel):
    username: str
    password: str
    invitation_code: str | None = None

    @field_validator("username")
    @classmethod
    def _valid_username(cls, value: str) -> str:
        return normalize_username(value)

    @field_validator("password")
    @classmethod
    def _valid_password(cls, value: str) -> str:
        return validate_password(value)


class _TokenRequest(BaseModel):
    username: str
    password: str


class _PasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _valid_new_password(cls, value: str) -> str:
        return validate_password(value)


@dataclass(frozen=True)
class _TokenClaims:
    user_id: uuid.UUID
    auth_version: int
    # SSE 长连接要按 token 到期时间收流（网关时代的 `auth_expires`），所以这里多带一个。
    expires_at: datetime


class _MfaEnrollRequest(BaseModel):
    # 开启第二因子会改变这个账号的登录方式，所以和改密一样要再验一次密码：
    # 光有 token 就够的话，偷到 token 的人可以把自己的认证器绑上去，实现持久化占坑。
    password: str


@dataclass(frozen=True)
class _AuthenticatedUser:
    id: uuid.UUID
    username: str
    tier: str
    role: str
    password_hash: str | None
    auth_version: int
    # 下面两个随 `_load_identity` 那一次主键读一起拿到，省掉 MFA 路由的第二次查询。
    # 带的是**密文**，明文只在 `_verify_code` 前一步解开。
    totp_secret: str | None
    totp_confirmed_at: datetime | None


def _decode_token(token: str) -> _TokenClaims:
    """Verify signature, issuer and required claims. Any failure is 401.

    This is the same check the Go gateway used to run (HS256 + issuer ``myink`` +
    required ``sub/iss/iat/exp/ver`` + UUID ``sub`` + integral ``ver`` >= 1).
    """
    require_auth_configuration()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[_ALG],
            issuer=_ISS,
            options={"require": ["sub", "iss", "iat", "exp", "ver"]},
        )
        user_id = uuid.UUID(claims["sub"])
        auth_version = claims["ver"]
        # bool is an int subclass, so it has to be rejected explicitly
        if isinstance(auth_version, bool) or not isinstance(auth_version, int) or auth_version < 1:
            raise ValueError("invalid token version")
        expires_at = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
    except (jwt.PyJWTError, KeyError, TypeError, ValueError, AttributeError, OSError, OverflowError):
        raise _invalid_credentials()
    return _TokenClaims(user_id=user_id, auth_version=auth_version, expires_at=expires_at)


def _load_identity(claims: _TokenClaims) -> _AuthenticatedUser | None:
    """Primary-key read of the account; ``None`` when it is gone or its session was revoked."""
    with new_session() as db:
        user = db.get(User, claims.user_id)
        if user is None or user.auth_version != claims.auth_version:
            return None
        return _AuthenticatedUser(
            id=user.id,
            username=user.username,
            tier=user.tier,
            role=user.role,
            password_hash=user.password_hash,
            auth_version=user.auth_version,
            totp_secret=user.totp_secret,
            totp_confirmed_at=user.totp_confirmed_at,
        )


def _create_mfa_challenge(user: User) -> str:
    """签一张只够用来验一次码的短票；它不是 access token（issuer 不同）。"""
    require_auth_configuration()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user.id),
            "iss": _MFA_ISS,
            "ver": user.auth_version,
            "iat": now,
            "exp": now + timedelta(seconds=_MFA_CHALLENGE_TTL),
        },
        settings.jwt_secret,
        algorithm=_ALG,
    )


def _decode_challenge(token: str) -> _TokenClaims:
    """只认挑战令牌。与 `_decode_token` 唯一的差别是 issuer，其余校验（含 `ver`）相同。"""
    require_auth_configuration()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[_ALG],
            issuer=_MFA_ISS,
            options={"require": ["sub", "iss", "iat", "exp", "ver"]},
        )
        user_id = uuid.UUID(claims["sub"])
        auth_version = claims["ver"]
        if isinstance(auth_version, bool) or not isinstance(auth_version, int) or auth_version < 1:
            raise ValueError("invalid token version")
        expires_at = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
    except (jwt.PyJWTError, KeyError, TypeError, ValueError, AttributeError, OSError, OverflowError):
        raise _mfa_invalid()
    return _TokenClaims(user_id=user_id, auth_version=auth_version, expires_at=expires_at)


def _mfa_enabled(user: User) -> bool:
    """只有「已确认」才算开启。写进密钥但没确认的半成品不该把人锁在门外。"""
    return user.totp_confirmed_at is not None and bool(user.totp_secret)


def _confirmed_totp_secret(user: _AuthenticatedUser) -> str | None:
    """已开启账号的密钥明文；没开启或解不开都返回 ``None``，调用方一律拒绝。"""
    if user.totp_confirmed_at is None:
        return None
    return decrypt_totp_secret(user.totp_secret)


def _verify_code(secret: str, code: str) -> bool:
    """±1 个 30 秒窗口，容忍客户端时钟漂移。非法输入当作不匹配，不抛给上层。"""
    candidate = code.strip()
    if not candidate.isdigit():
        return False
    try:
        # pyotp 解 base32 失败时抛 binascii.Error，它是 ValueError 的子类。
        return pyotp.TOTP(secret).verify(candidate, valid_window=1)
    except (ValueError, TypeError):
        return False


def _mfa_challenge_response(user: User) -> dict:
    return {
        "mfa_required": True,
        "mfa_token": _create_mfa_challenge(user),
        "expires_in": _MFA_CHALLENGE_TTL,
    }


def _decode_bearer(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> _TokenClaims:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _invalid_credentials()
    return _decode_token(credentials.credentials)


def _authenticated_user(claims: _TokenClaims = Depends(_decode_bearer)) -> _AuthenticatedUser:
    user = _load_identity(claims)
    if user is None:
        raise _invalid_credentials()
    return user


def require_admin(
    user: _AuthenticatedUser = Depends(_authenticated_user),
) -> _AuthenticatedUser:
    """Require a strictly authenticated account whose current DB role is admin."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="ADMIN_REQUIRED")
    return user


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _auth_response(user: User) -> dict:
    return {
        "token": create_access_token(user.id, user.tier, user.auth_version),
        "user_id": str(user.id),
        "username": user.username,
        "tier": user.tier,
        "role": user.role,
        "expires_in": settings.jwt_ttl,
    }


@router.post("/auth/register", status_code=status.HTTP_201_CREATED, response_model=AuthResponse,
             dependencies=[Depends(auth_rate_limit)])
def register(body: _RegisterRequest, response: Response) -> dict:
    require_auth_configuration()
    try:
        with new_session() as db:
            validate_invitation(db, body.invitation_code)
    except InvitationRejected as exc:
        raise HTTPException(status_code=403, detail=exc.code)
    with _password_capacity():
        password_hash = hash_password(body.password)
    with new_session() as db:
        user = User(
            username=body.username,
            password_hash=password_hash,
            auth_version=1,
            tier="normal",
            role="user",
            environment={},
        )
        try:
            consume_invitation(db, body.invitation_code)
            db.add(user)
            db.flush()
            payload = _auth_response(user)
            db.commit()
        except InvitationRejected as exc:
            db.rollback()
            raise HTTPException(status_code=403, detail=exc.code)
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="USERNAME_TAKEN")
        except Exception:
            db.rollback()
            raise
    _no_store(response)
    return payload


@router.post("/auth/token", response_model=AuthResponse | MfaChallengeOut,
             dependencies=[Depends(auth_rate_limit)])
def issue_token(body: _TokenRequest, response: Response) -> dict:
    require_auth_configuration()
    if not 1 <= len(body.password) <= 128:
        raise _invalid_credentials()
    try:
        username = normalize_username(body.username)
    except (TypeError, ValueError, AttributeError):
        raise _invalid_credentials()
    # 账号维度限流放在验密之前：换 IP（代理池）绕不过这个桶。见 ratelimit.account_auth_guard。
    account_auth_guard(username)
    with new_session() as db:
        user = db.execute(
            select(User).where(func.lower(func.btrim(User.username)) == username)
        ).scalar_one_or_none()
        stored_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
        with _password_capacity():
            password_matches = verify_password(body.password, stored_hash)
        if user is None or not password_matches:
            account_auth_failed(username)
            raise _invalid_credentials()
        # 密码对了但开了第二因子：不发 token，改发一张挑战票。200 而不是 401——密码没错，
        # 这不是错误；401 还会跟前端「带 token 的 401 就全局登出」的逻辑纠缠。
        payload = _mfa_challenge_response(user) if _mfa_enabled(user) else _auth_response(user)
    account_auth_cleared(username)
    _no_store(response)
    return payload


@router.get("/auth/session", response_model=AuthSessionOut)
def auth_session(response: Response, user: _AuthenticatedUser = Depends(_authenticated_user)) -> dict:
    # 自检登录态 + 顺手续期：返回一张新令牌。写一篇两万字要几分钟，30 分钟的硬到期会在
    # 写作中间把人踢出去；前端在旧令牌过期前调这里换新的，于是「标签页还开着」就等于
    # 「不会掉线」。旧令牌不吊销——它本来就还没到期，吊销会打断正拿它跑的请求和 SSE 流；
    # 真要即时踢人走 /auth/logout（自增 auth_version，所有设备立刻失效）。
    _no_store(response)
    return {
        "user_id": str(user.id),
        "username": user.username,
        "tier": user.tier,
        "role": user.role,
        "token": create_access_token(user.id, user.tier, user.auth_version),
        "expires_in": settings.jwt_ttl,
    }


@router.post("/auth/password", response_model=OkOut, dependencies=[Depends(auth_rate_limit)])
def change_password(
    body: _PasswordRequest,
    response: Response,
    user: _AuthenticatedUser = Depends(_authenticated_user),
) -> dict:
    with _password_capacity():
        if not verify_password(body.current_password, user.password_hash):
            raise _invalid_credentials()
        new_hash = hash_password(body.new_password)
    with new_session() as db:
        result = db.execute(
            update(User)
            .where(
                User.id == user.id,
                User.auth_version == user.auth_version,
                User.password_hash == user.password_hash,
            )
            .values(password_hash=new_hash, auth_version=User.auth_version + 1)
        )
        if result.rowcount != 1:
            db.rollback()
            raise _invalid_credentials()
        db.commit()
    _no_store(response)
    return {"ok": True}


@router.post("/auth/logout", response_model=OkOut)
def logout(
    response: Response,
    user: _AuthenticatedUser = Depends(_authenticated_user),
) -> dict:
    with new_session() as db:
        result = db.execute(
            update(User)
            .where(User.id == user.id, User.auth_version == user.auth_version)
            .values(auth_version=User.auth_version + 1)
        )
        if result.rowcount != 1:
            db.rollback()
            raise _invalid_credentials()
        db.commit()
    _no_store(response)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 第二因子（TOTP，`/admin` 用；机制见 docs/AUTH.md）
#
# 开启是**可选**的：没开启的账号登录行为与从前一字不差。一旦开启，登录就必须带验证码。
# 认器丢了只有一条路——服务器上 `myink mfa-disable <用户名>`。
# ---------------------------------------------------------------------------


@router.get("/auth/mfa", response_model=MfaStatusOut)
def mfa_status(response: Response, user: _AuthenticatedUser = Depends(require_admin)) -> dict:
    """给账号页读状态用。刻意不并进 `/auth/session`：那个端点 60 秒轮询一次、形状被测试钉住。"""
    _no_store(response)
    return {"enabled": user.totp_confirmed_at is not None}


@router.post("/auth/mfa/enroll", response_model=MfaEnrollOut,
             dependencies=[Depends(auth_rate_limit)])
def mfa_enroll(
    body: _MfaEnrollRequest,
    response: Response,
    user: _AuthenticatedUser = Depends(require_admin),
) -> dict:
    """生成一个**待确认**的密钥；确认之前不影响登录。

    已开启的账号不给重新注册（那等于用一次不带验证码的请求把第二因子换掉）——先关再开。
    """
    if user.totp_confirmed_at is not None:
        raise HTTPException(status_code=409, detail="MFA_ALREADY_ENABLED")
    with _password_capacity():
        if not verify_password(body.password, user.password_hash):
            raise _invalid_credentials()
    secret = pyotp.random_base32()
    with new_session() as db:
        result = db.execute(
            update(User)
            .where(User.id == user.id, User.auth_version == user.auth_version)
            .values(totp_secret=encrypt_totp_secret(secret))
        )
        if result.rowcount != 1:
            db.rollback()
            raise _invalid_credentials()
        db.commit()
    _no_store(response)
    return {
        "secret": secret,
        "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(
            name=user.username, issuer_name=_TOTP_ISSUER
        ),
    }


@router.post("/auth/mfa/confirm", response_model=OkOut,
             dependencies=[Depends(auth_rate_limit)])
def mfa_confirm(
    body: MfaCodeRequest,
    response: Response,
    user: _AuthenticatedUser = Depends(require_admin),
) -> dict:
    """拿认证器里刚出现的一次码确认开启。

    成功时**自增 auth_version**：`/auth/session` 是滑动续期（标签页开着就永不过期），
    所以开启之前签发的 token 否则会一直有效，把第二因子整个绕过去。代价是当前会话掉线一次。
    """
    if user.totp_confirmed_at is not None:
        raise HTTPException(status_code=409, detail="MFA_ALREADY_ENABLED")
    account = str(user.id)
    mfa_guard(account)
    secret = decrypt_totp_secret(user.totp_secret)
    if secret is None or not _verify_code(secret, body.code):
        mfa_failed(account)
        raise _mfa_invalid()
    with new_session() as db:
        result = db.execute(
            update(User)
            .where(User.id == user.id, User.auth_version == user.auth_version)
            .values(totp_confirmed_at=func.now(), auth_version=User.auth_version + 1)
        )
        if result.rowcount != 1:
            db.rollback()
            raise _invalid_credentials()
        db.commit()
    mfa_cleared(account)
    _no_store(response)
    return {"ok": True}


@router.post("/auth/mfa/disable", response_model=OkOut,
             dependencies=[Depends(auth_rate_limit)])
def mfa_disable(
    body: MfaCodeRequest,
    response: Response,
    user: _AuthenticatedUser = Depends(require_admin),
) -> dict:
    """验一次码再关（拿不出码的去服务器跑 `myink mfa-disable`）。同时踢掉所有会话。"""
    account = str(user.id)
    mfa_guard(account)
    secret = _confirmed_totp_secret(user)
    if secret is None or not _verify_code(secret, body.code):
        mfa_failed(account)
        raise _mfa_invalid()
    with new_session() as db:
        result = db.execute(
            update(User)
            .where(User.id == user.id, User.auth_version == user.auth_version)
            .values(totp_secret=None, totp_confirmed_at=None, auth_version=User.auth_version + 1)
        )
        if result.rowcount != 1:
            db.rollback()
            raise _invalid_credentials()
        db.commit()
    mfa_cleared(account)
    _no_store(response)
    return {"ok": True}


@router.post("/auth/mfa/verify", response_model=AuthResponse,
             dependencies=[Depends(auth_rate_limit)])
def verify_mfa(body: MfaVerifyRequest, response: Response) -> dict:
    """拿挑战票 + 一次码换正式 token。失败一律 401 MFA_INVALID。

    不区分「码错」「码过期」「票过期」，不给攻击者任何区分信号；与密码错分开只是为了让
    前端的第二步能说人话（票里已经有 sub，密码对没对这一步是已知的）。
    """
    require_auth_configuration()
    claims = _decode_challenge(body.mfa_token)
    account = str(claims.user_id)
    mfa_guard(account)
    with new_session() as db:
        user = db.get(User, claims.user_id)
        # 挑战票里的 ver 要跟库里再比一次：这中间改了密码/退出过，在途的票就该作废。
        if user is None or user.auth_version != claims.auth_version or not _mfa_enabled(user):
            mfa_failed(account)
            raise _mfa_invalid()
        secret = decrypt_totp_secret(user.totp_secret)
        if secret is None or not _verify_code(secret, body.code):
            mfa_failed(account)
            raise _mfa_invalid()
        payload = _auth_response(user)
    mfa_cleared(account)
    _no_store(response)
    return payload
