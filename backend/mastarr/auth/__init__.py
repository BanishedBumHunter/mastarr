"""Authentication and the authorization seam."""

from .deps import (
    get_current_user,
    get_optional_user,
    has_any_user,
    require_admin,
    require_requester,
    require_role,
)
from ..roles import Role, satisfies
from .security import (
    COOKIE_NAME,
    TokenError,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)

__all__ = [
    "COOKIE_NAME",
    "Role",
    "TokenError",
    "create_token",
    "decode_token",
    "get_current_user",
    "get_optional_user",
    "has_any_user",
    "hash_password",
    "require_admin",
    "require_requester",
    "require_role",
    "satisfies",
    "verify_password",
]
