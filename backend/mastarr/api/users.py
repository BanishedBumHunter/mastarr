"""User management. Admin-only, enforced entirely at the router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..auth.deps import require_admin
from ..auth.security import hash_password
from ..db import get_session
from ..models import User
from .schemas import CreateUserRequest, UpdateUserRequest, UserOut

# One dependency on the router covers every route below it — an endpoint added here
# cannot accidentally ship unprotected.
router = APIRouter(
    prefix="/users", tags=["users"], dependencies=[Depends(require_admin)]
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


@router.get("", response_model=list[UserOut])
async def list_users(session: Session = Depends(get_session)) -> list[UserOut]:
    return [_user_out(u) for u in session.exec(select(User)).all()]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest, session: Session = Depends(get_session)
) -> UserOut:
    username = body.username.strip()
    if session.exec(select(User).where(User.username == username)).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user named '{username}' already exists.",
        )

    user = User(
        username=username,
        password_hash=hash_password(body.password),
        role=body.role,
        jellyseerr_user_id=body.jellyseerr_user_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return _user_out(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> UserOut:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user.")

    if body.password is not None:
        user.password_hash = hash_password(body.password)
        # Invalidate every existing session for this user.
        user.token_epoch += 1

    if body.role is not None and body.role != user.role:
        _guard_last_admin(session, user, "change the role of")
        user.role = body.role
        user.token_epoch += 1

    if body.jellyseerr_user_id is not None:
        # 0 means "unlink" — the field is nullable and 0 is never a valid Jellyseerr id.
        user.jellyseerr_user_id = body.jellyseerr_user_id or None

    if body.is_active is not None and body.is_active != user.is_active:
        if not body.is_active:
            _guard_last_admin(session, user, "disable")
        user.is_active = body.is_active
        user.token_epoch += 1

    session.add(user)
    session.commit()
    session.refresh(user)
    return _user_out(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user.")
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account.",
        )
    _guard_last_admin(session, user, "delete")
    session.delete(user)
    session.commit()


def _guard_last_admin(session: Session, user: User, action: str) -> None:
    """Refuse anything that would leave the instance with no active admin.

    Without this, an admin can lock everyone out of stack configuration permanently, with
    no recovery path short of editing the database by hand.
    """
    from ..roles import Role

    if user.role != Role.ADMIN:
        return
    remaining = session.exec(
        select(User).where(
            User.role == Role.ADMIN,
            User.is_active == True,  # noqa: E712
            User.id != user.id,
        )
    ).first()
    if remaining is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot {action} the only remaining admin account.",
        )
