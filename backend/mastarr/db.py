"""SQLite engine and session management."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine, select

from .config import Settings, get_settings

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

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
            log.warning(
                "Database schema version %s does not match expected %s",
                existing.version,
                SCHEMA_VERSION,
            )


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a database session."""
    with Session(get_engine()) as session:
        yield session


def reset_engine() -> None:
    """Test hook — drops the cached engine so a new database path takes effect."""
    global _engine
    _engine = None
