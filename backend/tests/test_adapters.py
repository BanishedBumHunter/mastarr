"""Adapter parsing, error mapping, and the v1/v3 split."""

from __future__ import annotations

import httpx
import pytest
import respx

from mastarr.adapters import (
    ProwlarrAdapter,
    RadarrAdapter,
    ServiceError,
    ServiceStatus,
    ServiceUnauthorized,
    ServiceUnreachable,
    SonarrAdapter,
    UnsupportedOperation,
    build_adapter,
    default_ports,
    get_adapter_class,
    known_types,
    type_for_app_name,
)
from mastarr.adapters.registry import UnknownServiceType

from . import fixtures as fx

SONARR_URL = "http://sonarr.test:8989"
RADARR_URL = "http://radarr.test:7878"
PROWLARR_URL = "http://prowlarr.test:9696"

# Async tests are collected via `asyncio_mode = auto` in pytest.ini — no per-test marker.


# ------------------------------------------------------------------- registry


def test_registry_knows_every_registered_type():
    assert set(known_types()) == {
        "sonarr",
        "radarr",
        "lidarr",
        "readarr",
        "prowlarr",
        "jellyseerr",
        "suggestarr",
    }


def test_api_versions_are_per_service_not_assumed():
    """The core generalization: only Sonarr and Radarr are v3; everything else is v1."""
    assert get_adapter_class("sonarr").api_version == "v3"
    assert get_adapter_class("radarr").api_version == "v3"
    for v1_type in ("prowlarr", "lidarr", "readarr", "jellyseerr"):
        assert get_adapter_class(v1_type).api_version == "v1", v1_type


def test_api_base_reflects_the_version():
    assert build_adapter("sonarr", SONARR_URL).api_base == f"{SONARR_URL}/api/v3"
    assert build_adapter("prowlarr", PROWLARR_URL).api_base == f"{PROWLARR_URL}/api/v1"


def test_default_ports_match_upstream_defaults():
    assert default_ports() == {
        8989: "sonarr",
        7878: "radarr",
        8686: "lidarr",
        8787: "readarr",
        9696: "prowlarr",
        5055: "jellyseerr",
        5000: "suggestarr",
    }


def test_app_name_resolves_to_type():
    assert type_for_app_name("Sonarr") == "sonarr"
    assert type_for_app_name("PROWLARR") == "prowlarr"
    assert type_for_app_name("Bazarr") is None


def test_unknown_type_is_rejected_clearly():
    with pytest.raises(UnknownServiceType, match="No adapter for service type"):
        get_adapter_class("bazarr")


def test_trailing_slash_in_url_is_normalized():
    assert build_adapter("sonarr", f"{SONARR_URL}/").api_base == f"{SONARR_URL}/api/v3"


# ------------------------------------------------------------------- identity


@respx.mock
async def test_system_status_parses_identity():
    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        return_value=httpx.Response(200, json=fx.SONARR_STATUS)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        status = await adapter.system_status()
    assert status.app_name == "Sonarr"
    assert status.version == "4.0.10.2544"
    assert status.is_docker is True
    assert status.start_time is not None


@respx.mock
async def test_api_key_is_sent_as_header_never_query_param():
    """Query params land in every intermediate proxy's access log."""
    route = respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        return_value=httpx.Response(200, json=fx.SONARR_STATUS)
    )
    async with SonarrAdapter(SONARR_URL, "secret-key-value") as adapter:
        await adapter.system_status()

    request = route.calls[0].request
    assert request.headers["X-Api-Key"] == "secret-key-value"
    assert "secret-key-value" not in str(request.url)


@respx.mock
async def test_ping_needs_no_api_key():
    respx.get(f"{SONARR_URL}/ping").mock(
        return_value=httpx.Response(200, json=fx.PING_OK)
    )
    async with SonarrAdapter(SONARR_URL) as adapter:
        assert await adapter.ping() is True


