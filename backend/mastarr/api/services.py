"""Service CRUD and per-service detail. Admin-only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..adapters import (
    AdapterError,
    UnknownServiceType,
    describe_types,
    get_adapter_class,
    known_types,
)
from ..adapters.suggestarr import forget_tokens
from ..adapters.schemas import ServiceSnapshot
from ..auth.deps import require_admin
from ..db import get_session
from ..models import Service
from ..services import (
    adapter_for,
    invalidate_cache,
    snapshot_service,
    store_api_key,
)
from .schemas import ServiceIn, ServiceOut, ServiceUpdate

router = APIRouter(
    prefix="/services", tags=["services"], dependencies=[Depends(require_admin)]
)


def _service_out(service: Service) -> ServiceOut:
    return ServiceOut(
        id=service.id or 0,
        name=service.name,
        service_type=service.service_type,
        url=service.url,
        enabled=service.enabled,
        has_api_key=bool(service.api_key_encrypted),
        username=service.username,
        needs_username=get_adapter_class(service.service_type).requires_username
        if service.service_type in known_types()
        else False,
        managed_by_config=service.managed_by_config,
        last_status=service.last_status,
        last_version=service.last_version,
        last_checked_at=service.last_checked_at,
    )


def _get_or_404(session: Session, service_id: int) -> Service:
    service = session.get(Service, service_id)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such service."
        )
    return service


@router.get("/types")
async def service_types() -> list[dict[str, object]]:
    """Registered adapter types, so the frontend never hardcodes a service list."""
    return describe_types()


@router.get("", response_model=list[ServiceOut])
async def list_all(session: Session = Depends(get_session)) -> list[ServiceOut]:
    return [_service_out(s) for s in session.exec(select(Service)).all()]


@router.post("", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
async def create_service(
    body: ServiceIn, session: Session = Depends(get_session)
) -> ServiceOut:
    try:
        get_adapter_class(body.service_type)
    except UnknownServiceType as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if session.exec(select(Service).where(Service.name == body.name)).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A service named '{body.name}' already exists.",
        )

    service = Service(
        name=body.name,
        service_type=body.service_type.lower(),
        url=body.url.rstrip("/"),
        username=body.username or None,
        enabled=body.enabled,
    )
    store_api_key(service, body.api_key)
    session.add(service)
    session.commit()
    session.refresh(service)
    invalidate_cache()
    return _service_out(service)


@router.patch("/{service_id}", response_model=ServiceOut)
async def update_service(
    service_id: int, body: ServiceUpdate, session: Session = Depends(get_session)
) -> ServiceOut:
    service = _get_or_404(session, service_id)
    if service.managed_by_config:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This service is defined in config.yml. Edit the file instead — "
            "changes made here would be reverted on the next restart.",
        )

    if body.name is not None:
        service.name = body.name
    if body.url is not None:
        service.url = body.url.rstrip("/")
    if body.enabled is not None:
        service.enabled = body.enabled
    if body.username is not None:
        service.username = body.username or None
        # A username change invalidates any bearer token held for the old account.
        forget_tokens()
    # Absent means "leave the stored key alone"; empty string means "clear it".
    if body.api_key is not None:
        store_api_key(service, body.api_key or None)
        forget_tokens()

    session.add(service)
    session.commit()
    session.refresh(service)
    invalidate_cache(service_id)
    return _service_out(service)


@router.delete(
    "/{service_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_service(
    service_id: int, session: Session = Depends(get_session)
) -> None:
    service = _get_or_404(session, service_id)
    if service.managed_by_config:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This service is defined in config.yml. Remove it from the file instead.",
        )
    session.delete(service)
    session.commit()
    invalidate_cache(service_id)


@router.get("/{service_id}/snapshot", response_model=ServiceSnapshot)
async def service_snapshot(
    service_id: int, refresh: bool = False, session: Session = Depends(get_session)
) -> ServiceSnapshot:
    service = _get_or_404(session, service_id)
    return await snapshot_service(service, use_cache=not refresh)


@router.get("/{service_id}/{resource}")
async def service_resource(
    service_id: int, resource: str, session: Session = Depends(get_session)
) -> object:
    """Read one adapter-backed collection.

    Whitelisted rather than dispatched dynamically — `getattr(adapter, resource)` would
    happily expose `aclose`, `api_key`, or anything else the class happens to carry.
    """
    allowed = {
        "health",
        "diskspace",
        "queue",
        "history",
        "qualityprofiles",
        "rootfolders",
        "downloadclients",
        "indexers",
    }
    if resource not in allowed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown resource '{resource}'.",
        )

    method_names = {
        "health": "health",
        "diskspace": "disk_space",
        "queue": "queue",
        "history": "history",
        "qualityprofiles": "quality_profiles",
        "rootfolders": "root_folders",
        "downloadclients": "download_clients",
        "indexers": "indexers",
    }

    service = _get_or_404(session, service_id)
    adapter = adapter_for(service)
    try:
        return await getattr(adapter, method_names[resource])()
    except AdapterError as exc:
        # Adapter failures are upstream conditions, not Mastarr bugs — 502, with the
        # adapter's own message, which is written to be operator-readable.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message
        ) from exc
    finally:
        await adapter.aclose()
