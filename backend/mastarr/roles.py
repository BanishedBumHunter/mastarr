"""Roles.

An enum from the outset, never an `is_admin` boolean. A boolean forces a schema migration
and a rewrite of every check the moment a third role appears; an enum plus the rank ordering
below makes new roles additive.

Lives at the top level rather than inside `auth/` because a role is a domain concept that
`models` needs too — putting it in the auth package created a `models -> auth -> models`
import cycle. `mastarr.auth` re-exports `Role` for convenience.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"
    REQUESTER = "requester"


# Higher rank implies every capability of the ranks below it. A new role slots in by
# adding one entry here — no existing check changes.
_RANK: dict[Role, int] = {
    Role.REQUESTER: 10,
    Role.ADMIN: 100,
}


def rank(role: Role) -> int:
    return _RANK.get(role, 0)


def satisfies(actual: Role, required: Role) -> bool:
    """Does `actual` meet the bar set by `required`?"""
    return rank(actual) >= rank(required)
