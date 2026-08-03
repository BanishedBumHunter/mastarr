"""Bridge between stored `Service` rows and live adapters.

This is the only module that decrypts API keys and hands them to adapters, so the blast
radius of a key-handling mistake stays small.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlmodel import Session, select

from .adapters import (
    ArrAdapter,
    ServiceSnapshot,
    ServiceStatus,
    UnknownServiceType,
    build_adapter,
    get_adapter_class,
)
from .config import get_settings
from .crypto import DecryptionError, get_cipher
from .logging import forget_secret, register_secret
from .models import Service

log = logging.getLogger(__name__)


def store_api_key(service: Service, api_key: str | None) -> None:
    """Encrypt and attach a key, registering it for log redaction."""
    if not api_key:
        forget_secret(decrypt_api_key(service))
        service.api_key_encrypted = None
        return
    register_secret(api_key)
    service.api_key_encrypted = get_cipher().encrypt(api_key)


def decrypt_api_key(service: Service) -> str | None:
    if not service.api_key_encrypted:
        return None
    try:
        key = get_cipher().decrypt(service.api_key_encrypted)
    except DecryptionError as exc:
        log.warning("Service '%s': %s", service.name, exc)
        return None
    register_secret(key)
    return key


def adapter_for(service: Service) -> ArrAdapter:
    settings = get_settings()
    extra: dict[str, object] = {}
    # Only passed to types that ask for it, so every other adapter's signature is
    # untouched by the existence of password auth.
    if get_adapter_class(service.service_type).requires_username:
        extra["username"] = service.username
    return build_adapter(
        service.service_type,
        service.url,
        decrypt_api_key(service),
        name=service.name,
        service_id=service.id,
        timeout=settings.http_timeout,
        **extra,
    )


def list_services(session: Session, *, enabled_only: bool = True) -> list[Service]:
    statement = select(Service)
    if enabled_only:
        statement = statement.where(Service.enabled == True)  # noqa: E712
    return list(session.exec(statement).all())


# --------------------------------------------------------------------- snapshots

_cache: dict[int, tuple[float, ServiceSnapshot]] = {}


def _cached(service_id: int | None, ttl: float) -> ServiceSnapshot | None:
    if service_id is None or ttl <= 0:
        return None
    entry = _cache.get(service_id)
    if entry and (time.monotonic() - entry[0]) < ttl:
        return entry[1]
    return None


def invalidate_cache(service_id: int | None = None) -> None:
    if service_id is None:
        _cache.clear()
    else:
        _cache.pop(service_id, None)


async def snapshot_service(
    service: Service, *, use_cache: bool = True
) -> ServiceSnapshot:
    """One service's dashboard view. Never raises — an error becomes a status."""
    settings = get_settings()
    ttl = settings.dashboard_cache_seconds if use_cache else 0.0
    if (hit := _cached(service.id, ttl)) is not None:
        return hit

    try:
        adapter = adapter_for(service)
    except UnknownServiceType as exc:
        # A type present in the DB but no longer registered — e.g. downgrade after a
        # service was added. Surfaces as a degraded card, not a 500.
        return ServiceSnapshot(
            service_id=service.id,
            name=service.name,
            service_type=service.service_type,
            url=service.url,
            status=ServiceStatus.UNKNOWN,
            error=str(exc),
            checked_at=datetime.now(timezone.utc),
        )

    try:
        snapshot = await adapter.snapshot()
    finally:
        await adapter.aclose()

    if service.id is not None:
        _cache[service.id] = (time.monotonic(), snapshot)
    return snapshot


async def snapshot_all(
    services: list[Service], *, use_cache: bool = True
) -> list[ServiceSnapshot]:
    """Fan out across every service concurrently.

    `return_exceptions=True` is load-bearing: without it, one service raising an
    unexpected non-adapter error would take down the whole dashboard response. Anything
    that does escape is converted to an UNKNOWN card rather than propagated.
    """
    results = await asyncio.gather(
        *(snapshot_service(svc, use_cache=use_cache) for svc in services),
        return_exceptions=True,
    )

    snapshots: list[ServiceSnapshot] = []
    for service, result in zip(services, results):
        if isinstance(result, BaseException):
            log.exception(
                "Unexpected error snapshotting service '%s'", service.name,
                exc_info=result,
            )
            snapshots.append(
                ServiceSnapshot(
                    service_id=service.id,
                    name=service.name,
                    service_type=service.service_type,
                    url=service.url,
                    status=ServiceStatus.UNKNOWN,
                    error="An unexpected error occurred while contacting this service.",
                    checked_at=datetime.now(timezone.utc),
                )
            )
        else:
            snapshots.append(result)
    return snapshots


def persist_snapshot(session: Session, service: Service, snapshot: ServiceSnapshot) -> None:
    """Cache identity on the row so the UI can render before any live call returns."""
    service.last_status = snapshot.status.value
    service.last_version = snapshot.version
    service.last_checked_at = snapshot.checked_at
    session.add(service)


def sync_config_services(session: Session) -> int:
    """Reconcile services declared in config.yml into the DB.

    Declarative config wins for the services it declares — a YAML-managed service is
    marked `managed_by_config` and shown read-only in the UI, since a UI edit would be
    silently reverted on the next restart.
    """
    settings = get_settings()
    declared = settings.load_services()
    if not declared:
        return 0

    existing = {svc.name: svc for svc in session.exec(select(Service)).all()}
    count = 0
    for item in declared:
        service = existing.get(item.name) or Service(
            name=item.name, service_type=item.type, url=item.url
        )
        service.service_type = item.type
        service.url = item.url
        service.enabled = item.enabled
        service.managed_by_config = True
        if (key := item.resolve_api_key()) is not None:
            store_api_key(service, key)
        session.add(service)
        count += 1

    session.commit()
    invalidate_cache()
    return count
