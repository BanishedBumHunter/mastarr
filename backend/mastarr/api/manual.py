"""Manual control: interactive search, manual import, queue and blocklist. Admin-only.

The daily-driver half of "never open the *arr UIs". Reading is what Mastarr already did;
this is the part where you override what the service decided — pick a specific release,
import a file it couldn't place, drop something from the queue and stop it coming back.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..adapters import AdapterError, BlocklistItem, ImportCandidate, Release
from ..aggregate import ServiceFailure, _gather_over_services, find_service
from ..auth.deps import require_admin
from ..db import get_session
from ..models import Service
from ..services import adapter_for, invalidate_cache, list_services

router = APIRouter(prefix="/manual", tags=["manual"], dependencies=[Depends(require_admin)])


class GrabRequest(BaseModel):
    guid: str
    indexer_id: int


class ImportFile(BaseModel):
    """One chosen file, in the shape the *arr command expects."""

    path: str
    # Named generically; the route maps it onto seriesId/movieId per service type.
    media_id: int
    quality: dict = Field(default_factory=dict)
    season_number: int | None = None
    episode_ids: list[int] = Field(default_factory=list)


class ImportRequest(BaseModel):
    files: list[ImportFile]
    move: bool = True


class BlocklistOut(BaseModel):
    items: list[BlocklistItem] = Field(default_factory=list)
    failures: list[ServiceFailure] = Field(default_factory=list)


def _service_or_404(session: Session, service_id: int) -> Service:
    service = find_service(session, service_id)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such service.")
    return service


async def _call(service: Service, operation):
    adapter = adapter_for(service)
    try:
        return await operation(adapter)
    except AdapterError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message
        ) from exc
    finally:
        await adapter.aclose()


# ------------------------------------------------------- interactive search


@router.get("/{service_id}/releases", response_model=list[Release])
async def search_releases(
    service_id: int,
    item_id: int | None = Query(None, description="Series or movie id"),
    episode_id: int | None = Query(None, description="Narrow a TV search to one episode"),
    session: Session = Depends(get_session),
) -> list[Release]:
    """What's actually available, with the service's own verdict on each release.

    Deliberately slow — it queries every indexer synchronously. Callers should expect this
    to take tens of seconds and show a spinner rather than assume it hung.
    """
    service = _service_or_404(session, service_id)
    releases = await _call(
        service, lambda a: a.releases(item_id=item_id, episode_id=episode_id)
    )
    # Best first: accepted before rejected, then by the service's own scoring.
    releases.sort(key=lambda r: (r.rejected, -(r.custom_format_score or 0), -r.size_bytes))
    return releases


@router.post("/{service_id}/grab")
async def grab_release(
    service_id: int, body: GrabRequest, session: Session = Depends(get_session)
) -> dict[str, str]:
    """Take a specific release, including one the service rejected on its own."""
    service = _service_or_404(session, service_id)
    await _call(service, lambda a: a.grab_release(body.guid, body.indexer_id))
    invalidate_cache(service_id)
    return {"status": "grabbed"}


# ------------------------------------------------------------ manual import


@router.get("/{service_id}/import", response_model=list[ImportCandidate])
async def import_candidates(
    service_id: int,
    folder: str = Query(min_length=1),
    session: Session = Depends(get_session),
) -> list[ImportCandidate]:
    """Files in a folder the service could import, with its reasons for any it can't."""
    service = _service_or_404(session, service_id)
    return await _call(service, lambda a: a.import_candidates(folder))


@router.post("/{service_id}/import")
async def do_import(
    service_id: int, body: ImportRequest, session: Session = Depends(get_session)
) -> dict[str, str]:
    """Import chosen files.

    The id field is named per service type — Sonarr wants `seriesId`, Radarr `movieId` —
    so the generic `media_id` is mapped here rather than making the UI know the difference.
    """
    service = _service_or_404(session, service_id)
    adapter = adapter_for(service)
    id_field = f"{adapter.media_endpoint}Id" if adapter.media_endpoint else "id"
    await adapter.aclose()

    files = []
    for f in body.files:
        entry: dict = {"path": f.path, id_field: f.media_id, "quality": f.quality}
        if f.season_number is not None:
            entry["seasonNumber"] = f.season_number
        if f.episode_ids:
            entry["episodeIds"] = f.episode_ids
        files.append(entry)

    result = await _call(service, lambda a: a.do_import(files, move=body.move))
    invalidate_cache(service_id)
    return {"status": result}


# --------------------------------------------------------- queue & blocklist


@router.delete("/{service_id}/queue/{queue_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_from_queue(
    service_id: int,
    queue_id: int,
    blocklist: bool = Query(
        False, description="Also blocklist, so it isn't grabbed again on the next RSS pass"
    ),
    remove_from_client: bool = Query(True),
    session: Session = Depends(get_session),
) -> None:
    service = _service_or_404(session, service_id)
    await _call(
        service,
        lambda a: a.queue_remove(
            queue_id, remove_from_client=remove_from_client, blocklist=blocklist
        ),
    )
    invalidate_cache(service_id)


@router.get("/blocklist", response_model=BlocklistOut)
async def get_blocklist(session: Session = Depends(get_session)) -> BlocklistOut:
    """Blocklisted releases across every service."""
    items, failures = await _gather_over_services(
        list_services(session), lambda a: a.blocklist()
    )
    items.sort(key=lambda b: b.date or __import__("datetime").datetime.min, reverse=True)
    return BlocklistOut(items=items, failures=failures)


@router.delete(
    "/{service_id}/blocklist/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def remove_from_blocklist(
    service_id: int, item_id: int, session: Session = Depends(get_session)
) -> None:
    """Un-blocklist, making the release grabbable again."""
    service = _service_or_404(session, service_id)
    await _call(service, lambda a: a.blocklist_remove(item_id))
