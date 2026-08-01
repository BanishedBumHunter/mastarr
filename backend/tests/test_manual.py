"""Manual control: interactive search, manual import, queue and blocklist.

These are the operations that override what a service decided on its own, so the tests
care most about the overrides being deliberate: a rejected release must still be grabbable
(that's the point of interactive search), and removing something from the queue must not
silently blocklist it.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from mastarr.adapters import RadarrAdapter, SonarrAdapter, UnsupportedOperation

SONARR_URL = "http://sonarr.test:8989"
RADARR_URL = "http://radarr.test:7878"

# Shaped like a real Radarr interactive-search result, including a rejection.
RELEASES = [
    {
        "guid": "indexer-abc-1",
        "title": "Some.Movie.2026.1080p.BluRay.x264",
        "indexer": "NZBgeek",
        "indexerId": 1,
        "protocol": "usenet",
        "size": 8_000_000_000,
        "ageHours": 26.5,
        "publishDate": "2026-07-30T10:00:00Z",
        "quality": {"quality": {"id": 7, "name": "Bluray-1080p"}},
        "rejected": False,
        "rejections": [],
        "downloadAllowed": True,
        "customFormatScore": 50,
    },
    {
        "guid": "indexer-abc-2",
        "title": "Some.Movie.2026.1080p.DCPRIP.x264",
        "indexer": "NzbPlanet",
        "indexerId": 2,
        "protocol": "usenet",
        "size": 4_000_000_000,
        "ageHours": 600.0,
        "publishDate": "2026-07-05T10:00:00Z",
        "quality": {"quality": {"id": 3, "name": "HDTV-1080p"}},
        "rejected": True,
        "rejections": ["Quality HDTV-1080p is not wanted in profile"],
        "downloadAllowed": False,
        "customFormatScore": 0,
    },
]

IMPORT_CANDIDATES = [
    {
        "path": "/data/TV/Some Show/Season 01/ep01.mkv",
        "size": 2_000_000_000,
        "quality": {"quality": {"id": 3, "name": "WEBDL-1080p"}},
        "series": {"id": 7, "title": "Some Show"},
        "seasonNumber": 1,
        "episodes": [{"id": 90}],
        "rejections": [],
    },
    {
        # The service couldn't work out what this is — must not be presented as importable.
        "path": "/data/TV/unknown-thing.mkv",
        "size": 100,
        "quality": {},
        "rejections": [{"reason": "Unknown series"}],
    },
]

BLOCKLIST = {
    "records": [
        {
            "id": 3,
            "sourceTitle": "Bad.Release.2026",
            "date": "2026-07-30T12:00:00Z",
            "indexer": "NZBgeek",
            "protocol": "usenet",
            "quality": {"quality": {"id": 3, "name": "HDTV-1080p"}},
            "movie": {"title": "Some Movie"},
            "message": "Removed by the grab guard",
        }
    ]
}


# ------------------------------------------------------- interactive search


@respx.mock
async def test_search_uses_the_right_param_per_service_type():
    """Sonarr searches by seriesId, Radarr by movieId."""
    sonarr = respx.get(f"{SONARR_URL}/api/v3/release").mock(
        return_value=httpx.Response(200, json=[])
    )
    radarr = respx.get(f"{RADARR_URL}/api/v3/release").mock(
        return_value=httpx.Response(200, json=[])
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        await adapter.releases(item_id=7)
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        await adapter.releases(item_id=3)

    assert "seriesId=7" in str(sonarr.calls[0].request.url)
    assert "movieId=3" in str(radarr.calls[0].request.url)


@respx.mock
async def test_episode_search_overrides_the_series_param():
    route = respx.get(f"{SONARR_URL}/api/v3/release").mock(
        return_value=httpx.Response(200, json=[])
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        await adapter.releases(item_id=7, episode_id=90)
    url = str(route.calls[0].request.url)
    assert "episodeId=90" in url
    assert "seriesId" not in url


@respx.mock
async def test_releases_carry_the_rejection_reasons():
    """"Nothing downloaded" is a mystery; "rejected because X" is a decision."""
    respx.get(f"{RADARR_URL}/api/v3/release").mock(
        return_value=httpx.Response(200, json=RELEASES)
    )
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        releases = await adapter.releases(item_id=3)

    good, bad = releases[0], releases[1]
    assert good.rejected is False
    assert good.quality == "Bluray-1080p"
    assert good.age_days == 1.1
    assert bad.rejected is True
    assert bad.rejections == ["Quality HDTV-1080p is not wanted in profile"]
    assert bad.download_allowed is False


@respx.mock
async def test_search_ranks_accepted_releases_first(admin_client):
    """A rejected release is still listed — you may want it anyway — but not on top."""
    from sqlmodel import Session

    from mastarr.db import get_engine
    from mastarr.models import Service
    from mastarr.services import store_api_key

    with Session(get_engine()) as session:
        service = Service(name="Radarr", service_type="radarr", url=RADARR_URL)
        store_api_key(service, "key")
        session.add(service)
        session.commit()
        service_id = service.id

    respx.get(f"{RADARR_URL}/api/v3/release").mock(
        return_value=httpx.Response(200, json=list(reversed(RELEASES)))
    )
    body = admin_client.get(f"/api/manual/{service_id}/releases?item_id=3").json()
    assert body[0]["rejected"] is False, "a rejected release was ranked first"
    assert body[1]["rejected"] is True


@respx.mock
async def test_grab_sends_guid_and_indexer():
    route = respx.post(f"{RADARR_URL}/api/v3/release").mock(
        return_value=httpx.Response(201, json={})
    )
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        await adapter.grab_release("indexer-abc-2", 2)

    import json as _json

    assert _json.loads(route.calls[0].request.content) == {
        "guid": "indexer-abc-2",
        "indexerId": 2,
    }


async def test_services_without_a_library_cannot_search_interactively():
    from mastarr.adapters import build_adapter

    adapter = build_adapter("prowlarr", "http://p:9696", "key")
    try:
        with pytest.raises(UnsupportedOperation):
            await adapter.releases(item_id=1)
    finally:
        await adapter.aclose()


# ------------------------------------------------------------ manual import


@respx.mock
async def test_import_candidates_flag_what_cannot_be_placed():
    respx.get(f"{SONARR_URL}/api/v3/manualimport").mock(
        return_value=httpx.Response(200, json=IMPORT_CANDIDATES)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        candidates = await adapter.import_candidates("/data/TV")

    good, bad = candidates[0], candidates[1]
    assert good.importable is True
    assert good.media_title == "Some Show"
    assert good.episode_ids == [90]
    assert good.name == "ep01.mkv"

    assert bad.importable is False
    assert bad.rejections == ["Unknown series"]


@respx.mock
async def test_import_defaults_to_move_and_names_the_command():
    route = respx.post(f"{SONARR_URL}/api/v3/command").mock(
        return_value=httpx.Response(201, json={"status": "queued"})
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        await adapter.do_import([{"path": "/x.mkv", "seriesId": 7}])

    import json as _json

    sent = _json.loads(route.calls[0].request.content)
    assert sent["name"] == "ManualImport"
    assert sent["importMode"] == "move"


@respx.mock
async def test_import_route_maps_media_id_onto_the_right_field(admin_client):
    """Sonarr wants seriesId, Radarr movieId. The UI shouldn't have to know."""
    from sqlmodel import Session

    from mastarr.db import get_engine
    from mastarr.models import Service
    from mastarr.services import store_api_key

    with Session(get_engine()) as session:
        for name, kind, url in [("Sonarr", "sonarr", SONARR_URL), ("Radarr", "radarr", RADARR_URL)]:
            service = Service(name=name, service_type=kind, url=url)
            store_api_key(service, "key")
            session.add(service)
        session.commit()
        from sqlmodel import select

        ids = {s.name: s.id for s in session.exec(select(Service)).all()}

    sonarr = respx.post(f"{SONARR_URL}/api/v3/command").mock(
        return_value=httpx.Response(201, json={"status": "queued"})
    )
    radarr = respx.post(f"{RADARR_URL}/api/v3/command").mock(
        return_value=httpx.Response(201, json={"status": "queued"})
    )
    payload = {"files": [{"path": "/x.mkv", "media_id": 7, "quality": {}}], "move": True}
    admin_client.post(f"/api/manual/{ids['Sonarr']}/import", json=payload)
    admin_client.post(f"/api/manual/{ids['Radarr']}/import", json=payload)

    import json as _json

    assert "seriesId" in _json.loads(sonarr.calls[0].request.content)["files"][0]
    assert "movieId" in _json.loads(radarr.calls[0].request.content)["files"][0]


