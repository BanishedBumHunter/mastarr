"""Radarr — movies. API v3."""

from __future__ import annotations

from typing import Any, ClassVar

from .base import ArrAdapter
from .schemas import CalendarEntry, DateKind, LibraryItem


class RadarrAdapter(ArrAdapter):
    service_type: ClassVar[str] = "radarr"
    display_name: ClassVar[str] = "Radarr"
    api_version: ClassVar[str] = "v3"
    default_port: ClassVar[int] = 7878
    app_name: ClassVar[str] = "radarr"
    media_endpoint: ClassVar[str | None] = "movie"
    media_kind: ClassVar[str] = "movie"
    search_param: ClassVar[str] = "movieId"
    search_command: ClassVar[str] = "MoviesSearch"
    native_path: ClassVar[str] = "movie"
    remote_id_field: ClassVar[str] = "tmdbId"
    remote_id_prefix: ClassVar[str] = "tmdb:"
    search_on_add_field: ClassVar[str] = "searchForMovie"
    # Movies have no seasons.
    unsupported: ClassVar[frozenset[str]] = frozenset({"seasons"})
    # Radarr 6.4 serves import-list exclusions at `exclusions`, where Sonarr uses
    # `importlistexclusion`. Verified live — the Sonarr name 404s here.
    config_endpoint_overrides: ClassVar[dict[str, str]] = {
        "import_list_exclusion": "exclusions",
    }

    # Radarr carries up to three release dates on one record. Ordered by how people
    # actually think about "when can I watch this" — a digital release matters more than
    # the cinema date once it exists.
    _DATE_FIELDS: ClassVar[tuple[tuple[str, DateKind], ...]] = (
        ("digitalRelease", DateKind.DIGITAL),
        ("physicalRelease", DateKind.PHYSICAL),
        ("inCinemas", DateKind.CINEMA),
    )

    def _remote_id(self, item: dict[str, Any]) -> str | None:
        tmdb = item.get("tmdbId")
        return str(tmdb) if tmdb else None

    def _parse_calendar_item(self, item: dict[str, Any]) -> list[CalendarEntry]:
        """One movie -> ONE entry, not three.

        A record can carry cinema, digital and physical dates at once. Emitting all of
        them would show the same film three times in a week; emitting the first field
        found would bury the date people care about. So: take the most relevant date that
        exists, in the order above, and label which one it is.
        """
        chosen: tuple[Any, DateKind] | None = None
        for field, kind in self._DATE_FIELDS:
            parsed = self._parse_dt(item.get(field))
            if parsed is not None:
                chosen = (parsed, kind)
                break
        if chosen is None:
            return []

        date, kind = chosen
        return [
            CalendarEntry(
                service_id=self.service_id,
                service_type=self.service_type,
                service_name=self.name,
                media_kind="movie",
                item_id=item.get("id", 0),
                title=item.get("title") or "",
                date=date,
                date_kind=kind,
                has_file=bool(item.get("hasFile", False)),
                monitored=bool(item.get("monitored", True)),
                overview=item.get("overview"),
                runtime_minutes=item.get("runtime"),
                poster=self._poster_path(item),
            )
        ]

    def _parse_library_item(self, item: dict[str, Any]) -> LibraryItem:
        has_file = bool(item.get("hasFile", False))
        return LibraryItem(
            **self._base_library_fields(item),
            studio=item.get("studio"),
            size_bytes=int(item.get("sizeOnDisk") or 0),
            # 0/1 or 1/1 — the same progress bar the series view uses.
            have_count=1 if has_file else 0,
            total_count=1,
        )

    def _search_command_payload(self, item_id: int) -> dict[str, Any]:
        # Note the plural: Radarr's command takes a list, Sonarr's takes a single id.
        return {"name": self.search_command, "movieIds": [item_id]}

    def native_url(self, item_id: int) -> str | None:
        return f"{self.url}/movie/{item_id}"
