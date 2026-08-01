"""Lidarr — music. API **v1**, like Prowlarr and Readarr.

Not installed on the reference stack, so this ships unit-tested against fixtures only.
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import ArrAdapter
from .schemas import CalendarEntry, DateKind, LibraryItem


class LidarrAdapter(ArrAdapter):
    service_type: ClassVar[str] = "lidarr"
    display_name: ClassVar[str] = "Lidarr"
    api_version: ClassVar[str] = "v1"
    default_port: ClassVar[int] = 8686
    app_name: ClassVar[str] = "lidarr"
    media_endpoint: ClassVar[str | None] = "artist"
    media_kind: ClassVar[str] = "artist"
    search_param: ClassVar[str] = "artistId"
    search_command: ClassVar[str] = "ArtistSearch"
    native_path: ClassVar[str] = "artist"
    unsupported: ClassVar[frozenset[str]] = frozenset({"seasons"})

    def _remote_id(self, item: dict[str, Any]) -> str | None:
        mbid = item.get("foreignArtistId")
        return str(mbid) if mbid else None

    def _parse_calendar_item(self, item: dict[str, Any]) -> list[CalendarEntry]:
        """Lidarr's calendar is album release dates."""
        date = self._parse_dt(item.get("releaseDate"))
        if date is None:
            return []
        artist = item.get("artist") or {}
        return [
            CalendarEntry(
                service_id=self.service_id,
                service_type=self.service_type,
                service_name=self.name,
                media_kind="album",
                item_id=item.get("artistId") or item.get("id", 0),
                title=item.get("title") or "",
                parent_title=artist.get("artistName"),
                date=date,
                date_kind=DateKind.RELEASE,
                monitored=bool(item.get("monitored", True)),
                overview=item.get("overview"),
                poster=self._poster_path(artist) if artist else None,
            )
        ]

    def _parse_library_item(self, item: dict[str, Any]) -> LibraryItem:
        stats = item.get("statistics") or {}
        fields = self._base_library_fields(item)
        # Lidarr names artists `artistName`, not `title`.
        fields["title"] = item.get("artistName") or fields["title"]
        fields["sort_title"] = item.get("sortName") or fields["sort_title"]
        return LibraryItem(
            **fields,
            size_bytes=int(stats.get("sizeOnDisk") or 0),
            have_count=int(stats.get("trackFileCount") or 0),
            total_count=int(stats.get("trackCount") or 0),
        )

    def _search_command_payload(self, item_id: int) -> dict[str, Any]:
        return {"name": self.search_command, "artistId": item_id}

    def native_url(self, item_id: int) -> str | None:
        return f"{self.url}/artist/{item_id}"
