"""SuggestArr: password login, token caching, and the approval queue.

Payloads are shaped from SuggestArr's own `api_service/blueprints/` source, not from a
published API contract — it doesn't have one. That is the whole reason this adapter is
five calls in one file: everything it touches is something upstream may rename.

The interesting behaviour is all in the auth: this is the only type that logs in rather
than presenting a static key, so the token lifecycle is where the bugs would live.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from mastarr.adapters import ServiceError, ServiceUnauthorized, SuggestArrAdapter
from mastarr.adapters.suggestarr import forget_tokens

URL = "http://suggestarr.test:5000"
API = f"{URL}/api"

SUGGESTIONS = {
    "status": "success",
    "total": 2,
    "page": 1,
    "pages": 1,
    "items": [
        {
            "id": 11,
            "tmdb_id": 1396,
            "media_type": "tv",
            "title": "Breaking Bad",
            "year": "2008",
            "overview": "A chemistry teacher turns to crime.",
            "poster_url": "https://image.tmdb.org/t/p/w500/abc.jpg",
            "status": "awaiting_approval",
            "source_title": "Better Call Saul",
            "rating": 8.9,
            "created_at": "2026-08-01T10:00:00Z",
        },
        {
            "id": 12,
            "tmdb_id": 27205,
            "media_type": "movie",
            "title": "Inception",
            "year": None,
            "status": "awaiting_approval",
            "based_on": "Tenet",
        },
    ],
}


@pytest.fixture(autouse=True)
def clear_tokens():
    forget_tokens()
    yield
    forget_tokens()


def adapter() -> SuggestArrAdapter:
    return SuggestArrAdapter(URL, "hunter2", name="SuggestArr", service_id=3, username="admin")


def mock_login(token: str = "tok-abc") -> respx.Route:
    return respx.post(f"{API}/auth/login").mock(
        return_value=httpx.Response(
            200, json={"access_token": token, "role": "admin", "username": "admin"}
        )
    )


# ---------------------------------------------------------------------- auth


@respx.mock
@pytest.mark.asyncio
async def test_login_is_traded_for_a_bearer_token() -> None:
    login = mock_login()
    listing = respx.get(f"{API}/jobs/suggestions").mock(
        return_value=httpx.Response(200, json=SUGGESTIONS)
    )

    async with adapter() as a:
        await a.suggestions()

    assert login.called
    assert listing.calls.last.request.headers["Authorization"] == "Bearer tok-abc"
    # Never the *arr header — that would be silently ignored and read as anonymous.
    assert "X-Api-Key" not in listing.calls.last.request.headers


@respx.mock
@pytest.mark.asyncio
async def test_the_token_is_reused_across_calls() -> None:
    """SuggestArr rate limits its auth routes, so a login per request is a real cost."""
    login = mock_login()
    respx.get(f"{API}/jobs/suggestions").mock(
        return_value=httpx.Response(200, json=SUGGESTIONS)
    )

    async with adapter() as a:
        await a.suggestions()
        await a.suggestions()
    # A second adapter, as a real request would build — the cache is not per-instance.
    async with adapter() as a:
        await a.suggestions()

    assert login.call_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_an_expired_token_is_refreshed_once() -> None:
    """The cache TTL is a guess at SuggestArr's; the 401 is what actually decides."""
    login = mock_login("first")
    calls: list[int] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(401)
        return httpx.Response(200, json=SUGGESTIONS)

    respx.get(f"{API}/jobs/suggestions").mock(side_effect=respond)

    async with adapter() as a:
        await a.suggestions()  # warm the cache
        login.mock(
            return_value=httpx.Response(200, json={"access_token": "second"})
        )
        page = await a.suggestions()

    assert len(page.items) == 2
    assert login.call_count == 2, "must log in again after the token is rejected"


@respx.mock
@pytest.mark.asyncio
async def test_bad_credentials_do_not_retry_forever() -> None:
    """With no cached token a 401 means the password is wrong, not stale — one attempt."""
    login = respx.post(f"{API}/auth/login").mock(return_value=httpx.Response(401))

    async with adapter() as a:
        with pytest.raises(ServiceUnauthorized):
            await a.suggestions()

    assert login.call_count == 1


@pytest.mark.asyncio
async def test_a_missing_username_is_named_as_the_problem() -> None:
    """Configured like an *arr — password only. The error has to say what's missing."""
    a = SuggestArrAdapter(URL, "hunter2", name="SuggestArr")
    with pytest.raises(ServiceUnauthorized) as exc:
        await a.suggestions()
    assert "username" in str(exc.value).lower()
    await a.aclose()


# --------------------------------------------------------------- suggestions


