"""Requester-facing endpoints.

A placeholder shell for build priority 6. It exists now so the Requester role is a real,
testable surface rather than an empty route tree — and so the permission seam is exercised
by more than admin endpoints.

Rich discovery/browse is deliberately not reimplemented here: it is an Overseerr-backed
feature. When `OverseerrAdapter` lands, this module gets its data from the adapter layer
and the native fallback writes a monitored item to the appropriate *arr.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.deps import require_requester
from ..models import User

router = APIRouter(
    prefix="/requests", tags=["requests"], dependencies=[Depends(require_requester)]
)


@router.get("/capabilities")
async def capabilities(user: User = Depends(require_requester)) -> dict[str, object]:
    """What the request surface can currently do, so the UI renders honestly."""
    return {
        "backend": None,
        "discovery_available": False,
        "can_submit": False,
        "message": (
            "No Overseerr or Jellyseerr instance is connected, so media browsing is "
            "unavailable. An administrator can connect one, or request items directly "
            "from them in the meantime."
        ),
        "username": user.username,
    }


@router.get("/mine")
async def my_requests(user: User = Depends(require_requester)) -> list[dict[str, object]]:
    """A Requester's own requests — and only ever their own."""
    return []