# --------------------------------------------------------- queue & blocklist


@respx.mock
async def test_queue_removal_does_not_blocklist_unless_asked():
    """Blocklisting is a separate, stickier decision than just clearing the queue."""
    route = respx.delete(url__startswith=f"{RADARR_URL}/api/v3/queue/9").mock(
        return_value=httpx.Response(200)
    )
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        await adapter.queue_remove(9)
    assert "blocklist=false" in str(route.calls[0].request.url)


@respx.mock
async def test_queue_removal_can_blocklist():
    route = respx.delete(url__startswith=f"{RADARR_URL}/api/v3/queue/9").mock(
        return_value=httpx.Response(200)
    )
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        await adapter.queue_remove(9, blocklist=True)
    assert "blocklist=true" in str(route.calls[0].request.url)


@respx.mock
async def test_blocklist_parses():
    respx.get(f"{RADARR_URL}/api/v3/blocklist").mock(
        return_value=httpx.Response(200, json=BLOCKLIST)
    )
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        items = await adapter.blocklist()

    assert items[0].title == "Bad.Release.2026"
    assert items[0].media_title == "Some Movie"
    assert items[0].message == "Removed by the grab guard"


@respx.mock
async def test_blocklist_removal_makes_a_release_grabbable_again():
    route = respx.delete(f"{RADARR_URL}/api/v3/blocklist/3").mock(
        return_value=httpx.Response(200)
    )
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        await adapter.blocklist_remove(3)
    assert route.called


