"""System operations — backups, logs, updates, scheduled tasks, restart.

The other half of running a stack. Configuration says what a service should do; this says
whether it is healthy, current, and recoverable.

Two deliberate shapes here:

* **Updates fan out, everything else is per-service.** "Is anything out of date?" is a
  question about the whole stack and belongs on one screen. Logs are the opposite: volume
  is the entire problem, and merging four services into one stream loses the line you were
  looking for.
* **Filenames are never passed through from the client.** Backup downloads and log-file
  reads take an id, and the route resolves it against the service's own listing. A path
  arriving from the browser and being appended to a service URL is a traversal waiting to
  happen.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..adapters import AdapterError
from ..adapters.schemas import (
    BackupInfo,
    LogFile,
    LogPage,
    ScheduledTask,
    UpdateInfo,
    UpdateStatus,
)
from ..aggregate import ServiceFailure, find_service
from ..auth.deps import require_admin
from ..db import get_session
from ..models import Service
from ..services import adapter_for, list_services

# Admin-only throughout. These routes expose log contents, file paths and the ability to
# restart a service — none of it belongs to a Requester.
router = APIRouter(
    prefix="/system", tags=["system"], dependencies=[Depends(require_admin)]
)


class UpdateFleetOut(BaseModel):
    services: list[UpdateStatus] = Field(default_factory=list)
    failures: list[ServiceFailure] = Field(default_factory=list)


class TaskRunRequest(BaseModel):
    task_name: str


class ActionOut(BaseModel):
    status: str


def _service_or_404(session: Session, service_id: int) -> Service:
    service = find_service(session, service_id)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such service."
        )
    return service


async def _call(service: Service, operation):
    """Run one adapter operation, mapping adapter failures to an honest 502."""
    adapter = adapter_for(service)
    try:
        return await operation(adapter)
    except AdapterError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message
        ) from exc
    finally:
        await adapter.aclose()


# --------------------------------------------------------------------- updates


@router.get("/updates", response_model=UpdateFleetOut)
async def fleet_updates(session: Session = Depends(get_session)) -> UpdateFleetOut:
    """What version every service is on, and what it could be on.

    Fans out. A service that fails is reported in `failures` rather than dropped — a
    service silently missing from an update list reads as "up to date", which is the
    opposite of the truth.
    """
    services = list_services(session)

    async def one(service: Service) -> UpdateStatus:
        adapter = adapter_for(service)
        try:
            entries = await adapter.updates()
            # `installable` alone is not enough. A containerised *arr still reports
            # installable=true and will happily unpack a new build over itself — which
            # the next `docker run` throws away, or which breaks the image outright.
            # Sonarr's own UI gates on isDocker for exactly this reason. Verified on the
            # reference stack: isDocker=true, installable=true, updateMechanism=null.
            try:
                in_docker = bool((await adapter.system_status()).is_docker)
            except AdapterError:
                in_docker = False
        finally:
            await adapter.aclose()
        installed = next((e for e in entries if e.installed), None)
        newer = [e for e in entries if not e.installed]
        latest = newer[0] if newer else None
        blocked = ""
        if latest is not None:
            if in_docker:
                blocked = (
                    "Runs in a container — pull a newer image instead. Updating in "
                    "place would be discarded the next time the container is recreated."
                )
            elif not latest.installable:
                blocked = "The service reports this build as not installable."
        return UpdateStatus(
            service_id=service.id or 0,
            service_name=service.name,
            service_type=service.service_type,
            current_version=installed.version if installed else "",
            latest_version=latest.version if latest else (installed.version if installed else ""),
            update_available=latest is not None,
            installable=bool(latest and latest.installable and not in_docker),
            blocked_reason=blocked,
            release_date=latest.release_date if latest else None,
            changes_new=latest.changes_new if latest else [],
            changes_fixed=latest.changes_fixed if latest else [],
        )

    results = await asyncio.gather(
        *(one(s) for s in services), return_exceptions=True
    )
    out: list[UpdateStatus] = []
    failures: list[ServiceFailure] = []
    for service, result in zip(services, results):
        if isinstance(result, BaseException):
            message = (
                result.message
                if isinstance(result, AdapterError)
                else f"{type(result).__name__}"
            )
            failures.append(
                ServiceFailure(
                    service_id=service.id,
                    service_name=service.name,
                    service_type=service.service_type,
                    error=message,
                )
            )
        else:
            out.append(result)
    out.sort(key=lambda s: (not s.update_available, s.service_name.lower()))
    return UpdateFleetOut(services=out, failures=failures)


@router.get("/{service_id}/updates", response_model=list[UpdateInfo])
async def service_updates(
    service_id: int, session: Session = Depends(get_session)
) -> list[UpdateInfo]:
    """Full release history for one service, including changelogs."""
    service = _service_or_404(session, service_id)
    return await _call(service, lambda a: a.updates())


@router.post("/{service_id}/updates/install", response_model=ActionOut)
async def install_update(
    service_id: int, session: Session = Depends(get_session)
) -> ActionOut:
    """Trigger the service's built-in updater.

    Refuses when the service reports the update as not installable. That is the normal
    case in Docker, and queuing the command anyway would return "queued" for something
    that never happens — worse than an error, because it looks like it worked.
    """
    service = _service_or_404(session, service_id)

    async def run(adapter):
        entries = await adapter.updates()
        pending = [e for e in entries if not e.installed]
        if not pending:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{service.name} is already on the newest version.",
            )
        if not pending[0].installable:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{service.name} reports this build as not installable, so there is "
                    f"nothing to run."
                ),
            )
        try:
            in_docker = bool((await adapter.system_status()).is_docker)
        except AdapterError:
            in_docker = False
        if in_docker:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{service.name} runs in a container. It would accept this update "
                    f"and unpack a new build over itself, and the next time the "
                    f"container is recreated that would be thrown away. Pull a newer "
                    f"image instead."
                ),
            )
        return await adapter.install_update()

    return ActionOut(status=await _call(service, run))


# --------------------------------------------------------------------- backups


@router.get("/{service_id}/backups", response_model=list[BackupInfo])
async def list_backups(
    service_id: int, session: Session = Depends(get_session)
) -> list[BackupInfo]:
    service = _service_or_404(session, service_id)
    return await _call(service, lambda a: a.backups())


@router.post("/{service_id}/backups", response_model=ActionOut)
async def create_backup(
    service_id: int, session: Session = Depends(get_session)
) -> ActionOut:
    """Take a backup now. The service runs it as a queued command, so it is not
    instantaneous — the list refreshes when it lands."""
    service = _service_or_404(session, service_id)
    return ActionOut(status=await _call(service, lambda a: a.create_backup()))


@router.get("/{service_id}/backups/{backup_id}/download")
async def download_backup(
    service_id: int, backup_id: int, session: Session = Depends(get_session)
) -> Response:
    """Stream a backup out through Mastarr.

    Proxied rather than redirected: a redirect would need the service's API key in the
    browser, and rule 13 says that never happens. The filename comes from the service's
    own listing, never from the request.
    """
    service = _service_or_404(session, service_id)

    async def fetch(adapter):
        entries = await adapter.backups()
        match = next((b for b in entries if b.id == backup_id), None)
        if match is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No such backup."
            )
        body, content_type = await adapter.backup_bytes(match.path)
        return body, content_type, match.name

    body, content_type, name = await _call(service, fetch)
    return Response(
        content=body,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.delete(
    "/{service_id}/backups/{backup_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_backup(
    service_id: int, backup_id: int, session: Session = Depends(get_session)
) -> None:
    service = _service_or_404(session, service_id)
    await _call(service, lambda a: a.delete_backup(backup_id))


# ------------------------------------------------------------------------ logs


@router.get("/{service_id}/logs", response_model=LogPage)
async def logs(
    service_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    level: str | None = Query(None, description="fatal, error, warn, info, debug, trace"),
    session: Session = Depends(get_session),
) -> LogPage:
    service = _service_or_404(session, service_id)
    return await _call(
        service, lambda a: a.logs(page=page, page_size=page_size, level=level)
    )


@router.get("/{service_id}/log-files", response_model=list[LogFile])
async def log_files(
    service_id: int, session: Session = Depends(get_session)
) -> list[LogFile]:
    service = _service_or_404(session, service_id)
    return await _call(service, lambda a: a.log_files())


@router.get("/{service_id}/log-files/{file_id}")
async def log_file_contents(
    service_id: int, file_id: int, session: Session = Depends(get_session)
) -> Response:
    """Raw text of one rotated log file, resolved by id against the service's listing."""
    service = _service_or_404(session, service_id)

    async def fetch(adapter):
        files = await adapter.log_files()
        match = next((f for f in files if f.id == file_id), None)
        if match is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No such log file."
            )
        return await adapter.log_file_text(match.download_path), match.filename

    text, name = await _call(service, fetch)
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={"X-Log-Filename": name},
    )


