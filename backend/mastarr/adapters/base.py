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
    BackupInfo,
    BlocklistItem,
    CalendarEntry,
    DiskSpace,
    DownloadClient,
    Episode,
    HealthIssue,
    HealthSeverity,
    HistoryItem,
    ImportCandidate,
    Indexer,
    LibraryItem,
    LogFile,
    LogPage,
    LogRecord,
    Release,
    ScheduledTask,
    UpdateInfo,
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
    "remote_path_mapping": "remote_path_mappings",
    "import_list_exclusion": "import_list_exclusions",
    "download_client_options": "download_client_options",
    "host": "host",
    "ui": "ui",
    "import_list": "import_lists",
    "notification": "notifications",
    "metadata": "metadata",
    "delay_profile": "delay_profiles",
    "release_profile": "release_profiles",
    "quality_definition": "quality_definitions",
    "tag": "tags",
}

# Resources that are *provider* types: the service offers a `/schema` listing every
# implementation it supports, with full field definitions. One generic form renderer
# handles all of them, so a provider added by an upstream release appears in Mastarr with
# no code change.
PROVIDER_ENDPOINTS: dict[str, str] = {
    "download_client": "downloadclient",
    "indexer": "indexer",
    "import_list": "importlist",
    "notification": "notification",
    "metadata": "metadata",
}

# Non-provider config collections: plain lists with a fixed shape, no /schema.
CONFIG_ENDPOINTS_EXTRA: dict[str, str] = {
    "delay_profile": "delayprofile",
    "release_profile": "releaseprofile",
    "quality_definition": "qualitydefinition",
    "tag": "tag",
    "remote_path_mapping": "remotepathmapping",
    "import_list_exclusion": "importlistexclusion",
}

# Flat singleton settings objects, fetched and PUT whole.
SINGLETON_CONFIGS: dict[str, str] = {
    "naming": "config/naming",
    "media_management": "config/mediamanagement",
    "indexer_options": "config/indexer",
    "download_client_options": "config/downloadclient",
    "host": "config/host",
    "ui": "config/ui",
}

