"""SQLite engine and session management."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine, select

from .config import Settings, get_settings

log = logging.getLogger(__name__)

SCHEMA_VERSION = 4

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            f"sqlite:///{settings.db_path}",
            # FastAPI serves requests across threads; SQLite objects are otherwise
            # pinned to their creating thread.
            connect_args={"check_same_thread": False},
        )
    return _engine


def init_db(settings: Settings | None = None) -> None:
    """Create tables and stamp the schema version.

    No migration framework by design while the project is INACTIVE — see CLAUDE.md. The
    stamped version exists so that a future Alembic baseline knows where it started.
    """
    from . import models  # noqa: F401  — registers tables on SQLModel.metadata

    engine = get_engine()
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        existing = session.exec(select(models.SchemaVersion)).first()
        if existing is None:
            session.add(models.SchemaVersion(version=SCHEMA_VERSION))
            session.commit()
        elif existing.version != SCHEMA_VERSION:
            # Migrations are additive-only while the project is INACTIVE (see CLAUDE.md).
            # create_all above adds new tables but never new columns, so additive column
            # changes are applied here explicitly until Alembic lands.
            _apply_additive_migrations(session, existing.version)
            existing.version = SCHEMA_VERSION
            session.add(existing)
            session.commit()
            log.info("Database schema upgraded to version %s", SCHEMA_VERSION)


def _apply_additive_migrations(session: Session, from_version: int) -> None:
    """Add columns that `create_all` cannot add to an existing table.

    Deliberately minimal and additive-only: no drops, no renames, no data rewrites. If a
    change ever needs more than this, that is the signal to adopt Alembic rather than to
    grow this function.
    """
    from sqlalchemy import text

    # v3 adds the app_setting table, which create_all handles on its own — no column
    # change needed, so there is nothing to do here for it.

    if from_version < 2:
        columns = {
            row[1]
            for row in session.exec(text("PRAGMA table_info(user)")).all()  # type: ignore[arg-type]
        }
        if "jellyseerr_user_id" not in columns:
            session.exec(text("ALTER TABLE user ADD COLUMN jellyseerr_user_id INTEGER"))  # type: ignore[arg-type]
            log.info("Added user.jellyseerr_user_id")

    if from_version < 4:
        # v4: password-authenticated service types need somewhere to keep the username.
        columns = {
            row[1]
            for row in session.exec(text("PRAGMA table_info(service)")).all()  # type: ignore[arg-type]
        }
        if "username" not in columns:
            session.exec(text("ALTER TABLE service ADD COLUMN username VARCHAR"))  # type: ignore[arg-type]
            log.info("Added service.username")


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a database session."""
    with Session(get_engine()) as session:
        yield session


def reset_engine() -> None:
    """Test hook — drops the cached engine so a new database path takes effect."""
    global _engine
    _engine = None
