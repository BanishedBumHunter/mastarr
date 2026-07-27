"""The unified dashboard — one view across every connected service."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..adapters.schemas import ServiceSnapshot, ServiceStatus
from ..auth.deps import require_admin
from ..db import get_session
from ..services import list_services, persist_snapshot, snapshot_all

router = APIRouter(
    prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_admin)]
)


class DashboardTotals(BaseModel):
    services: int = 0
    online: int = 0
    degraded: int = 0
    unauthorized: int = 0
    unreachable: int = 0
    unknown: int = 0
    health_issues: int = 0
    queued_items: int = 0


class DashboardOut(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    totals: DashboardTotals
    services: list[ServiceSnapshot] = Field(default_factory=list)


@router.get("", response_model=DashboardOut)
async def dashboard(
    refresh: bool = False, session: Session = Depends(get_session)
) -> DashboardOut:
    """Fan out across all enabled services concurrently.

    Every snapshot is total — a dead service yields an UNREACHABLE card, never an
    exception — so this endpoint returns 200 with a complete picture even when the entire
    stack is down.
    """
    services = list_services(session, enabled_only=True)
    snapshots = await snapshot_all(services, use_cache=not refresh)

    for service, snapshot in zip(services, snapshots):
        persist_snapshot(session, service, snapshot)
    session.commit()

    totals = DashboardTotals(services=len(snapshots))
    counter = {
        ServiceStatus.ONLINE: "online",
        ServiceStatus.DEGRADED: "degraded",
        ServiceStatus.UNAUTHORIZED: "unauthorized",
        ServiceStatus.UNREACHABLE: "unreachable",
        ServiceStatus.UNKNOWN: "unknown",
    }
    for snapshot in snapshots:
        setattr(
            totals,
            counter[snapshot.status],
            getattr(totals, counter[snapshot.status]) + 1,
        )
        totals.health_issues += len(snapshot.health_issues)
        totals.queued_items += snapshot.queue_count or 0

    return DashboardOut(totals=totals, services=snapshots)
