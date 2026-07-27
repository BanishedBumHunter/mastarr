"""Service adapters. Every *arr interaction in Mastarr goes through this package."""

from .base import ArrAdapter
from .errors import (
    AdapterError,
    ServiceError,
    ServiceUnauthorized,
    ServiceUnreachable,
    UnsupportedOperation,
)
from .prowlarr import ProwlarrAdapter
from .radarr import RadarrAdapter
from .registry import (
    ADAPTERS,
    UnknownServiceType,
    build_adapter,
    default_ports,
    describe_types,
    get_adapter_class,
    known_types,
    type_for_app_name,
)
from .schemas import (
    DiskSpace,
    DownloadClient,
    HealthIssue,
    HealthSeverity,
    HistoryItem,
    Indexer,
    QualityProfile,
    QueueItem,
    RootFolder,
    SearchResult,
    ServiceSnapshot,
    ServiceStatus,
    SystemStatus,
)
from .sonarr import SonarrAdapter

__all__ = [
    "ADAPTERS",
    "AdapterError",
    "ArrAdapter",
    "DiskSpace",
    "DownloadClient",
    "HealthIssue",
    "HealthSeverity",
    "HistoryItem",
    "Indexer",
    "ProwlarrAdapter",
    "QualityProfile",
    "QueueItem",
    "RadarrAdapter",
    "RootFolder",
    "SearchResult",
    "ServiceError",
    "ServiceSnapshot",
    "ServiceStatus",
    "ServiceUnauthorized",
    "ServiceUnreachable",
    "SonarrAdapter",
    "SystemStatus",
    "UnknownServiceType",
    "UnsupportedOperation",
    "build_adapter",
    "default_ports",
    "describe_types",
    "get_adapter_class",
    "known_types",
    "type_for_app_name",
]