@respx.mock
async def test_ping_is_false_when_unreachable():
    respx.get(f"{SONARR_URL}/ping").mock(side_effect=httpx.ConnectError("refused"))
    async with SonarrAdapter(SONARR_URL) as adapter:
        assert await adapter.ping() is False


# --------------------------------------------------------------- error mapping


@respx.mock
async def test_401_maps_to_unauthorized():
    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        return_value=httpx.Response(401)
    )
    async with SonarrAdapter(SONARR_URL, "bad") as adapter:
        with pytest.raises(ServiceUnauthorized, match="rejected"):
            await adapter.system_status()


@respx.mock
async def test_missing_key_still_reports_unreachable_when_host_is_down():
    """Regression: a missing key must not mask a dead host.

    Reporting `unauthorized` for an unreachable service sends the operator hunting for a
    credential problem that does not exist.
    """
    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        side_effect=httpx.ConnectError("refused")
    )
    async with SonarrAdapter(SONARR_URL, api_key=None) as adapter:
        with pytest.raises(ServiceUnreachable):
            await adapter.system_status()


@respx.mock
async def test_missing_key_on_a_live_host_reports_unauthorized():
    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        return_value=httpx.Response(401)
    )
    async with SonarrAdapter(SONARR_URL, api_key=None) as adapter:
        with pytest.raises(ServiceUnauthorized, match="No API key configured"):
            await adapter.system_status()


@respx.mock
async def test_timeout_maps_to_unreachable():
    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        side_effect=httpx.ReadTimeout("too slow")
    )
    async with SonarrAdapter(SONARR_URL, "key", timeout=2.0) as adapter:
        with pytest.raises(ServiceUnreachable, match="Timed out"):
            await adapter.system_status()


@respx.mock
async def test_html_response_gives_an_actionable_error():
    """The classic 'URL points at a proxy or login page' misconfiguration."""
    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        return_value=httpx.Response(200, text="<!DOCTYPE html><html>Login</html>")
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        with pytest.raises(ServiceError, match="proxy or login page"):
            await adapter.system_status()


@respx.mock
async def test_500_maps_to_service_error():
    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        return_value=httpx.Response(500)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        with pytest.raises(ServiceError, match="HTTP 500"):
            await adapter.system_status()


