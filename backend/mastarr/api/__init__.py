"""HTTP API routers."""

from fastapi import APIRouter

from .. import __version__
from . import (
    activity,
    auth,
    calendar,
    config,
    dashboard,
    discover,
    discovery,
    images,
    library,
    services,
    settings,
    users,
)

api_router = APIRouter(prefix="/api")


@api_router.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Mastarr's own liveness — deliberately unauthenticated, for container health checks.

    Lives on the router rather than the app so it travels with the API wherever the
    router is mounted.
    """
    return {"status": "ok", "version": __version__}


api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(services.router)
api_router.include_router(discovery.router)
api_router.include_router(dashboard.router)
api_router.include_router(calendar.router)
api_router.include_router(library.router)
api_router.include_router(activity.router)
api_router.include_router(discover.router)
api_router.include_router(images.router)
api_router.include_router(settings.router)
api_router.include_router(config.router)

__all__ = ["api_router"]
