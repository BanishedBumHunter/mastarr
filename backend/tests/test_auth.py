"""Auth flow and the permission seam."""

from __future__ import annotations

import pytest

from mastarr.roles import Role, satisfies

from .conftest import ADMIN_ENDPOINTS, REQUESTER_ENDPOINTS


# ------------------------------------------------------------------ role model


def test_role_is_an_enum_not_a_boolean():
    """Guards the extension seam: a third role must be additive."""
    assert Role.ADMIN.value == "admin"
    assert Role.REQUESTER.value == "requester"
    assert len(Role) == 2


def test_admin_satisfies_requester_but_not_the_reverse():
    assert satisfies(Role.ADMIN, Role.REQUESTER)
    assert satisfies(Role.ADMIN, Role.ADMIN)
    assert satisfies(Role.REQUESTER, Role.REQUESTER)
    assert not satisfies(Role.REQUESTER, Role.ADMIN)


# ------------------------------------------------------------------- first run


def test_fresh_instance_reports_needing_setup(client):
    state = client.get("/api/auth/state").json()
    assert state["needs_setup"] is True
    assert state["authenticated"] is False


def test_setup_creates_an_admin_and_signs_in(client):
    response = client.post(
        "/api/auth/setup", json={"username": "chris", "password": "correcthorse1"}
    )
    assert response.status_code == 201
    assert response.json()["role"] == "admin"

    state = client.get("/api/auth/state").json()
    assert state["needs_setup"] is False
    assert state["authenticated"] is True


def test_setup_can_only_be_used_once(admin_client):
    """The empty user table is the authorization; once claimed, it is claimed forever."""
    response = admin_client.post(
        "/api/auth/setup", json={"username": "attacker", "password": "correcthorse1"}
    )
    assert response.status_code == 409


def test_setup_rejects_a_short_password(client):
    response = client.post("/api/auth/setup", json={"username": "chris", "password": "short"})
    assert response.status_code == 422


# ---------------------------------------------------------------------- login


def test_login_and_logout_round_trip(admin_client):
    admin_client.post("/api/auth/logout")
    assert admin_client.get("/api/auth/me").status_code == 401

    response = admin_client.post(
        "/api/auth/login", json={"username": "admin", "password": "adminpassword1"}
    )
    assert response.status_code == 200
    assert admin_client.get("/api/auth/me").json()["username"] == "admin"


def test_wrong_password_is_rejected(admin_client):
    admin_client.post("/api/auth/logout")
    response = admin_client.post(
        "/api/auth/login", json={"username": "admin", "password": "wrongpassword"}
    )
    assert response.status_code == 401


