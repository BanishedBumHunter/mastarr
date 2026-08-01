"""The database layer of Mastarr's own configuration.

Precedence is **env > YAML > DB > default**. This module owns the DB layer only.

The reason it reports *provenance* rather than just values: if an admin edits a setting in
the UI that the environment also sets, the edit will be saved and then ignored on the next
read. Silently doing that is maddening to debug, so the API tells the UI which layer owns
each value and the field renders locked with an explanation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlmodel import Session, select

from .config import Settings, get_settings
from .models import AppSetting

log = logging.getLogger(__name__)

# Only these may be edited through the UI. Secrets are absent on purpose — they live in
# the environment or a 0600 file, so this surface has nothing sensitive to expose.
EDITABLE: dict[str, dict[str, Any]] = {
    "session_hours": {
        "type": "int",
        "label": "Session length (hours)",
        "help": "How long a sign-in lasts before you have to log in again.",
        "min": 1,
        "max": 720,
    },
    "http_timeout": {
        "type": "float",
        "label": "Service timeout (seconds)",
        "help": "How long to wait for an *arr before marking it unreachable.",
        "min": 1,
        "max": 120,
    },
    "dashboard_cache_seconds": {
        "type": "float",
        "label": "Dashboard cache (seconds)",
        "help": "How long service health is reused before being re-fetched.",
        "min": 0,
        "max": 300,
    },
    "discovery_hosts": {
        "type": "list[str]",
        "label": "Default scan hosts",
        "help": "Pre-fills the Scan box on the Services tab. One host per line.",
    },
    "sweep_enabled": {
        "type": "bool",
        "label": "Periodic upgrade sweep",
        "help": "Ask each service to re-search for anything below its quality cutoff. "
        "The *arrs never do this on their own — upgrades otherwise only happen if a "
        "better release appears in the RSS window.",
    },
    "sweep_interval_hours": {
        "type": "int",
        "label": "Sweep every (hours)",
        "help": "168 = weekly.",
        "min": 1,
        "max": 8760,
    },
    "sweep_include_missing": {
        "type": "bool",
        "label": "Also search for missing items",
        "help": "Include a search for monitored items that have no file at all.",
    },
    "grab_guard_enabled": {
        "type": "bool",
        "label": "Reject suspicious grabs",
        "help": "Watches grabs and removes ones where a brand-new upload claims to be a "
        "much older title. Catch-and-undo, not prevention — the service grabs first and "
        "Mastarr reverses it seconds later.",
    },
    "grab_guard_max_days_after_release": {
        "type": "int",
        "label": "Flag uploads posted this long after release (days)",
        "help": "A release posted more than this many days after the media came out.",
        "min": 1,
        "max": 36500,
    },
    "grab_guard_min_media_age_days": {
        "type": "int",
        "label": "Only for media older than (days)",
        "help": "Protects new releases from being flagged. Anything younger is ignored.",
        "min": 0,
        "max": 36500,
    },
    "log_level": {
        "type": "enum",
        "label": "Log level",
        "help": "DEBUG is noisy; API keys are redacted at every level.",
        "choices": ["DEBUG", "INFO", "WARNING", "ERROR"],
    },
}


def _coerce(key: str, value: Any) -> Any:
    """Force a value to the declared type, so the UI can send strings for everything."""
    spec = EDITABLE[key]
    kind = spec["type"]
    if kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value)
    if kind == "list[str]":
        if isinstance(value, str):
            return [line.strip() for line in value.replace(",", "\n").splitlines() if line.strip()]
        return [str(v).strip() for v in value if str(v).strip()]
    if kind == "enum":
        text = str(value).upper()
        if text not in spec["choices"]:
            raise ValueError(f"{key} must be one of {', '.join(spec['choices'])}")
        return text
    return value


def _validate(key: str, value: Any) -> Any:
    spec = EDITABLE[key]
    if "min" in spec and value < spec["min"]:
        raise ValueError(f"{spec['label']} must be at least {spec['min']}.")
    if "max" in spec and value > spec["max"]:
        raise ValueError(f"{spec['label']} must be at most {spec['max']}.")
    return value


def read_all(session: Session) -> dict[str, Any]:
    """Every stored override, decoded."""
    stored: dict[str, Any] = {}
    for row in session.exec(select(AppSetting)).all():
        if row.key not in EDITABLE:
            continue  # a key from a newer version, or one since removed
        try:
            stored[row.key] = json.loads(row.value_json)
        except json.JSONDecodeError:
            log.warning("Ignoring unreadable stored setting %r", row.key)
    return stored


def write(session: Session, key: str, value: Any) -> Any:
    if key not in EDITABLE:
        raise ValueError(f"{key} is not an editable setting.")
    coerced = _validate(key, _coerce(key, value))

    row = session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value_json=json.dumps(coerced))
    else:
        row.value_json = json.dumps(coerced)
    session.add(row)
    return coerced


def clear(session: Session, key: str) -> None:
    """Drop an override so the value falls back to YAML or the built-in default."""
    row = session.get(AppSetting, key)
    if row is not None:
        session.delete(row)


def source_of(key: str, settings: Settings | None = None) -> str:
    """Which layer actually decides this setting: env | file | database | default.

    Used to render a field locked when something above the DB owns it.
    """
    import os

    resolved = settings or get_settings()
    if f"MASTARR_{key.upper()}" in os.environ:
        return "env"
    if key in resolved.yaml_overrides():
        return "file"
    return "database"


def describe(session: Session) -> list[dict[str, Any]]:
    """Every editable setting with its effective value, provenance and whether it's locked."""
    settings = get_settings()
    stored = read_all(session)
    out: list[dict[str, Any]] = []

    for key, spec in EDITABLE.items():
        source = source_of(key, settings)
        if source == "database" and key not in stored:
            source = "default"
        out.append(
            {
                "key": key,
                "value": getattr(settings, key, None),
                "stored_value": stored.get(key),
                "source": source,
                # Anything above the DB wins, so editing here would be a lie.
                "locked": source in ("env", "file"),
                **{k: v for k, v in spec.items() if k != "type"},
                "type": spec["type"],
            }
        )
    return out


def apply_to_settings(settings: Settings, stored: dict[str, Any]) -> Settings:
    """Layer stored values *beneath* anything explicitly set by env or YAML."""
    explicit = set(settings.model_fields_set)
    merged = {
        **{k: v for k, v in stored.items() if k not in explicit},
        **settings.model_dump(include=explicit),
    }
    return Settings(**merged)
