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
    """A download in flight, flattened across service types.

    Carries its origin: once queues from several services are merged into one list, an
    item with no service is one you can't act on — remove and blocklist both need to know
    which service to call.
    """

    id: int
    service_id: int | None = None
    service_name: str | None = None
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


# --------------------------------------------------------------- unified views


class DateKind(str, Enum):
    """Which kind of date a calendar entry represents.

    Sonarr has exactly one date per episode. Radarr has three (`inCinemas`,
    `digitalRelease`, `physicalRelease`) and an entry may carry all of them — so a naive
    merge either triples the row or silently drops two thirds of the information. Adapters
    collapse to one date and label which one it is; the UI filters on the label.
    """

    AIR = "air"
    DIGITAL = "digital"
    PHYSICAL = "physical"
    CINEMA = "cinema"
    RELEASE = "release"


class CalendarEntry(BaseModel):
    """One dated thing, from any service."""

    service_id: int | None = None
    service_type: str
    service_name: str
    media_kind: str  # series | movie | album | book
    item_id: int
    title: str  # the episode/movie title
    parent_title: str | None = None  # series title, for episodes
    date: datetime
    date_kind: DateKind = DateKind.AIR
    season_number: int | None = None
    episode_number: int | None = None
    has_file: bool = False
    monitored: bool = True
    overview: str | None = None
    runtime_minutes: int | None = None
    poster: str | None = None

    @property
    def episode_code(self) -> str | None:
        if self.season_number is None or self.episode_number is None:
            return None
        return f"S{self.season_number:02d}E{self.episode_number:02d}"


class LibraryItem(BaseModel):
    """A series or movie, normalized so one grid can render both."""

    service_id: int | None = None
    service_type: str
    service_name: str
    media_kind: str
    item_id: int
    title: str
    sort_title: str | None = None
    year: int | None = None
    overview: str | None = None
    poster: str | None = None
    status: str | None = None
    monitored: bool = True
    path: str | None = None
    quality_profile_id: int | None = None
    size_bytes: int = 0
    added: datetime | None = None
    genres: list[str] = Field(default_factory=list)
    runtime_minutes: int | None = None
    network: str | None = None  # series only
    studio: str | None = None  # movie only
    remote_id: str | None = None

    # Progress. For movies this is 0/1 or 1/1; for series it's episode counts, so one
    # progress bar works for both.
    have_count: int = 0
    total_count: int = 0

    @property
    def percent_complete(self) -> float:
        if self.total_count <= 0:
            return 0.0
        return round(min(self.have_count / self.total_count, 1.0) * 100, 1)

    @property
    def is_missing(self) -> bool:
        return self.monitored and self.have_count < self.total_count


class Episode(BaseModel):
    """A single episode, for the series detail view."""

    id: int
    season_number: int
    episode_number: int
    title: str | None = None
    air_date: datetime | None = None
    has_file: bool = False
    monitored: bool = True
    runtime_minutes: int | None = None
    size_bytes: int = 0
    overview: str | None = None


class Season(BaseModel):
    season_number: int
    monitored: bool = True
    episode_count: int = 0
    episode_file_count: int = 0
    size_bytes: int = 0
    episodes: list[Episode] = Field(default_factory=list)

    @property
    def percent_complete(self) -> float:
        if self.episode_count <= 0:
            return 0.0
        return round(self.episode_file_count / self.episode_count * 100, 1)


class LibraryDetail(BaseModel):
    """A library item plus everything the detail view needs."""

    item: LibraryItem
    seasons: list[Season] = Field(default_factory=list)
    # Deep link into the native app, for the configuration Mastarr deliberately doesn't
    # reimplement.
    native_url: str | None = None


class DiscoverResult(BaseModel):
    """A search/browse hit from the request front-end (Jellyseerr/Overseerr)."""

    tmdb_id: int
    media_kind: str  # movie | tv
    title: str
    year: int | None = None
    overview: str | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    vote_average: float | None = None
    # From mediaInfo: 1 unknown, 2 pending, 3 processing, 4 partial, 5 available
    media_status: int | None = None
    already_requested: bool = False
    available: bool = False


