"""SuggestArr's approval queue.

SuggestArr proposes things to watch based on what you've actually finished. In approval
mode it parks each proposal instead of requesting it, which makes the queue a decision
surface — and Mastarr already owns the others (release picking, queue removal, requests).

Admin-only. Approving a suggestion creates a real request and, downstream, a real
download, so this is not a Requester's button.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..adapters import AdapterError
from ..adapters.schemas import SuggestionPage
from ..adapters.suggestarr import SUGGESTION_STATUSES
from ..aggregate import first_service_of_type
from ..auth.deps import require_admin
from ..db import get_session
from ..services import adapter_for

router = APIRouter(
    prefix="/suggestions", tags=["suggestions"], dependencies=[Depends(require_admin)]
)


class DecideRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)
    action: str
    """approve, reject, blacklist or retry."""


class DecideOut(BaseModel):
    updated: int


class AvailabilityOut(BaseModel):
    """Whether this install has a SuggestArr at all, so the UI can hide the tab."""

    available: bool = False
    service_id: int | None = None
    service_name: str | None = None
    message: str | None = None


def _suggestarr(session: Session):
    service = first_service_of_type(session, "suggestarr")
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No SuggestArr is connected. Add one under Settings → Services, with the "
                "username and password you log into SuggestArr with."
            ),
        )
    return service


async def _call(service, operation):
    adapter = adapter_for(service)
    try:
        return await operation(adapter)
    except AdapterError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message
        ) from exc
    finally:
        await adapter.aclose()


@router.get("/availability", response_model=AvailabilityOut)
async def availability(session: Session = Depends(get_session)) -> AvailabilityOut:
    """Cheap, never fails. The UI asks this before showing the tab at all."""
    service = first_service_of_type(session, "suggestarr")
    if service is None:
        return AvailabilityOut(message="No SuggestArr connected.")
    if not service.username:
        return AvailabilityOut(
            service_id=service.id,
            service_name=service.name,
            message=(
                f"{service.name} needs a username as well as a password — it logs in "
                f"rather than taking an API key."
            ),
        )
    return AvailabilityOut(
        available=True, service_id=service.id, service_name=service.name
    )


@router.get("", response_model=SuggestionPage)
async def list_suggestions(
    suggestion_status: str = Query(
        "awaiting_approval", alias="status", description=", ".join(SUGGESTION_STATUSES)
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
    search: str = Query("", max_length=100),
    session: Session = Depends(get_session),
) -> SuggestionPage:
    if suggestion_status not in SUGGESTION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown status. Known: {', '.join(SUGGESTION_STATUSES)}.",
        )
    service = _suggestarr(session)
    return await _call(
        service,
        lambda a: a.suggestions(
            status=suggestion_status, page=page, per_page=per_page, search=search
        ),
    )


@router.post("/decide", response_model=DecideOut)
async def decide(
    body: DecideRequest, session: Session = Depends(get_session)
) -> DecideOut:
    """Approve, reject, blacklist or retry a batch.

    Approve creates real requests. Blacklist is the durable one — it stops the same title
    being suggested again, where reject only clears it from this queue.
    """
    if body.action not in ("approve", "reject", "blacklist", "retry"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be approve, reject, blacklist or retry.",
        )
    service = _suggestarr(session)
    updated = await _call(service, lambda a: a.decide(body.ids, body.action))
    return DecideOut(updated=updated)
