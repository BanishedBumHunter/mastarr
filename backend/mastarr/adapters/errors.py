"""Adapter error hierarchy.

Every failure mode an *arr can present is mapped onto one of these before leaving the
adapter package. Route handlers and the dashboard fan-out catch `AdapterError` and nothing
else — an `httpx` exception escaping the adapter layer is a bug, not a case to handle
upstream.
"""

from __future__ import annotations


class AdapterError(Exception):
    """Base for every adapter failure. Carries the status the UI should render."""

    status = "unknown"

    def __init__(self, message: str, *, service: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.service = service


class ServiceUnreachable(AdapterError):
    """Connection refused, DNS failure, TLS failure, or timeout."""

    status = "unreachable"


class ServiceUnauthorized(AdapterError):
    """Reached the service, but the API key is missing, wrong, or lacks permission."""

    status = "unauthorized"


class ServiceError(AdapterError):
    """Reached and authenticated, but the service returned an error or unparseable body."""

    status = "error"


class UnsupportedOperation(AdapterError):
    """This service type genuinely has no such endpoint (e.g. root folders on Prowlarr)."""

    status = "unsupported"