# Field `privacy` values that mark a secret. These are masked on the way out and must
# never be returned to the browser or written to a log.
SECRET_PRIVACY = frozenset({"apiKey", "password", "userName"})
SECRET_PLACEHOLDER = "********"


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
    # True for types that authenticate with a username and password instead of a static
    # API key. Lives here so the service form can ask for the right fields without the
    # frontend knowing which types those are.
    requires_username: ClassVar[bool] = False
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
        headers = {"Accept": "application/json", **await self._auth_headers()}

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

    async def _auth_headers(self) -> dict[str, str]:
        """Credentials for one request.

        Every *arr and Jellyseerr take a static API key in a header — never a query
        param, since those land in the access log of every reverse proxy between here and
        the service. Overridden by types that authenticate differently: SuggestArr trades
        a username and password for a short-lived bearer token.
        """
        if not self.api_key:
            return {}
        return {"X-Api-Key": self.api_key}

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

    async def update_item(
        self,
        item_id: int,
        *,
        quality_profile_id: int | None = None,
        root_folder_path: str | None = None,
        monitored: bool | None = None,
    ) -> LibraryItem:
        """Change an existing item's profile, root folder or monitoring.

        Round-trips the whole record like `set_monitored`, so fields Mastarr doesn't model
        survive. Note that changing the root folder only updates where the service *thinks*
        the item lives — the service moves files on its own schedule, if configured to.
        """
        self._guard("library")
        if self.media_endpoint is None:
            raise UnsupportedOperation(
                f"{self.display_name} manages no media library.", service=self.name
            )
        record = await self._request("GET", f"{self.media_endpoint}/{item_id}")
        if not isinstance(record, dict):
            raise ServiceError("Unexpected library payload.", service=self.name)

        if quality_profile_id is not None:
            record["qualityProfileId"] = quality_profile_id
        if monitored is not None:
            record["monitored"] = monitored
        if root_folder_path is not None:
            record["rootFolderPath"] = root_folder_path
            # `path` is the authoritative location; leaving it stale would point the
            # service at the old folder regardless of rootFolderPath.
            folder = (record.get("path") or "").rstrip("/").rsplit("/", 1)[-1]
            if folder:
                record["path"] = f"{root_folder_path.rstrip('/')}/{folder}"
            record["moveFiles"] = True

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

    # ------------------------------------------------- provider configuration

    # Per-type endpoint overrides, for the cases where the *arrs disagree with each other.
    # Radarr 6.4 serves import-list exclusions at `exclusions`; Sonarr uses
    # `importlistexclusion`. Same feature, different name.
    config_endpoint_overrides: ClassVar[dict[str, str]] = {}

    def _config_path(self, resource: str) -> str:
        """Endpoint for a config resource, whichever family it belongs to."""
        if resource in self.config_endpoint_overrides:
            return self.config_endpoint_overrides[resource]
        for table in (CONFIG_ENDPOINTS, PROVIDER_ENDPOINTS, CONFIG_ENDPOINTS_EXTRA):
            if resource in table:
                return table[resource]
        raise UnsupportedOperation(
            f"Unknown config resource '{resource}'.", service=self.name
        )

    @staticmethod
    def mask_secrets(record: dict[str, Any]) -> dict[str, Any]:
        """Replace secret field values with a placeholder.

        Applied to everything leaving the adapter for the UI. The *arrs happily return
        stored passwords and API keys in plaintext; forwarding those to a browser would
        undo the care taken with Mastarr's own credential handling.
        """
        masked = dict(record)
        fields = []
        for field in record.get("fields", []) or []:
            field = dict(field)
            if field.get("privacy") in SECRET_PRIVACY and field.get("value") not in (
                None,
                "",
            ):
                field["value"] = SECRET_PLACEHOLDER
            fields.append(field)
        if fields:
            masked["fields"] = fields
        return masked

    @staticmethod
    def restore_secrets(
        submitted: dict[str, Any], existing: dict[str, Any]
    ) -> dict[str, Any]:
        """Put back any secret the UI sent us as the placeholder.

        The browser never receives real secrets, so on edit it echoes the placeholder.
        Writing that through would replace a working password with literal asterisks.
        """
        current = {f.get("name"): f.get("value") for f in existing.get("fields", []) or []}
        merged = dict(submitted)
        fields = []
        for field in submitted.get("fields", []) or []:
            field = dict(field)
            if (
                field.get("privacy") in SECRET_PRIVACY
                and field.get("value") == SECRET_PLACEHOLDER
            ):
                field["value"] = current.get(field.get("name"))
            fields.append(field)
        if fields:
            merged["fields"] = fields
        return merged

    async def quality_profile_schema(self) -> dict[str, Any]:
        """A blank profile template.

        Returns all 26 quality entries in the service's canonical order, with the standard
        groups already formed — which is the only sane way to create a profile, since the
        quality ids and their ordering are the service's own vocabulary.
        """
        self._guard("quality_profiles")
        data = await self._request("GET", "qualityprofile/schema")
        return data if isinstance(data, dict) else {}

    async def provider_schema(self, resource: str) -> list[dict[str, Any]]:
        """Every implementation this service supports, with its field definitions."""
        self._guard(CONFIG_GUARD.get(resource, resource))
        if resource not in PROVIDER_ENDPOINTS:
            raise UnsupportedOperation(
                f"{resource} is not a provider type.", service=self.name
            )
        data = await self._request("GET", f"{PROVIDER_ENDPOINTS[resource]}/schema")
        return data if isinstance(data, list) else []

    async def list_config(self, resource: str) -> list[dict[str, Any]]:
        """Configured instances, with secrets masked."""
        self._guard(CONFIG_GUARD.get(resource, resource))
        data = await self._request("GET", self._config_path(resource))
        return [self.mask_secrets(r) for r in data] if isinstance(data, list) else []

    async def create_provider(
        self, resource: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._guard(CONFIG_GUARD.get(resource, resource))
        body = {k: v for k, v in payload.items() if k != "id"}
        result = await self._request("POST", self._config_path(resource), json=body)
        return self.mask_secrets(result) if isinstance(result, dict) else {}

    async def update_provider(
        self, resource: str, item_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        path = self._config_path(resource)
        self._guard(CONFIG_GUARD.get(resource, resource))
        existing = await self._request("GET", f"{path}/{item_id}")
        body = self.restore_secrets(payload, existing if isinstance(existing, dict) else {})
        body["id"] = item_id
        result = await self._request("PUT", f"{path}/{item_id}", json=body)
        return self.mask_secrets(result) if isinstance(result, dict) else {}

    async def delete_provider(self, resource: str, item_id: int) -> None:
        self._guard(CONFIG_GUARD.get(resource, resource))
        await self._request("DELETE", f"{self._config_path(resource)}/{item_id}")

    async def test_provider(self, resource: str, payload: dict[str, Any]) -> tuple[bool, str]:
        """Ask the service to validate a provider config before saving it.

        Returns (ok, message) rather than raising: a failed connection test is an expected
        outcome the form should render, not an error condition.
        """
        self._guard(CONFIG_GUARD.get(resource, resource))
        path = self._config_path(resource)
        body = dict(payload)
        if body.get("id"):
            existing = await self._request("GET", f"{path}/{body['id']}")
            body = self.restore_secrets(body, existing if isinstance(existing, dict) else {})
        try:
            await self._request("POST", f"{path}/test", json=body)
            return True, "Connection succeeded."
        except ServiceError as exc:
            return False, exc.message
        except AdapterError as exc:
            return False, exc.message

    # --------------------------------------------------- singleton settings

    async def get_singleton(self, name: str) -> dict[str, Any]:
        """One of the flat config objects (naming, media management, indexer options)."""
        self._guard(CONFIG_GUARD.get(name, name))
        if name not in SINGLETON_CONFIGS:
            raise UnsupportedOperation(f"Unknown setting group '{name}'.", service=self.name)
        data = await self._request("GET", SINGLETON_CONFIGS[name])
        return data if isinstance(data, dict) else {}

    async def update_singleton(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Merge changes into a singleton and PUT it back.

        Merged rather than replaced so fields Mastarr doesn't render survive the write.
        """
        current = await self.get_singleton(name)
        merged = {**current, **payload}
        path = SINGLETON_CONFIGS[name]
        result = await self._request(
            "PUT", f"{path}/{current.get('id', 1)}", json=merged
        )
        return result if isinstance(result, dict) else merged

    # ------------------------------------------------------- manual control

    # Query param the interactive-search endpoint expects, per media kind.
    search_param: ClassVar[str] = ""

    async def releases(
        self, *, item_id: int | None = None, episode_id: int | None = None
    ) -> list[Release]:
        """Interactive search: what's actually out there, and why it was or wasn't taken.

        Slow by nature — it queries every indexer synchronously — so callers should expect
        tens of seconds, not the usual sub-second adapter call.
        """
        self._guard("interactive_search")
        if episode_id is not None:
            params: dict[str, Any] = {"episodeId": episode_id}
        elif item_id is not None and self.search_param:
            params = {self.search_param: item_id}
        else:
            raise UnsupportedOperation(
                f"{self.display_name} cannot search interactively.", service=self.name
            )

        data = await self._request("GET", "release", params=params)
        if not isinstance(data, list):
            return []
        return [self._parse_release(r) for r in data]

    def _parse_release(self, item: dict[str, Any]) -> Release:
        quality = (item.get("quality") or {}).get("quality") or {}
        return Release(
            guid=item.get("guid") or "",
            title=item.get("title") or "",
            indexer=item.get("indexer"),
            indexer_id=item.get("indexerId"),
            protocol=item.get("protocol"),
            quality=quality.get("name"),
            size_bytes=int(item.get("size") or 0),
            seeders=item.get("seeders"),
            leechers=item.get("leechers"),
            age_hours=item.get("ageHours"),
            published=self._parse_dt(item.get("publishDate")),
            rejected=bool(item.get("rejected", False)),
            rejections=[str(r) for r in (item.get("rejections") or [])],
            download_allowed=bool(item.get("downloadAllowed", True)),
            custom_format_score=item.get("customFormatScore"),
        )

    async def grab_release(self, guid: str, indexer_id: int) -> None:
        """Take a specific release, overriding whatever the service would have chosen."""
        self._guard("interactive_search")
        await self._request(
            "POST", "release", json={"guid": guid, "indexerId": indexer_id}
        )

    async def import_candidates(self, folder: str) -> list[ImportCandidate]:
        """Files in a folder the service could import, with its own verdict on each."""
        self._guard("manual_import")
        data = await self._request("GET", "manualimport", params={"folder": folder})
        if not isinstance(data, list):
            return []
        return [self._parse_import_candidate(i) for i in data]

    def _parse_import_candidate(self, item: dict[str, Any]) -> ImportCandidate:
        quality = (item.get("quality") or {}).get("quality") or {}
        media = item.get(self.media_endpoint or "") or {}
        path = item.get("path") or ""
        return ImportCandidate(
            path=path,
            name=path.rsplit("/", 1)[-1],
            size_bytes=int(item.get("size") or 0),
            quality=quality.get("name"),
            media_title=media.get("title"),
            media_id=media.get("id"),
            season_number=item.get("seasonNumber"),
            episode_ids=[e.get("id") for e in (item.get("episodes") or []) if e.get("id")],
            rejections=[
                str(r.get("reason") if isinstance(r, dict) else r)
                for r in (item.get("rejections") or [])
            ],
        )

    async def do_import(self, files: list[dict[str, Any]], *, move: bool = True) -> str:
        """Import chosen files. `move` copies-and-removes; False leaves the source alone."""
        self._guard("manual_import")
        payload = {
            "name": "ManualImport",
            "files": files,
            "importMode": "move" if move else "copy",
        }
        result = await self._request("POST", "command", json=payload)
        return str((result or {}).get("status", "queued")) if isinstance(result, dict) else "queued"

    async def queue_remove(
        self,
        queue_id: int,
        *,
        remove_from_client: bool = True,
        blocklist: bool = False,
    ) -> None:
        """Drop a queue item.

        `blocklist=True` is what stops the same release being picked straight back up on
        the next RSS pass — without it, removing something usually just delays it.
        """
        self._guard("queue")
        await self._request(
            "DELETE",
            f"queue/{queue_id}",
            params={
                "removeFromClient": str(remove_from_client).lower(),
                "blocklist": str(blocklist).lower(),
            },
        )

    async def blocklist(self, page_size: int = 50) -> list[BlocklistItem]:
        self._guard("blocklist")
        data = await self._request(
            "GET", "blocklist", params={"pageSize": page_size, "sortKey": "date",
                                        "sortDirection": "descending"}
        )
        records = data.get("records", []) if isinstance(data, dict) else (data or [])
        out: list[BlocklistItem] = []
        for item in records:
            quality = (item.get("quality") or {}).get("quality") or {}
            media = item.get(self.media_endpoint or "") or {}
            out.append(
                BlocklistItem(
                    id=item.get("id", 0),
                    service_id=self.service_id,
                    service_name=self.name,
                    title=item.get("sourceTitle") or "",
                    media_title=media.get("title"),
                    quality=quality.get("name"),
                    indexer=item.get("indexer"),
                    protocol=item.get("protocol"),
                    date=self._parse_dt(item.get("date")),
                    message=item.get("message"),
                )
            )
        return out

    async def blocklist_remove(self, item_id: int) -> None:
        """Un-blocklist, so the release becomes grabbable again."""
        self._guard("blocklist")
        await self._request("DELETE", f"blocklist/{item_id}")

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
            service_id=self.service_id,
            service_name=self.name,
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


    # -------------------------------------------------------- system operations
    #
    # Everything below is the *operations* half of a service, as opposed to its
    # configuration: backups, logs, updates, scheduled tasks and restart. All five are
    # guarded separately, because they are not supported as a block — Prowlarr has
    # backups, logs, updates and tasks but no disk space, and Jellyseerr has none of them.

    async def backups(self) -> list[BackupInfo]:
        """Backups the service is currently holding, newest first."""
        self._guard("backups")
        data = await self._request("GET", "system/backup")
        if not isinstance(data, list):
            return []
        items = [
            BackupInfo(
                id=int(item.get("id") or 0),
                service_id=self.service_id,
                service_name=self.name,
                name=item.get("name") or "",
                path=item.get("path") or "",
                size_bytes=int(item.get("size") or 0),
                time=self._parse_dt(item.get("time")),
                kind=item.get("type") or "",
            )
            for item in data
            if isinstance(item, dict)
        ]
        return sorted(items, key=lambda b: (b.time is None, b.time), reverse=True)

    async def create_backup(self) -> str:
        """Ask the service to take a backup now. Returns the queued command's status."""
        self._guard("backups")
        result = await self._request("POST", "command", json={"name": "Backup"})
        if isinstance(result, dict):
            return str(result.get("status") or "queued")
        return "queued"

    async def delete_backup(self, backup_id: int) -> None:
        self._guard("backups")
        await self._request("DELETE", f"system/backup/{backup_id}")

    async def backup_bytes(self, path: str) -> tuple[bytes, str]:
        """Stream one backup out so it can be saved off the box.

        A backup that only exists inside the container it protects is not a backup.

        `path` is the `path` field the service itself reported, e.g.
        `/backup/scheduled/sonarr_backup_v4.0.18_2026.08.02.zip`. It is not constructed
        here: the *arrs partition backups into `scheduled/` and `manual/` subdirectories,
        so `/backup/<name>` 404s for every backup that isn't in the directory you guessed.
        Verified against live Sonarr, Radarr and Prowlarr.
        """
        self._guard("backups")
        client = await self._get_client()
        headers = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        url = f"{self.url}/{path.lstrip('/')}"
        try:
            response = await client.get(url, headers=headers, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise ServiceUnreachable(
                f"Could not download backup from {self.url}", service=self.name
            ) from exc
        if response.status_code >= 400:
            raise ServiceError(
                f"Backup download returned HTTP {response.status_code}", service=self.name
            )
        return response.content, "application/zip"

    async def logs(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        level: str | None = None,
    ) -> LogPage:
        """Paged log records, newest first.

        Kept paged rather than aggregated across services: logs are the one view where
        volume is the whole problem, and merging four services' worth into one stream is
        how you lose the line you were looking for.
        """
        self._guard("logs")
        params: dict[str, Any] = {
            "page": max(1, page),
            "pageSize": max(1, min(page_size, 250)),
            "sortKey": "time",
            "sortDirection": "descending",
        }
        if level:
            params["level"] = level
        data = await self._request("GET", "log", params=params)
        if not isinstance(data, dict):
            return LogPage(page=page, page_size=page_size)
        records = [
            LogRecord(
                id=int(item.get("id") or 0),
                time=self._parse_dt(item.get("time")),
                level=item.get("level") or "",
                logger=item.get("logger") or "",
                message=item.get("message") or "",
                exception=item.get("exception"),
            )
            for item in data.get("records") or []
            if isinstance(item, dict)
        ]
        return LogPage(
            records=records,
            page=int(data.get("page") or page),
            page_size=int(data.get("pageSize") or page_size),
            total=int(data.get("totalRecords") or 0),
        )

    async def log_files(self) -> list[LogFile]:
        """The rotated log files on disk, newest first."""
        self._guard("logs")
        data = await self._request("GET", "log/file")
        if not isinstance(data, list):
            return []
        files = [
            LogFile(
                id=int(item.get("id") or 0),
                filename=item.get("filename") or "",
                last_write=self._parse_dt(item.get("lastWriteTime")),
                download_path=item.get("downloadUrl") or "",
            )
            for item in data
            if isinstance(item, dict) and item.get("filename")
        ]
        return sorted(files, key=lambda f: (f.last_write is None, f.last_write), reverse=True)

    async def log_file_text(self, path: str) -> str:
        """Raw contents of one log file.

        `path` is the service's own `downloadUrl`, e.g. `/logfile/sonarr.txt` — outside
        the API prefix. Like backups, it comes from the service's listing rather than
        from the request, so a client can never steer this at an arbitrary path.
        """
        self._guard("logs")
        client = await self._get_client()
        headers = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        url = f"{self.url}/{path.lstrip('/')}"
        try:
            response = await client.get(url, headers=headers, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise ServiceUnreachable(
                f"Could not read log file from {self.url}", service=self.name
            ) from exc
        if response.status_code >= 400:
            raise ServiceError(
                f"Log file request returned HTTP {response.status_code}", service=self.name
            )
        return response.text

    @staticmethod
    def _parse_changes(raw: Any) -> tuple[list[str], list[str]]:
        if not isinstance(raw, dict):
            return [], []
        new = [str(x) for x in (raw.get("new") or []) if x]
        fixed = [str(x) for x in (raw.get("fixed") or []) if x]
        return new, fixed

    async def updates(self) -> list[UpdateInfo]:
        """Release history, newest first: what's installed and what's available."""
        self._guard("updates")
        data = await self._request("GET", "update")
        if not isinstance(data, list):
            return []
        out: list[UpdateInfo] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            new, fixed = self._parse_changes(item.get("changes"))
            out.append(
                UpdateInfo(
                    version=str(item.get("version") or ""),
                    branch=item.get("branch") or "",
                    release_date=self._parse_dt(item.get("releaseDate")),
                    installed=bool(item.get("installed")),
                    installable=bool(item.get("installable")),
                    latest=bool(item.get("latest")),
                    changes_new=new,
                    changes_fixed=fixed,
                )
            )
        return out

    async def install_update(self) -> str:
        """Trigger the service's own updater.

        Only meaningful where the service manages its own binaries. In Docker — which is
        how this stack runs — updates come from pulling a new image and the *arr reports
        `installable: false`. The route refuses in that case rather than queuing a command
        that will quietly do nothing.
        """
        self._guard("updates")
        result = await self._request(
            "POST", "command", json={"name": "ApplicationUpdate"}
        )
        if isinstance(result, dict):
            return str(result.get("status") or "queued")
        return "queued"

    async def tasks(self) -> list[ScheduledTask]:
        """The service's scheduled tasks, soonest-due first."""
        self._guard("tasks")
        data = await self._request("GET", "system/task")
        if not isinstance(data, list):
            return []
        items = [
            ScheduledTask(
                id=int(item.get("id") or 0),
                name=item.get("name") or "",
                task_name=item.get("taskName") or "",
                interval_minutes=int(item.get("interval") or 0),
                last_execution=self._parse_dt(item.get("lastExecution")),
                last_duration=item.get("lastDuration"),
                next_execution=self._parse_dt(item.get("nextExecution")),
            )
            for item in data
            if isinstance(item, dict)
        ]
        return sorted(items, key=lambda t: (t.next_execution is None, t.next_execution))

    async def run_task(self, task_name: str) -> str:
        """Run a scheduled task now, by its command name (`taskName`, not `name`)."""
        self._guard("tasks")
        result = await self._request("POST", "command", json={"name": task_name})
        if isinstance(result, dict):
            return str(result.get("status") or "queued")
        return "queued"

    async def restart(self) -> None:
        """Restart the service.

        The service tears down its HTTP listener while responding, so a dropped
        connection here is success, not failure — the caller treats transport errors as
        expected. Whether it comes back is the container runtime's business, not ours.
        """
        self._guard("restart")
        try:
            await self._request("POST", "system/restart")
        except ServiceUnreachable:
            return

_STATUS_MAP = {
    "unreachable": ServiceStatus.UNREACHABLE,
    "unauthorized": ServiceStatus.UNAUTHORIZED,
    "error": ServiceStatus.DEGRADED,
    "unsupported": ServiceStatus.DEGRADED,
    "unknown": ServiceStatus.UNKNOWN,
}
