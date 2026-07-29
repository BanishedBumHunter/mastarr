"""Auto-discovery of *arr services.

Two phases, because the *arrs expose exactly two useful signals:

1. **Presence** — `GET /ping` is unauthenticated on every *arr and returns
   `{"status":"OK"}`. So we can find services before any API key exists. This is what makes
   a genuinely zero-config first run possible.
2. **Identity** — `GET /api/<version>/system/status` returns `appName`, and requires a key.
   That field is the authoritative service type.

The port a service answers on is only ever a *hint* about which type it is, used to pick
which API version to try first. A service found on 8989 that reports `appName: Radarr` is
Radarr. Verified against the live stack: Sonarr:8989 and Radarr:7878 speak v3, Prowlarr:9696
speaks v1, and all three answer `/ping` while returning 401 on `system/status`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from .adapters.registry import distinctive_probe_type, probe_ports, probe_signatures
from .adapters import (
    AdapterError,
    ServiceUnauthorized,
    build_adapter,
    default_ports,
    get_adapter_class,
    known_types,
    type_for_app_name,
)

log = logging.getLogger(__name__)

DEFAULT_PROBE_TIMEOUT = 3.0


class DiscoveredService(BaseModel):
    """A candidate found by probing. `confirmed` distinguishes proof from inference."""

    url: str
    host: str
    port: int
    # Best guess before identification; authoritative after.
    service_type: str | None = None
    app_name: str | None = None
    version: str | None = None
    confirmed: bool = False
    reachable: bool = True
    needs_api_key: bool = False
    already_configured: bool = False
    detail: str | None = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


async def probe_endpoint(
    host: str,
    port: int,
    *,
    scheme: str = "http",
    timeout: float = DEFAULT_PROBE_TIMEOUT,
    client: httpx.AsyncClient | None = None,
) -> DiscoveredService | None:
    """Phase 1: is an *arr-shaped service listening here? No API key required."""
    url = f"{scheme}://{host}:{port}"
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    matched_path: str | None = None
    try:
        # Try each distinct unauthenticated probe endpoint. Most services answer /ping;
        # Jellyseerr only answers /api/v1/status, so a single hardcoded path would miss it
        # entirely and look like "Mastarr can't see my Jellyseerr".
        for path, service_type in probe_signatures():
            try:
                response = await client.get(f"{url}/{path}")
            except httpx.HTTPError:
                continue
            if response.status_code != 200:
                continue
            try:
                payload = response.json()
            except ValueError:
                continue
            if get_adapter_class(service_type).matches_probe(payload):
                matched_path = path
                break
    finally:
        if owns_client:
            await client.aclose()

    if matched_path is None:
        return None

    # Two independent hints, neither of which is proof:
    #   - a known default port suggests a type
    #   - a probe endpoint only *proves* a type when no other type shares it
    # `/ping` is answered by every *arr, so it never identifies one. Identity still comes
    # from system/status in phase two.
    guess = probe_ports().get(port) or distinctive_probe_type(matched_path)
    return DiscoveredService(
        url=url,
        host=host,
        port=port,
        service_type=guess,
        needs_api_key=True,
        detail=(
            f"Responds to /ping. Port suggests {guess.title()}; supply an API key to confirm."
            if guess
            else "Responds to /ping, but the port is not a known default. "
            "Supply an API key to identify it."
        ),
    )


async def identify(
    candidate: DiscoveredService,
    api_key: str,
    *,
    timeout: float = DEFAULT_PROBE_TIMEOUT,
) -> DiscoveredService:
    """Phase 2: confirm identity from `system/status`.

    Tries the type suggested by the port first, then every other registered type — this is
    what catches a service running on a non-default port, and what makes the v1/v3 split
    invisible to the caller.
    """
    ordered = [candidate.service_type] if candidate.service_type else []
    ordered += [t for t in known_types() if t != candidate.service_type]

    last_error: str | None = None
    for service_type in ordered:
        adapter = build_adapter(service_type, candidate.url, api_key, timeout=timeout)
        try:
            status = await adapter.system_status()
        except ServiceUnauthorized as exc:
            # A rejected key is conclusive about the key, not the type — stop guessing.
            candidate.needs_api_key = True
            candidate.detail = exc.message
            return candidate
        except AdapterError as exc:
            last_error = exc.message
            continue
        finally:
            await adapter.aclose()

        resolved = type_for_app_name(status.app_name) or service_type
        candidate.service_type = resolved
        candidate.app_name = status.app_name
        candidate.version = status.version
        candidate.confirmed = True
        candidate.needs_api_key = False
        candidate.detail = (
            f"Confirmed {status.app_name} {status.version} "
            f"(API {get_adapter_class(resolved).api_version})"
        )
        return candidate

    candidate.detail = last_error or "Could not identify this service."
    return candidate


async def scan_host(
    host: str,
    *,
    ports: list[int] | None = None,
    scheme: str = "http",
    timeout: float = DEFAULT_PROBE_TIMEOUT,
) -> list[DiscoveredService]:
    """Probe every known default port on one host, concurrently."""
    targets = ports or sorted(probe_ports())
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        results = await asyncio.gather(
            *(
                probe_endpoint(host, port, scheme=scheme, timeout=timeout, client=client)
                for port in targets
            ),
            return_exceptions=True,
        )

    found: list[DiscoveredService] = []
    for result in results:
        if isinstance(result, BaseException):
            log.debug("probe raised during scan of %s: %s", host, result)
            continue
        if result is not None:
            found.append(result)
    return found


async def scan_hosts(
    hosts: list[str],
    *,
    ports: list[int] | None = None,
    timeout: float = DEFAULT_PROBE_TIMEOUT,
) -> list[DiscoveredService]:
    """Scan several hosts. Accepts bare hosts, `host:port`, or full URLs."""
    results = await asyncio.gather(
        *(_scan_target(target, ports=ports, timeout=timeout) for target in hosts),
        return_exceptions=True,
    )
    found: list[DiscoveredService] = []
    for result in results:
        if isinstance(result, BaseException):
            log.debug("host scan failed: %s", result)
            continue
        found.extend(result)
    return found


async def _scan_target(
    target: str, *, ports: list[int] | None, timeout: float
) -> list[DiscoveredService]:
    scheme, host, explicit_port = _split_target(target)
    if explicit_port:
        result = await probe_endpoint(host, explicit_port, scheme=scheme, timeout=timeout)
        return [result] if result else []
    return await scan_host(host, ports=ports, scheme=scheme, timeout=timeout)


def _split_target(target: str) -> tuple[str, str, int | None]:
    """Normalize `host`, `host:port`, `http://host:port` into (scheme, host, port|None)."""
    raw = target.strip()
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    return parsed.scheme or "http", parsed.hostname or target, parsed.port
