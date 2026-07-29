"""Discovery and requests, backed by Jellyseerr/Overseerr.

Available to Requesters as well as admins — this is the surface that makes Mastarr worth
sharing with other people. Requesters see only their own requests, enforced server-side by
scoping the upstream query, so other users' data never reaches the response at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..adapters import AdapterError, JellyseerrAdapter
from ..adapters.schemas import DiscoverPage, MediaRequest
from ..aggregate import first_service_of_type
from ..auth.deps import require_admin, require_requester
from ..db import get_session
from ..models import Service, User
from ..roles import Role
from ..services import adapter_for

router = APIRouter(
    prefix="/discover", tags=["discover"], dependencies=[Depends(require_requester)]
)


class RequestCreate(BaseModel):
    tmdb_id: int
    media_kind: str = Field(pattern="^(movie|tv)$")
    seasons: list[int] | None = None


class Capabilities(BaseModel):
    """What the request surface can do right now, so the UI renders honestly."""

    backend: str | None = None
    available: bool = False
    can_request: bool = False
    message: str | None = None


def _jellyseerr(session: Session) -> tuple[Service, JellyseerrAdapter]:
    service = first_service_of_type(session, "jellyseerr")
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No Jellyseerr or Overseerr service is connected. An administrator can "
                "add one under Services."
            ),
        )
    adapter = adapter_for(service)
    if not isinstance(adapter, JellyseerrAdapter):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The configured request service is not a Jellyseerr instance.",
        )
    return service, adapter


async def _call(adapter, operation):
    try:
        return await operation(adapter)
    except AdapterError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message
        ) from exc
    finally:
        await adapter.aclose()


@router.get("/capabilities", response_model=Capabilities)
async def capabilities(session: Session = Depends(get_session)) -> Capabilities:
    """Deliberately never errors — the UI uses it to decide what to render."""
    service = first_service_of_type(session, "jellyseerr")
    if service is None:
        return Capabilities(
            message=(
                "No Jellyseerr or Overseerr instance is connected, so browsing and "
                "requesting are unavailable. An administrator can connect one."
            )
        )
    return Capabilities(backend="jellyseerr", available=True, can_request=True)


@router.get("/search", response_model=DiscoverPage)
async def search(
    q: str = Query(min_length=1),
    page: int = Query(1, ge=1),
    session: Session = Depends(get_session),
) -> DiscoverPage:
    _, adapter = _jellyseerr(session)
    return await _call(adapter, lambda a: a.discover_search(q, page))


@router.get("/feed", response_model=DiscoverPage)
async def feed(
    kind: str = Query("trending", pattern="^(trending|movies|tv)$"),
    page: int = Query(1, ge=1),
    session: Session = Depends(get_session),
) -> DiscoverPage:
    """Browse without searching, so the page isn't empty on arrival."""
    _, adapter = _jellyseerr(session)
    return await _call(adapter, lambda a: a.discover(kind, page))


@router.post("/request", response_model=MediaRequest, status_code=status.HTTP_201_CREATED)
async def create_request(
    body: RequestCreate,
    user: User = Depends(require_requester),
    session: Session = Depends(get_session),
) -> MediaRequest:
    """Submit a request, attributed to the caller's mapped Jellyseerr account."""
    _, adapter = _jellyseerr(session)
    return await _call(
        adapter,
        lambda a: a.create_request(
            tmdb_id=body.tmdb_id,
            media_kind=body.media_kind,
            user_id=user.jellyseerr_user_id,
            seasons=body.seasons,
        ),
    )


@router.get("/requests", response_model=list[MediaRequest])
async def list_requests(
    mine_only: bool = Query(False),
    take: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    user: User = Depends(require_requester),
    session: Session = Depends(get_session),
) -> list[MediaRequest]:
    """Requests. Admins see everything; Requesters are scoped to their own, upstream.

    The scoping is applied in the query sent to Jellyseerr rather than by filtering the
    response here — so another user's requests are never in the payload to begin with.
    """
    _, adapter = _jellyseerr(session)

    if user.role == Role.ADMIN and not mine_only:
        user_id = None
    else:
        user_id = user.jellyseerr_user_id
        if user_id is None:
            # Unmapped non-admin: returning everything would leak other people's
            # requests, so return nothing and let the UI explain.
            if user.role != Role.ADMIN:
                await adapter.aclose()
                return []

    return await _call(
        adapter, lambda a: a.requests(user_id=user_id, take=take, skip=skip)
    )


@router.post("/requests/{request_id}/decide", response_model=MediaRequest)
async def decide_request(
    request_id: int,
    approve: bool = Query(...),
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> MediaRequest:
    """Approve or decline. Admin-only, enforced by the extra dependency."""
    _, adapter = _jellyseerr(session)
    return await _call(adapter, lambda a: a.decide_request(request_id, approve))


@router.get("/users")
async def jellyseerr_users(
    _: User = Depends(require_admin), session: Session = Depends(get_session)
) -> list[dict]:
    """Jellyseerr accounts, so an admin can map Mastarr users onto them."""
    _, adapter = _jellyseerr(session)
    return await _call(adapter, lambda a: a.users())
