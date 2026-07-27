"""Password hashing and session tokens."""

from __future__ import annotations

import secrets
import stat
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from ..config import Settings, get_settings

_hasher = PasswordHasher()

ALGORITHM = "HS256"
COOKIE_NAME = "mastarr_session"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return False


def load_or_create_jwt_secret(settings: Settings) -> str:
    """Session signing secret, kept separate from the API-key encryption key.

    Two separate secrets so that rotating the session secret (log everybody out) can never
    be confused with rotating the encryption key (make every stored API key unreadable).
    """
    if settings.jwt_secret:
        return settings.jwt_secret

    secret_file = settings.data_dir / "jwt.secret"
    if secret_file.is_file():
        return secret_file.read_text().strip()

    secret = secrets.token_urlsafe(48)
    secret_file.write_text(secret)
    secret_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return secret


_secret: str | None = None


def _get_secret() -> str:
    global _secret
    if _secret is None:
        _secret = load_or_create_jwt_secret(get_settings())
    return _secret


def reset_secret() -> None:
    """Test hook."""
    global _secret
    _secret = None


class TokenError(Exception):
    """Token missing, malformed, expired, or superseded."""


def create_token(
    *, user_id: int, username: str, role: str, token_epoch: int = 0
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        # Bumped on password change, so old sessions die without a session table.
        "epoch": token_epoch,
        "iat": now,
        "exp": now + timedelta(hours=settings.session_hours),
    }
    return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Session expired.") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid session token.") from exc