@respx.mock
async def test_blocklist_aggregates_and_degrades(admin_client):
    """One dead service must not empty the whole view."""
    from sqlmodel import Session

    from mastarr.db import get_engine
    from mastarr.models import Service
    from mastarr.services import store_api_key

    with Session(get_engine()) as session:
        for name, kind, url in [("Sonarr", "sonarr", SONARR_URL), ("Radarr", "radarr", RADARR_URL)]:
            service = Service(name=name, service_type=kind, url=url)
            store_api_key(service, "key")
            session.add(service)
        session.commit()

    respx.get(f"{RADARR_URL}/api/v3/blocklist").mock(
        return_value=httpx.Response(200, json=BLOCKLIST)
    )
    respx.get(f"{SONARR_URL}/api/v3/blocklist").mock(
        side_effect=httpx.ConnectError("refused")
    )

    body = admin_client.get("/api/manual/blocklist").json()
    assert len(body["items"]) == 1
    assert len(body["failures"]) == 1
    assert body["failures"][0]["service_name"] == "Sonarr"


# ------------------------------------------------------------------ origin


@respx.mock
async def test_queue_items_know_which_service_they_came_from():
    """Merged into one list, an item without an origin is one you can't act on."""
    from . import fixtures as fx

    respx.get(f"{SONARR_URL}/api/v3/queue").mock(
        return_value=httpx.Response(200, json=fx.SONARR_QUEUE)
    )
    async with SonarrAdapter(SONARR_URL, "key", name="My Sonarr", service_id=42) as adapter:
        items = await adapter.queue()

    assert items[0].service_id == 42
    assert items[0].service_name == "My Sonarr"


@respx.mock
async def test_blocklist_items_know_their_service():
    respx.get(f"{RADARR_URL}/api/v3/blocklist").mock(
        return_value=httpx.Response(200, json=BLOCKLIST)
    )
    async with RadarrAdapter(RADARR_URL, "key", name="My Radarr", service_id=7) as adapter:
        items = await adapter.blocklist()

    assert items[0].service_id == 7
    assert items[0].service_name == "My Radarr"
