"""Upgrade sweep and grab guard.

Both of these act on their own — one issues searches, the other deletes downloads — so the
tests care most about them being *inert until switched on* and never firing on incomplete
information.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from sqlmodel import Session

from mastarr import grab_guard, sweeper
from mastarr.db import get_engine
from mastarr.models import Service
from mastarr.services import store_api_key

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)
SONARR_URL = "http://sonarr.test:8989"


def days_ago(n: float) -> datetime:
    return NOW - timedelta(days=n)


@pytest.fixture
def stack(admin_client):
    with Session(get_engine()) as session:
        for name, kind, url in [
            ("Sonarr", "sonarr", SONARR_URL),
            ("Radarr", "radarr", "http://radarr.test:7878"),
            ("Prowlarr", "prowlarr", "http://prowlarr.test:9696"),
        ]:
            service = Service(name=name, service_type=kind, url=url)
            store_api_key(service, "key")
            session.add(service)
        session.commit()
        yield session


# --------------------------------------------------------------- grab guard


def test_guard_rejects_a_fresh_upload_of_an_old_title():
    """The case it exists for: posted yesterday, film is years old."""
    verdict = grab_guard.evaluate(
        release_published=days_ago(1),
        media_released=days_ago(2000),
        now=NOW,
        max_days_after_release=365,
        min_media_age_days=180,
    )
    assert verdict.reject is True
    assert "re-upload" in verdict.reason or "fake" in verdict.reason


def test_guard_leaves_new_releases_alone():
    """During a launch window every release is days old and legitimate.

    Without this the guard would reject exactly the things you most want.
    """
    verdict = grab_guard.evaluate(
        release_published=days_ago(1),
        media_released=days_ago(3),
        now=NOW,
        max_days_after_release=365,
        min_media_age_days=180,
    )
    assert verdict.reject is False


def test_guard_allows_an_old_upload_of_an_old_title():
    """A release posted alongside the original release is normal, however old both are."""
    verdict = grab_guard.evaluate(
        release_published=days_ago(1995),
        media_released=days_ago(2000),
        now=NOW,
        max_days_after_release=365,
        min_media_age_days=180,
    )
    assert verdict.reject is False


def test_guard_never_acts_on_missing_dates():
    """Absence of evidence is not evidence. A guard that fires when it doesn't know is
    worse than no guard."""
    for published, released in [
        (None, days_ago(2000)),
        (days_ago(1), None),
        (None, None),
    ]:
        verdict = grab_guard.evaluate(
            release_published=published, media_released=released, now=NOW
        )
        assert verdict.reject is False
        assert "Not enough date information" in verdict.reason


async def test_guard_is_inert_while_disabled(stack):
    """Default state. Nothing is removed no matter how suspicious the payload."""
    payload = {
        "eventType": "Grab",
        "instanceName": "Sonarr",
        "release": {"releaseTitle": "Old.Movie.2001", "publishDate": days_ago(1).isoformat()},
        "movie": {"releaseDate": days_ago(3000).isoformat()},
    }
    verdict = await grab_guard.handle_grab(stack, payload)
    assert verdict.reject is False
    assert "disabled" in verdict.reason.lower()


@respx.mock
async def test_guard_removes_and_blocklists_when_enabled(stack, monkeypatch):
    monkeypatch.setenv("MASTARR_GRAB_GUARD_ENABLED", "true")
    from mastarr.config import get_settings

    get_settings.cache_clear()

    respx.get(f"{SONARR_URL}/api/v3/queue").mock(
        return_value=httpx.Response(
            200, json={"records": [{"id": 55, "title": "Old.Movie.2001"}]}
        )
    )
    delete = respx.delete(url__startswith=f"{SONARR_URL}/api/v3/queue/55").mock(
        return_value=httpx.Response(200)
    )

    payload = {
        "eventType": "Grab",
        "instanceName": "Sonarr",
        "release": {
            "releaseTitle": "Old.Movie.2001",
            "publishDate": datetime.now(timezone.utc).isoformat(),
        },
        "series": {"firstAired": days_ago(3000).isoformat()},
    }
    verdict = await grab_guard.handle_grab(stack, payload)

    assert verdict.reject is True
    assert delete.called
    # Blocklisting is the point — without it the next RSS pass re-grabs the same release.
    assert "blocklist=true" in str(delete.calls[0].request.url)

    audit = grab_guard.audit_log()
    assert audit[0]["action"] == "rejected"
    get_settings.cache_clear()


async def test_guard_records_a_failure_rather_than_acting_blindly(stack, monkeypatch):
    """An unmatched instance name must be logged, not guessed at."""
    monkeypatch.setenv("MASTARR_GRAB_GUARD_ENABLED", "true")
    from mastarr.config import get_settings

    get_settings.cache_clear()
    payload = {
        "eventType": "Grab",
        "instanceName": "SomeOtherInstance",
        "release": {
            "releaseTitle": "x",
            "publishDate": datetime.now(timezone.utc).isoformat(),
        },
        "movie": {"releaseDate": days_ago(3000).isoformat()},
    }
    await grab_guard.handle_grab(stack, payload)
    assert grab_guard.audit_log()[0]["action"] == "failed"
    get_settings.cache_clear()


# -------------------------------------------------------------------- sweep


def test_sweep_commands_are_named_per_service_type():
    assert sweeper.SWEEP_COMMANDS["sonarr"]["cutoff"] == "CutoffUnmetEpisodeSearch"
    assert sweeper.SWEEP_COMMANDS["radarr"]["cutoff"] == "CutoffUnmetMoviesSearch"
    # Prowlarr and Jellyseerr have no library, so they are simply absent.
    assert "prowlarr" not in sweeper.SWEEP_COMMANDS
    assert "jellyseerr" not in sweeper.SWEEP_COMMANDS


def test_cutoff_endpoint_is_the_one_that_exists():
    """`wanted/cutoffunmet` 404s on a live Sonarr; `wanted/cutoff` is correct."""
    assert sweeper.CUTOFF_ENDPOINT == "wanted/cutoff"


@respx.mock
async def test_sweep_issues_commands_only_to_services_that_can_take_them(stack):
    sonarr = respx.post(f"{SONARR_URL}/api/v3/command").mock(
        return_value=httpx.Response(201, json={"status": "queued"})
    )
    radarr = respx.post("http://radarr.test:7878/api/v3/command").mock(
        return_value=httpx.Response(201, json={"status": "queued"})
    )
    prowlarr = respx.post("http://prowlarr.test:9696/api/v1/command")

    results = await sweeper.run_sweep(stack, include_missing=True)

    assert sonarr.call_count == 2  # cutoff + missing
    assert radarr.call_count == 2
    assert prowlarr.call_count == 0, "Prowlarr has no library to sweep"
    assert all(r.ok for r in results)

    import json as _json

    names = {_json.loads(c.request.content)["name"] for c in sonarr.calls}
    assert names == {"CutoffUnmetEpisodeSearch", "MissingEpisodeSearch"}


@respx.mock
async def test_sweep_can_skip_the_missing_search(stack):
    sonarr = respx.post(f"{SONARR_URL}/api/v3/command").mock(
        return_value=httpx.Response(201, json={})
    )
    respx.post("http://radarr.test:7878/api/v3/command").mock(
        return_value=httpx.Response(201, json={})
    )
    await sweeper.run_sweep(stack, include_missing=False)
    assert sonarr.call_count == 1


@respx.mock
async def test_one_failing_service_does_not_abort_the_sweep(stack):
    respx.post(f"{SONARR_URL}/api/v3/command").mock(
        side_effect=httpx.ConnectError("refused")
    )
    radarr = respx.post("http://radarr.test:7878/api/v3/command").mock(
        return_value=httpx.Response(201, json={})
    )
    results = await sweeper.run_sweep(stack, include_missing=False)

    assert radarr.called, "a dead Sonarr stopped Radarr being swept"
    assert any(not r.ok for r in results)
    assert any(r.ok for r in results)


@respx.mock
async def test_below_cutoff_count_is_read_from_the_right_endpoint(stack):
    route = respx.get(f"{SONARR_URL}/api/v3/wanted/cutoff").mock(
        return_value=httpx.Response(200, json={"totalRecords": 940, "records": []})
    )
    from sqlmodel import select

    service = stack.exec(select(Service).where(Service.name == "Sonarr")).one()
    assert await sweeper.below_cutoff_count(service) == 940
    assert route.called


async def test_below_cutoff_is_none_for_services_without_a_library(stack):
    from sqlmodel import select

    prowlarr = stack.exec(select(Service).where(Service.name == "Prowlarr")).one()
    assert await sweeper.below_cutoff_count(prowlarr) is None


# ------------------------------------------------------------------ webhook


def test_webhook_rejects_a_bad_token(admin_client):
    response = admin_client.post(
        "/api/automation/guard/webhook?token=wrong", json={"eventType": "Grab"}
    )
    assert response.status_code == 401


def test_webhook_acknowledges_a_test_event(admin_client):
    """Sonarr's Test button must go green without running the rule on a fake payload."""
    from mastarr.api.automation import webhook_token

    response = admin_client.post(
        f"/api/automation/guard/webhook?token={webhook_token()}",
        json={"eventType": "Test"},
    )
    assert response.status_code == 202
    assert response.json()["ok"] is True


def test_webhook_url_carries_the_token(admin_client):
    body = admin_client.get("/api/automation/guard/webhook-url").json()
    assert "token=" in body["url"]
    assert body["url"].endswith(__import__("mastarr.api.automation", fromlist=["x"]).webhook_token())
