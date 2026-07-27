"""Logging setup with global API-key redaction.

"Never log an API key" is not a rule you can enforce by remembering it — httpx logs request
URLs, tracebacks embed local variables, and a third-party library will eventually print a
header dict. So redaction is installed as a filter on the root logger and applies to every
record from every library, whether or not that code knows Mastarr exists.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Registered at runtime as services are loaded, so we can redact the literal key values.
_known_secrets: set[str] = set()

# Structural patterns, for keys we have not been told about (someone else's service, a
# key typed into a form, a URL with ?apikey= in it).
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(x-api-key['\"\s:=]+)([A-Za-z0-9_\-]{8,})"),
    re.compile(r"(?i)([?&](?:api_?key)=)([A-Za-z0-9_\-]{8,})"),
    re.compile(r"(?i)('?api_?key'?\s*[:=]\s*['\"]?)([A-Za-z0-9_\-]{8,})"),
    re.compile(r"(?i)(authorization['\"\s:=]+bearer\s+)(\S+)"),
)

REDACTED = "***REDACTED***"


def register_secret(secret: str | None) -> None:
    """Track a known key so it is redacted anywhere it appears, in any format."""
    if secret and len(secret) >= 8:
        _known_secrets.add(secret)


def forget_secret(secret: str | None) -> None:
    _known_secrets.discard(secret or "")


def redact(text: str) -> str:
    for secret in _known_secrets:
        if secret in text:
            text = text.replace(secret, REDACTED)
    for pattern in _PATTERNS:
        text = pattern.sub(rf"\1{REDACTED}", text)
    return text


class RedactionFilter(logging.Filter):
    """Scrubs secrets from the message and every positional arg of each record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = self._redact_args(record.args)
        return True

    @staticmethod
    def _redact_args(args: Any) -> Any:
        if isinstance(args, dict):
            return {k: redact(v) if isinstance(v, str) else v for k, v in args.items()}
        if isinstance(args, tuple):
            return tuple(redact(a) if isinstance(a, str) else a for a in args)
        return args


def configure_logging(level: str = "INFO") -> None:
    """Install the redaction filter on every handler of the root logger."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    redaction = RedactionFilter()
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(redaction)

    # httpx logs full request URLs at INFO, which would leak keys passed as query params.
    logging.getLogger("httpx").setLevel(logging.WARNING)
