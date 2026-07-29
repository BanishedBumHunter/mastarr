"""App-level routing: the SPA fallback must not shadow the API."""

from __future__ import annotations

from pathlib import Path

import pytest

from mastarr import main


@pytest.fixture
def spa_client(tmp_path, monkeypatch, isolated_env):
    """A client with a bundled frontend, as produced by the Docker build."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>Mastarr</title>")
    (static / "assets" / "app.js").write_text("console.log(1)")

    monkeypatch.setattr(main, "FRONTEND_DIR", static)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from mastarr.api import api_router

    app = FastAPI(lifespan=main.app.router.lifespan_context)
    app.include_router(api_router)
    monkeypatch.setattr(main, "app", app)
    main._mount_frontend()

    with TestClient(app) as client:
        yield client


def test_spa_is_served_at_root(spa_client):
    response = spa_client.get("/")
    assert response.status_code == 200
    assert "Mastarr" in response.text


def test_client_side_routes_fall_back_to_index(spa_client):
    """Deep links must work on refresh, not 404."""
    for route in ("/services", "/users", "/some/nested/route"):
        response = spa_client.get(route)
        assert response.status_code == 200
        assert "<!doctype html>" in response.text


def test_real_asset_files_are_served(spa_client):
    assert spa_client.get("/assets/app.js").status_code == 200


def test_unmatched_api_paths_404_instead_of_returning_html(spa_client):
    """Regression: the catch-all used to answer any /api GET with index.html and a 200,
    which reads as success to an API client and hides real 404s and 405s."""
    response = spa_client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "<!doctype html>" not in response.text


def test_wrong_method_on_a_real_api_route_is_not_masked(spa_client):
    """GET on a POST-only endpoint must not come back as a 200 HTML page."""
    response = spa_client.get("/api/discovery/scan")
    assert response.status_code in (404, 405)
    assert "<!doctype html>" not in response.text


def test_api_routes_still_work_with_the_spa_mounted(spa_client):
    assert spa_client.get("/api/health").json()["status"] == "ok"
    assert spa_client.get("/api/auth/state").json()["needs_setup"] is True


def test_path_traversal_is_rejected(spa_client, tmp_path):
    """`/../` must not escape the static root into the data volume."""
    (tmp_path / "secret.key").write_text("super-secret-fernet-key")
    response = spa_client.get("/../secret.key")
    assert "super-secret-fernet-key" not in response.text


def test_api_only_mode_when_no_frontend_is_bundled(isolated_env, monkeypatch):
    """Local dev serves the UI from Vite; the app must still boot without static files."""
    monkeypatch.setattr(main, "FRONTEND_DIR", Path("/nonexistent/static"))

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from mastarr.api import api_router

    app = FastAPI(lifespan=main.app.router.lifespan_context)
    app.include_router(api_router)
    monkeypatch.setattr(main, "app", app)
    main._mount_frontend()

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 404


# ------------------------------------------------------- data dir preflight


def test_preflight_accepts_a_writable_dir(isolated_env, tmp_path):
    from mastarr.config import get_settings

    main._preflight_data_dir(get_settings())  # must not raise


def test_preflight_names_the_uid_when_the_dir_is_read_only(isolated_env, tmp_path, monkeypatch):
    """The most common install failure must produce an actionable message.

    Without this the first symptom is SQLAlchemy's 'unable to open database file', which
    sends people looking for a database problem instead of a chown.
    """
    import os
    import stat

    import pytest

    from mastarr.config import get_settings

    if os.getuid() == 0:
        pytest.skip("root bypasses file permissions, so this check cannot be exercised")

    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x, no write

    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", readonly)

    try:
        with pytest.raises(RuntimeError) as excinfo:
            main._preflight_data_dir(settings)
        message = str(excinfo.value)
        assert "not writable" in message
        assert str(os.getuid()) in message, "must name the uid the operator has to chown to"
        assert "chown" in message
    finally:
        readonly.chmod(stat.S_IRWXU)  # so pytest can clean up


def test_preflight_creates_a_missing_data_dir(isolated_env, tmp_path, monkeypatch):
    from mastarr.config import get_settings

    target = tmp_path / "nested" / "mastarr"
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", target)

    main._preflight_data_dir(settings)
    assert target.is_dir()


def test_preflight_leaves_no_probe_file_behind(isolated_env, tmp_path, monkeypatch):
    from mastarr.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    main._preflight_data_dir(settings)
    assert not (tmp_path / ".write-test").exists()
