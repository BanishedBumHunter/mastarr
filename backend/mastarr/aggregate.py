"""Cross-service aggregation — the actual "one interface" layer.

Every function here fans out across the configured services and merges the results into one
list. They all follow the same rule the dashboard established: **a failing service degrades
the view, it never empties it.** A dead Radarr means the calendar shows TV only, plus a
note saying which service is missing — not an error page and not a silently short list.

That "plus a note" matters. Silently returning partial data would be worse than failing:
the user would think their library really is that small.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, TypeVar

from pydantic import BaseModel, Field
from sqlmodel import Session

from .adapters import (
    AdapterError,
    ArrAdapter,
    CalendarEntry,
    HistoryItem,
    LibraryItem,
    QueueItem,
    UnknownServiceType,
)
from .models import Service
from .services import adapter_for, list_services

log = logging.getLogger(__name__)

T = TypeVar("T")


class ServiceFailure(BaseModel):
    """Why one service is missing from an aggregated view."""

    service_id: int | None = None
    service_name: str
    service_type: str
    error: str


class Aggregated(BaseModel):
    """A merged result plus an honest account of what's missing from it."""

    items: list[Any] = Field(default_factory=list)
    failures: list[ServiceFailure] = Field(default_factory=list)

    @property
    def partial(self) -> bool:
        return bool(self.failures)


async def _gather_over_services(
    services: list[Service],
    call: Callable[[ArrAdapter], Awaitable[list[T]]],
    *,
    skip_unsupported: bool = True,
) -> tuple[list[T], list[ServiceFailure]]:
    """Run `call` against every service concurrently, collecting results and failures.

    `skip_unsupported` exists because "Prowlarr has no calendar" is not a failure worth
    telling the user about — it is a permanent property of the type, and surfacing it as a
    warning on every page load would train people to ignore warnings.
    """

    async def run(service: Service) -> tuple[list[T], ServiceFailure | None]:
        try:
            adapter = adapter_for(service)
        except UnknownServiceType as exc:
            return [], ServiceFailure(
                service_id=service.id,
                service_name=service.name,
                service_type=service.service_type,
                error=str(exc),
            )
        try:
            return await call(adapter), None
        except AdapterError as exc:
            if skip_unsupported and exc.status == "unsupported":
                return [], None
            return [], ServiceFailure(
                service_id=service.id,
                service_name=service.name,
                service_type=service.service_type,
                error=exc.message,
            )
        finally:
            await adapter.aclose()

    results = await asyncio.gather(
        *(run(service) for service in services), return_exceptions=True
    )

    items: list[T] = []
    failures: list[ServiceFailure] = []
    for service, result in zip(services, results):
        if isinstance(result, BaseException):
            # An adapter raising something outside AdapterError is a bug, but it must not
            # take down the whole view.
            log.exception("Unexpected error aggregating '%s'", service.name, exc_info=result)
            failures.append(
                ServiceFailure(
                    service_id=service.id,
                    service_name=service.name,
                    service_type=service.service_type,
                    error="An unexpected error occurred contacting this service.",
                )
            )
            continue
        batch, failure = result
        items.extend(batch)
        if failure is not None:
            failures.append(failure)
    return items, failures


# ------------------------------------------------------------------- calendar


async def calendar(
    session: Session, start: datetime, end: datetime
) -> tuple[list[CalendarEntry], list[ServiceFailure]]:
    entries, failures = await _gather_over_services(
        list_services(session), lambda a: a.calendar(start, end)
    )
    entries.sort(key=lambda e: (e.date, e.parent_title or e.title))
    return entries, failures


# -------------------------------------------------------------------- library


async def library(
    session: Session, media_kind: str | None = None
) -> tuple[list[LibraryItem], list[ServiceFailure]]:
    """Every library item across every service.

    Unpaged on purpose — the real libraries here are hundreds of items, and shipping the
    whole set lets the UI filter and sort instantly instead of round-tripping per keystroke.
    """
    services = list_services(session)
    if media_kind:
        # Filter by type before making requests, so a "movies" view never touches Sonarr.
        from .adapters import get_adapter_class

        def matches(service: Service) -> bool:
            try:
                return get_adapter_class(service.service_type).media_kind == media_kind
            except UnknownServiceType:
                return False

        services = [s for s in services if matches(s)]

    items, failures = await _gather_over_services(services, lambda a: a.library())
    items.sort(key=lambda i: (i.sort_title or i.title).lower())
    return items, failures


# ------------------------------------------------------------------- activity


async def queue(session: Session) -> tuple[list[QueueItem], list[ServiceFailure]]:
    items, failures = await _gather_over_services(
        list_services(session), lambda a: a.queue()
    )
    return items, failures


async def history(
    session: Session, page_size: int = 50
) -> tuple[list[HistoryItem], list[ServiceFailure]]:
    """Recent history across services.

    Each service is asked for its most recent `page_size` rows and the merged result is
    trimmed back to `page_size`. With ~8000 rows in one service alone, pulling everything
    to sort globally would be wasteful; taking the newest from each and merging gives the
    correct head of the timeline for a fraction of the work.
    """
    items, failures = await _gather_over_services(
        list_services(session), lambda a: a.history(page_size=page_size)
    )
    items.sort(key=lambda h: h.date or datetime.min.replace(tzinfo=None), reverse=True)
    return items[:page_size], failures


async def wanted(
    session: Session, page_size: int = 100
) -> tuple[list[LibraryItem], list[ServiceFailure]]:
    items, failures = await _gather_over_services(
        list_services(session), lambda a: a.wanted_missing(page_size=page_size)
    )
    items.sort(key=lambda i: (i.sort_title or i.title).lower())
    return items, failures


# --------------------------------------------------------------- service lookup


def find_service(session: Session, service_id: int) -> Service | None:
    return session.get(Service, service_id)


def first_service_of_type(session: Session, service_type: str) -> Service | None:
    """The first enabled service of a type — used to find 'the' Jellyseerr."""
    for service in list_services(session):
        if service.service_type == service_type:
            return service
    return None
