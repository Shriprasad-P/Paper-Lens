"""Canonical authentication and principal boundary for API routes.

Shared deployments use opaque, revocable cookie/bearer sessions.  The
development desktop path is deliberately explicit: a validated desktop token
maps to one trusted local principal and is never accepted as shared-mode auth.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request, Response, status

from .models.auth import User

logger = logging.getLogger("paperlens.auth")

LEGACY_USER_ID = "user_legacy_local"
LEGACY_USER_EMAIL = "local@paperlens.invalid"
DESKTOP_USER_ID = "user_desktop_local"
DESKTOP_USER_EMAIL = "desktop@paperlens.invalid"


@dataclass(frozen=True, slots=True)
class Principal:
    id: str
    email: str

    def as_user(self) -> User:
        return User(id=self.id, email=self.email)


def normalize_email(value: str) -> str:
    """Normalize login identifiers deterministically without changing content."""

    return value.strip().casefold()


def session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def password_hash(password: str) -> str:
    """Hash a password with Argon2id when installed, otherwise scrypt.

    ``argon2-cffi`` is the production dependency.  The stdlib scrypt fallback
    keeps offline/local test environments safe when optional wheels are absent;
    both algorithms are salted, memory-hard, and verified in constant time.
    """

    try:
        from argon2 import PasswordHasher  # type: ignore[import-not-found]

        return PasswordHasher().hash(password)
    except ImportError:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
        return "scrypt$32768$8$1$" + _b64(salt) + "$" + _b64(digest)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        if stored_hash.startswith("$argon2"):
            from argon2 import PasswordHasher  # type: ignore[import-not-found]
            from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError  # type: ignore[import-not-found]

            try:
                return bool(PasswordHasher().verify(stored_hash, password))
            except (InvalidHashError, VerificationError, VerifyMismatchError):
                return False
        if stored_hash.startswith("scrypt$"):
            _, n, r, p, encoded_salt, encoded_digest = stored_hash.split("$", 5)
            candidate = hashlib.scrypt(
                password.encode("utf-8"),
                salt=_unb64(encoded_salt),
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=len(_unb64(encoded_digest)),
                maxmem=64 * 1024 * 1024,
            )
            return hmac.compare_digest(candidate, _unb64(encoded_digest))
    except (ImportError, ValueError, TypeError):
        return False
    return False


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def session_cookie_secure(request: Request) -> bool:
    return request.app.state.settings.environment == "production"


def issue_session(request: Request, user_id: str) -> str:
    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=request.app.state.settings.auth_session_ttl_seconds)
    request.app.state.database.create_session(
        session_id=f"session_{uuid4().hex}",
        user_id=user_id,
        token_hash=session_token_hash(token),
        created_at=now,
        expires_at=expires_at,
    )
    return token


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        key=request.app.state.settings.auth_cookie_name,
        value=token,
        max_age=request.app.state.settings.auth_session_ttl_seconds,
        expires=request.app.state.settings.auth_session_ttl_seconds,
        httponly=True,
        secure=session_cookie_secure(request),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(key=request.app.state.settings.auth_cookie_name, path="/")


def _presented_token(request: Request) -> str | None:
    cookie = request.cookies.get(request.app.state.settings.auth_cookie_name)
    if cookie:
        return cookie
    authorization = request.headers.get("authorization", "")
    scheme, _, value = authorization.partition(" ")
    if scheme.casefold() == "bearer" and value.strip():
        return value.strip()
    return None


def get_current_user(request: Request) -> User | None:
    """Resolve the one canonical principal for a request.

    The function intentionally does not raise so public auth endpoints can
    inspect an anonymous request.  Protected routes call
    :func:`require_current_user`.
    """

    cached = getattr(request.state, "current_user", None)
    if isinstance(cached, User):
        return cached
    database = request.app.state.database
    if getattr(request.state, "desktop_authenticated", False) and not request.app.state.settings.requires_authentication:
        user = database.ensure_local_user(DESKTOP_USER_ID, DESKTOP_USER_EMAIL)
        request.state.current_user = user
        return user

    token = _presented_token(request)
    if token:
        user = database.get_user_by_session_hash(session_token_hash(token))
        if user is not None:
            request.state.current_user = user
            return user
        _audit(request, "session_rejected", None, {"reason": "invalid_or_expired"})

    if not request.app.state.settings.requires_authentication:
        user = database.ensure_local_user(LEGACY_USER_ID, LEGACY_USER_EMAIL)
        request.state.current_user = user
        return user
    return None


def require_current_user(request: Request) -> User:
    user = get_current_user(request)
    if user is None:
        _audit(request, "authorization_rejected", None, {"reason": "unauthenticated"})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication is required.")
    return user


def revoke_presented_session(request: Request) -> bool:
    token = _presented_token(request)
    if not token:
        return False
    user = get_current_user(request)
    revoked = request.app.state.database.revoke_session(session_token_hash(token))
    if revoked:
        _audit(request, "session_revoked", user.id if user else None, {})
    return revoked


def _audit(request: Request, event: str, user_id: str | None, metadata: dict[str, Any]) -> None:
    try:
        request.app.state.database.record_audit_event(
            event=event,
            user_id=user_id,
            metadata={"request_id": getattr(request.state, "request_id", "unknown"), **metadata},
        )
    except Exception:
        logger.warning(json.dumps({"event": "audit_write_failed", "audit_event": event}, separators=(",", ":")))


def audit(request: Request, event: str, user_id: str | None, metadata: dict[str, Any] | None = None) -> None:
    _audit(request, event, user_id, metadata or {})
