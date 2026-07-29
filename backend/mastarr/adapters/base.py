"""The shared *arr adapter.

Sonarr, Radarr, Lidarr, Readarr and Prowlarr descend from a common codebase, so their APIs
are near-identical in shape. This base class implements the whole common surface; the
subclasses exist to declare *which* dialect they speak and to override the handful of
endpoints where the payload genuinely differs.

Two things are parameterized rather than assumed:

* `api_version` — Sonarr/Radarr are on v3, Prowlarr/Lidarr/Readarr are on v1. Hardcoding
  v3 anywhere in a shared path would make every v1 service a special case.
* the media endpoint (`series` vs `movie` vs `artist`) — exposed as `media_endpoint` so
  lookups and title resolution stay generic.
"""

from __future__ import annotations

import logging
from abc import ABC
from datetime import datetime, timezone
from typing import Any, ClassVar

import httpx

from .errors import (
    AdapterError,
    ServiceError,
    ServiceUnauthorized,
    ServiceUnreachable,
    UnsupportedOperation,
)
from .schemas import (
    CalendarEntry,
    DiskSpace,
    DownloadClient,
    Episode,
    HealthIssue,
    HealthSeverity,
    HistoryItem,
    Indexer,
    LibraryItem,
    QualityProfile,
    QueueItem,
    RootFolder,
    Season,
    SearchResult,
    ServiceSnapshot,
    ServiceStatus,
    SystemStatus,
)

log = logging.getLogger(__name__)

# Health checks that report as `warning` but describe no operational problem.
#
# Sonarr and Radarr raise `UpdateCheck` at warning severity whenever a newer release
# exists — which is most of the time. Letting that drive DEGRADED would leave the
# dashboard permanently amber and make the status colour meaningless. The issue is still
# listed on the card; it just doesn't change the verdict.
INFORMATIONAL_HEALTH_SOURCES = frozenset({"UpdateCheck"})

# Config collections Mastarr can read and push. The key is the name used throughout the
# sync layer and the API; the value is the *arr endpoint. Kept in one place so a service
# type that spells an endpoint differently only has to override this mapping.
CONFIG_ENDPOINTS: dict[str, str] = {
    "quality_profile": "qualityprofile",
    "custom_format": "customformat",
    "root_folder": "rootfolder",
    "download_client": "downloadclient",
    "indexer": "indexer",
}

# The `unsupported` sets predate config sync and use the plural names of the normalized
# read methods (`quality_profiles`). Mapping here rather than renaming either side keeps
# one vocabulary per layer and means a type that declares `quality_profiles` unsupported
# automatically blocks the config-sync path too — no set can drift out of step with the
# other.
CONFIG_GUARD: dict[str, str] = {
    "quality_profile": "quality_profiles",
    "custom_format": "custom_formats",
    "root_folder": "root_folders",
    "download_client": "download_clients",
    "indexer": "indexers",
    "naming": "naming",
}


