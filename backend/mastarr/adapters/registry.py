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


def probe_ports() -> dict[int, str]:
    """Ports a scan should try: the defaults, plus common alternates.

    People move these. The reference stack runs Jellyseerr on 5057 rather than the
    documented 5055, and scanning only defaults meant discovery silently never found it —
    which reads as "Mastarr can't see my Jellyseerr" rather than "wrong port".

    Still only a hint: identity always comes from `system/status`.
    """
    ports = default_ports()
    for cls in ADAPTERS.values():
        for offset in cls.alternate_ports:
            ports.setdefault(offset, cls.service_type)
    return ports


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


def probe_signatures() -> list[tuple[str, str]]:
    """Distinct (probe_path, service_type) pairs a scan should try.

    Deduplicated by path so a scan makes one request per distinct endpoint rather than one
    per registered type. The service_type is just a handle for calling `matches_probe`.
    """
    seen: dict[str, str] = {}
    for name, cls in ADAPTERS.items():
        seen.setdefault(cls.probe_path, name)
    return sorted(seen.items())


def distinctive_probe_type(probe_path: str) -> str | None:
    """The service type a probe path *proves*, if it only belongs to one type.

    `/ping` is answered by five different *arrs, so responding to it says a service is
    there but nothing about which — guessing from it would be a confident lie. Jellyseerr's
    `/api/v1/status` is unique to Jellyseerr, so that one genuinely identifies it.
    """
    owners = [name for name, cls in ADAPTERS.items() if cls.probe_path == probe_path]
    return owners[0] if len(owners) == 1 else None
