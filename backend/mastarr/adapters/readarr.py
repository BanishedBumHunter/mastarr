"""Readarr — books. API **v1**, like Prowlarr and Lidarr.

Not installed on the reference stack, so this ships unit-tested against fixtures only.
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import ArrAdapter
from .schemas import CalendarEntry, DateKind, LibraryItem


class ReadarrAdapter(ArrAdapter):
    service_type: ClassVar[str] = "readarr"
    display_name: ClassVar[str] = "Readarr"
    api_version: ClassVar[str] = "v1"
    default_port: ClassVar[int] = 8787
    app_name: ClassVar[str] = "readarr"
    media_endpoint: ClassVar[str | None] = "author"
    media_kind: ClassVar[str] = "author"
    search_param: ClassVar[str] = "authorId"
    search_command: ClassVar[str] = "AuthorSearch"
    native_path: ClassVar[str] = "author"
    unsupported: ClassVar[frozenset[str]] = frozenset({"seasons"})

    def _remote_id(self, item: dict[str, Any]) -> str | None:
        gr = item.get("foreignAuthorId")
        return str(gr) if gr else None

    def _parse_calendar_item(self, item: dict[str, Any]) -> list[CalendarEntry]:
        date = self._parse_dt(item.get("releaseDate"))
        if date is None:
            return []
        author = item.get("author") or {}
        return [
            CalendarEntry(
                service_id=self.service_id,
                service_type=self.service_type,
                service_name=self.name,
                media_kind="book",
                item_id=item.get("authorId") or item.get("id", 0),
                title=item.get("title") or "",
                parent_title=author.get("authorName"),
                date=date,
                date_kind=DateKind.RELEASE,
                monitored=bool(item.get("monitored", True)),
                overview=item.get("overview"),
                poster=self._poster_path(author) if author else None,
            )
        ]

    def _parse_library_item(self, item: dict[str, Any]) -> LibraryItem:
        stats = item.get("statistics") or {}
        fields = self._base_library_fields(item)
        fields["title"] = item.get("authorName") or fields["title"]
        fields["sort_title"] = item.get("sortName") or fields["sort_title"]
        return LibraryItem(
            **fields,
            size_bytes=int(stats.get("sizeOnDisk") or 0),
            have_count=int(stats.get("bookFileCount") or 0),
            total_count=int(stats.get("bookCount") or 0),
        )

    def _search_command_payload(self, item_id: int) -> dict[str, Any]:
        return {"name": self.search_command, "authorId": item_id}

    def native_url(self, item_id: int) -> str | None:
        return f"{self.url}/author/{item_id}"
