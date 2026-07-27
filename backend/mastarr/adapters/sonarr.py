"""Sonarr — TV series. API v3."""

from __future__ import annotations

from typing import Any, ClassVar

from .base import ArrAdapter
from .schemas import HistoryItem, QueueItem


class SonarrAdapter(ArrAdapter):
    service_type: ClassVar[str] = "sonarr"
    display_name: ClassVar[str] = "Sonarr"
    api_version: ClassVar[str] = "v3"
    default_port: ClassVar[int] = 8989
    app_name: ClassVar[str] = "sonarr"
    media_endpoint: ClassVar[str | None] = "series"

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
