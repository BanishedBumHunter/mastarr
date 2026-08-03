"""Per-service configuration: providers and settings groups. Admin-only.

This is what makes "never open the *arr UIs again" possible. The *arrs describe their own
forms — `GET /{resource}/schema` returns every implementation with typed, labelled fields —
so one generic renderer covers 69 provider types across download clients, indexers, import
lists, notifications and metadata, and a provider added upstream appears with no code change.

Deliberately a separate router from `config.py`: that one owns *cross-service* copying and
has a `/{resource}` catch-all which would swallow these paths.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..adapters import AdapterError
from ..adapters.base import PROVIDER_ENDPOINTS, SINGLETON_CONFIGS
from ..aggregate import find_service
from ..auth.deps import require_admin
from ..db import get_session
from ..models import Service
from ..services import adapter_for, invalidate_cache

router = APIRouter(
    prefix="/providers", tags=["providers"], dependencies=[Depends(require_admin)]
)


class ProviderPayload(BaseModel):
    """A provider config as the form submits it.

    Free-form because the shape is whatever the service's schema declared — validating it
    here would mean duplicating 69 schemas and going stale the moment one changes. The
    service validates on write, and `test` exists to check before saving.
    """

    data: dict = Field(default_factory=dict)


class SingletonPayload(BaseModel):
    data: dict = Field(default_factory=dict)


def _service_or_404(session: Session, service_id: int) -> Service:
    service = find_service(session, service_id)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such service."
        )
    return service


async def _call(service: Service, operation):
    adapter = adapter_for(service)
    try:
        return await operation(adapter)
    except AdapterError as exc:
        # Upstream's problem, not ours — 502 points the finger correctly.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message
        ) from exc
    finally:
        await adapter.aclose()


@router.get("/kinds")
async def provider_kinds() -> dict[str, list[str]]:
    """What can be configured per service, so the UI builds its own tabs."""
    return {
        "providers": sorted(PROVIDER_ENDPOINTS),
        "settings_groups": sorted(SINGLETON_CONFIGS),
    }


@router.get("/{service_id}/quality-profile-schema")
async def quality_profile_schema(
    service_id: int, session: Session = Depends(get_session)
) -> dict:
    """Blank profile template — the starting point for creating one."""
    service = _service_or_404(session, service_id)
    return await _call(service, lambda a: a.quality_profile_schema())


# ---------------------------------------------------------- settings groups


@router.get("/{service_id}/settings/{name}")
async def get_settings_group(
    service_id: int, name: str, session: Session = Depends(get_session)
) -> dict:
    service = _service_or_404(session, service_id)
    return await _call(service, lambda a: a.get_singleton(name))


@router.put("/{service_id}/settings/{name}")
async def update_settings_group(
    service_id: int,
    name: str,
    body: SingletonPayload,
    session: Session = Depends(get_session),
) -> dict:
    """Merged into the existing record, so fields Mastarr doesn't render survive."""
    service = _service_or_404(session, service_id)
    result = await _call(service, lambda a: a.update_singleton(name, body.data))
    invalidate_cache(service_id)
    return result


# ----------------------------------------------------------------- providers


@router.get("/{service_id}/{resource}/schema")
async def provider_schema(
    service_id: int, resource: str, session: Session = Depends(get_session)
) -> list[dict]:
    """Every implementation this service supports, with full field definitions."""
    service = _service_or_404(session, service_id)
    return await _call(service, lambda a: a.provider_schema(resource))


@router.get("/{service_id}/{resource}")
async def list_providers(
    service_id: int, resource: str, session: Session = Depends(get_session)
) -> list[dict]:
    """Configured instances. Secrets are masked by the adapter before they get here."""
    service = _service_or_404(session, service_id)
    return await _call(service, lambda a: a.list_config(resource))


@router.post("/{service_id}/{resource}", status_code=status.HTTP_201_CREATED)
async def create_provider(
    service_id: int,
    resource: str,
    body: ProviderPayload,
    session: Session = Depends(get_session),
) -> dict:
    service = _service_or_404(session, service_id)
    result = await _call(service, lambda a: a.create_provider(resource, body.data))
    invalidate_cache(service_id)
    return result


@router.put("/{service_id}/{resource}/{item_id}")
async def update_provider(
    service_id: int,
    resource: str,
    item_id: int,
    body: ProviderPayload,
    session: Session = Depends(get_session),
) -> dict:
    """Edit. The adapter restores any secret the form echoed back as a placeholder."""
    service = _service_or_404(session, service_id)
    result = await _call(
        service, lambda a: a.update_provider(resource, item_id, body.data)
    )
    invalidate_cache(service_id)
    return result


@router.delete(
    "/{service_id}/{resource}/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_provider(
    service_id: int, resource: str, item_id: int, session: Session = Depends(get_session)
) -> None:
    service = _service_or_404(session, service_id)
    await _call(service, lambda a: a.delete_provider(resource, item_id))
    invalidate_cache(service_id)


@router.post("/{service_id}/{resource}/test")
async def test_provider(
    service_id: int,
    resource: str,
    body: ProviderPayload,
    session: Session = Depends(get_session),
) -> dict:
    """Validate a config before saving it.

    Returns `{ok, message}` with a 200 even on failure — a failed connection test is an
    expected answer for the form to render, not an error.
    """
    service = _service_or_404(session, service_id)
    ok, message = await _call(service, lambda a: a.test_provider(resource, body.data))
    return {"ok": ok, "message": message}


