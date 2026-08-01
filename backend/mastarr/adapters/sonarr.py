"""Sonarr — TV series. API v3."""

from __future__ import annotations

from typing import Any, ClassVar

from .base import ArrAdapter
from .schemas import CalendarEntry, DateKind, Episode, HistoryItem, LibraryItem, QueueItem, Season


class SonarrAdapter(ArrAdapter):
    service_type: ClassVar[str] = "sonarr"
    display_name: ClassVar[str] = "Sonarr"
    api_version: ClassVar[str] = "v3"
    default_port: ClassVar[int] = 8989
    app_name: ClassVar[str] = "sonarr"
    media_endpoint: ClassVar[str | None] = "series"
    media_kind: ClassVar[str] = "series"
    # Without this the calendar returns bare episode records with no series title.
    calendar_params: ClassVar[dict[str, str]] = {"includeSeries": "true"}
    search_param: ClassVar[str] = "seriesId"
    search_command: ClassVar[str] = "SeriesSearch"
    native_path: ClassVar[str] = "series"
    remote_id_field: ClassVar[str] = "tvdbId"
    remote_id_prefix: ClassVar[str] = "tvdb:"
    search_on_add_field: ClassVar[str] = "searchForMissingEpisodes"

    def _remote_id(self, item: dict[str, Any]) -> str | None:
        tvdb = item.get("tvdbId")
        return str(tvdb) if tvdb else None

    def _parse_queue_item(self, item: dict[str, Any]) -> QueueItem:
        """Append the episode reference, which only Sonarr has."""
        parsed = super()._parse_queue_item(item)
        episode = item.get("episode") or {}
        if episode:
            season = episode.get("seasonNumber")
            number = episode.get("episodeNumber")
            if season is not None and number is not None:
                code = f"S{season:02d}E{number:02d}"
                parsed.media_title = (
                    f"{parsed.media_title} — {code}" if parsed.media_title else code
                )
        return parsed

    def _parse_history_item(self, item: dict[str, Any]) -> HistoryItem:
        parsed = super()._parse_history_item(item)
        if not parsed.media_title:
            # History rows often carry only ids; the series title is then in the
            # denormalized `sourceTitle`, which the base class already used.
            parsed.media_title = (item.get("series") or {}).get("title")
        return parsed

    # ------------------------------------------------------------- unified views

    def _parse_calendar_item(self, item: dict[str, Any]) -> list[CalendarEntry]:
        """One episode -> one entry. Sonarr has exactly one date, unlike Radarr."""
        air = self._parse_dt(item.get("airDateUtc"))
        if air is None:
            return []
        series = item.get("series") or {}
        return [
            CalendarEntry(
                service_id=self.service_id,
                service_type=self.service_type,
                service_name=self.name,
                media_kind="series",
                item_id=item.get("seriesId") or item.get("id", 0),
                title=item.get("title") or "",
                parent_title=series.get("title"),
                date=air,
                date_kind=DateKind.AIR,
                season_number=item.get("seasonNumber"),
                episode_number=item.get("episodeNumber"),
                has_file=bool(item.get("hasFile", False)),
                monitored=bool(item.get("monitored", True)),
                overview=item.get("overview"),
                runtime_minutes=item.get("runtime"),
                poster=self._poster_path(series) if series else None,
            )
        ]

    def _parse_library_item(self, item: dict[str, Any]) -> LibraryItem:
        stats = item.get("statistics") or {}
        return LibraryItem(
            **self._base_library_fields(item),
            network=item.get("network"),
            size_bytes=int(stats.get("sizeOnDisk") or 0),
            # Episode counts, so one progress bar serves both series and movies.
            have_count=int(stats.get("episodeFileCount") or 0),
            total_count=int(stats.get("episodeCount") or 0),
        )

    def _search_command_payload(self, item_id: int) -> dict[str, Any]:
        return {"name": self.search_command, "seriesId": item_id}

    def native_url(self, item_id: int) -> str | None:
        return f"{self.url}/series/{item_id}"

    async def seasons(self, item_id: int) -> list[Season]:
        """Season breakdown with episodes, for the detail view.

        Merges two calls: the series record carries per-season monitored flags and
        statistics, while /episode carries the individual episodes.
        """
        series = await self._request("GET", f"series/{item_id}")
        episodes_raw = await self._request("GET", "episode", params={"seriesId": item_id})

        by_season: dict[int, list[Episode]] = {}
        for raw in episodes_raw or []:
            number = raw.get("seasonNumber")
            if number is None:
                continue
            by_season.setdefault(number, []).append(
                Episode(
                    id=raw.get("id", 0),
                    season_number=number,
                    episode_number=raw.get("episodeNumber", 0),
                    title=raw.get("title"),
                    air_date=self._parse_dt(raw.get("airDateUtc")),
                    has_file=bool(raw.get("hasFile", False)),
                    monitored=bool(raw.get("monitored", True)),
                    runtime_minutes=raw.get("runtime"),
                    overview=raw.get("overview"),
                )
            )

        seasons: list[Season] = []
        for raw_season in (series or {}).get("seasons", []) or []:
            number = raw_season.get("seasonNumber")
            if number is None:
                continue
            stats = raw_season.get("statistics") or {}
            episodes = sorted(by_season.get(number, []), key=lambda e: e.episode_number)
            seasons.append(
                Season(
                    season_number=number,
                    monitored=bool(raw_season.get("monitored", True)),
                    episode_count=int(stats.get("episodeCount") or len(episodes)),
                    episode_file_count=int(
                        stats.get("episodeFileCount")
                        or sum(1 for e in episodes if e.has_file)
                    ),
                    size_bytes=int(stats.get("sizeOnDisk") or 0),
                    episodes=episodes,
                )
            )
        return sorted(seasons, key=lambda s: s.season_number)

    async def set_season_monitored(
        self, item_id: int, season_number: int, monitored: bool
    ) -> LibraryItem:
        """Season monitoring lives inside the series record's `seasons` array."""
        record = await self._request("GET", f"series/{item_id}")
        if not isinstance(record, dict):
            from .errors import ServiceError

            raise ServiceError("Unexpected series payload.", service=self.name)

        found = False
        for season in record.get("seasons", []) or []:
            if season.get("seasonNumber") == season_number:
                season["monitored"] = monitored
                found = True
                break
        if not found:
            from .errors import ServiceError

            raise ServiceError(
                f"Season {season_number} not found on this series.", service=self.name
            )

        updated = await self._request("PUT", f"series/{item_id}", json=record)
        return self._parse_library_item(updated if isinstance(updated, dict) else record)
