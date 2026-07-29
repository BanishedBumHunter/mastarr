"""Authentication endpoints: first-run setup, login, logout, whoami."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session, select

from ..auth.deps import get_current_user, get_optional_user, has_any_user
from ..roles import Role
from ..auth.security import COOKIE_NAME, create_token, hash_password, verify_password
from ..config import get_settings
from ..db import get_session
from ..models import User
from .schemas import AuthState, LoginRequest, SetupRequest, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.session_hours * 3600,
        path="/",
        # Not `secure=True`: Mastarr is commonly reached over plain HTTP on a LAN, and a
        # secure cookie would silently break login there. Put it behind TLS at the proxy.
        secure=False,
    )


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id or 0,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        jellyseerr_user_id=user.jellyseerr_user_id,
    )


@router.get("/state", response_model=AuthState)
async def auth_state(
    user: User | None = Depends(get_optional_user),
    session: Session = Depends(get_session),
) -> AuthState:
    """Unauthenticated bootstrap. Tells the frontend which shell to mount."""
    return AuthState(
        needs_setup=not has_any_user(session),
        authenticated=user is not None,
        user=_user_out(user) if user else None,
    )


@router.post("/setup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def first_run_setup(
    body: SetupRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> UserOut:
    """Claim an unclaimed instance by creating the admin account.

    Deliberately unauthenticated, and deliberately usable exactly once — the empty user
    table *is* the authorization. Once any user exists this returns 409 forever.
    """
    if has_any_user(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This instance has already been set up.",
        )

    user = User(
        username=body.username.strip(),
        password_hash=hash_password(body.password),
        role=Role.ADMIN,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    _set_session_cookie(
        response,
        create_token(
            user_id=user.id or 0,
            username=user.username,
            role=user.role.value,
            token_epoch=user.token_epoch,
        ),
    )
    return _user_out(user)


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> UserOut:
    user = session.exec(
        select(User).where(User.username == body.username.strip())
    ).first()

    # Same message and same work for "no such user" and "wrong password", so the endpoint
    # is not a username oracle.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled."
        )

    _set_session_cookie(
        response,
        create_token(
            user_id=user.id or 0,
            username=user.username,
            role=user.role.value,
            token_epoch=user.token_epoch,
        ),
    )
    return _user_out(user)


@router.post("/token")
async def issue_token(
    body: LoginRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    """Bearer token for programmatic clients (scripts, CLI).

    Kept separate from `/login` so the browser flow stays strictly cookie-based and the
    frontend never has a token to store — nothing for XSS to steal.
    """
    user = session.exec(
        select(User).where(User.username == body.username.strip())
    ).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled."
        )

    token = create_token(
        user_id=user.id or 0,
        username=user.username,
        role=user.role.value,
        token_epoch=user.token_epoch,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": get_settings().session_hours * 3600,
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def logout(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
async def whoami(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)
