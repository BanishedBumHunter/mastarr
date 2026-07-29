"""SQLModel tables for Mastarr's own config DB.

Only Mastarr's state lives here — connected services, users, prefs. Media state is never
mirrored; that always comes live from the *arrs through an adapter.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel

from .roles import Role


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Service(SQLModel, table=True):
    """A connected *arr service. `api_key_encrypted` is Fernet ciphertext, never plaintext."""

    __tablename__ = "service"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    service_type: str = Field(index=True)
    url: str
    api_key_encrypted: Optional[str] = None
    enabled: bool = True

    # Populated from the last successful system/status call, so the UI can show identity
    # and version without blocking on a live request.
    last_status: Optional[str] = None
    last_version: Optional[str] = None
    last_checked_at: Optional[datetime] = None

    # True when the row came from config.yml — the UI marks these read-only, since a UI
    # edit would be silently reverted on next startup reconcile.
    managed_by_config: bool = False

    created_at: datetime = Field(default_factory=_utcnow)


class User(SQLModel, table=True):
    __tablename__ = "user"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    role: Role = Field(default=Role.REQUESTER)
    is_active: bool = True
    created_at: datetime = Field(default_factory=_utcnow)

    # Bumped on password change or forced logout; embedded in issued tokens so existing
    # sessions are invalidated without needing a server-side session table.
    token_epoch: int = 0

    # Maps this account onto a Jellyseerr user, so requests are attributed to the right
    # person and "my requests" is a real server-side filter rather than a client-side
    # pretence. Unmapped users fall back to whoever owns the API key.
    jellyseerr_user_id: Optional[int] = None


class SchemaVersion(SQLModel, table=True):
    """Standing in for Alembic while the project is INACTIVE. See CLAUDE.md."""

    __tablename__ = "schema_version"

    id: Optional[int] = Field(default=None, primary_key=True)
    version: int = 1
    applied_at: datetime = Field(default_factory=_utcnow)
