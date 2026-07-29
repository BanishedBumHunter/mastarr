"""Unified activity — queues and history across every service."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..adapters.schemas import HistoryItem, LibraryItem, QueueItem
from ..aggregate import ServiceFailure, history as aggregate_history
from ..aggregate import queue as aggregate_queue
from ..aggregate import wanted as aggregate_wanted
from ..auth.deps import require_admin
from ..db import get_session

# Admin-only: queues expose indexer names, download clients and file paths.
router = APIRouter(
    prefix="/activity", tags=["activity"], dependencies=[Depends(require_admin)]
)


class QueueOut(BaseModel):
    items: list[QueueItem] = Field(default_factory=list)
    failures: list[ServiceFailure] = Field(default_factory=list)


class HistoryOut(BaseModel):
    items: list[HistoryItem] = Field(default_factory=list)
    failures: list[ServiceFailure] = Field(default_factory=list)


class WantedOut(BaseModel):
    items: list[LibraryItem] = Field(default_factory=list)
    failures: list[ServiceFailure] = Field(default_factory=list)


@router.get("/queue", response_model=QueueOut)
async def get_queue(session: Session = Depends(get_session)) -> QueueOut:
    items, failures = await aggregate_queue(session)
    return QueueOut(items=items, failures=failures)


@router.get("/history", response_model=HistoryOut)
async def get_history(
    page_size: int = Query(50, ge=1, le=200), session: Session = Depends(get_session)
) -> HistoryOut:
    items, failures = await aggregate_history(session, page_size=page_size)
    return HistoryOut(items=items, failures=failures)


@router.get("/wanted", response_model=WantedOut)
async def get_wanted(
    page_size: int = Query(100, ge=1, le=500), session: Session = Depends(get_session)
) -> WantedOut:
    """Monitored things that have no file yet — the actionable gaps."""
    items, failures = await aggregate_wanted(session, page_size=page_size)
    return WantedOut(items=items, failures=failures)
