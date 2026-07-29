"""Poster/artwork proxy for *arr-hosted images.

Why proxy at all, when *arr covers need no API key? Because it keeps everything on one
origin: the browser never has to reach the *arr directly, so Mastarr works unchanged behind
a reverse proxy, over HTTPS, or from outside the LAN — and the *arr URLs stay private.

Jellyseerr posters are deliberately NOT proxied: they come from TMDB's CDN, which the
browser can fetch directly and which is far better at serving images than we are.
"""

from __future__ import annotations

import logging
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session

from ..adapters import AdapterError
from ..aggregate import find_service
from ..auth.deps import require_requester
from ..db import get_session
from ..services import adapter_for

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/images", tags=["images"], dependencies=[Depends(require_requester)]
)

# Only paths the *arrs actually serve artwork from. Without an allowlist this endpoint
# would happily fetch ANY path on a configured service using its stored API key —
# turning an authenticated image proxy into a way to read the whole *arr API, and to
# probe the LAN. The allowlist is the security control here, not an optimisation.
ALLOWED_PREFIXES = ("MediaCover/", "mediacover/")

# A day: artwork changes rarely, and posters dominate the byte count of the library grid.
CACHE_SECONDS = 86400


@router.get("/{service_id}/{path:path}")
async def get_image(
    service_id: int, path: str, session: Session = Depends(get_session)
) -> Response:
    clean = unquote(path).lstrip("/")

    # Reject traversal before the prefix check, so `MediaCover/../../etc/passwd` can't
    # satisfy the allowlist and then escape.
    if ".." in clean or clean.startswith("/") or "\\" in clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image path."
        )
    if not clean.startswith(ALLOWED_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only cover art may be fetched through this endpoint.",
        )

    service = find_service(session, service_id)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such service."
        )

    adapter = adapter_for(service)
    try:
        body, content_type = await adapter.image_bytes(clean)
    except AdapterError as exc:
        # A missing poster must not break the grid — the UI falls back to a placeholder.
        log.debug("image fetch failed for service %s: %s", service_id, exc.message)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image unavailable."
        ) from exc
    finally:
        await adapter.aclose()

    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": f"private, max-age={CACHE_SECONDS}"},
    )
