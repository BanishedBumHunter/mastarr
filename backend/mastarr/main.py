"""FastAPI application: serves the API and the built frontend from one container."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from . import __version__
from .adapters import AdapterError
from .api import api_router
from .config import get_settings
from .db import get_engine, init_db
from .logging import configure_logging
from .services import sync_config_services

log = logging.getLogger(__name__)

# Populated by the Docker build; absent in local dev, where Vite serves the UI instead.
FRONTEND_DIR = Path(__file__).resolve().parent / "static"


def _preflight_data_dir(settings) -> None:
    """Fail with an actionable message when the data volume isn't writable.

    Without this the first symptom is SQLAlchemy's `unable to open database file`, which
    reads like a database bug rather than "your mounted directory is owned by the wrong
    uid". That is by far the most common install failure, so it is worth catching by name.
    """
    import os

    data_dir = settings.data_dir
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Cannot create the data directory {data_dir}: {exc}.\n"
            f"Mastarr runs as uid {os.getuid()}. Give that user ownership of the "
            f"directory you mounted at {data_dir} — e.g. "
            f"`chown -R {os.getuid()}:{os.getgid()} /path/to/your/mastarr/config` on the "
            f"host — or set `user:` in your compose file to a uid that already owns it."
        ) from exc

    probe = data_dir / ".write-test"
    try:
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        raise RuntimeError(
            f"The data directory {data_dir} is not writable: {exc}.\n"
            f"Mastarr runs as uid {os.getuid()}:{os.getgid()}. Either give that user "
            f"ownership of the host directory you mounted there — e.g. "
            f"`chown -R {os.getuid()}:{os.getgid()} /path/to/your/mastarr/config` — or "
            f"set `user: \"<uid>:<gid>\"` in your compose file to match the existing owner."
        ) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    _preflight_data_dir(settings)
    init_db(settings)

    with Session(get_engine()) as session:
        count = sync_config_services(session)
        if count:
            log.info("Reconciled %d service(s) from config file", count)

    log.info("Mastarr %s ready — data dir %s", __version__, settings.data_dir)
    yield


app = FastAPI(
    title="Mastarr",
    version=__version__,
    description="A unified control plane for the *arr stack.",
    lifespan=lifespan,
)

app.include_router(api_router)


@app.exception_handler(AdapterError)
async def adapter_error_handler(request, exc: AdapterError) -> JSONResponse:
    """Last-resort net.

    Adapter errors should be caught where they are raised; this exists so that one that
    slips through becomes an honest 502 rather than a 500 that reads like a Mastarr bug.
    """
    log.warning("Unhandled adapter error on %s: %s", request.url.path, exc.message)
    return JSONResponse(status_code=502, content={"detail": exc.message})


def _mount_frontend() -> None:
    """Serve the built SPA, if it was bundled into the image."""
    if not FRONTEND_DIR.is_dir():
        log.info("No bundled frontend at %s — API-only mode", FRONTEND_DIR)
        return

    assets = FRONTEND_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index = FRONTEND_DIR / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """Client-side routing: serve real files, fall back to index.html for routes.

        Registered last, so it only sees paths no real route matched. The explicit /api
        guard matters anyway: without it, a typo'd or wrong-method API request returns
        index.html with a 200, which looks like success to any API client and hides
        genuine 404s and 405s behind a page of HTML.
        """
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found."})

        candidate = (FRONTEND_DIR / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(FRONTEND_DIR.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(index)


_mount_frontend()