class ArrAdapter(ABC):
    """Common interface to one *arr service.

    Subclasses set the class vars below and override only where a payload differs. Adding a
    new *arr type should never require editing this file.
    """

    service_type: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    api_version: ClassVar[str] = "v3"
    default_port: ClassVar[int] = 0
    # Ports this type is commonly moved to. Scanned in addition to default_port.
    alternate_ports: ClassVar[tuple[int, ...]] = ()
    # Unauthenticated endpoint that proves something is listening. Every *arr serves
    # /ping; Jellyseerr does not, so this is per-type rather than assumed.
    probe_path: ClassVar[str] = "ping"
    # What `system/status` reports in `appName`, lowercased. Usually the service type,
    # but kept separate because they are not guaranteed to match.
    app_name: ClassVar[str] = ""
    # None for services that manage no media library of their own (Prowlarr).
    media_endpoint: ClassVar[str | None] = None
    # Endpoints this type does not implement, mapped to why. Checked before any request.
    unsupported: ClassVar[frozenset[str]] = frozenset()
    # What this type calls its items in the unified UI.
    media_kind: ClassVar[str] = "item"
    # Extra query params the calendar endpoint needs (Sonarr wants the series expanded).
    calendar_params: ClassVar[dict[str, str]] = {}
    # The *arr command that searches for one item, e.g. "MoviesSearch".
    search_command: ClassVar[str] = ""
    # Path fragment in the native UI, for deep links.
    native_path: ClassVar[str] = ""
    # External-id field and the lookup prefix that finds by it, for native adds.
    remote_id_field: ClassVar[str] = ""
    remote_id_prefix: ClassVar[str] = ""
    # What the service calls "search after adding" inside addOptions.
    search_on_add_field: ClassVar[str] = "searchForMissingEpisodes"

    def __init__(
        self,
        url: str,
        api_key: str | None = None,
        *,
        name: str | None = None,
        service_id: int | None = None,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.name = name or self.display_name or self.service_type
        self.service_id = service_id
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None

    # ------------------------------------------------------------------ plumbing

    @property
    def api_base(self) -> str:
        return f"{self.url}/api/{self.api_version}"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> ArrAdapter:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        absolute: bool = False,
    ) -> Any:
        """Single funnel for every HTTP call. Maps all transport failures to AdapterError.

        Note there is deliberately no "missing API key" short-circuit here. Refusing to
        send the request when no key is configured would report an unreachable host as
        `unauthorized`, telling the operator to fix a key when the box is actually down.
        Reachability is a property of the network, so we let the network decide it: an
        unauthenticated request to a live *arr returns 401 quickly and cheaply.
        """
        url = path if absolute else f"{self.api_base}/{path.lstrip('/')}"
        headers = {"Accept": "application/json"}
        if self.api_key:
            # Header, never a query param — query params end up in access logs on every
            # reverse proxy between here and the service.
            headers["X-Api-Key"] = self.api_key

        client = await self._get_client()
        try:
            response = await client.request(
                method, url, headers=headers, params=params, json=json
            )
        except httpx.TimeoutException as exc:
            raise ServiceUnreachable(
                f"Timed out after {self.timeout:g}s connecting to {self.url}",
                service=self.name,
            ) from exc
        except httpx.HTTPError as exc:
            # Covers connect errors, DNS, TLS, protocol errors. str(exc) can contain the
            # URL but never the key, since the key only ever travels as a header.
            raise ServiceUnreachable(
                f"Could not reach {self.url}: {type(exc).__name__}", service=self.name
            ) from exc

        if response.status_code in (401, 403):
            raise ServiceUnauthorized(
                "API key was rejected."
                if self.api_key
                else "No API key configured for this service.",
                service=self.name,
            )
        if response.status_code == 404:
            raise ServiceError(
                f"Endpoint not found: {path}. The service may be a different type or "
                f"an unsupported version.",
                service=self.name,
            )
        if response.status_code >= 400:
            raise ServiceError(
                f"{self.name} returned HTTP {response.status_code}", service=self.name
            )

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            # Classic symptom of a reverse proxy or login page answering instead of the
            # API — worth naming explicitly, it is a common misconfiguration.
            raise ServiceError(
                f"{self.name} returned a non-JSON response. Check that the URL points "
                f"at the service itself and not a proxy or login page.",
                service=self.name,
            ) from exc

    def _guard(self, operation: str) -> None:
        if operation in self.unsupported:
            raise UnsupportedOperation(
                f"{self.display_name} does not support {operation}.", service=self.name
            )

    @classmethod
    def matches_probe(cls, payload: Any) -> bool:
        """Does this unauthenticated probe response look like our kind of service?

        The *arrs answer `/ping` with `{"status":"OK"}`. Overridden where that isn't true.
        """
        return (
            isinstance(payload, dict)
            and str(payload.get("status", "")).lower() == "ok"
        )

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if not value or not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    # ------------------------------------------------------------------ interface

    async def ping(self) -> bool:
        """Unauthenticated liveness check.

        `/ping` is open on every *arr, which is what makes presence detection possible
        before an API key has been supplied.
        """
        try:
            result = await self._request("GET", f"{self.url}/ping", absolute=True)
        except AdapterError:
            return False
        if isinstance(result, dict):
            return str(result.get("status", "")).lower() == "ok"
        return result is not None

    async def system_status(self) -> SystemStatus:
        data = await self._request("GET", "system/status")
        if not isinstance(data, dict):
            raise ServiceError("Unexpected system/status payload.", service=self.name)
        return SystemStatus(
            app_name=data.get("appName") or self.display_name,
            version=data.get("version") or "unknown",
            instance_name=data.get("instanceName"),
            os_name=data.get("osName"),
            is_docker=data.get("isDocker"),
            start_time=self._parse_dt(data.get("startTime")),
        )

    async def health(self) -> list[HealthIssue]:
        data = await self._request("GET", "health")
        if not isinstance(data, list):
            return []
        issues: list[HealthIssue] = []
        for item in data:
            raw = str(item.get("type", "warning")).lower()
            severity = (
                HealthSeverity(raw)
                if raw in {s.value for s in HealthSeverity}
                else HealthSeverity.WARNING
            )
            issues.append(
                HealthIssue(
                    source=item.get("source") or "unknown",
                    severity=severity,
                    message=item.get("message") or "",
                    wiki_url=item.get("wikiUrl"),
                )
            )
        return issues

    async def disk_space(self) -> list[DiskSpace]:
        self._guard("disk_space")
        data = await self._request("GET", "diskspace")
        if not isinstance(data, list):
            return []
        return [
            DiskSpace(
                path=item.get("path") or "",
                label=item.get("label") or None,
                free_bytes=int(item.get("freeSpace") or 0),
                total_bytes=int(item.get("totalSpace") or 0),
            )
            for item in data
        ]

    async def queue(self, page_size: int = 100) -> list[QueueItem]:
        self._guard("queue")
        data = await self._request(
            "GET",
            "queue",
            params={"pageSize": page_size, "includeUnknownItems": "true"},
        )
        records = data.get("records", []) if isinstance(data, dict) else (data or [])
        return [self._parse_queue_item(item) for item in records]

    async def history(self, page_size: int = 50) -> list[HistoryItem]:
        self._guard("history")
        data = await self._request(
            "GET",
            "history",
            params={"pageSize": page_size, "sortKey": "date", "sortDirection": "descending"},
        )
        records = data.get("records", []) if isinstance(data, dict) else (data or [])
        return [self._parse_history_item(item) for item in records]

    async def quality_profiles(self) -> list[QualityProfile]:
        self._guard("quality_profiles")
        data = await self._request("GET", "qualityprofile")
        if not isinstance(data, list):
            return []
        return [
            QualityProfile(
                id=item.get("id", 0),
                name=item.get("name") or "",
                upgrade_allowed=bool(item.get("upgradeAllowed", False)),
                cutoff_name=self._cutoff_name(item),
            )
            for item in data
        ]

    async def root_folders(self) -> list[RootFolder]:
        self._guard("root_folders")
        data = await self._request("GET", "rootfolder")
        if not isinstance(data, list):
            return []
        return [
            RootFolder(
                id=item.get("id", 0),
                path=item.get("path") or "",
                accessible=bool(item.get("accessible", True)),
                free_space_bytes=item.get("freeSpace"),
            )
            for item in data
        ]

    async def download_clients(self) -> list[DownloadClient]:
        self._guard("download_clients")
        data = await self._request("GET", "downloadclient")
        if not isinstance(data, list):
            return []
        return [
            DownloadClient(
                id=item.get("id", 0),
                name=item.get("name") or "",
                implementation=item.get("implementation") or "",
                enabled=bool(item.get("enable", True)),
                protocol=item.get("protocol"),
                priority=item.get("priority"),
            )
            for item in data
        ]

    async def indexers(self) -> list[Indexer]:
        self._guard("indexers")
        data = await self._request("GET", "indexer")
        if not isinstance(data, list):
            return []
        return [
            Indexer(
                id=item.get("id", 0),
                name=item.get("name") or "",
                implementation=item.get("implementation") or "",
                enabled=bool(item.get("enable", item.get("enabled", True))),
                protocol=item.get("protocol"),
                priority=item.get("priority"),
            )
            for item in data
        ]

    async def search(self, term: str) -> list[SearchResult]:
        """Library lookup — what could be added, not what releases exist."""
        self._guard("search")
        if self.media_endpoint is None:
            raise UnsupportedOperation(
                f"{self.display_name} manages no media library.", service=self.name
            )
        data = await self._request(
            "GET", f"{self.media_endpoint}/lookup", params={"term": term}
        )
        if not isinstance(data, list):
            return []
        return [self._parse_search_result(item) for item in data]

    # --------------------------------------------------------- unified views

    async def calendar(self, start: datetime, end: datetime) -> list[CalendarEntry]:
        """Dated items in a window, normalized onto one timeline."""
        self._guard("calendar")
        data = await self._request(
            "GET",
            "calendar",
            params={
                "start": start.date().isoformat(),
                "end": end.date().isoformat(),
                **self.calendar_params,
            },
        )
        if not isinstance(data, list):
            return []
        entries: list[CalendarEntry] = []
        for item in data:
            entries.extend(self._parse_calendar_item(item))
        return entries

    async def library(self) -> list[LibraryItem]:
        """The whole library.

        Deliberately unpaged: the *arrs return everything in one call and real libraries
        here are hundreds of items, not millions. Paging would add complexity and make
        client-side search worse.
        """
        self._guard("library")
        if self.media_endpoint is None:
            raise UnsupportedOperation(
                f"{self.display_name} manages no media library.", service=self.name
            )
        data = await self._request("GET", self.media_endpoint)
        if not isinstance(data, list):
            return []
        return [self._parse_library_item(item) for item in data]

    async def library_item(self, item_id: int) -> LibraryItem:
        self._guard("library")
        if self.media_endpoint is None:
            raise UnsupportedOperation(
                f"{self.display_name} manages no media library.", service=self.name
            )
        data = await self._request("GET", f"{self.media_endpoint}/{item_id}")
        if not isinstance(data, dict):
            raise ServiceError("Unexpected library payload.", service=self.name)
        return self._parse_library_item(data)

    async def seasons(self, item_id: int) -> list[Season]:
        """Season/episode breakdown. Only meaningful for episodic services."""
        self._guard("seasons")
        return []

    async def wanted_missing(self, page_size: int = 50) -> list[LibraryItem]:
        self._guard("wanted_missing")
        data = await self._request(
            "GET", "wanted/missing", params={"pageSize": page_size}
        )
        records = data.get("records", []) if isinstance(data, dict) else (data or [])
        return [self._parse_library_item(item) for item in records]

    # ------------------------------------------------------- write operations

    async def set_monitored(self, item_id: int, monitored: bool) -> LibraryItem:
        """Toggle monitoring.

        The *arrs have no PATCH for this — you GET the whole record, change the field and
        PUT it back. Round-tripping the untouched payload is what keeps us from silently
        clobbering fields we don't model.
        """
        self._guard("library")
        if self.media_endpoint is None:
            raise UnsupportedOperation(
                f"{self.display_name} manages no media library.", service=self.name
            )
        record = await self._request("GET", f"{self.media_endpoint}/{item_id}")
        if not isinstance(record, dict):
            raise ServiceError("Unexpected library payload.", service=self.name)
        record["monitored"] = monitored
        updated = await self._request(
            "PUT", f"{self.media_endpoint}/{item_id}", json=record
        )
        return self._parse_library_item(updated if isinstance(updated, dict) else record)

    async def set_season_monitored(
        self, item_id: int, season_number: int, monitored: bool
    ) -> LibraryItem:
        self._guard("seasons")
        raise UnsupportedOperation(
            f"{self.display_name} has no seasons.", service=self.name
        )

    async def trigger_search(self, item_id: int) -> str:
        """Ask the service to go looking for this item now."""
        self._guard("search_command")
        payload = self._search_command_payload(item_id)
        result = await self._request("POST", "command", json=payload)
        if isinstance(result, dict):
            return str(result.get("status") or "queued")
        return "queued"

    async def delete_item(self, item_id: int, delete_files: bool = False) -> None:
        self._guard("library")
        if self.media_endpoint is None:
            raise UnsupportedOperation(
                f"{self.display_name} manages no media library.", service=self.name
            )
        await self._request(
            "DELETE",
            f"{self.media_endpoint}/{item_id}",
            params={
                "deleteFiles": str(delete_files).lower(),
                "addImportListExclusion": "false",
            },
        )

    # ------------------------------------------------- configuration writes

    async def raw_config(self, resource: str) -> list[dict[str, Any]]:
        """Untouched records for a config collection.

        Config sync deliberately works on the *raw* payload rather than the normalized
        schemas: copying a quality profile means reproducing every field the service
        knows about, including ones Mastarr doesn't model. Normalizing and re-expanding
        would quietly drop them.
        """
        self._guard(CONFIG_GUARD[resource])
        data = await self._request("GET", CONFIG_ENDPOINTS[resource])
        return data if isinstance(data, list) else []

    async def create_config(self, resource: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._guard(CONFIG_GUARD[resource])
        body = {k: v for k, v in payload.items() if k != "id"}
        result = await self._request("POST", CONFIG_ENDPOINTS[resource], json=body)
        return result if isinstance(result, dict) else {}

    async def update_config(
        self, resource: str, item_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._guard(CONFIG_GUARD[resource])
        body = {**payload, "id": item_id}
        result = await self._request(
            "PUT", f"{CONFIG_ENDPOINTS[resource]}/{item_id}", json=body
        )
        return result if isinstance(result, dict) else {}

    async def delete_config(self, resource: str, item_id: int) -> None:
        self._guard(CONFIG_GUARD[resource])
        await self._request("DELETE", f"{CONFIG_ENDPOINTS[resource]}/{item_id}")

    async def get_naming(self) -> dict[str, Any]:
        self._guard("naming")
        data = await self._request("GET", "config/naming")
        return data if isinstance(data, dict) else {}

    async def update_naming(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Naming is a singleton record, so it is always a PUT against its own id."""
        self._guard("naming")
        current = await self.get_naming()
        merged = {**current, **payload}
        result = await self._request(
            "PUT", f"config/naming/{current.get('id', 1)}", json=merged
        )
        return result if isinstance(result, dict) else merged

    async def image_bytes(self, path: str) -> tuple[bytes, str]:
        """Fetch a poster/banner for the image proxy. Returns (body, content-type)."""
        client = await self._get_client()
        headers = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        url = f"{self.url}/{path.lstrip('/')}"
        try:
            response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise ServiceUnreachable(
                f"Could not fetch image from {self.url}", service=self.name
            ) from exc
        if response.status_code >= 400:
            raise ServiceError(
                f"Image request returned HTTP {response.status_code}", service=self.name
            )
        return response.content, response.headers.get("content-type", "image/jpeg")

    async def add_item(
        self,
        *,
        remote_id: str,
        quality_profile_id: int,
        root_folder_path: str,
        monitored: bool = True,
        search_on_add: bool = True,
    ) -> dict[str, Any]:
        """Add a new item to the library from a lookup result.

        The native request path, used only when no Jellyseerr/Overseerr is connected.
        Looks the item up first so the payload carries whatever metadata the service
        expects, rather than us trying to synthesise a record it will reject.
        """
        self._guard("library")
        if self.media_endpoint is None or not self.remote_id_field:
            raise UnsupportedOperation(
                f"{self.display_name} cannot add items this way.", service=self.name
            )

        results = await self._request(
            "GET",
            f"{self.media_endpoint}/lookup",
            params={"term": f"{self.remote_id_prefix}{remote_id}"},
        )
        if not isinstance(results, list) or not results:
            raise ServiceError(
                f"Nothing found for {self.remote_id_field} {remote_id}.", service=self.name
            )

        record = dict(results[0])
        record.update(
            {
                "qualityProfileId": quality_profile_id,
                "rootFolderPath": root_folder_path,
                "monitored": monitored,
                "addOptions": {self.search_on_add_field: search_on_add},
            }
        )
        created = await self._request("POST", self.media_endpoint, json=record)
        return created if isinstance(created, dict) else record

    def native_url(self, item_id: int) -> str | None:
        """Deep link into the service's own UI, for what Mastarr doesn't reimplement."""
        return self.url

    async def snapshot(self) -> ServiceSnapshot:
        """One total, never-raising view of this service for the dashboard.

        Any AdapterError becomes a snapshot carrying that status. This is the method the
        dashboard fan-out calls, and the reason a dead service degrades rather than
        breaking the page.
        """
        base = ServiceSnapshot(
            service_id=self.service_id,
            name=self.name,
            service_type=self.service_type,
            url=self.url,
            status=ServiceStatus.UNKNOWN,
            checked_at=datetime.now(timezone.utc),
        )
        try:
            status = await self.system_status()
        except AdapterError as exc:
            base.status = _STATUS_MAP.get(exc.status, ServiceStatus.UNKNOWN)
            base.error = exc.message
            return base

        base.version = status.version
        base.app_name = status.app_name
        base.status = ServiceStatus.ONLINE

        # Health and disk are best-effort: a service that answers system/status but errors
        # on /health is still meaningfully online, and should render as such.
        try:
            base.health_issues = await self.health()
        except AdapterError as exc:
            log.debug("health check failed for %s: %s", self.name, exc.message)
        if any(
            issue.severity in (HealthSeverity.WARNING, HealthSeverity.ERROR)
            and issue.source not in INFORMATIONAL_HEALTH_SOURCES
            for issue in base.health_issues
        ):
            base.status = ServiceStatus.DEGRADED

        try:
            base.disk_space = await self.disk_space()
        except AdapterError as exc:
            log.debug("disk space failed for %s: %s", self.name, exc.message)

        try:
            base.queue_count = len(await self.queue(page_size=1000))
        except AdapterError as exc:
            log.debug("queue failed for %s: %s", self.name, exc.message)

        return base

    # ------------------------------------------------- per-type parsing overrides

    def _cutoff_name(self, profile: dict[str, Any]) -> str | None:
        cutoff = profile.get("cutoff")
        for item in profile.get("items", []) or []:
            quality = item.get("quality") or {}
            if quality.get("id") == cutoff:
                return quality.get("name")
            if item.get("id") == cutoff and item.get("name"):
                return item.get("name")
        return None

    def _media_title(self, item: dict[str, Any]) -> str | None:
        """Where the human-readable library title lives. Differs per service type."""
        if self.media_endpoint and isinstance(item.get(self.media_endpoint), dict):
            return item[self.media_endpoint].get("title")
        return None

    def _parse_queue_item(self, item: dict[str, Any]) -> QueueItem:
        quality = (item.get("quality") or {}).get("quality") or {}
        messages = item.get("statusMessages") or []
        error = item.get("errorMessage") or None
        if not error and messages:
            first = messages[0].get("messages") or []
            error = first[0] if first else None
        return QueueItem(
            id=item.get("id", 0),
            title=item.get("title") or "",
            status=item.get("status") or "unknown",
            media_title=self._media_title(item),
            quality=quality.get("name"),
            size_bytes=int(item.get("size") or 0),
            size_left_bytes=int(item.get("sizeleft") or 0),
            download_client=item.get("downloadClient"),
            indexer=item.get("indexer"),
            error_message=error,
            estimated_completion=self._parse_dt(item.get("estimatedCompletionTime")),
        )

    def _parse_history_item(self, item: dict[str, Any]) -> HistoryItem:
        quality = (item.get("quality") or {}).get("quality") or {}
        return HistoryItem(
            id=item.get("id", 0),
            event_type=item.get("eventType") or "unknown",
            title=item.get("sourceTitle") or "",
            media_title=self._media_title(item),
            quality=quality.get("name"),
            date=self._parse_dt(item.get("date")),
            source_title=item.get("sourceTitle"),
        )

    def _parse_search_result(self, item: dict[str, Any]) -> SearchResult:
        images = item.get("images") or []
        poster = next(
            (
                img.get("remoteUrl") or img.get("url")
                for img in images
                if img.get("coverType") == "poster"
            ),
            None,
        )
        return SearchResult(
            title=item.get("title") or "",
            year=item.get("year"),
            overview=item.get("overview"),
            poster_url=poster,
            remote_id=self._remote_id(item),
            already_added=bool(item.get("id")),
        )

    def _remote_id(self, item: dict[str, Any]) -> str | None:
        """The external database id this service keys on — tvdbId, tmdbId, and so on."""
        return None

    # ------------------------------------------- unified-view parsing overrides

    def _poster_path(self, item: dict[str, Any]) -> str | None:
        """Service-relative poster path, for the image proxy.

        Prefers the local `/MediaCover/...` URL over `remoteUrl`: it is already cached by
        the service, so it loads fast and keeps working if TMDB is unreachable.
        """
        for image in item.get("images", []) or []:
            if image.get("coverType") != "poster":
                continue
            local = image.get("url")
            if local:
                return str(local).lstrip("/")
            remote = image.get("remoteUrl")
            if remote:
                return str(remote)
        return None

    def _parse_calendar_item(self, item: dict[str, Any]) -> list[CalendarEntry]:
        """One raw calendar record -> zero or more normalized entries.

        Returns a list because a Radarr movie can legitimately produce several dated
        events (cinema, digital, physical) from a single record.
        """
        return []

    def _parse_library_item(self, item: dict[str, Any]) -> LibraryItem:
        raise NotImplementedError(
            f"{type(self).__name__} must implement _parse_library_item"
        )

    def _search_command_payload(self, item_id: int) -> dict[str, Any]:
        raise UnsupportedOperation(
            f"{self.display_name} has no search command.", service=self.name
        )

    def _base_library_fields(self, item: dict[str, Any]) -> dict[str, Any]:
        """Fields every *arr library record shares, so subclasses only add differences."""
        return {
            "service_id": self.service_id,
            "service_type": self.service_type,
            "service_name": self.name,
            "media_kind": self.media_kind,
            "item_id": item.get("id", 0),
            "title": item.get("title") or "",
            "sort_title": item.get("sortTitle"),
            "year": item.get("year") or None,
            "overview": item.get("overview"),
            "poster": self._poster_path(item),
            "status": item.get("status"),
            "monitored": bool(item.get("monitored", True)),
            "path": item.get("path"),
            "quality_profile_id": item.get("qualityProfileId"),
            "added": self._parse_dt(item.get("added")),
            "genres": item.get("genres") or [],
            "runtime_minutes": item.get("runtime"),
            "remote_id": self._remote_id(item),
        }


_STATUS_MAP = {
    "unreachable": ServiceStatus.UNREACHABLE,
    "unauthorized": ServiceStatus.UNAUTHORIZED,
    "error": ServiceStatus.DEGRADED,
    "unsupported": ServiceStatus.DEGRADED,
    "unknown": ServiceStatus.UNKNOWN,
}
