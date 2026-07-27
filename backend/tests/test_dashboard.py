"""Dashboard aggregation and the graceful-degradation guarantee."""

from __future__ import annotations

import httpx
import respx

from . import fixtures as fx


def _add(client, name, service_type, url, api_key="key"):
    response = client.post(
        "/api/services",
        json={
            "name": name,
            "service_type": service_type,
            "url": url,
            "api_key": api_key,
        },
    )
    assert response.status_code == 201
    return response.json()


def _mock_healthy(url, status_payload, api_version="v3"):
    base = f"{url}/api/{api_version}"
    respx.get(f"{base}/system/status").mock(
        return_value=httpx.Response(200, json=status_payload)
    )
    respx.get(f"{base}/health").mock(return_value=httpx.Response(200, json=fx.HEALTH_OK))
    respx.get(f"{base}/diskspace").mock(
        return_value=httpx.Response(200, json=fx.DISKSPACE)
    )
    respx.get(f"{base}/queue").mock(return_value=httpx.Response(200, json={"records": []}))


def test_empty_dashboard_is_valid(admin_client):
    body = admin_client.get("/api/dashboard").json()
    assert body["totals"]["services"] == 0
    assert body["services"] == []


@respx.mock
def test_dashboard_aggregates_across_services(admin_client):
    _mock_healthy("http://sonarr.test:8989", fx.SONARR_STATUS)
    _mock_healthy("http://radarr.test:7878", fx.RADARR_STATUS)
    _mock_healthy("http://prowlarr.test:9696", fx.PROWLARR_STATUS, api_version="v1")

    _add(admin_client, "Sonarr", "sonarr", "http://sonarr.test:8989")
    _add(admin_client, "Radarr", "radarr", "http://radarr.test:7878")
    _add(admin_client, "Prowlarr", "prowlarr", "http://prowlarr.test:9696")

    body = admin_client.get("/api/dashboard?refresh=true").json()
    assert body["totals"]["services"] == 3
    assert body["totals"]["online"] == 3
    assert {s["app_name"] for s in body["services"]} == {"Sonarr", "Radarr", "Prowlarr"}


@respx.mock
def test_dashboard_renders_fully_when_every_service_is_down(admin_client):
    """The core requirement: the UI degrades, it never crashes."""
    respx.route().mock(side_effect=httpx.ConnectError("refused"))

    _add(admin_client, "Sonarr", "sonarr", "http://sonarr.test:8989")
    _add(admin_client, "Radarr", "radarr", "http://radarr.test:7878")

    response = admin_client.get("/api/dashboard?refresh=true")
    assert response.status_code == 200

    body = response.json()
    assert body["totals"]["unreachable"] == 2
    assert all(s["status"] == "unreachable" for s in body["services"])
    assert all(s["error"] for s in body["services"])


@respx.mock
def test_one_dead_service_does_not_affect_the_others(admin_client):
    """Isolation: a broken service must not take healthy ones down with it."""
    _mock_healthy("http://sonarr.test:8989", fx.SONARR_STATUS)
    respx.get("http://radarr.test:7878/api/v3/system/status").mock(
        side_effect=httpx.ConnectError("refused")
    )

    _add(admin_client, "Sonarr", "sonarr", "http://sonarr.test:8989")
    _add(admin_client, "Radarr", "radarr", "http://radarr.test:7878")

    body = admin_client.get("/api/dashboard?refresh=true").json()
    by_name = {s["name"]: s for s in body["services"]}

    assert by_name["Sonarr"]["status"] == "online"
    assert by_name["Sonarr"]["version"] == "4.0.10.2544"
    assert by_name["Radarr"]["status"] == "unreachable"


@respx.mock
def test_mixed_status_matrix(admin_client):
    """The scenario from the plan: three real services with no keys, plus a bogus URL."""
    for port in (8989, 7878, 9696):
        version = "v1" if port == 9696 else "v3"
        respx.get(f"http://arr.test:{port}/api/{version}/system/status").mock(
            return_value=httpx.Response(401)
        )
    respx.get("http://nope.test:8989/api/v3/system/status").mock(
        side_effect=httpx.ConnectError("refused")
    )

    _add(admin_client, "Sonarr", "sonarr", "http://arr.test:8989", api_key="")
    _add(admin_client, "Radarr", "radarr", "http://arr.test:7878", api_key="")
    _add(admin_client, "Prowlarr", "prowlarr", "http://arr.test:9696", api_key="")
    _add(admin_client, "Bogus", "sonarr", "http://nope.test:8989", api_key="")

    body = admin_client.get("/api/dashboard?refresh=true").json()
    assert body["totals"]["unauthorized"] == 3
    assert body["totals"]["unreachable"] == 1
    assert len(body["services"]) == 4