# ----------------------------------------------------------------------- tasks


@router.get("/{service_id}/tasks", response_model=list[ScheduledTask])
async def tasks(
    service_id: int, session: Session = Depends(get_session)
) -> list[ScheduledTask]:
    service = _service_or_404(session, service_id)
    return await _call(service, lambda a: a.tasks())


@router.post("/{service_id}/tasks/run", response_model=ActionOut)
async def run_task(
    service_id: int, body: TaskRunRequest, session: Session = Depends(get_session)
) -> ActionOut:
    """Run a scheduled task now.

    The task must be one the service actually schedules — checked against its own list
    rather than forwarded, so this endpoint can't be used to issue arbitrary commands.
    """
    service = _service_or_404(session, service_id)

    async def run(adapter):
        known = await adapter.tasks()
        if not any(t.task_name == body.task_name for t in known):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{service.name} has no scheduled task named {body.task_name}.",
            )
        return await adapter.run_task(body.task_name)

    return ActionOut(status=await _call(service, run))


# --------------------------------------------------------------------- restart


@router.post("/{service_id}/restart", response_model=ActionOut)
async def restart(
    service_id: int, session: Session = Depends(get_session)
) -> ActionOut:
    """Restart a service.

    Returns as soon as the request is accepted. The service drops its listener while
    replying, so the adapter treats a dropped connection as success — waiting for it to
    come back is the container runtime's job, and blocking here would just time out.
    """
    service = _service_or_404(session, service_id)
    await _call(service, lambda a: a.restart())
    return ActionOut(status="restarting")
