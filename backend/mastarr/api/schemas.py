"""Request/response bodies for the HTTP API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..roles import Role


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class UserOut(BaseModel):
    id: int
    username: str
    role: Role
    is_active: bool
    created_at: datetime
    # Which Jellyseerr account this user's requests are attributed to.
    jellyseerr_user_id: int | None = None


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    role: Role = Role.REQUESTER
    jellyseerr_user_id: int | None = None


class UpdateUserRequest(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=256)
    role: Role | None = None
    is_active: bool | None = None
    jellyseerr_user_id: int | None = None


class AuthState(BaseModel):
    """Bootstrap payload — lets the frontend pick a route tree before rendering."""

    needs_setup: bool
    authenticated: bool
    user: UserOut | None = None


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    service_type: str
    url: str
    api_key: str | None = None
    enabled: bool = True


class ServiceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    # Absent leaves the stored key untouched; empty string clears it.
    api_key: str | None = None
    enabled: bool | None = None


class ServiceOut(BaseModel):
    """A configured service. Deliberately carries no API key, only whether one is set."""

    id: int
    name: str
    service_type: str
    url: str
    enabled: bool
    has_api_key: bool
    managed_by_config: bool
    last_status: str | None = None
    last_version: str | None = None
    last_checked_at: datetime | None = None


class ScanRequest(BaseModel):
    hosts: list[str] = Field(default_factory=list)
    ports: list[int] | None = None


class IdentifyRequest(BaseModel):
    url: str
    api_key: str
    service_type: str | None = None
