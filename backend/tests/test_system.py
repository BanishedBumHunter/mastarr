"""System operations: backups, logs, updates, scheduled tasks, restart.

Payloads here are shaped from live probes of Sonarr 4.0.18 and Prowlarr 2.5 rather than
invented, because three of the shapes are surprising:

* `system/backup` calls the manual/scheduled distinction `type`, which collides with a
  Python builtin and with our `service_type`, so it is normalized to `kind`.
* `update` returns the *whole release history*, not just what is pending. "Is there an
  update?" means "is there a non-installed entry", not "is the list non-empty".
* Backups and log files are served from `/backup/<name>` and `/logfile/<name>` — outside
  the `/api/<version>` prefix that every other call uses.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from mastarr.adapters import (
    JellyseerrAdapter,
    ProwlarrAdapter,
    SonarrAdapter,
    UnsupportedOperation,
)

SONARR_URL = "http://sonarr.test:8989"
API = f"{SONARR_URL}/api/v3"


BACKUPS = [
    {
        "id": 4,
        "name": "sonarr_backup_v4.0.18_2026.08.02_19.12.13.zip",
        "path": "/backup/scheduled/sonarr_backup_v4.0.18_2026.08.02_19.12.13.zip",
        "type": "scheduled",
        "size": 2_411_255,
        "time": "2026-08-02T23:12:17Z",
    },
    {
        "id": 9,
        "name": "sonarr_backup_v4.0.18_2026.07.26_19.11.02.zip",
        "path": "/backup/manual/sonarr_backup_v4.0.18_2026.07.26_19.11.02.zip",
        "type": "manual",
        "size": 2_398_100,
        "time": "2026-07-26T23:11:05Z",
    },
]

LOG_PAGE = {
    "page": 1,
    "pageSize": 50,
    "totalRecords": 11213,
    "records": [
        {
            "id": 5001,
            "time": "2026-08-03T10:34:11Z",
            "level": "error",
            "logger": "DownloadService",
            "message": "Couldn't add report to download queue",
            "exception": "System.Net.WebException: timed out",
        },
        {
            "id": 5000,
            "time": "2026-08-03T10:33:18Z",
            "level": "info",
            "logger": "RssSyncService",
            "message": "RSS sync completed",
        },
    ],
}

LOG_FILES = [
    {
        "id": 19,
        "filename": "sonarr.debug.txt",
        "lastWriteTime": "2026-08-03T10:34:11Z",
        "downloadUrl": "/logfile/sonarr.debug.txt",
    },
    {
        "id": 42,
        "filename": "sonarr.txt",
        "lastWriteTime": "2026-08-03T10:33:18Z",
        "downloadUrl": "/logfile/sonarr.txt",
    },
]

# Real shape: the installed release is in the middle of the list, not at either end.
UPDATES = [
    {
        "version": "4.0.19.2995",
        "branch": "main",
        "releaseDate": "2026-07-30T00:00:00Z",
        "installed": False,
        "installable": True,
        "latest": True,
        "changes": {"new": ["Faster RSS sync"], "fixed": ["Import list crash"]},
    },
    {
        "version": "4.0.18.2978",
        "branch": "main",
        "releaseDate": "2026-07-01T00:00:00Z",
        "installed": True,
        "installable": False,
        "latest": False,
        "changes": {"new": [], "fixed": ["Calendar timezone"]},
    },
]

STATUS_BARE_METAL = {"appName": "Sonarr", "version": "4.0.18.2978", "isDocker": False}
STATUS_DOCKER = {"appName": "Sonarr", "version": "4.0.18.2978", "isDocker": True}

TASKS = [
    {
        "id": 1,
        "name": "Backup",
        "taskName": "Backup",
        "interval": 10080,
        "lastExecution": "2026-08-02T23:12:00Z",
        "lastDuration": "00:00:04.1234567",
        "nextExecution": "2026-08-09T23:12:00Z",
    },
    {
        "id": 2,
        "name": "Check Health",
        "taskName": "CheckHealth",
        "interval": 360,
        "lastExecution": "2026-08-03T06:58:00Z",
        "lastDuration": "00:00:00.0500000",
        "nextExecution": "2026-08-03T12:58:00Z",
    },
]


def adapter() -> SonarrAdapter:
    return SonarrAdapter(SONARR_URL, "key", name="Sonarr", service_id=1)


# ------------------------------------------------------------------- backups


@respx.mock
@pytest.mark.asyncio
async def test_backups_normalize_type_to_kind_and_sort_newest_first() -> None:
    respx.get(f"{API}/system/backup").mock(return_value=httpx.Response(200, json=BACKUPS))
    async with adapter() as a:
        result = await a.backups()

    assert [b.id for b in result] == [4, 9], "newest backup must come first"
    assert result[0].kind == "scheduled"
    assert result[0].size_bytes == 2_411_255
    assert result[0].service_id == 1 and result[0].service_name == "Sonarr"


@respx.mock
@pytest.mark.asyncio
async def test_backup_bytes_uses_the_service_reported_path() -> None:
    """Backups live under `scheduled/` or `manual/`, outside /api/v3.

    Guessing `/backup/<name>` 404s for every backup in the other directory — this is a
    live-probed regression, not a hypothetical.
    """
    route = respx.get(f"{SONARR_URL}/backup/scheduled/sonarr_backup.zip").mock(
        return_value=httpx.Response(200, content=b"PK\x03\x04zipbytes")
    )
    async with adapter() as a:
        body, content_type = await a.backup_bytes("/backup/scheduled/sonarr_backup.zip")

    assert route.called
    assert body == b"PK\x03\x04zipbytes"
    assert content_type == "application/zip"


@respx.mock
@pytest.mark.asyncio
async def test_create_backup_issues_the_backup_command() -> None:
    route = respx.post(f"{API}/command").mock(
        return_value=httpx.Response(201, json={"status": "queued"})
    )
    async with adapter() as a:
        assert await a.create_backup() == "queued"

    assert route.calls.last.request.content == b'{"name":"Backup"}'


# ---------------------------------------------------------------------- logs


@respx.mock
@pytest.mark.asyncio
async def test_logs_page_and_carry_exceptions() -> None:
    route = respx.get(f"{API}/log").mock(return_value=httpx.Response(200, json=LOG_PAGE))
    async with adapter() as a:
        page = await a.logs(page=1, page_size=50, level="error")

    assert page.total == 11213
    assert len(page.records) == 2
    assert page.records[0].level == "error"
    assert "WebException" in (page.records[0].exception or "")
    assert page.records[1].exception is None

    params = route.calls.last.request.url.params
    assert params["level"] == "error"
    assert params["sortDirection"] == "descending", "newest-first is the only useful order"


@respx.mock
@pytest.mark.asyncio
async def test_log_page_size_is_capped() -> None:
    """An unbounded page size lets one request pull the entire log table into memory."""
    route = respx.get(f"{API}/log").mock(return_value=httpx.Response(200, json=LOG_PAGE))
    async with adapter() as a:
        await a.logs(page_size=100_000)

    assert route.calls.last.request.url.params["pageSize"] == "250"


@respx.mock
@pytest.mark.asyncio
async def test_log_files_carry_the_service_reported_download_path() -> None:
    respx.get(f"{API}/log/file").mock(return_value=httpx.Response(200, json=LOG_FILES))
    async with adapter() as a:
        files = await a.log_files()

    assert [f.filename for f in files] == ["sonarr.debug.txt", "sonarr.txt"]
    assert files[0].download_path == "/logfile/sonarr.debug.txt"


@respx.mock
@pytest.mark.asyncio
async def test_log_file_text_uses_the_unprefixed_path() -> None:
    route = respx.get(f"{SONARR_URL}/logfile/sonarr.txt").mock(
        return_value=httpx.Response(200, text="10:33 info RSS sync completed\n")
    )
    async with adapter() as a:
        text = await a.log_file_text("/logfile/sonarr.txt")

    assert route.called
    assert "RSS sync completed" in text


# ------------------------------------------------------------------- updates


@respx.mock
@pytest.mark.asyncio
async def test_updates_identify_installed_among_history() -> None:
    respx.get(f"{API}/update").mock(return_value=httpx.Response(200, json=UPDATES))
    async with adapter() as a:
        entries = await a.updates()

    installed = [e for e in entries if e.installed]
    assert [e.version for e in installed] == ["4.0.18.2978"]
    assert entries[0].version == "4.0.19.2995"
    assert entries[0].changes_new == ["Faster RSS sync"]
    assert entries[0].changes_fixed == ["Import list crash"]


@respx.mock
@pytest.mark.asyncio
async def test_install_update_issues_application_update() -> None:
    route = respx.post(f"{API}/command").mock(
        return_value=httpx.Response(201, json={"status": "started"})
    )
    async with adapter() as a:
        assert await a.install_update() == "started"

    assert b"ApplicationUpdate" in route.calls.last.request.content


# --------------------------------------------------------------------- tasks


@respx.mock
@pytest.mark.asyncio
async def test_tasks_sort_by_next_due() -> None:
    respx.get(f"{API}/system/task").mock(return_value=httpx.Response(200, json=TASKS))
    async with adapter() as a:
        result = await a.tasks()

    assert [t.name for t in result] == ["Check Health", "Backup"]
    assert result[0].task_name == "CheckHealth"
    assert result[1].interval_minutes == 10080


@respx.mock
@pytest.mark.asyncio
async def test_run_task_sends_the_command_name_not_the_label() -> None:
    """`name` is 'Check Health'; the command is 'CheckHealth'. Sending the label 400s."""
    route = respx.post(f"{API}/command").mock(
        return_value=httpx.Response(201, json={"status": "queued"})
    )
    async with adapter() as a:
        await a.run_task("CheckHealth")

    assert route.calls.last.request.content == b'{"name":"CheckHealth"}'


# ------------------------------------------------------------------- restart


@respx.mock
@pytest.mark.asyncio
async def test_restart_treats_a_dropped_connection_as_success() -> None:
    """The service tears down its listener mid-reply. That is what success looks like."""
    respx.post(f"{API}/system/restart").mock(side_effect=httpx.ConnectError("closed"))
    async with adapter() as a:
        await a.restart()  # must not raise


# ------------------------------------------------------------- support matrix


@pytest.mark.asyncio
async def test_jellyseerr_declares_every_system_operation_unsupported() -> None:
    """Jellyseerr shares the transport but none of this surface. Probed, not assumed."""
    a = JellyseerrAdapter("http://jellyseerr.test:5055", "key")
    for call in (a.backups(), a.logs(), a.updates(), a.tasks(), a.restart()):
        with pytest.raises(UnsupportedOperation):
            await call
    await a.aclose()


@respx.mock
@pytest.mark.asyncio
async def test_prowlarr_supports_system_operations() -> None:
    """Prowlarr has no library, queue or disk space — but it does have all of these."""
    base = "http://prowlarr.test:9696/api/v1"
    respx.get(f"{base}/system/backup").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{base}/update").mock(return_value=httpx.Response(200, json=UPDATES))
    respx.get(f"{base}/system/task").mock(return_value=httpx.Response(200, json=TASKS))

    a = ProwlarrAdapter("http://prowlarr.test:9696", "key")
    assert await a.backups() == []
    assert len(await a.updates()) == 2
    assert len(await a.tasks()) == 2
    await a.aclose()


# ------------------------------------------------------------------ API layer
#
# These cover the decisions the routes make on top of the adapter: refusing an update the
# service can't install, resolving filenames from the service's own listing rather than
# the request, and validating a task name before forwarding it.

from sqlmodel import Session  # noqa: E402

from mastarr.db import get_engine  # noqa: E402
from mastarr.models import Service  # noqa: E402
from mastarr.services import store_api_key  # noqa: E402


@pytest.fixture
def stack(admin_client):
    with Session(get_engine()) as session:
        for name, kind, url in [
            ("Sonarr", "sonarr", SONARR_URL),
            ("Jellyseerr", "jellyseerr", "http://jellyseerr.test:5055"),
        ]:
            service = Service(name=name, service_type=kind, url=url)
            store_api_key(service, "key")
            session.add(service)
        session.commit()
    return admin_client


@respx.mock
def test_install_update_refuses_inside_a_container(stack) -> None:
    """The trap. A containerised *arr reports installable=true and will unpack a build
    over itself; the next `docker run` throws it away. Its own UI gates on isDocker, and
    the reference stack really does report isDocker=true with installable=true."""
    respx.get(f"{API}/update").mock(return_value=httpx.Response(200, json=UPDATES))
    respx.get(f"{API}/system/status").mock(
        return_value=httpx.Response(200, json=STATUS_DOCKER)
    )
    command = respx.post(f"{API}/command").mock(
        return_value=httpx.Response(201, json={"status": "queued"})
    )

    response = stack.post("/api/system/1/updates/install")

    assert response.status_code == 409
    assert "container" in response.json()["detail"].lower()
    assert not command.called


@respx.mock
def test_install_update_refuses_when_the_service_says_not_installable(stack) -> None:
    not_installable = [{**UPDATES[0], "installable": False}, UPDATES[1]]
    respx.get(f"{API}/update").mock(
        return_value=httpx.Response(200, json=not_installable)
    )

    response = stack.post("/api/system/1/updates/install")

    assert response.status_code == 409
    assert "not installable" in response.json()["detail"]


@respx.mock
def test_install_update_proceeds_outside_a_container(stack) -> None:
    respx.get(f"{API}/update").mock(return_value=httpx.Response(200, json=UPDATES))
    respx.get(f"{API}/system/status").mock(
        return_value=httpx.Response(200, json=STATUS_BARE_METAL)
    )
    command = respx.post(f"{API}/command").mock(
        return_value=httpx.Response(201, json={"status": "queued"})
    )

    response = stack.post("/api/system/1/updates/install")

    assert response.status_code == 200
    assert b"ApplicationUpdate" in command.calls.last.request.content


@respx.mock
def test_install_update_refuses_when_already_current(stack) -> None:
    respx.get(f"{API}/update").mock(return_value=httpx.Response(200, json=[UPDATES[1]]))

    response = stack.post("/api/system/1/updates/install")

    assert response.status_code == 409
    assert "newest" in response.json()["detail"]


@respx.mock
def test_backup_download_resolves_the_name_from_the_service(stack) -> None:
    """The client sends an id. A filename arriving from the browser and being appended to
    a service URL is a traversal; the route never does that."""
    respx.get(f"{API}/system/backup").mock(return_value=httpx.Response(200, json=BACKUPS))
    route = respx.get(
        f"{SONARR_URL}/backup/scheduled/sonarr_backup_v4.0.18_2026.08.02_19.12.13.zip"
    ).mock(return_value=httpx.Response(200, content=b"zip"))

    response = stack.get("/api/system/1/backups/4/download")

    assert response.status_code == 200
    assert route.called
    assert "sonarr_backup_v4.0.18" in response.headers["content-disposition"]


@respx.mock
def test_backup_download_404s_for_an_id_the_service_does_not_have(stack) -> None:
    respx.get(f"{API}/system/backup").mock(return_value=httpx.Response(200, json=BACKUPS))

    assert stack.get("/api/system/1/backups/999/download").status_code == 404


@respx.mock
def test_run_task_refuses_a_command_the_service_does_not_schedule(stack) -> None:
    """Without this the endpoint forwards arbitrary command names to the service."""
    respx.get(f"{API}/system/task").mock(return_value=httpx.Response(200, json=TASKS))
    command = respx.post(f"{API}/command").mock(
        return_value=httpx.Response(201, json={"status": "queued"})
    )

    response = stack.post(
        "/api/system/1/tasks/run", json={"task_name": "RefreshMonitoredDownloads"}
    )

    assert response.status_code == 400
    assert not command.called, "an unknown task must never reach the service"


@respx.mock
def test_run_task_forwards_a_known_command(stack) -> None:
    respx.get(f"{API}/system/task").mock(return_value=httpx.Response(200, json=TASKS))
    respx.post(f"{API}/command").mock(
        return_value=httpx.Response(201, json={"status": "queued"})
    )

    response = stack.post("/api/system/1/tasks/run", json={"task_name": "CheckHealth"})

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


@respx.mock
def test_fleet_updates_reports_a_failing_service_instead_of_dropping_it(stack) -> None:
    """A service missing from an update list reads as 'up to date'. It must not be."""
    respx.get(f"{API}/update").mock(return_value=httpx.Response(200, json=UPDATES))
    respx.get(f"{API}/system/status").mock(
        return_value=httpx.Response(200, json=STATUS_DOCKER)
    )

    response = stack.get("/api/system/updates")
    body = response.json()

    assert response.status_code == 200
    assert [s["service_name"] for s in body["services"]] == ["Sonarr"]
    assert body["services"][0]["update_available"] is True
    # Available, but not offered as a one-click install — it's in a container.
    assert body["services"][0]["installable"] is False
    assert "container" in body["services"][0]["blocked_reason"]
    assert body["services"][0]["current_version"] == "4.0.18.2978"
    assert body["services"][0]["latest_version"] == "4.0.19.2995"
    # Jellyseerr declares updates unsupported, so it lands in failures, not silence.
    assert [f["service_name"] for f in body["failures"]] == ["Jellyseerr"]
