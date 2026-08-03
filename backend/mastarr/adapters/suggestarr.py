"""SuggestArr — recommendation engine with an approval queue.

SuggestArr watches what you've actually finished and proposes more of it, then (in
approval mode) parks each proposal in a queue instead of requesting it outright. That
queue is the reason this adapter exists: it is a decision surface, and Mastarr already
owns the other decision surfaces.

It is the odd one out in three ways, all of them handled here rather than leaking into
the base:

* **Auth is a login, not a key.** Username and password are traded for a short-lived
  bearer token. Every other type takes a static `X-Api-Key`.
* **The API prefix is `/api`**, with no version segment.
* **No `system/status`.** Identity comes from `/api/health`, so discovery cannot confirm
  it the usual way.

Contract read from the project's own `api_service/blueprints/` — SuggestArr publishes no
API documentation, so this adapter is pinned to route shapes that upstream is free to
change. It is deliberately small for that reason: five calls, all inside one file.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

import httpx

from ..logging import register_secret
from .base import ArrAdapter
from .errors import ServiceError, ServiceUnauthorized, ServiceUnreachable
from .schemas import (
    HealthIssue,
    HealthSeverity,
    Suggestion,
    SuggestionPage,
    SystemStatus,
)

# Statuses SuggestArr's own routes accept. Anything else is a 400 from its side, so it is
# rejected here instead of round-tripping to find out.
SUGGESTION_STATUSES = (
    "awaiting_approval",
    "queued",
    "submitting",
    "submitted",
    "rejected",
    "failed",
)

# Access tokens are short-lived and every Mastarr request builds a fresh adapter, so
# without a cache each call would cost an extra login round trip — and SuggestArr rate
# limits its own auth endpoints. Keyed by (url, username); cleared whenever a token is
# rejected. Holds tokens only, never passwords.
_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}
_TOKEN_TTL_SECONDS = 10 * 60


def forget_tokens() -> None:
    """Drop every cached token. Called when a service's credentials change."""
    _TOKEN_CACHE.clear()


