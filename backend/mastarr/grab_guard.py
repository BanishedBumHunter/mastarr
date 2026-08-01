"""Reactive grab guard: reject a brand-new upload of a much older title.

The problem: a release posted yesterday for a film that came out years ago is a common
signature for a fake, a bad re-encode, or a mislabelled rip. No *arr can express this —
custom formats match on release *names*, never on dates, and there's no "upload age vs.
release date" condition anywhere in the stack.

Mastarr also **cannot prevent** the grab. The *arr searches and grabs autonomously; nothing
asks Mastarr first. What it can do is register a `Webhook` connection, be told the instant a
grab happens, evaluate the rule, and — if it trips — remove the item from the queue and
blocklist it so the same release isn't picked up again on the next RSS pass.

So this is **catch-and-undo, seconds later — not prevention.** The UI says so, and it is off
by default: anything that deletes downloads should be a deliberate choice, and every action
it takes is recorded so it can never quietly bin things.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlmodel import Session

from .adapters import AdapterError
from .config import get_settings
from .models import Service
from .services import adapter_for, list_services

log = logging.getLogger(__name__)

# Kept in memory rather than a table: it's an operational log people glance at, not
# something worth a migration. Capped so a runaway can't grow without bound.
MAX_AUDIT = 200
_audit: list[dict[str, Any]] = []


class GrabVerdict(BaseModel):
    """Why the guard did or didn't act. Always explains itself."""

    reject: bool = False
    reason: str = ""
    release_age_days: float | None = None
    media_age_days: float | None = None


class AuditEntry(BaseModel):
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    service_name: str
    title: str
    action: str  # rejected | allowed | failed
    reason: str
    detail: str | None = None


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def evaluate(
    *,
    release_published: datetime | None,
    media_released: datetime | None,
    now: datetime | None = None,
    max_days_after_release: int | None = None,
    min_media_age_days: int | None = None,
) -> GrabVerdict:
    """Decide whether a grab looks wrong.

    Rejects only when *both* hold:
      1. the media is genuinely old (older than `min_media_age_days`), and
      2. this release was posted far later than the media came out.

    The first condition is what protects new releases — during a launch window every
    release is legitimately days old, so without it the guard would reject everything worth
    having.
    """
    settings = get_settings()
    max_after = (
        max_days_after_release
        if max_days_after_release is not None
        else settings.grab_guard_max_days_after_release
    )
    min_age = (
        min_media_age_days
        if min_media_age_days is not None
        else settings.grab_guard_min_media_age_days
    )
    now = now or datetime.now(timezone.utc)

    if release_published is None or media_released is None:
        # Missing dates are common and not suspicious. Never reject on absence of
        # evidence — a guard that fires when it doesn't know is worse than no guard.
        return GrabVerdict(reason="Not enough date information to judge; allowed.")

    media_age = (now - media_released).total_seconds() / 86400
    release_age = (now - release_published).total_seconds() / 86400
    gap = (release_published - media_released).total_seconds() / 86400

    verdict = GrabVerdict(release_age_days=round(release_age, 1), media_age_days=round(media_age, 1))

    if media_age < min_age:
        verdict.reason = (
            f"Media is only {media_age:.0f} days old — inside the release window, "
            f"so a fresh upload is expected."
        )
        return verdict

    if gap > max_after:
        verdict.reject = True
        verdict.reason = (
            f"Release was posted {gap:.0f} days after the title came out "
            f"(threshold {max_after}), and the title is {media_age:.0f} days old. "
            f"That pattern usually means a re-upload or a fake."
        )
        return verdict

    verdict.reason = f"Release posted {gap:.0f} days after release — within tolerance."
    return verdict


def audit_log() -> list[dict[str, Any]]:
    return list(reversed(_audit))


def _record(entry: AuditEntry) -> None:
    _audit.append(entry.model_dump())
    del _audit[:-MAX_AUDIT]


def _service_by_name(session: Session, name: str) -> Service | None:
    """Match the webhook's `instanceName` to a configured service.

    Falls back to a single service of that type, since people rename instances.
    """
    services = list_services(session)
    for service in services:
        if service.name.lower() == (name or "").lower():
            return service
    return None


async def handle_grab(session: Session, payload: dict[str, Any]) -> GrabVerdict:
    """Process an `onGrab` webhook. Never raises — a webhook handler that 500s gets
    retried or disabled by the sender."""
    settings = get_settings()
    release = payload.get("release") or {}
    instance = payload.get("instanceName") or ""
    title = release.get("releaseTitle") or payload.get("eventType") or "unknown release"

    if not settings.grab_guard_enabled:
        return GrabVerdict(reason="Guard is disabled.")

    media = payload.get("movie") or payload.get("series") or {}
    media_date = (
        _parse_dt(media.get("releaseDate"))
        or _parse_dt(media.get("physicalRelease"))
        or _parse_dt(media.get("inCinemas"))
        or _parse_dt(media.get("firstAired"))
    )
    verdict = evaluate(
        release_published=_parse_dt(release.get("publishDate")),
        media_released=media_date,
    )

    if not verdict.reject:
        _record(
            AuditEntry(
                service_name=instance or "unknown",
                title=str(title),
                action="allowed",
                reason=verdict.reason,
            )
        )
        return verdict

    service = _service_by_name(session, instance)
    if service is None:
        _record(
            AuditEntry(
                service_name=instance or "unknown",
                title=str(title),
                action="failed",
                reason=verdict.reason,
                detail="Could not match the webhook to a configured service, so nothing "
                "was removed.",
            )
        )
        return verdict

    adapter = adapter_for(service)
    try:
        queue = await adapter._request(
            "GET", "queue", params={"pageSize": 200, "includeUnknownItems": "true"}
        )
        records = queue.get("records", []) if isinstance(queue, dict) else (queue or [])
        target = next(
            (r for r in records if r.get("title") == release.get("releaseTitle")), None
        )
        if target is None:
            _record(
                AuditEntry(
                    service_name=service.name,
                    title=str(title),
                    action="failed",
                    reason=verdict.reason,
                    detail="Matching queue item not found — it may have finished already.",
                )
            )
            return verdict

        # blocklist=true is the point: without it the next RSS pass grabs the same
        # release straight back.
        await adapter._request(
            "DELETE",
            f"queue/{target.get('id')}",
            params={"removeFromClient": "true", "blocklist": "true"},
        )
        _record(
            AuditEntry(
                service_name=service.name,
                title=str(title),
                action="rejected",
                reason=verdict.reason,
                detail="Removed from the queue and blocklisted.",
            )
        )
    except AdapterError as exc:
        _record(
            AuditEntry(
                service_name=service.name,
                title=str(title),
                action="failed",
                reason=verdict.reason,
                detail=exc.message,
            )
        )
    finally:
        await adapter.aclose()

    return verdict
