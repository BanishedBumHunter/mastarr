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


class EditRequest(BaseModel):
    """Only the fields present are changed."""

    quality_profile_id: int | None = None
    root_folder_path: str | None = None
    monitored: bool | None = None


class AddRequest(BaseModel):
    remote_id: str
    quality_profile_id: int
    root_folder_path: str
    monitored: bool = True
    search_on_add: bool = True


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


# Literal sub-paths first: `/{service_id}/{item_id}` with an int item_id would
# otherwise capture /1/options and reject 'options' as a bad integer.
@router.get("/{service_id}/options")
async def add_options(
    service_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    """Quality profiles and root folders, for the add/edit pickers."""
    service = _service_or_404(session, service_id)

    async def load(adapter):
        return {
            "quality_profiles": [p.model_dump() for p in await adapter.quality_profiles()],
            "root_folders": [f.model_dump() for f in await adapter.root_folders()],
        }

    return await _call(service, load)


@router.get("/{service_id}/lookup")
async def lookup(
    service_id: int,
    term: str = Query(min_length=1),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Search the service's metadata provider for something to add."""
    service = _service_or_404(session, service_id)
    results = await _call(service, lambda a: a.search(term))
    return [r.model_dump() for r in results]


@router.post("/{service_id}/add", status_code=status.HTTP_201_CREATED)
async def add_item(
    service_id: int, body: AddRequest, session: Session = Depends(get_session)
) -> dict:
    """Add something new to a service's library."""
    service = _service_or_404(session, service_id)
    result = await _call(
        service,
        lambda a: a.add_item(
            remote_id=body.remote_id,
            quality_profile_id=body.quality_profile_id,
            root_folder_path=body.root_folder_path,
            monitored=body.monitored,
            search_on_add=body.search_on_add,
        ),
    )
    invalidate_cache(service_id)
    return {"id": result.get("id"), "title": result.get("title")}


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


@router.patch("/{service_id}/{item_id}", response_model=LibraryItem)
async def edit_item(
    service_id: int,
    item_id: int,
    body: EditRequest,
    session: Session = Depends(get_session),
) -> LibraryItem:
    """Change quality profile, root folder or monitoring on an existing item."""
    service = _service_or_404(session, service_id)
    result = await _call(
        service,
        lambda a: a.update_item(
            item_id,
            quality_profile_id=body.quality_profile_id,
            root_folder_path=body.root_folder_path,
            monitored=body.monitored,
        ),
    )
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