@respx.mock
def test_degraded_service_counts_health_issues(admin_client):
    base = "http://sonarr.test:8989/api/v3"
    respx.get(f"{base}/system/status").mock(
        return_value=httpx.Response(200, json=fx.SONARR_STATUS)
    )
    respx.get(f"{base}/health").mock(
        return_value=httpx.Response(200, json=fx.HEALTH_WARNINGS)
    )
    respx.get(f"{base}/diskspace").mock(return_value=httpx.Response(200, json=fx.DISKSPACE))
    respx.get(f"{base}/queue").mock(
        return_value=httpx.Response(200, json=fx.SONARR_QUEUE)
    )

    _add(admin_client, "Sonarr", "sonarr", "http://sonarr.test:8989")
    body = admin_client.get("/api/dashboard?refresh=true").json()

    assert body["totals"]["degraded"] == 1
    assert body["totals"]["health_issues"] == 2
    assert body["totals"]["queued_items"] == 2


@respx.mock
def test_disabled_services_are_excluded(admin_client):
    _mock_healthy("http://sonarr.test:8989", fx.SONARR_STATUS)
    created = _add(admin_client, "Sonarr", "sonarr", "http://sonarr.test:8989")
    admin_client.patch(f"/api/services/{created['id']}", json={"enabled": False})

    assert admin_client.get("/api/dashboard?refresh=true").json()["totals"]["services"] == 0


@respx.mock
def test_unknown_service_type_in_db_degrades_rather_than_500s(admin_client):
    """A type that was valid when saved but is no longer registered."""
    from sqlmodel import Session, select

    from mastarr.db import get_engine
    from mastarr.models import Service

    _mock_healthy("http://sonarr.test:8989", fx.SONARR_STATUS)
    _add(admin_client, "Sonarr", "sonarr", "http://sonarr.test:8989")

    with Session(get_engine()) as session:
        service = session.exec(select(Service)).one()
        service.service_type = "bazarr"
        session.add(service)
        session.commit()

    response = admin_client.get("/api/dashboard?refresh=true")
    assert response.status_code == 200
    assert response.json()["services"][0]["status"] == "unknown"


@respx.mock
def test_snapshot_results_are_cached_then_refreshable(admin_client):
    _mock_healthy("http://sonarr.test:8989", fx.SONARR_STATUS)
    route = respx.get("http://sonarr.test:8989/api/v3/system/status")
    _add(admin_client, "Sonarr", "sonarr", "http://sonarr.test:8989")

    admin_client.get("/api/dashboard?refresh=true")
    calls_after_first = route.call_count

    admin_client.get("/api/dashboard")  # served from cache
    assert route.call_count == calls_after_first

    admin_client.get("/api/dashboard?refresh=true")  # forced
    assert route.call_count > calls_after_first


@respx.mock
def test_resource_endpoint_returns_502_on_adapter_failure(admin_client):
    _mock_healthy("http://sonarr.test:8989", fx.SONARR_STATUS)
    created = _add(admin_client, "Sonarr", "sonarr", "http://sonarr.test:8989")

    respx.get("http://sonarr.test:8989/api/v3/history").mock(
        side_effect=httpx.ConnectError("refused")
    )
    response = admin_client.get(f"/api/services/{created['id']}/history")

    # Upstream problem, not a Mastarr bug.
    assert response.status_code == 502


def test_resource_endpoint_rejects_unknown_resource_names(admin_client):
    """Guards against `getattr(adapter, resource)` exposing internals."""
    created = _add(admin_client, "Sonarr", "sonarr", "http://sonarr.test:8989")
    for probe in ("aclose", "api_key", "_request", "__class__"):
        assert admin_client.get(f"/api/services/{created['id']}/{probe}").status_code == 404


def test_service_type_endpoint_exposes_the_registry(admin_client):
    types = {t["type"]: t for t in admin_client.get("/api/services/types").json()}
    assert types["prowlarr"]["api_version"] == "v1"
    assert types["sonarr"]["api_version"] == "v3"
    assert types["prowlarr"]["manages_media"] is False


def test_unknown_service_type_is_rejected_at_creation(admin_client):
    response = admin_client.post(
        "/api/services",
        json={"name": "Bazarr", "service_type": "bazarr", "url": "http://x:6767"},
    )
    assert response.status_code == 400


def test_duplicate_service_name_is_rejected(admin_client):
    payload = {
        "name": "Sonarr",
        "service_type": "sonarr",
        "url": "http://sonarr.test:8989",
    }
    admin_client.post("/api/services", json=payload)
    assert admin_client.post("/api/services", json=payload).status_code == 409


def test_patch_without_api_key_field_preserves_the_stored_key(admin_client):
    """Absent means 'leave alone'; empty string means 'clear'."""
    created = _add(admin_client, "Sonarr", "sonarr", "http://sonarr.test:8989", "thekey123")

    admin_client.patch(f"/api/services/{created['id']}", json={"name": "Sonarr TV"})
    assert admin_client.get("/api/services").json()[0]["has_api_key"] is True

    admin_client.patch(f"/api/services/{created['id']}", json={"api_key": ""})
    assert admin_client.get("/api/services").json()[0]["has_api_key"] is False
