"""Discovery: the presence/identity split."""

from __future__ import annotations

import httpx
import respx

from mastarr.discovery import (
    DiscoveredService,
    _split_target,
    identify,
    probe_endpoint,
    scan_host,
)

from . import fixtures as fx


# ------------------------------------------------------------ target parsing


def test_split_target_handles_bare_host():
    assert _split_target("192.168.1.250") == ("http", "192.168.1.250", None)


def test_split_target_handles_host_and_port():
    assert _split_target("192.168.1.250:8989") == ("http", "192.168.1.250", 8989)


def test_split_target_handles_full_url():
    assert _split_target("https://arr.local:443") == ("https", "arr.local", 443)


# -------------------------------------------------------- phase 1: presence


@respx.mock
async def test_probe_finds_a_service_without_any_api_key():
    """The property that makes zero-config first run possible."""
    respx.get("http://host.test:8989/ping").mock(
        return_value=httpx.Response(200, json=fx.PING_OK)
    )
    found = await probe_endpoint("host.test", 8989)

    assert found is not None
    assert found.service_type == "sonarr"  # from the port, as a hint
    assert found.confirmed is False  # but not proven
    assert found.needs_api_key is True


@respx.mock
async def test_probe_returns_none_when_nothing_listens():
    respx.get("http://host.test:8989/ping").mock(
        side_effect=httpx.ConnectError("refused")
    )
    assert await probe_endpoint("host.test", 8989) is None


@respx.mock
async def test_probe_rejects_a_non_arr_service_on_an_arr_port():
    """Something else squatting on 8989 must not be reported as Sonarr."""
    respx.get("http://host.test:8989/ping").mock(
        return_value=httpx.Response(200, text="<html>nginx</html>")
    )
    assert await probe_endpoint("host.test", 8989) is None


@respx.mock
async def test_probe_rejects_wrong_json_shape():
    respx.get("http://host.test:8989/ping").mock(
        return_value=httpx.Response(200, json={"hello": "world"})
    )
    assert await probe_endpoint("host.test", 8989) is None


@respx.mock
async def test_probe_on_unknown_port_has_no_type_guess():
    respx.get("http://host.test:9999/ping").mock(
        return_value=httpx.Response(200, json=fx.PING_OK)
    )
    found = await probe_endpoint("host.test", 9999)
    assert found is not None
    assert found.service_type is None


@respx.mock
async def test_scan_host_finds_the_whole_stack():
    """Mirrors the real 192.168.1.250 layout."""
    for port in (8989, 7878, 9696):
        respx.get(f"http://host.test:{port}/ping").mock(
            return_value=httpx.Response(200, json=fx.PING_OK)
        )
    found = await scan_host("host.test")

    assert {f.service_type for f in found} == {"sonarr", "radarr", "prowlarr"}
    assert all(f.needs_api_key for f in found)


@respx.mock
async def test_scan_host_tolerates_a_partially_present_stack():
    respx.get("http://host.test:8989/ping").mock(
        return_value=httpx.Response(200, json=fx.PING_OK)
    )
    respx.get("http://host.test:7878/ping").mock(
        side_effect=httpx.ConnectError("refused")
    )
    respx.get("http://host.test:9696/ping").mock(side_effect=httpx.ReadTimeout("slow"))

    found = await scan_host("host.test")
    assert [f.service_type for f in found] == ["sonarr"]


# -------------------------------------------------------- phase 2: identity


@respx.mock
async def test_identify_confirms_via_system_status():
    respx.get("http://host.test:8989/api/v3/system/status").mock(
        return_value=httpx.Response(200, json=fx.SONARR_STATUS)
    )
    candidate = DiscoveredService(
        url="http://host.test:8989", host="host.test", port=8989, service_type="sonarr"
    )
    result = await identify(candidate, "key")

    assert result.confirmed is True
    assert result.app_name == "Sonarr"
    assert result.version == "4.0.10.2544"
    assert "API v3" in (result.detail or "")


@respx.mock
async def test_identify_trusts_app_name_over_the_port():
    """Radarr running on Sonarr's port is Radarr. The port was only ever a hint."""
    respx.get("http://host.test:8989/api/v3/system/status").mock(
        return_value=httpx.Response(200, json=fx.RADARR_STATUS)
    )
    candidate = DiscoveredService(
        url="http://host.test:8989", host="host.test", port=8989, service_type="sonarr"
    )
    result = await identify(candidate, "key")

    assert result.service_type == "radarr"
    assert result.app_name == "Radarr"


@respx.mock
async def test_identify_finds_a_v1_service_on_a_nonstandard_port():
    """Falls through to other types — and therefore other API versions — when the first
    guess 404s. This is what makes the v1/v3 split invisible to the caller."""
    respx.get("http://host.test:9999/api/v3/system/status").mock(
        return_value=httpx.Response(404)
    )
    # Jellyseerr shares the v1 prefix but a different status path; identify walks past it.
    respx.get("http://host.test:9999/api/v1/status").mock(
        return_value=httpx.Response(404)
    )
    respx.get("http://host.test:9999/api/v1/system/status").mock(
        return_value=httpx.Response(200, json=fx.PROWLARR_STATUS)
    )
    candidate = DiscoveredService(
        url="http://host.test:9999", host="host.test", port=9999, service_type="sonarr"
    )
    result = await identify(candidate, "key")

    assert result.confirmed is True
    assert result.service_type == "prowlarr"
    assert "API v1" in (result.detail or "")


@respx.mock
async def test_identify_stops_guessing_on_a_rejected_key():
    """A 401 is conclusive about the credential, so trying more types is pointless noise."""
    route = respx.get("http://host.test:8989/api/v3/system/status").mock(
        return_value=httpx.Response(401)
    )
    candidate = DiscoveredService(
        url="http://host.test:8989", host="host.test", port=8989, service_type="sonarr"
    )
    result = await identify(candidate, "bad-key")

    assert result.confirmed is False
    assert result.needs_api_key is True
    assert route.call_count == 1


@respx.mock
async def test_identify_reports_failure_when_nothing_matches():
    respx.route(host="host.test").mock(return_value=httpx.Response(404))
    candidate = DiscoveredService(
        url="http://host.test:8989", host="host.test", port=8989
    )
    result = await identify(candidate, "key")

    assert result.confirmed is False
    assert result.detail is not None


# ----------------------------------------------------------------- endpoint


def test_scan_endpoint_marks_already_configured_services(admin_client):
    import respx as _respx

    with _respx.mock:
        _respx.get("http://host.test:8989/ping").mock(
            return_value=httpx.Response(200, json=fx.PING_OK)
        )
        _respx.get("http://host.test:7878/ping").mock(
            side_effect=httpx.ConnectError("refused")
        )
        _respx.get("http://host.test:9696/ping").mock(
            side_effect=httpx.ConnectError("refused")
        )

        admin_client.post(
            "/api/services",
            json={
                "name": "Sonarr",
                "service_type": "sonarr",
                "url": "http://host.test:8989",
            },
        )
        found = admin_client.post(
            "/api/discovery/scan", json={"hosts": ["host.test"]}
        ).json()

    assert len(found) == 1
    assert found[0]["already_configured"] is True
