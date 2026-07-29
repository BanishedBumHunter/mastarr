"""Unified calendar — Sonarr, Radarr and friends on one timeline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..adapters.schemas import CalendarEntry
from ..aggregate import ServiceFailure, calendar as aggregate_calendar
from ..auth.deps import require_requester
from ..db import get_session

# Requester-level: seeing what's coming is not privileged information, and it's one of the
# things that makes Mastarr worth opening for a non-admin.
router = APIRouter(
    prefix="/calendar", tags=["calendar"], dependencies=[Depends(require_requester)]
)


class CalendarOut(BaseModel):
    start: datetime
    end: datetime
    entries: list[CalendarEntry] = Field(default_factory=list)
    # Named so the UI can say *which* service is missing rather than showing a short list
    # as though it were complete.
    failures: list[ServiceFailure] = Field(default_factory=list)


@router.get("", response_model=CalendarOut)
async def get_calendar(
    days_back: int = Query(7, ge=0, le=90),
    days_forward: int = Query(28, ge=1, le=365),
    session: Session = Depends(get_session),
) -> CalendarOut:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days_back)
    end = now + timedelta(days=days_forward)
    entries, failures = await aggregate_calendar(session, start, end)
    return CalendarOut(start=start, end=end, entries=entries, failures=failures)
