"""The unified views: calendar normalization, library merging, discovery proxying."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from mastarr.adapters import (
    DateKind,
    JellyseerrAdapter,
    LidarrAdapter,
    RadarrAdapter,
    ReadarrAdapter,
    SonarrAdapter,
)

from . import fixtures as fx

SONARR_URL = "http://sonarr.test:8989"
RADARR_URL = "http://radarr.test:7878"
SEERR_URL = "http://seerr.test:5055"

START = datetime(2026, 7, 29, tzinfo=timezone.utc)
END = START + timedelta(days=60)


# ------------------------------------------------------------------ calendar


@respx.mock
async def test_sonarr_calendar_normalizes_episodes():
    respx.get(f"{SONARR_URL}/api/v3/calendar").mock(
        return_value=httpx.Response(200, json=fx.SONARR_CALENDAR)
    )
    async with SonarrAdapter(SONARR_URL, "key", name="Sonarr") as adapter:
        entries = await adapter.calendar(START, END)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.parent_title == "Some Show"
    assert entry.episode_code == "S01E02"
    assert entry.date_kind is DateKind.AIR
    assert entry.media_kind == "series"
    assert entry.poster == "MediaCover/7/poster.jpg"


@respx.mock
async def test_sonarr_calendar_requests_the_series_expansion():
    """Without includeSeries the entries have no show title, which makes them useless."""
    route = respx.get(f"{SONARR_URL}/api/v3/calendar").mock(
        return_value=httpx.Response(200, json=fx.SONARR_CALENDAR)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        await adapter.calendar(START, END)
    assert "includeSeries=true" in str(route.calls[0].request.url)


@respx.mock
async def test_radarr_multidate_movie_produces_exactly_one_entry():
    """The three-date problem.

    A movie carrying cinema, digital AND physical dates must appear once — emitting all
    three would show the same film three times in one week.
    """
    respx.get(f"{RADARR_URL}/api/v3/calendar").mock(
        return_value=httpx.Response(200, json=fx.RADARR_CALENDAR_MULTIDATE)
    )
    async with RadarrAdapter(RADARR_URL, "key", name="Radarr") as adapter:
        entries = await adapter.calendar(START, END)

    by_id = {e.item_id: e for e in entries}
    assert len(entries) == len(by_id), "a movie appeared more than once"

    # Digital wins over physical and cinema — it's when you can actually watch it.
    assert by_id[3].date_kind is DateKind.DIGITAL
    assert by_id[3].date.date().isoformat() == "2026-08-10"

    # Cinema-only still shows up, correctly labelled.
    assert by_id[4].date_kind is DateKind.CINEMA

    # A movie with no dates is dropped, not dated to the epoch.
    assert 5 not in by_id


@respx.mock
async def test_calendar_tolerates_a_junk_payload():
    respx.get(f"{RADARR_URL}/api/v3/calendar").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        assert await adapter.calendar(START, END) == []


# ------------------------------------------------------------------- library


@respx.mock
async def test_series_and_movies_normalize_to_one_shape():
    """The point of LibraryItem: one grid renders both without branching."""
    respx.get(f"{SONARR_URL}/api/v3/series").mock(
        return_value=httpx.Response(200, json=fx.SONARR_SERIES_LIBRARY)
    )
    respx.get(f"{RADARR_URL}/api/v3/movie").mock(
        return_value=httpx.Response(200, json=fx.RADARR_MOVIE_LIBRARY)
    )
    async with SonarrAdapter(SONARR_URL, "key", name="Sonarr") as adapter:
        series = await adapter.library()
    async with RadarrAdapter(RADARR_URL, "key", name="Radarr") as adapter:
        movies = await adapter.library()

    show = series[0]
    assert show.media_kind == "series"
    assert (show.have_count, show.total_count) == (8, 10)
    assert show.percent_complete == 80.0
    assert show.is_missing is True
    assert show.network == "HBO"

    movie = movies[0]
    assert movie.media_kind == "movie"
    # Movies collapse to 0/1 or 1/1 so the same progress bar works.
    assert (movie.have_count, movie.total_count) == (1, 1)
    assert movie.percent_complete == 100.0
    assert movie.is_missing is False
    assert movie.studio == "A Studio"

    assert movies[1].is_missing is True


@respx.mock
async def test_unmonitored_incomplete_item_is_not_reported_missing():
    """`missing` means "monitored and absent" — an unmonitored gap is a choice."""
    payload = [dict(fx.RADARR_MOVIE_LIBRARY[1], monitored=False)]
    respx.get(f"{RADARR_URL}/api/v3/movie").mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        items = await adapter.library()
    assert items[0].is_missing is False


@respx.mock
async def test_poster_prefers_the_local_cover_over_the_remote_url():
    """Local covers are already cached by the service and survive TMDB being down."""
    payload = [
        dict(
            fx.SONARR_SERIES_LIBRARY[0],
            images=[
                {
                    "coverType": "poster",
                    "url": "/MediaCover/7/poster.jpg",
                    "remoteUrl": "https://tmdb/poster.jpg",
                }
            ],
        )
    ]
    respx.get(f"{SONARR_URL}/api/v3/series").mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        items = await adapter.library()
    assert items[0].poster == "MediaCover/7/poster.jpg"


# ------------------------------------------------------------------- seasons


@respx.mock
async def test_seasons_merge_series_flags_with_episode_records():
    respx.get(f"{SONARR_URL}/api/v3/series/7").mock(
        return_value=httpx.Response(200, json=fx.SONARR_SERIES_DETAIL)
    )
    respx.get(f"{SONARR_URL}/api/v3/episode").mock(
        return_value=httpx.Response(200, json=fx.SONARR_EPISODES)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        seasons = await adapter.seasons(7)

    assert [s.season_number for s in seasons] == [0, 1]
    specials, season_one = seasons

    assert specials.monitored is False
    assert season_one.monitored is True
    assert season_one.percent_complete == 50.0
    # Episodes arrive unsorted from the API and must come back in order.
    assert [e.episode_number for e in season_one.episodes] == [1, 2]
    assert season_one.episodes[0].has_file is True


@respx.mock
async def test_movies_report_no_seasons_rather_than_erroring():
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        from mastarr.adapters import UnsupportedOperation

        with pytest.raises(UnsupportedOperation):
            await adapter.seasons(3)


# ------------------------------------------------------------ write operations


@respx.mock
async def test_set_monitored_round_trips_the_whole_record():
    """A PATCH-style partial write would drop every field Mastarr doesn't model."""
    record = dict(fx.SONARR_SERIES_LIBRARY[0])
    respx.get(f"{SONARR_URL}/api/v3/series/7").mock(
        return_value=httpx.Response(200, json=record)
    )
    put = respx.put(f"{SONARR_URL}/api/v3/series/7").mock(
        return_value=httpx.Response(200, json=dict(record, monitored=False))
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        result = await adapter.set_monitored(7, False)

    import json as _json

    sent = _json.loads(put.calls[0].request.content)
    assert sent["monitored"] is False
    # Untouched fields must survive the round trip.
    assert sent["path"] == "/media/tv/Some Show"
    assert sent["qualityProfileId"] == 1
    assert result.monitored is False


@respx.mock
async def test_season_monitor_edits_only_the_named_season():
    respx.get(f"{SONARR_URL}/api/v3/series/7").mock(
        return_value=httpx.Response(200, json=fx.SONARR_SERIES_DETAIL)
    )
    put = respx.put(f"{SONARR_URL}/api/v3/series/7").mock(
        return_value=httpx.Response(200, json=fx.SONARR_SERIES_DETAIL)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        await adapter.set_season_monitored(7, 1, False)

    import json as _json

    sent = _json.loads(put.calls[0].request.content)
    by_number = {s["seasonNumber"]: s for s in sent["seasons"]}
    assert by_number[1]["monitored"] is False
    assert by_number[0]["monitored"] is False  # untouched, was already False


@respx.mock
async def test_season_monitor_rejects_a_season_that_does_not_exist():
    respx.get(f"{SONARR_URL}/api/v3/series/7").mock(
        return_value=httpx.Response(200, json=fx.SONARR_SERIES_DETAIL)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        from mastarr.adapters import ServiceError

        with pytest.raises(ServiceError, match="Season 9"):
            await adapter.set_season_monitored(7, 9, False)


@respx.mock
async def test_search_commands_differ_per_service():
    """Sonarr takes a single seriesId; Radarr takes a list of movieIds."""
    son = respx.post(f"{SONARR_URL}/api/v3/command").mock(
        return_value=httpx.Response(201, json={"status": "queued"})
    )
    rad = respx.post(f"{RADARR_URL}/api/v3/command").mock(
        return_value=httpx.Response(201, json={"status": "queued"})
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        await adapter.trigger_search(7)
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        await adapter.trigger_search(3)

    import json as _json

    assert _json.loads(son.calls[0].request.content) == {
        "name": "SeriesSearch",
        "seriesId": 7,
    }
    assert _json.loads(rad.calls[0].request.content) == {
        "name": "MoviesSearch",
        "movieIds": [3],
    }


@respx.mock
async def test_delete_defaults_to_keeping_files():
    """Deleting files is irreversible, so it must never be the default."""
    route = respx.delete(f"{RADARR_URL}/api/v3/movie/3").mock(
        return_value=httpx.Response(200)
    )
    async with RadarrAdapter(RADARR_URL, "key") as adapter:
        await adapter.delete_item(3)
    assert "deleteFiles=false" in str(route.calls[0].request.url)


# ---------------------------------------------------------------- jellyseerr


@respx.mock
async def test_jellyseerr_status_parses_without_an_app_name():
    """Jellyseerr's /status has no appName, so the *arr parser can't be reused."""
    respx.get(f"{SEERR_URL}/api/v1/status").mock(
        return_value=httpx.Response(200, json=fx.JELLYSEERR_STATUS)
    )
    async with JellyseerrAdapter(SEERR_URL, "key") as adapter:
        status = await adapter.system_status()
    assert status.version == "3.3.0"
    assert status.app_name == "Jellyseerr"


@respx.mock
async def test_search_filters_out_person_results():
    """People aren't requestable; rendering them would produce broken cards."""
    respx.get(f"{SEERR_URL}/api/v1/search").mock(
        return_value=httpx.Response(200, json=fx.JELLYSEERR_SEARCH)
    )
    async with JellyseerrAdapter(SEERR_URL, "key") as adapter:
        page = await adapter.discover_search("dune")

    assert page.total_results == 1265
    assert [r.media_kind for r in page.results] == ["movie", "tv"]
    assert page.results[0].title == "Dune"
    assert page.results[0].year == 2021
    assert page.results[0].available is True
    # TV items use `name`/`firstAirDate` rather than `title`/`releaseDate`.
    assert page.results[1].title == "Dune: Prophecy"
    assert page.results[1].year == 2024


@respx.mock
async def test_poster_urls_point_at_the_tmdb_cdn():
    """Not proxied — the browser fetches these directly."""
    respx.get(f"{SEERR_URL}/api/v1/search").mock(
        return_value=httpx.Response(200, json=fx.JELLYSEERR_SEARCH)
    )
    async with JellyseerrAdapter(SEERR_URL, "key") as adapter:
        page = await adapter.discover_search("dune")
    assert page.results[0].poster_url == "https://image.tmdb.org/t/p/w500/poster1.jpg"


@respx.mock
async def test_requests_can_be_scoped_to_one_user_upstream():
    """Scoping must happen in the query, so other users' data never reaches us."""
    route = respx.get(f"{SEERR_URL}/api/v1/request").mock(
        return_value=httpx.Response(200, json=fx.JELLYSEERR_REQUESTS)
    )
    async with JellyseerrAdapter(SEERR_URL, "key") as adapter:
        requests = await adapter.requests(user_id=2)

    assert "requestedBy=2" in str(route.calls[0].request.url)
    assert requests[0].requested_by == "Andy"
    assert requests[0].status == 2


@respx.mock
async def test_creating_a_tv_request_defaults_to_all_seasons():
    """Jellyseerr rejects a TV request with no seasons, so a default is required."""
    route = respx.post(f"{SEERR_URL}/api/v1/request").mock(
        return_value=httpx.Response(201, json=fx.JELLYSEERR_REQUESTS["results"][0])
    )
    async with JellyseerrAdapter(SEERR_URL, "key") as adapter:
        await adapter.create_request(tmdb_id=90228, media_kind="tv", user_id=3)

    import json as _json

    sent = _json.loads(route.calls[0].request.content)
    assert sent == {"mediaType": "tv", "mediaId": 90228, "userId": 3, "seasons": "all"}


@respx.mock
async def test_movie_requests_carry_no_seasons_field():
    route = respx.post(f"{SEERR_URL}/api/v1/request").mock(
        return_value=httpx.Response(201, json=fx.JELLYSEERR_REQUESTS["results"][0])
    )
    async with JellyseerrAdapter(SEERR_URL, "key") as adapter:
        await adapter.create_request(tmdb_id=438631, media_kind="movie")

    import json as _json

    sent = _json.loads(route.calls[0].request.content)
    assert "seasons" not in sent
    assert "userId" not in sent  # unmapped user falls back to the key's owner


# ------------------------------------------------------------ lidarr/readarr


@pytest.mark.parametrize(
    "cls,endpoint,title_field,name",
    [
        (LidarrAdapter, "artist", "artistName", "Some Band"),
        (ReadarrAdapter, "author", "authorName", "Some Author"),
    ],
)
@respx.mock
async def test_music_and_book_libraries_use_their_own_title_field(
    cls, endpoint, title_field, name
):
    """Lidarr/Readarr name the item `artistName`/`authorName`, not `title`.

    Untested against a live service — neither is installed on the reference stack.
    """
    url = f"http://{cls.service_type}.test:{cls.default_port}"
    payload = [
        {
            "id": 1,
            title_field: name,
            "monitored": True,
            "images": [],
            "statistics": {
                "trackFileCount": 5,
                "trackCount": 10,
                "bookFileCount": 5,
                "bookCount": 10,
                "sizeOnDisk": 1_000_000,
            },
        }
    ]
    respx.get(f"{url}/api/v1/{endpoint}").mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with cls(url, "key") as adapter:
        items = await adapter.library()

    assert items[0].title == name
    assert (items[0].have_count, items[0].total_count) == (5, 10)


# ----------------------------------------------- degradation vs informational


@respx.mock
async def test_update_available_does_not_degrade_a_service():
    """Regression from live use.

    Sonarr reports `UpdateCheck` at *warning* severity whenever a newer release exists,
    which is nearly always. Treating that as DEGRADED left the dashboard permanently
    amber and made the status colour meaningless.
    """
    from mastarr.adapters import ServiceStatus

    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        return_value=httpx.Response(200, json=fx.SONARR_STATUS)
    )
    respx.get(f"{SONARR_URL}/api/v3/health").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "source": "UpdateCheck",
                    "type": "warning",
                    "message": "New update is available: v4.0.19.2995",
                }
            ],
        )
    )
    respx.get(f"{SONARR_URL}/api/v3/diskspace").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{SONARR_URL}/api/v3/queue").mock(
        return_value=httpx.Response(200, json={"records": []})
    )

    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        snap = await adapter.snapshot()

    assert snap.status is ServiceStatus.ONLINE
    # Still surfaced on the card — it just doesn't change the verdict.
    assert len(snap.health_issues) == 1


