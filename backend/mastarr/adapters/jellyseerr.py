"""Jellyseerr / Overseerr — media discovery and request front-end. API v1.

Not an *arr, but it speaks the same transport: `X-Api-Key`, `/api/v1`, JSON. So it
subclasses `ArrAdapter` purely to reuse `_request` and the `AdapterError` mapping, and
declares every *arr-specific endpoint unsupported. If this ever starts to strain, the fix
is to lift the transport into a shared base — not to bend Jellyseerr into an *arr shape.

Discovery is deliberately proxied rather than reimplemented: Jellyseerr already does TMDB
search, trending, recommendations and the whole request lifecycle, and duplicating that
would be a large amount of work with no benefit.

Overseerr and Jellyseerr share this API surface, so one adapter serves both.
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import ArrAdapter
from .errors import ServiceError
from .schemas import DiscoverPage, DiscoverResult, MediaRequest, SystemStatus

# Jellyseerr's mediaInfo.status vocabulary.
MEDIA_STATUS_AVAILABLE = 5
MEDIA_STATUS_PARTIALLY_AVAILABLE = 4
MEDIA_STATUS_PROCESSING = 3
MEDIA_STATUS_PENDING = 2

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"


class JellyseerrAdapter(ArrAdapter):
    service_type: ClassVar[str] = "jellyseerr"
    display_name: ClassVar[str] = "Jellyseerr"
    api_version: ClassVar[str] = "v1"
    default_port: ClassVar[int] = 5055
    # Overseerr/Jellyseerr are very often moved off 5055 when both run, or when
    # something else already holds the port.
    alternate_ports: ClassVar[tuple[int, ...]] = (5056, 5057)
    # Jellyseerr has no /ping — it 307-redirects. Its /api/v1/status is unauthenticated
    # and returns version info, which serves the same purpose.
    probe_path: ClassVar[str] = "api/v1/status"
    app_name: ClassVar[str] = "jellyseerr"
    media_endpoint: ClassVar[str | None] = None
    media_kind: ClassVar[str] = "request"
    native_path: ClassVar[str] = ""

    # Everything an *arr has and a request front-end doesn't. Verified against a live
    # Jellyseerr 3.3 — each of these 404s. Declaring them keeps aggregated views from
    # collecting a permanent "Jellyseerr failed" banner they'd learn to ignore.
    unsupported: ClassVar[frozenset[str]] = frozenset(
        {
            "disk_space",
            "queue",
            "history",
            "indexers",
            "download_clients",
            "quality_profiles",
            "root_folders",
            "seasons",
            "calendar",
            "library",
            "wanted_missing",
            "search_command",
            "custom_formats",
            "naming",
        }
    )

    @classmethod
    def matches_probe(cls, payload: Any) -> bool:
        """`/api/v1/status` returns `{version, commitTag, ...}` with no auth."""
        return isinstance(payload, dict) and "version" in payload and "commitTag" in payload

    # ------------------------------------------------------------------ identity

    async def system_status(self) -> SystemStatus:
        """Jellyseerr's /status has no `appName`, so the base implementation can't parse it."""
        data = await self._request("GET", "status")
        if not isinstance(data, dict):
            raise ServiceError("Unexpected status payload.", service=self.name)
        return SystemStatus(
            app_name=self.display_name,
            version=data.get("version") or "unknown",
            instance_name=self.name,
        )

    async def health(self) -> list:
        """No health endpoint. Reaching /status at all is the health signal."""
        return []

    # ------------------------------------------------------------------ discovery

    @staticmethod
    def _image_url(path: str | None, size: str = "w500") -> str | None:
        """TMDB CDN URL.

        Returned as an absolute URL so the browser fetches it directly — relaying poster
        images through Mastarr would waste bandwidth for no gain, unlike *arr covers which
        need the proxy.
        """
        if not path:
            return None
        return f"{TMDB_IMAGE_BASE}/{size}{path}"

    def _parse_result(self, item: dict[str, Any]) -> DiscoverResult | None:
        kind = item.get("mediaType")
        if kind not in ("movie", "tv"):
            return None  # `person` results are noise here
        info = item.get("mediaInfo") or {}
        status = info.get("status")
        date = item.get("releaseDate") or item.get("firstAirDate") or ""
        return DiscoverResult(
            tmdb_id=item.get("id", 0),
            media_kind=kind,
            title=item.get("title") or item.get("name") or "",
            year=int(date[:4]) if date[:4].isdigit() else None,
            overview=item.get("overview"),
            poster_url=self._image_url(item.get("posterPath")),
            backdrop_url=self._image_url(item.get("backdropPath"), "w780"),
            vote_average=item.get("voteAverage"),
            media_status=status,
            available=status == MEDIA_STATUS_AVAILABLE,
            already_requested=status in (MEDIA_STATUS_PENDING, MEDIA_STATUS_PROCESSING),
        )

    def _parse_page(self, data: Any) -> DiscoverPage:
        if not isinstance(data, dict):
            return DiscoverPage()
        results = [self._parse_result(r) for r in data.get("results", [])]
        return DiscoverPage(
            page=data.get("page", 1),
            total_pages=data.get("totalPages", 1),
            total_results=data.get("totalResults", 0),
            results=[r for r in results if r is not None],
        )

    async def discover_search(self, query: str, page: int = 1) -> DiscoverPage:
        return self._parse_page(
            await self._request("GET", "search", params={"query": query, "page": page})
        )

    async def discover(self, kind: str = "trending", page: int = 1) -> DiscoverPage:
        """Browse without a query. `kind` is trending | movies | tv."""
        allowed = {"trending": "discover/trending", "movies": "discover/movies", "tv": "discover/tv"}
        path = allowed.get(kind)
        if path is None:
            raise ServiceError(f"Unknown discover feed '{kind}'.", service=self.name)
        return self._parse_page(await self._request("GET", path, params={"page": page}))

    # ------------------------------------------------------------------ requests

    def _parse_request(self, item: dict[str, Any]) -> MediaRequest:
        media = item.get("media") or {}
        requester = item.get("requestedBy") or {}
        return MediaRequest(
            id=item.get("id", 0),
            media_kind=item.get("type") or "movie",
            status=item.get("status", 1),
            title=media.get("title") or media.get("name"),
            tmdb_id=media.get("tmdbId"),
            poster_url=self._image_url(media.get("posterPath")),
            requested_by=requester.get("displayName") or requester.get("email"),
            requested_by_id=requester.get("id"),
            created_at=self._parse_dt(item.get("createdAt")),
            media_status=media.get("status"),
        )

    async def requests(
        self, *, user_id: int | None = None, take: int = 50, skip: int = 0
    ) -> list[MediaRequest]:
        """Requests, optionally scoped to one Jellyseerr user.

        Scoping happens server-side so a Requester's own-requests view never has the other
        users' data in the response at all.
        """
        params: dict[str, Any] = {"take": take, "skip": skip, "sort": "added"}
        if user_id is not None:
            params["requestedBy"] = user_id
        data = await self._request("GET", "request", params=params)
        records = data.get("results", []) if isinstance(data, dict) else (data or [])
        return [self._parse_request(r) for r in records]

    async def create_request(
        self,
        *,
        tmdb_id: int,
        media_kind: str,
        user_id: int | None = None,
        seasons: list[int] | str | None = None,
    ) -> MediaRequest:
        """Submit a request, attributed to `user_id` when one is mapped."""
        payload: dict[str, Any] = {"mediaType": media_kind, "mediaId": tmdb_id}
        if user_id is not None:
            payload["userId"] = user_id
        if media_kind == "tv":
            # Jellyseerr requires seasons for TV; "all" is the sane default.
            payload["seasons"] = seasons if seasons is not None else "all"

        data = await self._request("POST", "request", json=payload)
        if not isinstance(data, dict):
            raise ServiceError("Unexpected request payload.", service=self.name)
        return self._parse_request(data)

    async def decide_request(self, request_id: int, approve: bool) -> MediaRequest:
        action = "approve" if approve else "decline"
        data = await self._request("POST", f"request/{request_id}/{action}")
        if not isinstance(data, dict):
            raise ServiceError("Unexpected request payload.", service=self.name)
        return self._parse_request(data)

    async def users(self) -> list[dict[str, Any]]:
        """Jellyseerr accounts, so an admin can map Mastarr users onto them."""
        data = await self._request("GET", "user", params={"take": 100})
        records = data.get("results", []) if isinstance(data, dict) else (data or [])
        return [
            {
                "id": u.get("id"),
                "display_name": u.get("displayName") or u.get("email"),
                "email": u.get("email"),
            }
            for u in records
        ]

    def native_url(self, item_id: int) -> str | None:
        return self.url
