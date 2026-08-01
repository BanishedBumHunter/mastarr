"""Upgrade sweep and grab guard.

The webhook receiver is the one endpoint in Mastarr that is *not* behind the admin role:
the *arrs call it machine-to-machine and can't hold a session. It's protected by a shared
token instead, and it only ever accepts a payload — it returns no data.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlmodel import Session

from .. import grab_guard, sweeper
from ..auth.deps import require_admin
from ..auth.security import load_or_create_jwt_secret
from ..config import get_settings
from ..db import get_session

router = APIRouter(prefix="/automation", tags=["automation"])


def webhook_token() -> str:
    """Stable per-install token the *arrs include when calling back.

    Derived from the JWT secret rather than stored separately, so there's one less thing
    to persist and rotate — and rotating sessions correctly invalidates stale webhooks too.
    """
    import hashlib

    secret = load_or_create_jwt_secret(get_settings())
    return hashlib.sha256(f"webhook:{secret}".encode()).hexdigest()[:32]


# ------------------------------------------------------------------- sweep


@router.get("/sweep", dependencies=[Depends(require_admin)])
async def sweep_status(session: Session = Depends(get_session)) -> sweeper.SweepStatus:
    """Sweep state plus how many items are below cutoff per service."""
    return await sweeper.status(session)


@router.post("/sweep/run", dependencies=[Depends(require_admin)])
async def run_sweep(
    include_missing: bool | None = Query(None),
    session: Session = Depends(get_session),
) -> list[sweeper.SweepResult]:
    """Sweep now, regardless of schedule."""
    settings = get_settings()
    return await sweeper.run_sweep(
        session,
        include_missing=(
            settings.sweep_include_missing if include_missing is None else include_missing
        ),
    )


# -------------------------------------------------------------- grab guard


@router.get("/guard/audit", dependencies=[Depends(require_admin)])
async def guard_audit() -> list[dict]:
    """Everything the guard has done. It must never act invisibly."""
    return grab_guard.audit_log()


@router.get("/guard/webhook-url", dependencies=[Depends(require_admin)])
async def guard_webhook_url(request: Request) -> dict[str, str]:
    """The URL to paste into each *arr's Webhook connection."""
    base = str(request.base_url).rstrip("/")
    return {
        "url": f"{base}/api/automation/guard/webhook?token={webhook_token()}",
        "method": "POST",
        "note": "Add this as a Webhook connection in each service, with 'On Grab' enabled.",
    }


@router.post("/guard/webhook", status_code=status.HTTP_202_ACCEPTED)
async def guard_webhook(
    request: Request,
    token: str = Query(...),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Receive an *arr webhook. Token-authenticated, since services can't hold a session."""
    if not hmac.compare_digest(token, webhook_token()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token."
        )

    payload = await request.json()
    event = (payload or {}).get("eventType")

    # Sonarr sends a Test event when you press Test. Acknowledge it so the button goes
    # green, but don't run the rule against a fabricated payload.
    if event in ("Test", "test"):
        return {"ok": True, "detail": "Test received."}
    if event not in ("Grab", "grab"):
        return {"ok": True, "detail": f"Ignoring {event} event."}

    verdict = await grab_guard.handle_grab(session, payload)
    return {"ok": True, "rejected": verdict.reject, "reason": verdict.reason}
