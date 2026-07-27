"""Normalized shapes returned by adapters.

The *arrs return near-identical but not identical payloads: Sonarr's queue item references a
`seriesId` and `episodeId`, Radarr's a `movieId`; Sonarr nests `series.title`, Radarr nests
`movie.title`. Adapters flatten all of that into these types, so everything above the
adapter layer — API routes, the dashboard, the frontend — is service-agnostic.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ServiceStatus(str, Enum):
    """The one enum that drives dashboard rendering.

    DEGRADED vs ONLINE is the distinction that matters operationally: a service can be
    perfectly reachable and still be shouting about a missing root folder or a failed
    download client.
    """

    ONLINE = "online"
    DEGRADED = "degraded"
    UNAUTHORIZED = "unauthorized"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


class HealthSeverity(str, Enum):
    OK = "ok"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"


class SystemStatus(BaseModel):
    """Identity and version, from `system/status`. `app_name` is the authoritative type."""

    app_name: str
    version: str
    instance_name: str | None = None
    os_name: str | None = None
    is_docker: bool | None = None
    start_time: datetime | None = None


class HealthIssue(BaseModel):
    source: str
    severity: HealthSeverity = HealthSeverity.WARNING
    message: str
    wiki_url: str | None = None


class DiskSpace(BaseModel):
    path: str
    label: str | None = None
    free_bytes: int
    total_bytes: int

    @property
    def used_bytes(self) -> int:
        return max(self.total_bytes - self.free_bytes, 0)

    @property
    def used_percent(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return round(self.used_bytes / self.total_bytes * 100, 1)


class QueueItem(BaseModel):
    """A download in flight, flattened across service types."""

    id: int
    title: str
    status: str
    media_title: str | None = None
    quality: str | None = None
    size_bytes: int = 0
    size_left_bytes: int = 0
    download_client: str | None = None
    indexer: str | None = None
    error_message: str | None = None
    estimated_completion: datetime | None = None

    @property
    def progress_percent(self) -> float:
        if self.size_bytes <= 0:
            return 0.0
        done = self.size_bytes - self.size_left_bytes
        return round(max(done, 0) / self.size_bytes * 100, 1)


class HistoryItem(BaseModel):
    id: int
    event_type: str
    title: str
    media_title: str | None = None
    quality: str | None = None
    date: datetime | None = None
    source_title: str | None = None


class QualityProfile(BaseModel):
    id: int
    name: str
    upgrade_allowed: bool = False
    cutoff_name: str | None = None


class RootFolder(BaseModel):
    id: int
    path: str
    accessible: bool = True
    free_space_bytes: int | None = None


class DownloadClient(BaseModel):
    id: int
    name: str
    implementation: str
    enabled: bool = True
    protocol: str | None = None
    priority: int | None = None


class Indexer(BaseModel):
    id: int
    name: str
    implementation: str
    enabled: bool = True
    protocol: str | None = None
    priority: int | None = None


class SearchResult(BaseModel):
    """A lookup hit — a series/movie that could be added, not a release."""

    title: str
    year: int | None = None
    overview: str | None = None
    poster_url: str | None = None
    remote_id: str | None = Field(
        default=None, description="tvdbId / tmdbId, as a string for type-agnostic handling"
    )
    already_added: bool = False


class ServiceSnapshot(BaseModel):
    """Everything the dashboard shows for one service, including the failure case.

    This type is deliberately total: an unreachable service produces a valid snapshot with
    `status=UNREACHABLE` and an error message, never an exception or a missing entry. That
    is what lets the dashboard degrade instead of crash.
    """

    service_id: int | None = None
    name: str
    service_type: str
    url: str
    status: ServiceStatus
    version: str | None = None
    app_name: str | None = None
    error: str | None = None
    health_issues: list[HealthIssue] = Field(default_factory=list)
    disk_space: list[DiskSpace] = Field(default_factory=list)
    queue_count: int | None = None
    checked_at: datetime | None = None
