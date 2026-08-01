"""Periodic upgrade sweep — a gap the *arrs genuinely leave open.

Quality profiles have `upgradeAllowed` + `cutoff`: grab whatever is available now, then
keep replacing it with something better until you reach your ceiling. That part works.

What doesn't exist is anything that goes *looking*. The scheduled task list on a stock
Sonarr is `ApplicationUpdateCheck, Backup, CheckHealth, CleanUpRecycleBin, Housekeeping,
ImportListSync, MessagingCleanup, RefreshMonitoredDownloads, RefreshSeries, RssSync,
UpdateSceneMapping` — no cutoff or upgrade sweep anywhere. Upgrades therefore only happen by
luck, when something better happens to appear inside the 15-minute RSS window. Anything
already sitting below its cutoff stays there forever. On the reference stack that was **940
episodes**.

So Mastarr runs the sweep itself: periodically ask each service to search for what's below
cutoff (and what's missing), which is exactly the button the *arr UI has but never presses
on a schedule.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlmodel import Session

from .adapters import AdapterError, UnknownServiceType, get_adapter_class
from .config import get_settings
from .db import get_engine
from .models import Service
from .services import adapter_for, list_services

log = logging.getLogger(__name__)

# Per-type commands. The *arrs name these differently, so it's a lookup rather than a
# shared constant — and a type absent from here simply isn't swept.
SWEEP_COMMANDS: dict[str, dict[str, str]] = {
    "sonarr": {"cutoff": "CutoffUnmetEpisodeSearch", "missing": "MissingEpisodeSearch"},
    "radarr": {"cutoff": "CutoffUnmetMoviesSearch", "missing": "MissingMoviesSearch"},
    "lidarr": {"cutoff": "CutoffUnmetAlbumSearch", "missing": "MissingAlbumSearch"},
    "readarr": {"cutoff": "CutoffUnmetBookSearch", "missing": "MissingBookSearch"},
}

# Endpoint that counts what's below cutoff. Note it is `wanted/cutoff`, not
# `wanted/cutoffunmet` — the latter 404s.
CUTOFF_ENDPOINT = "wanted/cutoff"


class SweepResult(BaseModel):
    service_id: int | None = None
    service_name: str
    command: str
    ok: bool
    detail: str | None = None


class SweepStatus(BaseModel):
    enabled: bool = False
    interval_hours: int = 168
    last_run: datetime | None = None
    next_run: datetime | None = None
    running: bool = False
    services: list[dict[str, Any]] = Field(default_factory=list)
    last_results: list[SweepResult] = Field(default_factory=list)


_state: dict[str, Any] = {"last_run": None, "running": False, "last_results": []}


async def below_cutoff_count(service: Service) -> int | None:
    """How many items are below their profile cutoff. None when unsupported."""
    try:
        get_adapter_class(service.service_type)
    except UnknownServiceType:
        return None
    if service.service_type not in SWEEP_COMMANDS:
        return None

    adapter = adapter_for(service)
    try:
        data = await adapter._request(
            "GET", CUTOFF_ENDPOINT, params={"page": 1, "pageSize": 1}
        )
        if isinstance(data, dict):
            return int(data.get("totalRecords") or 0)
        return None
    except AdapterError as exc:
        log.debug("cutoff count failed for %s: %s", service.name, exc.message)
        return None
    finally:
        await adapter.aclose()


async def sweep_service(service: Service, *, include_missing: bool) -> list[SweepResult]:
    """Ask one service to hunt for upgrades (and optionally for missing items)."""
    commands = SWEEP_COMMANDS.get(service.service_type)
    if not commands:
        return []

    wanted = ["cutoff"] + (["missing"] if include_missing else [])
    results: list[SweepResult] = []
    adapter = adapter_for(service)
    try:
        for key in wanted:
            name = commands[key]
            try:
                await adapter._request("POST", "command", json={"name": name})
                results.append(
                    SweepResult(
                        service_id=service.id, service_name=service.name,
                        command=name, ok=True,
                    )
                )
            except AdapterError as exc:
                results.append(
                    SweepResult(
                        service_id=service.id, service_name=service.name,
                        command=name, ok=False, detail=exc.message,
                    )
                )
    finally:
        await adapter.aclose()
    return results


async def run_sweep(session: Session, *, include_missing: bool = True) -> list[SweepResult]:
    """Sweep every eligible service. Safe to call at any time and to run twice."""
    if _state["running"]:
        return [
            SweepResult(
                service_name="(sweep)", command="-", ok=False,
                detail="A sweep is already running.",
            )
        ]

    _state["running"] = True
    try:
        results: list[SweepResult] = []
        for service in list_services(session):
            results.extend(await sweep_service(service, include_missing=include_missing))
        _state["last_run"] = datetime.now(timezone.utc)
        _state["last_results"] = results
        log.info("Upgrade sweep issued %d command(s)", len(results))
        return results
    finally:
        _state["running"] = False


async def status(session: Session) -> SweepStatus:
    settings = get_settings()
    counts = []
    for service in list_services(session):
        count = await below_cutoff_count(service)
        if count is not None:
            counts.append(
                {"service_id": service.id, "service_name": service.name,
                 "below_cutoff": count}
            )

    last = _state["last_run"]
    interval = getattr(settings, "sweep_interval_hours", 168)
    return SweepStatus(
        enabled=getattr(settings, "sweep_enabled", False),
        interval_hours=interval,
        last_run=last,
        next_run=None,
        running=bool(_state["running"]),
        services=counts,
        last_results=_state["last_results"],
    )


async def _loop() -> None:
    """Background loop.

    Deliberately dumb: it wakes on a fixed interval and checks whether enough time has
    passed. No cron, no persistence of the schedule — a sweep is idempotent, so a missed
    run just happens on the next tick, and there is nothing to reconcile after a restart.
    """
    while True:
        try:
            settings = get_settings()
            if getattr(settings, "sweep_enabled", False):
                interval = max(int(getattr(settings, "sweep_interval_hours", 168)), 1)
                last = _state["last_run"]
                due = last is None or (
                    datetime.now(timezone.utc) - last
                ).total_seconds() >= interval * 3600
                if due:
                    with Session(get_engine()) as session:
                        await run_sweep(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A scheduler that dies on one bad tick is worse than useless.
            log.exception("Upgrade sweep tick failed; continuing")
        await asyncio.sleep(900)  # 15 minutes


_task: asyncio.Task | None = None


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
        log.info("Upgrade sweep scheduler started")


async def stop() -> None:
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
