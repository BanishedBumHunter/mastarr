"""Unified library — browse and manage series/movies from one place."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..adapters import AdapterError
from ..adapters.schemas import LibraryDetail, LibraryItem
from ..aggregate import ServiceFailure, find_service
from ..aggregate import library as aggregate_library
from ..auth.deps import require_admin
from ..db import get_session
from ..models import Service
from ..services import adapter_for, invalidate_cache

# Admin-only: this exposes file paths, disk usage and destructive actions.
router = APIRouter(
    prefix="/library", tags=["library"], dependencies=[Depends(require_admin)]
)


class LibraryOut(BaseModel):
    items: list[LibraryItem] = Field(default_factory=list)
    failures: list[ServiceFailure] = Field(default_factory=list)


class MonitorRequest(BaseModel):
    monitored: bool


class SeasonMonitorRequest(BaseModel):
    season_number: int
    monitored: bool


def _service_or_404(session: Session, service_id: int) -> Service:
    service = find_service(session, service_id)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such service."
        )
    return service


async def _call(service: Service, operation):
    """Run one adapter operation, mapping adapter failures to an honest 502.

    A failure here is the upstream service's problem, not a bug in Mastarr — 500 would
    point the finger in the wrong direction.
    """
    adapter = adapter_for(service)
    try:
        return await operation(adapter)
    except AdapterError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message
        ) from exc
    finally:
        await adapter.aclose()


@router.get("", response_model=LibraryOut)
async def get_library(
    media_kind: str | None = Query(
        None, description="Filter to one kind up front, e.g. series or movie"
    ),
    session: Session = Depends(get_session),
) -> LibraryOut:
    """Everything, unpaged.

    Real libraries here are hundreds of items, so one payload lets the UI filter and sort
    instantly rather than round-tripping on every keystroke.
    """
    items, failures = await aggregate_library(session, media_kind=media_kind)
    return LibraryOut(items=items, failures=failures)


@router.get("/{service_id}/{item_id}", response_model=LibraryDetail)
async def get_item(
    service_id: int, item_id: int, session: Session = Depends(get_session)
) -> LibraryDetail:
    service = _service_or_404(session, service_id)

    async def load(adapter):
        item = await adapter.library_item(item_id)
        try:
            seasons = await adapter.seasons(item_id)
        except AdapterError:
            seasons = []  # movies and music have none; not an error
        return LibraryDetail(
            item=item, seasons=seasons, native_url=adapter.native_url(item_id)
        )

    return await _call(service, load)


@router.post("/{service_id}/{item_id}/monitor", response_model=LibraryItem)
async def set_monitored(
    service_id: int,
    item_id: int,
    body: MonitorRequest,
    session: Session = Depends(get_session),
) -> LibraryItem:
    service = _service_or_404(session, service_id)
    result = await _call(service, lambda a: a.set_monitored(item_id, body.monitored))
    invalidate_cache(service_id)
    return result


@router.post("/{service_id}/{item_id}/season-monitor", response_model=LibraryItem)
async def set_season_monitored(
    service_id: int,
    item_id: int,
    body: SeasonMonitorRequest,
    session: Session = Depends(get_session),
) -> LibraryItem:
    service = _service_or_404(session, service_id)
    result = await _call(
        service,
        lambda a: a.set_season_monitored(item_id, body.season_number, body.monitored),
    )
    invalidate_cache(service_id)
    return result


@router.post("/{service_id}/{item_id}/search")
async def trigger_search(
    service_id: int, item_id: int, session: Session = Depends(get_session)
) -> dict[str, str]:
    """Ask the owning service to go looking for this item now."""
    service = _service_or_404(session, service_id)
    result = await _call(service, lambda a: a.trigger_search(item_id))
    return {"status": result}


@router.delete("/{service_id}/{item_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_item(
    service_id: int,
    item_id: int,
    delete_files: bool = Query(
        False, description="Also remove files from disk. Irreversible."
    ),
    session: Session = Depends(get_session),
) -> None:
    service = _service_or_404(session, service_id)
    await _call(service, lambda a: a.delete_item(item_id, delete_files))
    invalidate_cache(service_id)
