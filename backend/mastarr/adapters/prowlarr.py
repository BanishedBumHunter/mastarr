"""Prowlarr — indexer manager. API **v1**, not v3.

Prowlarr is the reason `api_version` is a class attribute rather than a constant: it shares
the *arr codebase and endpoint shapes but never moved to v3. Lidarr and Readarr are the
same, so this adapter is the template for both.

Prowlarr manages no media library — no root folders, no quality profiles, no download
queue, no disk space. Those are declared unsupported rather than left to 404, so the UI can
hide them instead of rendering an error.

Indexer *management* (the reflect-out flow where Prowlarr is the source of truth) is build
priority 5. Reading the indexer list works today via the inherited implementation.
"""

from __future__ import annotations

from typing import ClassVar

from .base import ArrAdapter


class ProwlarrAdapter(ArrAdapter):
    service_type: ClassVar[str] = "prowlarr"
    display_name: ClassVar[str] = "Prowlarr"
    api_version: ClassVar[str] = "v1"
    default_port: ClassVar[int] = 9696
    app_name: ClassVar[str] = "prowlarr"
    media_endpoint: ClassVar[str | None] = None

    # Verified against a live Prowlarr 2.5: every one of these 404s. Declaring them
    # up front matters — otherwise each aggregated view (calendar, library, wanted)
    # collects a "Prowlarr failed" warning on every page load, and a warning that is
    # always present is a warning people learn to ignore.
    unsupported: ClassVar[frozenset[str]] = frozenset(
        {
            "disk_space",
            "queue",
            "quality_profiles",
            "root_folders",
            "search",
            "calendar",
            "library",
            "wanted_missing",
            "seasons",
            "search_command",
        }
    )
