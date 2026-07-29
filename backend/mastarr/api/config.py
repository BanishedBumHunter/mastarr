"""Cross-stack configuration: browse, preview a push, apply it. Admin-only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from .. import config_sync
from ..auth.deps import require_admin
from ..config_sync import ApplyResult, SyncPreview
from ..db import get_session

router = APIRouter(
    prefix="/config", tags=["config"], dependencies=[Depends(require_admin)]
)


class SyncRequest(BaseModel):
    resource: str
    source_service_id: int
    # Ignored for `naming`, which is a singleton per service.
    item_id: int = 0
    target_service_ids: list[int] = Field(default_factory=list)


@router.get("/resources")
async def resources() -> dict[str, object]:
    """What can be synced, and how far each type travels.

    The frontend uses this to explain compatibility rather than hardcoding the rules.
    """
    return {
        "resources": [
            {
                "key": key,
                "portability": portability.value,
                "note": (
                    "Can be copied to any service."
                    if portability is config_sync.Portability.ANY
                    else "Only to services of the same media type — the underlying "
                    "quality definitions differ."
                ),
            }
            for key, portability in config_sync.PORTABILITY.items()
        ]
    }


@router.get("/{resource}")
async def collect(resource: str, session: Session = Depends(get_session)) -> list[dict]:
    """Every instance of this resource across all services."""
    if resource not in config_sync.PORTABILITY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown config resource '{resource}'.",
        )
    return await config_sync.collect(session, resource)


@router.post("/preview", response_model=SyncPreview)
async def preview(body: SyncRequest, session: Session = Depends(get_session)) -> SyncPreview:
    """What *would* happen. Writes nothing."""
    try:
        return await config_sync.preview(
            session,
            resource=body.resource,
            source_service_id=body.source_service_id,
            item_id=body.item_id,
            target_service_ids=body.target_service_ids or None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post("/apply", response_model=list[ApplyResult])
async def apply(
    body: SyncRequest,
    confirm: bool = Query(False, description="Must be true — guards against a stray POST"),
    session: Session = Depends(get_session),
) -> list[ApplyResult]:
    """Actually write. Re-previews first, so a stale plan can't overwrite newer work."""
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pass confirm=true to apply configuration changes.",
        )
    if not body.target_service_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose at least one target service.",
        )
    try:
        return await config_sync.apply(
            session,
            resource=body.resource,
            source_service_id=body.source_service_id,
            item_id=body.item_id,
            target_service_ids=body.target_service_ids,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


# ------------------------------------------------------------------ indexers


@router.get("/indexers/overview")
async def indexer_overview(session: Session = Depends(get_session)) -> dict[str, object]:
    """Indexers from Prowlarr, plus the apps Prowlarr syncs them to.

    Prowlarr is the source of truth by design: it owns the indexer list and pushes it to
    the *arrs itself. Mastarr shows the reach rather than writing indexers into each
    service, which would fight Prowlarr's own sync and cause duplicates.
    """
    from ..adapters import AdapterError, ProwlarrAdapter
    from ..aggregate import first_service_of_type
    from ..services import adapter_for

    service = first_service_of_type(session, "prowlarr")
    if service is None:
        return {
            "available": False,
            "message": (
                "No Prowlarr service is connected. Add one to manage indexers centrally, "
                "or configure indexers in each service directly."
            ),
            "indexers": [],
            "applications": [],
        }

    adapter = adapter_for(service)
    if not isinstance(adapter, ProwlarrAdapter):
        await adapter.aclose()
        return {"available": False, "message": "Configured service is not Prowlarr.",
                "indexers": [], "applications": []}

    try:
        indexers = await adapter.indexers()
        applications = await adapter.applications()
        try:
            stats = await adapter.indexer_stats()
        except AdapterError:
            stats = {}  # stats are a nicety; never fail the page over them
    except AdapterError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message
        ) from exc
    finally:
        await adapter.aclose()

    return {
        "available": True,
        "service_id": service.id,
        "service_name": service.name,
        "native_url": service.url,
        "applications": applications,
        "indexers": [
            {**i.model_dump(), "stats": stats.get(i.id)} for i in indexers
        ],
    }


@router.post("/indexers/{indexer_id}/test")
async def test_indexer(
    indexer_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    from ..adapters import ProwlarrAdapter
    from ..aggregate import first_service_of_type
    from ..services import adapter_for

    service = first_service_of_type(session, "prowlarr")
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No Prowlarr service is connected.",
        )
    adapter = adapter_for(service)
    try:
        if not isinstance(adapter, ProwlarrAdapter):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Configured service is not Prowlarr.",
            )
        return {"ok": await adapter.test_indexer(indexer_id)}
    finally:
        await adapter.aclose()
