"""Cross-stack configuration: compare, preview, push.

The brief asked to "standardize settings across services and offer to apply to all". The
hard part is that **not everything is portable**, and pushing something that isn't corrupts
the target. Verified against a live stack:

- A **quality profile** is a list of quality *IDs*, and the IDs mean different things per
  service type. Sonarr's vocabulary is `SDTV`/`DVD`/`Bluray-480p`; Radarr's is
  `WORKPRINT`/`CAM`/`TELESYNC`. Copying a Sonarr profile into Radarr yields a profile
  referencing qualities that don't exist there.
- **Naming** is per-type too: Sonarr has `animeEpisodeFormat`/`seasonFolderFormat`, Radarr
  has `movieFolderFormat`/`standardMovieFormat`. Only two fields are shared.
- **Custom formats** are specification-based (regex over release names) and portable
  anywhere.
- **Root folders** and **download clients** share a schema across types.

So compatibility is computed, surfaced, and enforced — a target that can't take a resource
is reported `incompatible` rather than being written to and quietly broken.

Nothing is ever written by the preview path. `apply` re-reads the target before writing so
it can't act on a stale diff.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from sqlmodel import Session

from .adapters import AdapterError, UnknownServiceType, get_adapter_class
from .models import Service
from .services import adapter_for, list_services

log = logging.getLogger(__name__)


class Portability(str, Enum):
    """How far a config resource can travel."""

    ANY = "any"  # any *arr that has the endpoint
    SAME_MEDIA_KIND = "same_media_kind"  # series -> series, movie -> movie


PORTABILITY: dict[str, Portability] = {
    "custom_format": Portability.ANY,
    "root_folder": Portability.ANY,
    "download_client": Portability.ANY,
    "quality_profile": Portability.SAME_MEDIA_KIND,
    "naming": Portability.SAME_MEDIA_KIND,
}

# The field each resource is matched on when deciding create-vs-update. Not `id`: ids are
# per-service, so the same profile has different ids everywhere.
MATCH_FIELD: dict[str, str] = {
    "quality_profile": "name",
    "custom_format": "name",
    "root_folder": "path",
    "download_client": "name",
}

# Fields that are meaningless to compare or copy — service-local identity and derived
# state. Copying `id` would collide; copying `freeSpace` would be nonsense.
IGNORED_FIELDS = frozenset(
    {"id", "freeSpace", "unmappedFolders", "accessible", "totalSpace", "tags"}
)

# The only naming fields that mean the same thing in every *arr.
SHARED_NAMING_FIELDS = frozenset({"colonReplacementFormat", "replaceIllegalCharacters"})

# Presentation and derived metadata inside nested objects (custom format specifications,
# download client fields). The target service regenerates all of it, and some of it is
# service-branded — `infoLink` on a Sonarr custom format points at the *sonarr* wiki, and
# Radarr rewrites it to its own on save.
#
# Without stripping these, a format copied to another service compares as different
# forever after, so a correctly-synced item shows a permanent "update available". Compare
# behaviour, not the service's own UI labels.
COSMETIC_NESTED_FIELDS = frozenset(
    {
        "infoLink",
        "implementationName",
        "label",
        "helpText",
        "helpTextWarning",
        "helpLink",
        "order",
        "unit",
        "type",
        "advanced",
        "privacy",
        "placeholder",
        "section",
        "selectOptions",
        "selectOptionsProviderAction",
        "hidden",
        "isFloat",
        "presets",
    }
)


def _strip_cosmetic(value: Any) -> Any:
    """Recursively drop presentation metadata so diffs reflect real behaviour."""
    if isinstance(value, dict):
        return {
            k: _strip_cosmetic(v)
            for k, v in value.items()
            if k not in COSMETIC_NESTED_FIELDS and k != "id"
        }
    if isinstance(value, list):
        return [_strip_cosmetic(v) for v in value]
    return value


class Action(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    IDENTICAL = "identical"
    INCOMPATIBLE = "incompatible"
    ERROR = "error"


class FieldDiff(BaseModel):
    field: str
    current: Any = None
    proposed: Any = None


class TargetPlan(BaseModel):
    """What would happen to one service."""

    service_id: int
    service_name: str
    service_type: str
    action: Action
    reason: str | None = None
    target_item_id: int | None = None
    changes: list[FieldDiff] = Field(default_factory=list)


class SyncPreview(BaseModel):
    resource: str
    source_service_id: int
    source_service_name: str
    item_name: str
    targets: list[TargetPlan] = Field(default_factory=list)


class ApplyResult(BaseModel):
    service_id: int
    service_name: str
    action: Action
    ok: bool
    detail: str | None = None


def _media_kind(service: Service) -> str | None:
    try:
        return get_adapter_class(service.service_type).media_kind
    except UnknownServiceType:
        return None


def _supports(service: Service, resource: str) -> bool:
    """Uses the adapter's own `unsupported` set via the shared guard-name mapping, so a
    type only ever has to declare a gap once."""
    from .adapters.base import CONFIG_GUARD

    try:
        cls = get_adapter_class(service.service_type)
    except UnknownServiceType:
        return False
    return CONFIG_GUARD.get(resource, resource) not in cls.unsupported


def compatibility(source: Service, target: Service, resource: str) -> tuple[bool, str | None]:
    """Can `resource` move from source to target? Returns (ok, reason-if-not)."""
    if target.id == source.id:
        return False, "This is the source service."
    if not _supports(target, resource):
        display = get_adapter_class(target.service_type).display_name
        return False, f"{display} has no {resource.replace('_', ' ')}s."

    if PORTABILITY[resource] is Portability.SAME_MEDIA_KIND:
        source_kind, target_kind = _media_kind(source), _media_kind(target)
        if source_kind != target_kind:
            return False, (
                f"{resource.replace('_', ' ').title()}s are specific to "
                f"{source_kind} services and can't be copied to a {target_kind} service — "
                f"the two use different quality definitions."
            )
    return True, None


def _comparable(payload: dict[str, Any], resource: str) -> dict[str, Any]:
    """Strip fields that are service-local, derived, or purely cosmetic.

    Applied to both sides of a diff *and* to the body that gets written, so what you were
    shown is what gets sent.
    """
    cleaned = {
        k: _strip_cosmetic(v) for k, v in payload.items() if k not in IGNORED_FIELDS
    }
    if resource == "naming":
        # Only the genuinely shared fields travel; the rest are per-type formats.
        return {k: v for k, v in cleaned.items() if k in SHARED_NAMING_FIELDS}
    return cleaned


def _diff(current: dict[str, Any], proposed: dict[str, Any], resource: str) -> list[FieldDiff]:
    left = _comparable(current, resource)
    right = _comparable(proposed, resource)
    return [
        FieldDiff(field=key, current=left.get(key), proposed=right[key])
        for key in sorted(right)
        if left.get(key) != right[key]
    ]


async def preview(
    session: Session,
    *,
    resource: str,
    source_service_id: int,
    item_id: int,
    target_service_ids: list[int] | None = None,
) -> SyncPreview:
    """Work out what pushing one item everywhere would do. Writes nothing."""
    if resource not in PORTABILITY:
        raise ValueError(f"Unknown config resource '{resource}'.")

    source = session.get(Service, source_service_id)
    if source is None:
        raise ValueError("Source service not found.")

    source_adapter = adapter_for(source)
    try:
        if resource == "naming":
            item = await source_adapter.get_naming()
            item_name = "Naming scheme"
        else:
            items = await source_adapter.raw_config(resource)
            item = next((i for i in items if i.get("id") == item_id), None)
            if item is None:
                raise ValueError("Item not found on the source service.")
            item_name = str(item.get(MATCH_FIELD[resource], item_id))
    finally:
        await source_adapter.aclose()

    candidates = list_services(session)
    if target_service_ids:
        wanted = set(target_service_ids)
        candidates = [s for s in candidates if s.id in wanted]

    plans: list[TargetPlan] = []
    for target in candidates:
        base = TargetPlan(
            service_id=target.id or 0,
            service_name=target.name,
            service_type=target.service_type,
            action=Action.INCOMPATIBLE,
        )
        ok, reason = compatibility(source, target, resource)
        if not ok:
            base.reason = reason
            plans.append(base)
            continue

        adapter = adapter_for(target)
        try:
            if resource == "naming":
                existing = await adapter.get_naming()
                changes = _diff(existing, item, resource)
                base.target_item_id = existing.get("id")
                base.action = Action.IDENTICAL if not changes else Action.UPDATE
                base.changes = changes
            else:
                existing_items = await adapter.raw_config(resource)
                key = MATCH_FIELD[resource]
                match = next(
                    (i for i in existing_items if i.get(key) == item.get(key)), None
                )
                if match is None:
                    base.action = Action.CREATE
                    base.changes = _diff({}, item, resource)
                else:
                    changes = _diff(match, item, resource)
                    base.target_item_id = match.get("id")
                    base.action = Action.IDENTICAL if not changes else Action.UPDATE
                    base.changes = changes
        except AdapterError as exc:
            base.action = Action.ERROR
            base.reason = exc.message
        finally:
            await adapter.aclose()

        plans.append(base)

    return SyncPreview(
        resource=resource,
        source_service_id=source_service_id,
        source_service_name=source.name,
        item_name=item_name,
        targets=plans,
    )


async def apply(
    session: Session,
    *,
    resource: str,
    source_service_id: int,
    item_id: int,
    target_service_ids: list[int],
) -> list[ApplyResult]:
    """Push an item to the named targets.

    Re-runs the preview first rather than trusting a plan the client sends back: the
    target may have changed since it was generated, and a stale diff would overwrite work
    done in the meantime. Only targets the fresh preview marks CREATE or UPDATE are
    written.
    """
    plan = await preview(
        session,
        resource=resource,
        source_service_id=source_service_id,
        item_id=item_id,
        target_service_ids=target_service_ids,
    )

    source = session.get(Service, source_service_id)
    if source is None:
        raise ValueError("Source service not found.")

    source_adapter = adapter_for(source)
    try:
        if resource == "naming":
            payload = await source_adapter.get_naming()
        else:
            items = await source_adapter.raw_config(resource)
            payload = next((i for i in items if i.get("id") == item_id), {})
    finally:
        await source_adapter.aclose()

    body = _comparable(payload, resource)
    results: list[ApplyResult] = []

    for target_plan in plan.targets:
        if target_plan.action in (Action.INCOMPATIBLE, Action.ERROR):
            results.append(
                ApplyResult(
                    service_id=target_plan.service_id,
                    service_name=target_plan.service_name,
                    action=target_plan.action,
                    ok=False,
                    detail=target_plan.reason,
                )
            )
            continue
        if target_plan.action is Action.IDENTICAL:
            results.append(
                ApplyResult(
                    service_id=target_plan.service_id,
                    service_name=target_plan.service_name,
                    action=Action.IDENTICAL,
                    ok=True,
                    detail="Already matches — nothing to do.",
                )
            )
            continue

        target = session.get(Service, target_plan.service_id)
        if target is None:
            continue
        adapter = adapter_for(target)
        try:
            if resource == "naming":
                await adapter.update_naming(body)
            elif target_plan.action is Action.CREATE:
                await adapter.create_config(resource, body)
            else:
                await adapter.update_config(
                    resource, target_plan.target_item_id or 0, body
                )
            results.append(
                ApplyResult(
                    service_id=target_plan.service_id,
                    service_name=target_plan.service_name,
                    action=target_plan.action,
                    ok=True,
                )
            )
        except AdapterError as exc:
            results.append(
                ApplyResult(
                    service_id=target_plan.service_id,
                    service_name=target_plan.service_name,
                    action=target_plan.action,
                    ok=False,
                    detail=exc.message,
                )
            )
        finally:
            await adapter.aclose()

    return results


async def collect(session: Session, resource: str) -> list[dict[str, Any]]:
    """Every instance of a config resource across all services, for the settings tabs."""
    out: list[dict[str, Any]] = []
    for service in list_services(session):
        if not _supports(service, resource):
            continue
        adapter = adapter_for(service)
        try:
            items = (
                [await adapter.get_naming()]
                if resource == "naming"
                else await adapter.raw_config(resource)
            )
            for item in items:
                out.append(
                    {
                        "service_id": service.id,
                        "service_name": service.name,
                        "service_type": service.service_type,
                        "media_kind": _media_kind(service),
                        "item": item,
                    }
                )
        except AdapterError as exc:
            log.debug("collect %s failed for %s: %s", resource, service.name, exc.message)
        finally:
            await adapter.aclose()
    return out
