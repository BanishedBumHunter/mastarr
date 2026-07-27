"""Discovery endpoints. Admin-only."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..auth.deps import require_admin
from ..config import get_settings
from ..db import get_session
from ..discovery import DiscoveredService, identify, scan_hosts
from ..models import Service
from .schemas import IdentifyRequest, ScanRequest

router = APIRouter(
    prefix="/discovery", tags=["discovery"], dependencies=[Depends(require_admin)]
)


def _mark_configured(
    found: list[DiscoveredService], session: Session
) -> list[DiscoveredService]:
    """Flag candidates already present, so the UI offers 'add' only for genuinely new ones."""
    known = {s.url.rstrip("/") for s in session.exec(select(Service)).all()}
    for candidate in found:
        candidate.already_configured = candidate.url.rstrip("/") in known
    return found


@router.post("/scan", response_model=list[DiscoveredService])
async def scan(
    body: ScanRequest, session: Session = Depends(get_session)
) -> list[DiscoveredService]:
    """Phase 1 — probe for *arr services. No API keys needed.

    Falls back to the hosts configured in settings, then to localhost, so the button does
    something sensible on a fresh install with an empty form.
    """
    settings = get_settings()
    hosts = body.hosts or settings.discovery_hosts or ["127.0.0.1"]
    found = await scan_hosts(hosts, ports=body.ports)
    return _mark_configured(found, session)


@router.post("/identify", response_model=DiscoveredService)
async def identify_service(body: IdentifyRequest) -> DiscoveredService:
    """Phase 2 — confirm a candidate's true identity using an API key.

    `appName` from system/status is authoritative; the port only chose which API version
    to try first.
    """
    from urllib.parse import urlparse

    parsed = urlparse(body.url if "://" in body.url else f"http://{body.url}")
    candidate = DiscoveredService(
        url=body.url.rstrip("/"),
        host=parsed.hostname or body.url,
        port=parsed.port or 0,
        service_type=body.service_type,
    )
    return await identify(candidate, body.api_key)
