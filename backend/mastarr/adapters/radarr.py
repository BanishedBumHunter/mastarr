"""Radarr — movies. API v3."""

from __future__ import annotations

from typing import Any, ClassVar

from .base import ArrAdapter


class RadarrAdapter(ArrAdapter):
    service_type: ClassVar[str] = "radarr"
    display_name: ClassVar[str] = "Radarr"
    api_version: ClassVar[str] = "v3"
    default_port: ClassVar[int] = 7878
    app_name: ClassVar[str] = "radarr"
    media_endpoint: ClassVar[str | None] = "movie"

    def _remote_id(self, item: dict[str, Any]) -> str | None:
        tmdb = item.get("tmdbId")
        return str(tmdb) if tmdb else None