@respx.mock
async def test_a_real_problem_still_degrades():
    """The other half: informational filtering must not swallow genuine faults."""
    from mastarr.adapters import ServiceStatus

    respx.get(f"{SONARR_URL}/api/v3/system/status").mock(
        return_value=httpx.Response(200, json=fx.SONARR_STATUS)
    )
    respx.get(f"{SONARR_URL}/api/v3/health").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"source": "UpdateCheck", "type": "warning", "message": "Update available"},
                {
                    "source": "RootFolderCheck",
                    "type": "error",
                    "message": "Missing root folder: /media/tv",
                },
            ],
        )
    )
    respx.get(f"{SONARR_URL}/api/v3/diskspace").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{SONARR_URL}/api/v3/queue").mock(
        return_value=httpx.Response(200, json={"records": []})
    )

    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        snap = await adapter.snapshot()

    assert snap.status is ServiceStatus.DEGRADED


@pytest.mark.parametrize(
    "operation", ["calendar", "library", "wanted_missing", "queue", "disk_space"]
)
async def test_prowlarr_declares_every_endpoint_it_lacks(operation):
    """Verified by probing a live Prowlarr — all of these 404.

    Undeclared, each one becomes a "Prowlarr failed" banner on every aggregated view,
    and a warning that is always present is one people stop reading.
    """
    from datetime import datetime, timezone

    from mastarr.adapters import ProwlarrAdapter, UnsupportedOperation

    async with ProwlarrAdapter("http://prowlarr.test:9696", "key") as adapter:
        with pytest.raises(UnsupportedOperation):
            if operation == "calendar":
                await adapter.calendar(
                    datetime.now(timezone.utc), datetime.now(timezone.utc)
                )
            else:
                await getattr(adapter, operation)()


@pytest.mark.parametrize(
    "operation", ["calendar", "library", "queue", "history", "disk_space", "wanted_missing"]
)
async def test_jellyseerr_declares_every_arr_endpoint_it_lacks(operation):
    """Verified by probing a live Jellyseerr 3.3 — all of these 404.

    Jellyseerr reuses the *arr transport but is not an *arr, so every *arr-shaped
    endpoint must be declared unsupported rather than left to fail at runtime.
    """
    from datetime import datetime, timezone

    from mastarr.adapters import UnsupportedOperation

    async with JellyseerrAdapter(SEERR_URL, "key") as adapter:
        with pytest.raises(UnsupportedOperation):
            if operation == "calendar":
                await adapter.calendar(
                    datetime.now(timezone.utc), datetime.now(timezone.utc)
                )
            else:
                await getattr(adapter, operation)()