@respx.mock
async def test_httpx_errors_never_escape_the_adapter():
    """Everything above the adapter layer only ever catches AdapterError."""
    respx.get(f"{SONARR_URL}/api/v3/health").mock(
        side_effect=httpx.ConnectError("boom")
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        with pytest.raises(ServiceUnreachable):
            await adapter.health()


# ------------------------------------------------------------------- parsing


@respx.mock
async def test_health_parses_severities():
    respx.get(f"{SONARR_URL}/api/v3/health").mock(
        return_value=httpx.Response(200, json=fx.HEALTH_WARNINGS)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        issues = await adapter.health()
    assert [i.severity.value for i in issues] == ["warning", "error"]
    assert issues[1].message == "Missing root folder: /media/tv"


@respx.mock
async def test_disk_space_computes_usage():
    respx.get(f"{SONARR_URL}/api/v3/diskspace").mock(
        return_value=httpx.Response(200, json=fx.DISKSPACE)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        disks = await adapter.disk_space()
    assert disks[0].used_bytes == 6_000_000_000_000
    assert disks[0].used_percent == 75.0


@respx.mock
async def test_sonarr_queue_flattens_and_adds_episode_code():
    respx.get(f"{SONARR_URL}/api/v3/queue").mock(
        return_value=httpx.Response(200, json=fx.SONARR_QUEUE)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        items = await adapter.queue()

    assert items[0].media_title == "Some Show — S01E02"
    assert items[0].quality == "WEBDL-1080p"
    assert items[0].progress_percent == 75.0
    # Non-ASCII titles must survive intact.
    assert items[1].media_title == "Другое Шоу — S02E01"
    # statusMessages is the fallback when errorMessage is absent.
    assert items[1].error_message == "No files found are eligible"


@respx.mock
async def test_radarr_queue_uses_movie_not_series():
    """Same normalized shape from a different payload — the point of the adapter layer."""
    respx.get(f"{RADARR_URL}/api/v3/queue").mock(
        return_value=httpx.Response(200, json=fx.RADARR_QUEUE)
    )
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        items = await adapter.queue()

    assert items[0].media_title == "Some Movie"
    assert items[0].quality == "Bluray-2160p"
    assert items[0].progress_percent == 75.0


@respx.mock
async def test_queue_handles_bare_list_without_records_envelope():
    respx.get(f"{SONARR_URL}/api/v3/queue").mock(
        return_value=httpx.Response(200, json=[])
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        assert await adapter.queue() == []


@respx.mock
async def test_history_parses():
    respx.get(f"{SONARR_URL}/api/v3/history").mock(
        return_value=httpx.Response(200, json=fx.SONARR_HISTORY)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        items = await adapter.history()
    assert items[0].event_type == "downloadFolderImported"
    assert items[0].media_title == "Some Show"


@respx.mock
async def test_quality_profiles_resolve_cutoff_name():
    respx.get(f"{SONARR_URL}/api/v3/qualityprofile").mock(
        return_value=httpx.Response(200, json=fx.QUALITY_PROFILES)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        profiles = await adapter.quality_profiles()
    assert profiles[0].cutoff_name == "WEBDL-1080p"
    assert profiles[0].upgrade_allowed is True


@respx.mock
async def test_root_folders_surface_inaccessible_paths():
    respx.get(f"{SONARR_URL}/api/v3/rootfolder").mock(
        return_value=httpx.Response(200, json=fx.ROOT_FOLDERS)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        folders = await adapter.root_folders()
    assert folders[1].accessible is False


@respx.mock
async def test_download_clients_map_enable_field():
    respx.get(f"{SONARR_URL}/api/v3/downloadclient").mock(
        return_value=httpx.Response(200, json=fx.DOWNLOAD_CLIENTS)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        clients = await adapter.download_clients()
    assert [c.enabled for c in clients] == [True, False]


@respx.mock
async def test_prowlarr_indexers_use_enabled_not_enable():
    """Prowlarr spells the field differently; the base adapter tolerates both."""
    respx.get(f"{PROWLARR_URL}/api/v1/indexer").mock(
        return_value=httpx.Response(200, json=fx.PROWLARR_INDEXERS)
    )
    async with ProwlarrAdapter(PROWLARR_URL, "key") as adapter:
        indexers = await adapter.indexers()
    assert indexers[0].enabled is True
    assert indexers[0].name == "1337x"


@respx.mock
async def test_search_extracts_remote_ids_per_type():
    respx.get(f"{SONARR_URL}/api/v3/series/lookup").mock(
        return_value=httpx.Response(200, json=fx.SONARR_LOOKUP)
    )
    respx.get(f"{RADARR_URL}/api/v3/movie/lookup").mock(
        return_value=httpx.Response(200, json=fx.RADARR_LOOKUP)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        series = await adapter.search("some show")
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        movies = await adapter.search("some movie")

    assert series[0].remote_id == "123456"  # tvdbId
    assert series[1].already_added is True
    assert movies[0].remote_id == "99887"  # tmdbId
    assert movies[0].poster_url == "/MediaCover/1/poster.jpg"


# --------------------------------------------------------------- unsupported


@pytest.mark.parametrize(
    "operation", ["disk_space", "queue", "quality_profiles", "root_folders"]
)
async def test_prowlarr_declares_unsupported_operations(operation):
    """Declared up front rather than left to 404, so the UI can hide them."""
    async with ProwlarrAdapter(PROWLARR_URL, "key") as adapter:
        with pytest.raises(UnsupportedOperation):
            await getattr(adapter, operation)()


async def test_prowlarr_search_is_unsupported_it_manages_no_library():
    async with ProwlarrAdapter(PROWLARR_URL, "key") as adapter:
        with pytest.raises(UnsupportedOperation):
            await adapter.search("anything")


# ------------------------------------------------------------------ snapshot


@respx.mock
async def test_snapshot_online_when_healthy():
    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        return_value=httpx.Response(200, json=fx.SONARR_STATUS)
    )
    respx.get(f"{SONARR_URL}/api/v3/health").mock(
        return_value=httpx.Response(200, json=fx.HEALTH_OK)
    )
    respx.get(f"{SONARR_URL}/api/v3/diskspace").mock(
        return_value=httpx.Response(200, json=fx.DISKSPACE)
    )
    respx.get(f"{SONARR_URL}/api/v3/queue").mock(
        return_value=httpx.Response(200, json=fx.SONARR_QUEUE)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        snap = await adapter.snapshot()

    assert snap.status is ServiceStatus.ONLINE
    assert snap.version == "4.0.10.2544"
    assert snap.queue_count == 2
    assert len(snap.disk_space) == 2


@respx.mock
async def test_snapshot_degraded_when_health_warnings_present():
    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        return_value=httpx.Response(200, json=fx.SONARR_STATUS)
    )
    respx.get(f"{SONARR_URL}/api/v3/health").mock(
        return_value=httpx.Response(200, json=fx.HEALTH_WARNINGS)
    )
    respx.get(f"{SONARR_URL}/api/v3/diskspace").mock(
        return_value=httpx.Response(200, json=fx.DISKSPACE)
    )
    respx.get(f"{SONARR_URL}/api/v3/queue").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        snap = await adapter.snapshot()

    assert snap.status is ServiceStatus.DEGRADED
    assert len(snap.health_issues) == 2


@respx.mock
async def test_notice_level_health_does_not_degrade():
    """An available-update notice is not an operational problem."""
    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        return_value=httpx.Response(200, json=fx.SONARR_STATUS)
    )
    respx.get(f"{SONARR_URL}/api/v3/health").mock(
        return_value=httpx.Response(200, json=fx.HEALTH_NOTICE_ONLY)
    )
    respx.get(f"{SONARR_URL}/api/v3/diskspace").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(f"{SONARR_URL}/api/v3/queue").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        snap = await adapter.snapshot()

    assert snap.status is ServiceStatus.ONLINE


@respx.mock
async def test_snapshot_never_raises_on_unreachable():
    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        side_effect=httpx.ConnectError("refused")
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        snap = await adapter.snapshot()

    assert snap.status is ServiceStatus.UNREACHABLE
    assert snap.error is not None
    assert snap.version is None


@respx.mock
async def test_snapshot_survives_partial_failure():
    """system/status works but /health 500s — still meaningfully online."""
    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        return_value=httpx.Response(200, json=fx.SONARR_STATUS)
    )
    respx.get(f"{SONARR_URL}/api/v3/health").mock(return_value=httpx.Response(500))
    respx.get(f"{SONARR_URL}/api/v3/diskspace").mock(return_value=httpx.Response(500))
    respx.get(f"{SONARR_URL}/api/v3/queue").mock(return_value=httpx.Response(500))

    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        snap = await adapter.snapshot()

    assert snap.status is ServiceStatus.ONLINE
    assert snap.version == "4.0.10.2544"
    assert snap.queue_count is None


@respx.mock
async def test_prowlarr_snapshot_works_despite_unsupported_operations():
    """Unsupported endpoints must not drag a healthy Prowlarr out of ONLINE."""
    respx.get(f"{PROWLARR_URL}/api/v1/system/status").mock(
        return_value=httpx.Response(200, json=fx.PROWLARR_STATUS)
    )
    respx.get(f"{PROWLARR_URL}/api/v1/health").mock(
        return_value=httpx.Response(200, json=fx.HEALTH_OK)
    )
    async with ProwlarrAdapter(PROWLARR_URL, "key") as adapter:
        snap = await adapter.snapshot()

    assert snap.status is ServiceStatus.ONLINE
    assert snap.version == "1.24.3.4754"
    assert snap.disk_space == []
    assert snap.queue_count is None
