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


ADMIN_ENDPOINTS = [
    ("GET", "/api/dashboard"),
    ("GET", "/api/services"),
    ("POST", "/api/services"),
    ("GET", "/api/users"),
    ("POST", "/api/users"),
    ("POST", "/api/discovery/scan"),
]