class SuggestArrAdapter(ArrAdapter):
    service_type: ClassVar[str] = "suggestarr"
    display_name: ClassVar[str] = "SuggestArr"
    app_name: ClassVar[str] = "suggestarr"
    default_port: ClassVar[int] = 5000
    alternate_ports: ClassVar[tuple[int, ...]] = (5001, 8080)
    probe_path: ClassVar[str] = "api/health"
    media_endpoint: ClassVar[str | None] = None
    media_kind: ClassVar[str] = "suggestion"
    requires_username: ClassVar[bool] = True

    # SuggestArr is a recommender, not a library manager. It shares the HTTP transport
    # and nothing else — every one of these 404s or means nothing here.
    unsupported: ClassVar[frozenset[str]] = frozenset(
        {
            "backups",
            "logs",
            "updates",
            "tasks",
            "restart",
            "disk_space",
            "queue",
            "history",
            "calendar",
            "library",
            "wanted_missing",
            "seasons",
            "search",
            "search_command",
            "quality_profiles",
            "root_folders",
            "custom_formats",
            "naming",
            "indexers",
            "download_clients",
            "import_lists",
            "notifications",
            "metadata",
            "delay_profiles",
            "release_profiles",
            "quality_definitions",
            "tags",
            "remote_path_mappings",
            "import_list_exclusions",
            "download_client_options",
            "host",
            "ui",
        }
    )

    def __init__(self, *args: Any, username: str | None = None, **kwargs: Any) -> None:
        # `api_key` carries the password: it is the one field that is already Fernet
        # encrypted at rest and already registered for log redaction. Giving passwords a
        # second, parallel storage path would mean a second thing to get wrong.
        super().__init__(*args, **kwargs)
        self.username = username

    @property
    def api_base(self) -> str:
        """`/api`, with no version segment — unlike every *arr and Jellyseerr."""
        return f"{self.url}/api"

    @classmethod
    def matches_probe(cls, payload: Any) -> bool:
        """`/api/health` answers with a status field; there is no `/ping` here."""
        if not isinstance(payload, dict):
            return False
        return "status" in payload or "healthy" in payload

    # --------------------------------------------------------------------- auth

    @property
    def _cache_key(self) -> tuple[str, str]:
        return (self.url, self.username or "")

    async def _login(self) -> str:
        """Trade username and password for an access token.

        Deliberately not routed through `_request`: that method calls `_auth_headers`,
        and asking for credentials in order to obtain credentials is a loop.
        """
        if not self.username or not self.api_key:
            raise ServiceUnauthorized(
                f"{self.display_name} needs a username and password, not an API key.",
                service=self.name,
            )
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.api_base}/auth/login",
                json={"username": self.username, "password": self.api_key},
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise ServiceUnreachable(
                f"Could not reach {self.url}: {type(exc).__name__}", service=self.name
            ) from exc

        if response.status_code in (401, 403):
            raise ServiceUnauthorized(
                "SuggestArr rejected the username or password.", service=self.name
            )
        if response.status_code >= 400:
            raise ServiceError(
                f"{self.name} returned HTTP {response.status_code} from login",
                service=self.name,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ServiceError(
                f"{self.name} returned a non-JSON login response. Check the URL points "
                f"at SuggestArr itself and not a proxy or login page.",
                service=self.name,
            ) from exc

        token = (payload or {}).get("access_token")
        if not token:
            raise ServiceError(
                "SuggestArr's login response carried no access token.", service=self.name
            )
        # A bearer token is a live credential for as long as it lasts, so it joins the
        # same redaction set as the API keys — rule 9 is about secrets, not about keys.
        register_secret(str(token))
        _TOKEN_CACHE[self._cache_key] = (str(token), time.monotonic() + _TOKEN_TTL_SECONDS)
        return str(token)

    async def _auth_headers(self) -> dict[str, str]:
        cached = _TOKEN_CACHE.get(self._cache_key)
        if cached and cached[1] > time.monotonic():
            return {"Authorization": f"Bearer {cached[0]}"}
        return {"Authorization": f"Bearer {await self._login()}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """One retry on 401, because a cached token can expire mid-flight.

        The TTL here is a guess at SuggestArr's, not a reading of it — the token's own
        expiry is authoritative and we don't parse it. So the rejection, not the clock,
        is what actually decides a token is dead.
        """
        try:
            return await super()._request(method, path, **kwargs)
        except ServiceUnauthorized:
            if self._cache_key not in _TOKEN_CACHE:
                raise  # Never had a token — the credentials are wrong, not stale.
            _TOKEN_CACHE.pop(self._cache_key, None)
            return await super()._request(method, path, **kwargs)

    async def ping(self) -> bool:
        """Unauthenticated liveness. `/api/health` is open; there is no `/ping`."""
        try:
            result = await self._request(
                "GET", f"{self.api_base}/health", absolute=True
            )
        except Exception:
            return False
        return isinstance(result, dict)

    # -------------------------------------------------------------- suggestions

    def _parse(self, item: dict[str, Any]) -> Suggestion:
        return Suggestion(
            id=int(item.get("id") or 0),
            service_id=self.service_id,
            service_name=self.name,
            tmdb_id=int(item["tmdb_id"]) if item.get("tmdb_id") else None,
            media_kind=item.get("media_type") or item.get("media_kind") or "",
            title=item.get("title") or item.get("name") or "Untitled",
            year=int(item["year"]) if str(item.get("year") or "").isdigit() else None,
            overview=item.get("overview"),
            poster_url=item.get("poster_url") or item.get("poster_path"),
            status=item.get("status") or "",
            # The whole point of a suggestion: what it was suggested *from*. Without it
            # the queue is a list of titles with no reason attached, and every approval
            # is a coin flip.
            source_title=item.get("source_title") or item.get("based_on"),
            rating=float(item["rating"]) if item.get("rating") is not None else None,
            requested_by=item.get("requested_by") or item.get("owner_username"),
            created_at=self._parse_dt(item.get("created_at")),
        )

    async def suggestions(
        self,
        *,
        status: str = "awaiting_approval",
        page: int = 1,
        per_page: int = 24,
        search: str = "",
    ) -> SuggestionPage:
        if status not in SUGGESTION_STATUSES:
            raise ServiceError(
                f"'{status}' is not a SuggestArr suggestion status. "
                f"Known: {', '.join(SUGGESTION_STATUSES)}.",
                service=self.name,
            )
        params: dict[str, Any] = {
            "status": status,
            "page": max(1, page),
            "per_page": max(1, min(per_page, 100)),
        }
        if search:
            params["search"] = search[:100]
        data = await self._request("GET", "jobs/suggestions", params=params)
        if not isinstance(data, dict):
            return SuggestionPage(page=page, per_page=per_page)
        return SuggestionPage(
            items=[self._parse(i) for i in data.get("items") or [] if isinstance(i, dict)],
            total=int(data.get("total") or 0),
            page=int(data.get("page") or page),
            per_page=per_page,
            pages=int(data.get("pages") or 1),
        )

    async def decide(self, ids: list[int], action: str) -> int:
        """Approve, reject, blacklist or retry. Returns how many rows changed.

        SuggestArr caps a batch at 100 ids and rate limits these to 20/minute, so the
        cap is enforced here rather than discovered as a 400 halfway through.
        """
        if action not in ("approve", "reject", "blacklist", "retry"):
            raise ServiceError(f"Unknown suggestion action '{action}'.", service=self.name)
        if not ids:
            return 0
        if len(ids) > 100:
            raise ServiceError(
                "SuggestArr accepts at most 100 suggestions per call.", service=self.name
            )
        result = await self._request(
            "POST", f"jobs/suggestions/{action}", json={"ids": [int(i) for i in ids]}
        )
        if isinstance(result, dict):
            return int(result.get("updated") or 0)
        return 0

    # ------------------------------------------------------------- identity

    async def _health_payload(self) -> dict[str, Any]:
        """`/api/health`, tolerating its 503.

        Readiness answers 503 when a dependency is down but still returns the useful
        body — per-dependency statuses. Treating that as a transport failure would throw
        away the only diagnosis SuggestArr offers.
        """
        client = await self._get_client()
        try:
            response = await client.get(
                f"{self.api_base}/health", headers={"Accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise ServiceUnreachable(
                f"Could not reach {self.url}: {type(exc).__name__}", service=self.name
            ) from exc
        if response.status_code >= 400 and response.status_code != 503:
            raise ServiceError(
                f"{self.name} returned HTTP {response.status_code}", service=self.name
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ServiceError(
                f"{self.name} returned a non-JSON health response.", service=self.name
            ) from exc
        return payload if isinstance(payload, dict) else {}

    async def system_status(self) -> SystemStatus:
        """SuggestArr has no `system/status`, so identity comes from health.

        It publishes no version there either. Reporting "unknown" is the honest answer;
        inventing one would make the dashboard's version column quietly wrong.
        """
        await self._health_payload()
        return SystemStatus(app_name=self.app_name, version="unknown")

    async def health(self) -> list[HealthIssue]:
        """Each unreachable dependency becomes one issue.

        `not_configured` is not a problem — an install with no LLM configured is a normal
        install, and flagging it would put a permanent warning on the dashboard.
        """
        payload = await self._health_payload()
        issues: list[HealthIssue] = []
        for key, label in (
            ("db", "Database"),
            ("tmdb", "TMDB"),
            ("seer", "Jellyseerr/Overseerr"),
            ("llm", "LLM"),
        ):
            value = str(payload.get(key) or "").lower()
            if value != "error":
                continue
            # DB and TMDB are what SuggestArr calls critical — without them it produces
            # nothing at all. Seer and LLM degrade it rather than stop it.
            critical = key in ("db", "tmdb")
            issues.append(
                HealthIssue(
                    source=f"SuggestArr/{key}",
                    severity=HealthSeverity.ERROR if critical else HealthSeverity.WARNING,
                    message=(
                        f"{label} is unreachable."
                        + ("" if critical else " Suggestions still generate without it.")
                    ),
                )
            )
        return issues
