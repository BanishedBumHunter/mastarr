"""Adapter registry — the one place a service type is wired in.

Adding a new *arr means: write `adapters/<type>.py`, import it here, add it to `ADAPTERS`.
Nothing else in the codebase should need to know the type exists. If you find yourself
editing a route handler or the frontend to add a service type, the abstraction has leaked.
"""

from __future__ import annotations

from typing import Type

from .base import ArrAdapter
from .jellyseerr import JellyseerrAdapter
from .lidarr import LidarrAdapter
from .prowlarr import ProwlarrAdapter
from .radarr import RadarrAdapter
from .readarr import ReadarrAdapter
from .sonarr import SonarrAdapter

# Adding a service type is one import plus one line here. Nothing else in the codebase
# should need to know the type exists.
ADAPTERS: dict[str, Type[ArrAdapter]] = {
    SonarrAdapter.service_type: SonarrAdapter,
    RadarrAdapter.service_type: RadarrAdapter,
    LidarrAdapter.service_type: LidarrAdapter,
    ReadarrAdapter.service_type: ReadarrAdapter,
    ProwlarrAdapter.service_type: ProwlarrAdapter,
    JellyseerrAdapter.service_type: JellyseerrAdapter,
}


class UnknownServiceType(ValueError):
    """A service type with no registered adapter."""


def get_adapter_class(service_type: str) -> Type[ArrAdapter]:
    try:
        return ADAPTERS[service_type.lower().strip()]
    except KeyError as exc:
        known = ", ".join(sorted(ADAPTERS))
        raise UnknownServiceType(
            f"No adapter for service type '{service_type}'. Known types: {known}"
        ) from exc


def build_adapter(service_type: str, url: str, api_key: str | None = None, **kwargs) -> ArrAdapter:
    return get_adapter_class(service_type)(url, api_key, **kwargs)


def known_types() -> list[str]:
    return sorted(ADAPTERS)


def default_ports() -> dict[int, str]:
    """port -> service_type, for discovery probing. Ports are hints only; identity always
    comes from `system/status`."""
    return {cls.default_port: name for name, cls in ADAPTERS.items() if cls.default_port}


def type_for_app_name(app_name: str) -> str | None:
    """Resolve the authoritative `appName` from system/status to a registered type."""
    needle = (app_name or "").lower().strip()
    for name, cls in ADAPTERS.items():
        if cls.app_name == needle:
            return name
    return None


def describe_types() -> list[dict[str, object]]:
    """Type metadata for the frontend, so the UI never hardcodes a service list."""
    return [
        {
            "type": name,
            "display_name": cls.display_name,
            "api_version": cls.api_version,
            "default_port": cls.default_port,
            "manages_media": cls.media_endpoint is not None,
            "media_kind": cls.media_kind,
            "unsupported": sorted(cls.unsupported),
        }
        for name, cls in sorted(ADAPTERS.items())
    ]
