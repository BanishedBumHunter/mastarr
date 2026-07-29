"""Mastarr's own settings. Admin-only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session

from ..auth.deps import require_admin
from ..config import get_settings, set_db_overrides
from ..db import get_session
from .. import settings_store

router = APIRouter(
    prefix="/settings", tags=["settings"], dependencies=[Depends(require_admin)]
)


class SettingUpdate(BaseModel):
    key: str
    # `None` clears the stored override so the value falls back to YAML or the default.
    value: object | None = None


def _refresh(session: Session) -> None:
    """Re-install the DB layer so the change takes effect without a restart."""
    set_db_overrides(settings_store.read_all(session))


@router.get("")
async def list_settings(session: Session = Depends(get_session)) -> list[dict]:
    """Every editable setting with its effective value and which layer owns it."""
    return settings_store.describe(session)


@router.put("")
async def update_setting(
    body: SettingUpdate, session: Session = Depends(get_session)
) -> list[dict]:
    # Refuse rather than accept-and-ignore: an edit to an env-controlled setting would
    # save fine and then do nothing, which is maddening to debug.
    if settings_store.source_of(body.key) in ("env", "file"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{body.key}' is set by the environment or config file, which take "
                f"precedence over the database. Change it there instead."
            ),
        )

    try:
        if body.value is None:
            settings_store.clear(session, body.key)
        else:
            settings_store.write(session, body.key, body.value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    session.commit()
    _refresh(session)
    return settings_store.describe(session)


@router.get("/about")
async def about() -> dict[str, object]:
    """Read-only facts about this instance, for the footer of the General tab."""
    from .. import __version__
    from ..db import SCHEMA_VERSION

    settings = get_settings()
    return {
        "version": __version__,
        "schema_version": SCHEMA_VERSION,
        "data_dir": str(settings.data_dir),
        "config_file": str(settings.config_file) if settings.config_file else None,
    }