class MediaRequest(BaseModel):
    """A request in the front-end's queue."""

    id: int
    media_kind: str
    # 1 pending, 2 approved, 3 declined
    status: int
    title: str | None = None
    year: int | None = None
    poster_url: str | None = None
    tmdb_id: int | None = None
    requested_by: str | None = None
    requested_by_id: int | None = None
    created_at: datetime | None = None
    # From the linked mediaInfo, so the UI can show "approved but not downloaded yet".
    media_status: int | None = None


class DiscoverPage(BaseModel):
    page: int = 1
    total_pages: int = 1
    total_results: int = 0
    results: list[DiscoverResult] = Field(default_factory=list)


# ------------------------------------------------------------ manual control


class Release(BaseModel):
    """One candidate release from an interactive search.

    `rejected` plus `rejections` is the important part: the service will happily tell you
    *why* it won't auto-grab something, and surfacing that turns "nothing downloaded" from
    a mystery into a decision.
    """

    guid: str
    title: str
    indexer: str | None = None
    indexer_id: int | None = None
    protocol: str | None = None
    quality: str | None = None
    size_bytes: int = 0
    seeders: int | None = None
    leechers: int | None = None
    age_hours: float | None = None
    published: datetime | None = None
    rejected: bool = False
    rejections: list[str] = Field(default_factory=list)
    download_allowed: bool = True
    custom_format_score: int | None = None

    @property
    def age_days(self) -> float | None:
        return round(self.age_hours / 24, 1) if self.age_hours is not None else None


class ImportCandidate(BaseModel):
    """A file sitting on disk that could be imported."""

    path: str
    name: str
    size_bytes: int = 0
    quality: str | None = None
    # What the service thinks it belongs to; may be absent when it can't tell.
    media_title: str | None = None
    media_id: int | None = None
    season_number: int | None = None
    episode_ids: list[int] = Field(default_factory=list)
    rejections: list[str] = Field(default_factory=list)

    @property
    def importable(self) -> bool:
        """No rejections and enough identification to file it somewhere."""
        return not self.rejections and self.media_id is not None


class BlocklistItem(BaseModel):
    id: int
    service_id: int | None = None
    service_name: str | None = None
    title: str
    media_title: str | None = None
    quality: str | None = None
    indexer: str | None = None
    protocol: str | None = None
    date: datetime | None = None
    message: str | None = None


# --------------------------------------------------------------- system operations


class BackupInfo(BaseModel):
    id: int
    service_id: int | None = None
    service_name: str | None = None
    name: str
    path: str = ""
    size_bytes: int = 0
    time: datetime | None = None
    kind: str = ""
    """`scheduled` or `manual` — the *arrs call this `type`."""


class LogRecord(BaseModel):
    id: int
    time: datetime | None = None
    level: str = ""
    logger: str = ""
    message: str = ""
    exception: str | None = None


class LogPage(BaseModel):
    records: list[LogRecord] = Field(default_factory=list)
    page: int = 1
    page_size: int = 50
    total: int = 0


class LogFile(BaseModel):
    id: int
    filename: str
    last_write: datetime | None = None
    download_path: str = ""
    """Service-reported path, e.g. `/logfile/sonarr.txt`. Never constructed here."""


class UpdateInfo(BaseModel):
    version: str
    branch: str = ""
    release_date: datetime | None = None
    installed: bool = False
    installable: bool = False
    latest: bool = False
    changes_new: list[str] = Field(default_factory=list)
    changes_fixed: list[str] = Field(default_factory=list)


class UpdateStatus(BaseModel):
    """What one service's update situation looks like, for the fleet view."""

    service_id: int
    service_name: str
    service_type: str
    current_version: str = ""
    latest_version: str = ""
    update_available: bool = False
    installable: bool = False
    """Whether Mastarr will offer an Install button. See `blocked_reason`."""
    blocked_reason: str = ""
    """Why installing is unavailable, in words. Empty when it is available."""
    release_date: datetime | None = None
    changes_new: list[str] = Field(default_factory=list)
    changes_fixed: list[str] = Field(default_factory=list)


class ScheduledTask(BaseModel):
    id: int
    name: str
    task_name: str = ""
    interval_minutes: int = 0
    last_execution: datetime | None = None
    last_duration: str | None = None
    next_execution: datetime | None = None
