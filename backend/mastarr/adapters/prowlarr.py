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

from typing import Any, ClassVar

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
            "custom_formats",
            "naming",
            # Verified by probing a live Prowlarr 2.5 — each of these 404s.
            "import_lists",
            "metadata",
            "delay_profiles",
            "release_profiles",
            "quality_definitions",
            "media_management",
            "indexer_options",
            "interactive_search",
            "manual_import",
            "blocklist",
        }
    )

    async def applications(self) -> list[dict[str, Any]]:
        """The *arr apps Prowlarr pushes indexers to.

        This is what makes Prowlarr the source of truth: indexers are configured here
        once and Prowlarr syncs them outward. Mastarr shows the reach rather than writing
        indexers into each *arr itself, which would fight Prowlarr's own sync.
        """
        data = await self._request("GET", "applications")
        if not isinstance(data, list):
            return []
        return [
            {
                "id": a.get("id"),
                "name": a.get("name"),
                "implementation": a.get("implementation"),
                "sync_level": a.get("syncLevel"),
                "tags": a.get("tags") or [],
            }
            for a in data
        ]

    async def indexer_stats(self) -> dict[int, dict[str, Any]]:
        """Per-indexer query/grab counts, keyed by indexer id."""
        data = await self._request("GET", "indexerstats")
        if not isinstance(data, dict):
            return {}
        return {
            row.get("indexerId"): {
                "queries": row.get("numberOfQueries", 0),
                "grabs": row.get("numberOfGrabs", 0),
                "failures": row.get("numberOfFailedQueries", 0),
            }
            for row in data.get("indexers", [])
            if row.get("indexerId") is not None
        }

    async def test_indexer(self, indexer_id: int) -> bool:
        """Ask Prowlarr to test an indexer. Returns False rather than raising on failure."""
        from .errors import AdapterError

        try:
            records = await self._request("GET", f"indexer/{indexer_id}")
            await self._request("POST", "indexer/test", json=records)
            return True
        except AdapterError:
            return False