def test_login_is_not_a_username_oracle(admin_client):
    """Unknown user and wrong password must be indistinguishable."""
    admin_client.post("/api/auth/logout")
    unknown = admin_client.post(
        "/api/auth/login", json={"username": "nobody", "password": "whatever12"}
    )
    wrong = admin_client.post(
        "/api/auth/login", json={"username": "admin", "password": "whatever12"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_password_is_hashed_not_stored(admin_client, tmp_path):
    """The plaintext password must appear nowhere in the database file."""
    db_bytes = (tmp_path / "mastarr.db").read_bytes()
    assert b"adminpassword1" not in db_bytes
    assert b"$argon2" in db_bytes


def test_session_cookie_is_httponly(admin_client):
    admin_client.post("/api/auth/logout")
    response = admin_client.post(
        "/api/auth/login", json={"username": "admin", "password": "adminpassword1"}
    )
    assert "httponly" in response.headers["set-cookie"].lower()


# ------------------------------------------------------------- bearer tokens


def test_token_endpoint_issues_a_working_bearer_token(admin_client):
    token = admin_client.post(
        "/api/auth/token", json={"username": "admin", "password": "adminpassword1"}
    ).json()["access_token"]

    admin_client.cookies.clear()
    response = admin_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_garbage_token_is_rejected(client):
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


# ------------------------------------------------------- the permission seam


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_endpoints_reject_anonymous(client, method, path):
    response = client.request(method, path, json={})
    assert response.status_code == 401, f"{method} {path} was reachable anonymously"


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_endpoints_reject_requesters(admin_client, method, path):
    """The core role test: a Requester must get 403 on every admin surface."""
    admin_client.post(
        "/api/users",
        json={"username": "bob", "password": "bobpassword1", "role": "requester"},
    )
    token = admin_client.post(
        "/api/auth/token", json={"username": "bob", "password": "bobpassword1"}
    ).json()["access_token"]

    admin_client.cookies.clear()
    response = admin_client.request(
        method, path, json={}, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403, f"{method} {path} was reachable by a requester"


def test_requester_can_reach_requester_endpoints(admin_client):
    admin_client.post(
        "/api/users",
        json={"username": "bob", "password": "bobpassword1", "role": "requester"},
    )
    token = admin_client.post(
        "/api/auth/token", json={"username": "bob", "password": "bobpassword1"}
    ).json()["access_token"]

    admin_client.cookies.clear()
    response = admin_client.get(
        "/api/discover/capabilities", headers={"Authorization": f"Bearer {token}"}
    )
    # 200 with available=False when no Jellyseerr is connected — the point is that a
    # Requester reaches it at all.
    assert response.status_code == 200
    assert response.json()["available"] is False


def test_admin_also_satisfies_requester_endpoints(admin_client):
    """Rank ordering means admin inherits requester access without a second grant."""
    assert admin_client.get("/api/discover/capabilities").status_code == 200


# ------------------------------------------------------------ user management


def test_admin_creates_a_requester(admin_client):
    response = admin_client.post(
        "/api/users",
        json={"username": "alice", "password": "alicepassword1", "role": "requester"},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "requester"


def test_duplicate_usernames_are_rejected(admin_client):
    payload = {"username": "alice", "password": "alicepassword1", "role": "requester"}
    admin_client.post("/api/users", json=payload)
    assert admin_client.post("/api/users", json=payload).status_code == 409


def test_password_change_invalidates_existing_sessions(admin_client):
    admin_client.post(
        "/api/users",
        json={"username": "bob", "password": "bobpassword1", "role": "requester"},
    )
    bob_id = next(
        u["id"] for u in admin_client.get("/api/users").json() if u["username"] == "bob"
    )
    token = admin_client.post(
        "/api/auth/token", json={"username": "bob", "password": "bobpassword1"}
    ).json()["access_token"]

    headers = {"Authorization": f"Bearer {token}"}
    assert admin_client.get("/api/auth/me", headers=headers).status_code == 200

    admin_client.patch(f"/api/users/{bob_id}", json={"password": "newpassword12"})
    assert admin_client.get("/api/auth/me", headers=headers).status_code == 401


def test_role_downgrade_takes_effect_immediately(admin_client):
    """Role is re-read from the DB, never trusted from the token."""
    admin_client.post(
        "/api/users",
        json={"username": "carol", "password": "carolpassword1", "role": "admin"},
    )
    carol_id = next(
        u["id"] for u in admin_client.get("/api/users").json() if u["username"] == "carol"
    )
    token = admin_client.post(
        "/api/auth/token", json={"username": "carol", "password": "carolpassword1"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    saved_cookies = admin_client.cookies.jar
    assert admin_client.get("/api/users", headers=headers).status_code == 200

    admin_client.patch(f"/api/users/{carol_id}", json={"role": "requester"})
    # Old token still carries role=admin, but the DB says otherwise.
    assert admin_client.get("/api/users", headers=headers).status_code == 401
    assert saved_cookies is not None


def test_cannot_delete_own_account(admin_client):
    admin_id = admin_client.get("/api/auth/me").json()["id"]
    response = admin_client.delete(f"/api/users/{admin_id}")
    assert response.status_code == 400


def test_cannot_demote_the_last_admin(admin_client):
    """Without this guard an admin can permanently lock everyone out of config."""
    admin_id = admin_client.get("/api/auth/me").json()["id"]
    response = admin_client.patch(f"/api/users/{admin_id}", json={"role": "requester"})
    assert response.status_code == 400
    assert "only remaining admin" in response.json()["detail"]


def test_can_demote_an_admin_when_another_remains(admin_client):
    admin_client.post(
        "/api/users",
        json={"username": "dave", "password": "davepassword1", "role": "admin"},
    )
    dave_id = next(
        u["id"] for u in admin_client.get("/api/users").json() if u["username"] == "dave"
    )
    response = admin_client.patch(f"/api/users/{dave_id}", json={"role": "requester"})
    assert response.status_code == 200
    assert response.json()["role"] == "requester"


def test_disabled_account_cannot_log_in(admin_client):
    admin_client.post(
        "/api/users",
        json={"username": "eve", "password": "evepassword1", "role": "requester"},
    )
    eve_id = next(
        u["id"] for u in admin_client.get("/api/users").json() if u["username"] == "eve"
    )
    admin_client.patch(f"/api/users/{eve_id}", json={"is_active": False})

    admin_client.cookies.clear()
    response = admin_client.post(
        "/api/auth/login", json={"username": "eve", "password": "evepassword1"}
    )
    assert response.status_code == 403


@pytest.mark.parametrize("method,path", REQUESTER_ENDPOINTS)
def test_requester_endpoints_are_reachable_by_requesters(admin_client, method, path):
    """Requester-level routes must not accidentally be admin-gated.

    The inverse of the matrix above: it is just as broken for a Requester to be locked out
    of Discover as it is for them to reach Users.
    """
    admin_client.post(
        "/api/users",
        json={"username": "bob", "password": "bobpassword1", "role": "requester"},
    )
    token = admin_client.post(
        "/api/auth/token", json={"username": "bob", "password": "bobpassword1"}
    ).json()["access_token"]

    admin_client.cookies.clear()
    response = admin_client.request(
        method, path, headers={"Authorization": f"Bearer {token}"}
    )
    # 503 is fine — it means "no Jellyseerr connected", which is an availability answer,
    # not an authorization one. 403 would mean the role gate is wrong.
    assert response.status_code != 403, f"{method} {path} wrongly denied to a requester"
    assert response.status_code != 401, f"{method} {path} rejected a valid token"


@pytest.mark.parametrize("method,path", REQUESTER_ENDPOINTS)
def test_requester_endpoints_still_reject_anonymous(client, method, path):
    assert client.request(method, path).status_code == 401
