"""The authorization seam.

Every protected endpoint declares its requirement here and nowhere else:

    @router.get("/services", dependencies=[Depends(require_role(Role.ADMIN))])

or, when the handler needs the user:

    async def handler(user: User = Depends(require_admin)):

Ad-hoc `if user.role == ...` inside a handler is banned by CLAUDE.md. Centralizing means
adding a role, changing how roles nest, or adding audit logging is a single-file change —
and it means an endpoint can never accidentally ship with no check at all, because the
absence of a dependency is visible at the router.
"""

from __future__ import annotations

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlmodel import Session, select

from ..db import get_session
from ..models import User
from ..roles import Role, satisfies
from .security import COOKIE_NAME, TokenError, decode_token

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_token(
    authorization: str | None, cookie_token: str | None
) -> str | None:
    """Bearer header for API clients, httpOnly cookie for the browser UI."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return cookie_token


async def get_current_user(
    authorization: str | None = Header(default=None),
    mastarr_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    session: Session = Depends(get_session),
) -> User:
    token = _extract_token(authorization, mastarr_session)
    if not token:
        raise CREDENTIALS_ERROR

    try:
        payload = decode_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError) as exc:
        raise CREDENTIALS_ERROR from exc

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise CREDENTIALS_ERROR

    # Role and epoch are re-read from the DB, never trusted from the token. A role
    # downgrade or forced logout therefore takes effect immediately rather than at token
    # expiry.
    if payload.get("epoch", 0) != user.token_epoch:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been invalidated. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_optional_user(
    authorization: str | None = Header(default=None),
    mastarr_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    session: Session = Depends(get_session),
) -> User | None:
    """For endpoints that vary by auth state but do not require it (e.g. bootstrap)."""
    try:
        return await get_current_user(authorization, mastarr_session, session)
    except HTTPException:
        return None


def require_role(required: Role):
    """Build a dependency enforcing `required`. This is the only authorization decision."""

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if not satisfies(user.role, required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the {required.value} role.",
            )
        return user

    return dependency


require_admin = require_role(Role.ADMIN)
require_requester = require_role(Role.REQUESTER)


def has_any_user(session: Session) -> bool:
    """First-run detection: is the instance claimed yet?"""
    return session.exec(select(User).limit(1)).first() is not None
