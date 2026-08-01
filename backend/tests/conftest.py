"""Shared fixtures. Every test runs against a throwaway SQLite DB and data dir."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Point every global at a temp dir and clear all module-level caches.

    Mastarr caches the settings, engine, cipher and JWT secret at module level for runtime
    efficiency; without resetting them, test N would silently reuse test N-1's database.
    """
    monkeypatch.setenv("MASTARR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MASTARR_CONFIG_FILE", raising=False)
    monkeypatch.delenv("MASTARR_SECRET_KEY", raising=False)
    monkeypatch.delenv("MASTARR_JWT_SECRET", raising=False)

    from mastarr import crypto, db, services
    from mastarr.auth import security
    from mastarr.config import get_settings

    get_settings.cache_clear()
    db.reset_engine()
    crypto.reset_cipher()
    security.reset_secret()
    services.invalidate_cache()

    yield

    get_settings.cache_clear()
    db.reset_engine()
    crypto.reset_cipher()
    security.reset_secret()
    services.invalidate_cache()


@pytest.fixture
def client(isolated_env) -> TestClient:
    from mastarr.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_client(client) -> TestClient:
    """A client already authenticated as the first-run admin."""
    response = client.post(
        "/api/auth/setup", json={"username": "admin", "password": "adminpassword1"}
    )
    assert response.status_code == 201
    return client


# Every admin-only endpoint. Parameterized over in test_auth so a newly added route that
# forgets its role dependency fails the suite rather than shipping open.
ADMIN_ENDPOINTS = [
    ("GET", "/api/dashboard"),
    ("GET", "/api/services"),
    ("POST", "/api/services"),
    ("GET", "/api/users"),
    ("POST", "/api/users"),
    ("POST", "/api/discovery/scan"),
    ("GET", "/api/library"),
    ("GET", "/api/library/1/1"),
    ("POST", "/api/library/1/1/monitor"),
    ("POST", "/api/library/1/1/season-monitor"),
    ("POST", "/api/library/1/1/search"),
    ("DELETE", "/api/library/1/1"),
    ("GET", "/api/activity/queue"),
    ("GET", "/api/activity/history"),
    ("GET", "/api/activity/wanted"),
    ("GET", "/api/discover/users"),
    ("GET", "/api/settings"),
    ("PUT", "/api/settings"),
    ("GET", "/api/settings/about"),
    ("GET", "/api/config/resources"),
    ("GET", "/api/config/custom_format"),
    ("POST", "/api/config/preview"),
    ("POST", "/api/config/apply"),
    ("GET", "/api/config/indexers/overview"),
    ("GET", "/api/providers/kinds"),
    ("GET", "/api/providers/1/download_client"),
    ("GET", "/api/providers/1/download_client/schema"),
    ("POST", "/api/providers/1/download_client"),
    ("GET", "/api/providers/1/settings/naming"),
    ("PUT", "/api/providers/1/settings/naming"),
    ("GET", "/api/automation/sweep"),
    ("POST", "/api/automation/sweep/run"),
    ("GET", "/api/automation/guard/audit"),
    ("GET", "/api/automation/guard/webhook-url"),
    ("GET", "/api/manual/blocklist"),
    ("GET", "/api/manual/1/releases"),
    ("POST", "/api/manual/1/grab"),
    ("GET", "/api/manual/1/import"),
    ("POST", "/api/manual/1/import"),
    ("DELETE", "/api/manual/1/queue/1"),
    ("DELETE", "/api/manual/1/blocklist/1"),
]

# Reachable by Requesters too. Listed so the split is explicit and reviewable, rather than
# something you have to infer by reading every router.
REQUESTER_ENDPOINTS = [
    ("GET", "/api/discover/capabilities"),
    ("GET", "/api/calendar"),
    ("GET", "/api/discover/requests"),
]