@respx.mock
@pytest.mark.asyncio
async def test_suggestions_parse_including_the_reason() -> None:
    mock_login()
    respx.get(f"{API}/jobs/suggestions").mock(
        return_value=httpx.Response(200, json=SUGGESTIONS)
    )

    async with adapter() as a:
        page = await a.suggestions()

    assert page.total == 2
    first, second = page.items
    assert first.title == "Breaking Bad" and first.year == 2008
    assert first.source_title == "Better Call Saul"
    # SuggestArr spells the reason two ways depending on the code path that made it.
    assert second.source_title == "Tenet"
    assert second.year is None, "a null year must not become 0"
    assert first.service_id == 3 and first.service_name == "SuggestArr"


@respx.mock
@pytest.mark.asyncio
async def test_an_unknown_status_is_rejected_before_the_request() -> None:
    mock_login()
    listing = respx.get(f"{API}/jobs/suggestions").mock(
        return_value=httpx.Response(200, json=SUGGESTIONS)
    )

    async with adapter() as a:
        with pytest.raises(ServiceError):
            await a.suggestions(status="approved")

    assert not listing.called


@respx.mock
@pytest.mark.asyncio
async def test_per_page_is_capped_at_what_suggestarr_accepts() -> None:
    mock_login()
    route = respx.get(f"{API}/jobs/suggestions").mock(
        return_value=httpx.Response(200, json=SUGGESTIONS)
    )

    async with adapter() as a:
        await a.suggestions(per_page=5000)

    assert route.calls.last.request.url.params["per_page"] == "100"


@respx.mock
@pytest.mark.asyncio
async def test_decide_posts_ids_to_the_action_route() -> None:
    mock_login()
    route = respx.post(f"{API}/jobs/suggestions/approve").mock(
        return_value=httpx.Response(200, json={"status": "success", "updated": 2})
    )

    async with adapter() as a:
        assert await a.decide([11, 12], "approve") == 2

    assert route.calls.last.request.content == b'{"ids":[11,12]}'


@respx.mock
@pytest.mark.asyncio
async def test_decide_refuses_more_than_suggestarr_will_take() -> None:
    """SuggestArr 400s above 100. Failing here says why instead of showing its error."""
    mock_login()
    async with adapter() as a:
        with pytest.raises(ServiceError):
            await a.decide(list(range(101)), "approve")


@respx.mock
@pytest.mark.asyncio
async def test_decide_rejects_an_action_that_is_not_a_route() -> None:
    """Without this the action string builds an arbitrary path under jobs/suggestions."""
    mock_login()
    async with adapter() as a:
        with pytest.raises(ServiceError):
            await a.decide([1], "../../config/save")


# -------------------------------------------------------------------- health


@respx.mock
@pytest.mark.asyncio
async def test_health_reports_only_real_failures() -> None:
    """`not_configured` is a normal install, not a problem worth an amber dashboard."""
    respx.get(f"{API}/health").mock(
        return_value=httpx.Response(
            503,
            json={
                "status": "error",
                "db": "ok",
                "tmdb": "error",
                "seer": "error",
                "llm": "not_configured",
            },
        )
    )

    async with adapter() as a:
        issues = await a.health()

    sources = {i.source for i in issues}
    assert sources == {"SuggestArr/tmdb", "SuggestArr/seer"}
    by_source = {i.source: i.severity for i in issues}
    assert by_source["SuggestArr/tmdb"] == "error", "TMDB is critical to SuggestArr"
    assert by_source["SuggestArr/seer"] == "warning"


@respx.mock
@pytest.mark.asyncio
async def test_health_503_is_read_not_treated_as_a_transport_failure() -> None:
    """Readiness answers 503 with the diagnosis in the body. Discarding it loses it."""
    respx.get(f"{API}/health").mock(
        return_value=httpx.Response(503, json={"status": "error", "db": "error"})
    )

    async with adapter() as a:
        status = await a.system_status()
        issues = await a.health()

    assert status.app_name == "suggestarr"
    assert status.version == "unknown", "SuggestArr publishes no version — don't invent one"
    assert [i.source for i in issues] == ["SuggestArr/db"]


# -------------------------------------------------------------- registration


@pytest.mark.asyncio
async def test_suggestarr_declares_the_arr_surface_unsupported() -> None:
    """It shares the transport and nothing else. An undeclared gap becomes a 404 banner
    on every aggregated view."""
    from mastarr.adapters import UnsupportedOperation

    from datetime import datetime, timezone

    now = datetime.now(tz=timezone.utc)
    a = adapter()
    for call in (
        a.calendar(now, now),
        a.library(),
        a.queue(),
        a.disk_space(),
        a.backups(),
        a.logs(),
        a.updates(),
    ):
        with pytest.raises(UnsupportedOperation):
            await call
    await a.aclose()


def test_suggestarr_is_the_only_type_that_needs_a_username() -> None:
    """`requires_username` lives on the adapter so the service form asks for the right
    fields without the frontend keeping its own list of types."""
    from mastarr.adapters.registry import ADAPTERS

    needs = {name for name, cls in ADAPTERS.items() if cls.requires_username}
    assert needs == {"suggestarr"}
