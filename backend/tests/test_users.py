"""Session revocation, self-service password change and administrator user management."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import AuditEvent, Role, User, UserStatus
from app.security import SESSION_COOKIE, verify_password
from tests.conftest import TEST_PASSWORD

TEMP = "Temp-Pass-123!"
NEW = "Brand-New-456!"


def login(client, username: str, password: str = TEST_PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


# ---------------------------------------------------------------- session revocation
def test_logout_revokes_the_token_server_side(client, make_user) -> None:
    make_user("derrick")
    assert login(client, "derrick").status_code == 200
    stolen = client.cookies.get(SESSION_COOKIE)
    assert client.post("/api/auth/logout").status_code == 204
    # A copy of the old token no longer works, even though it has not expired.
    with TestClient(create_app()) as other:
        r = other.get("/api/auth/me", headers={"Authorization": f"Bearer {stolen}"})
        assert r.status_code == 401


def test_logout_without_a_session_still_succeeds(client) -> None:
    assert client.post("/api/auth/logout").status_code == 204


def test_tampered_token_version_is_rejected(client, make_user, db) -> None:
    user = make_user("derrick")
    login(client, "derrick")
    user.token_version += 1  # e.g. revoked from another device
    db.commit()
    assert client.get("/api/auth/me").status_code == 401


# ---------------------------------------------------------------- change password
def test_change_password_keeps_this_session_and_ends_others(client, make_user, db) -> None:
    make_user("derrick")
    login(client, "derrick")
    with TestClient(create_app()) as laptop:
        assert login(laptop, "derrick").status_code == 200
        r = client.post(
            "/api/auth/change-password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW},
        )
        assert r.status_code == 200, r.text
        assert client.get("/api/auth/me").status_code == 200  # this device continues
        assert laptop.get("/api/auth/me").status_code == 401  # the other is signed out
    assert login(client, "derrick", TEST_PASSWORD).status_code == 401
    assert login(client, "derrick", NEW).status_code == 200


@pytest.mark.parametrize(
    ("current", "new", "code", "message"),
    [
        ("wrong-Pass-1!", NEW, 400, "current password is incorrect"),
        (TEST_PASSWORD, "short1!", 422, "at least 8"),
        (TEST_PASSWORD, TEST_PASSWORD, 422, "different"),
    ],
)
def test_change_password_rejections(client, make_user, current, new, code, message) -> None:
    make_user("derrick")
    login(client, "derrick")
    r = client.post(
        "/api/auth/change-password", json={"current_password": current, "new_password": new}
    )
    assert r.status_code == code and message in r.json()["detail"]


def test_change_password_wrong_current_counts_towards_lockout(client, make_user) -> None:
    make_user("derrick")
    login(client, "derrick")
    codes = [
        client.post(
            "/api/auth/change-password",
            json={"current_password": f"bad-{i}-Pass!", "new_password": NEW},
        ).status_code
        for i in range(5)
    ]
    assert codes[:4] == [400] * 4 and codes[4] == 429


def test_change_password_requires_a_session(client) -> None:
    r = client.post(
        "/api/auth/change-password", json={"current_password": "x", "new_password": NEW}
    )
    assert r.status_code == 401


# ---------------------------------------------------------------- user management
@pytest.fixture
def admin_client(client, make_user) -> TestClient:
    make_user("boss", role=Role.ADMIN)
    assert login(client, "boss").status_code == 200
    return client


def test_admin_creates_user_who_must_change_password(admin_client, db) -> None:
    r = admin_client.post(
        "/api/users",
        json={
            "username": "Grace.W",
            "email": "grace@example.com",
            "full_name": "  Grace   Wanjiru ",
            "role": "operations",
            "temporary_password": TEMP,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["username"] == "grace.w" and body["full_name"] == "Grace Wanjiru"
    assert body["must_change_password"] is True and body["status"] == "active"
    assert "password" not in str(body).lower().replace("must_change_password", "").replace(
        "password_changed_at", ""
    )
    user = db.scalar(select(User).where(User.username == "grace.w"))
    assert verify_password(TEMP, user.password_hash)
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "user.created"))
    assert TEMP not in str(event.changes) and TEMP not in event.summary

    with TestClient(create_app()) as grace:
        me = login(grace, "grace.w", TEMP).json()["user"]
        assert me["must_change_password"] is True
        grace.post(
            "/api/auth/change-password", json={"current_password": TEMP, "new_password": NEW}
        )
        assert grace.get("/api/auth/me").json()["must_change_password"] is False


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"username": "ab"}, 422),  # too short
        ({"username": "has space"}, 422),
        ({"email": "not-an-email"}, 422),
        ({"temporary_password": "weak"}, 422),
        ({"role": "superuser"}, 422),
        ({"username": "boss"}, 409),  # already taken
        ({"email": "BOSS@example.com"}, 409),  # case-insensitive email clash
    ],
)
def test_create_user_validation(admin_client, payload, code) -> None:
    base = {
        "username": "newbie",
        "email": "newbie@example.com",
        "full_name": "New Person",
        "role": "viewer",
        "temporary_password": TEMP,
    }
    assert admin_client.post("/api/users", json={**base, **payload}).status_code == code


def test_role_change_and_deactivation_revoke_sessions(admin_client, make_user, db) -> None:
    target = make_user("ops", role=Role.OPERATIONS)
    with TestClient(create_app()) as ops:
        login(ops, "ops")
        assert ops.get("/api/auth/me").status_code == 200
        r = admin_client.patch(f"/api/users/{target.id}", json={"role": "viewer"})
        assert r.status_code == 200 and r.json()["role"] == "viewer"
        assert ops.get("/api/auth/me").status_code == 401  # must sign in again

        login(ops, "ops")
        admin_client.patch(f"/api/users/{target.id}", json={"status": "deactivated"})
        assert ops.get("/api/auth/me").status_code == 401
        assert login(ops, "ops").status_code == 403  # correct password, inactive account

        admin_client.patch(f"/api/users/{target.id}", json={"status": "active"})
        assert login(ops, "ops").status_code == 200


def test_admin_cannot_lock_themselves_or_the_system_out(admin_client, db) -> None:
    me = db.scalar(select(User).where(User.username == "boss"))
    r = admin_client.patch(f"/api/users/{me.id}", json={"role": "viewer"})
    assert r.status_code == 409 and "your own" in r.json()["detail"]
    r = admin_client.patch(f"/api/users/{me.id}", json={"status": "deactivated"})
    assert r.status_code == 409


def test_last_active_admin_is_protected(admin_client, make_user, db) -> None:
    other = make_user("second", role=Role.ADMIN)
    me = db.scalar(select(User).where(User.username == "boss"))
    # With two admins, the other one may be demoted...
    assert admin_client.patch(f"/api/users/{other.id}", json={"role": "viewer"}).status_code == 200
    # ...but then "boss" is the last one, and a second admin cannot remove them either.
    db.refresh(other)
    other.role, other.status = Role.ADMIN, UserStatus.DEACTIVATED
    db.commit()
    assert (
        admin_client.patch(f"/api/users/{me.id}", json={"status": "deactivated"}).status_code == 409
    )


def test_reset_password_issues_temporary_password_and_signs_out(admin_client, make_user) -> None:
    target = make_user("driver.lead", role=Role.FLEET_MANAGER)
    with TestClient(create_app()) as them:
        login(them, "driver.lead")
        r = admin_client.post(
            f"/api/users/{target.id}/reset-password", json={"temporary_password": TEMP}
        )
        assert r.status_code == 200 and r.json()["must_change_password"] is True
        assert them.get("/api/auth/me").status_code == 401
        assert login(them, "driver.lead", TEST_PASSWORD).status_code == 401
        assert login(them, "driver.lead", TEMP).status_code == 200
    weak = admin_client.post(
        f"/api/users/{target.id}/reset-password", json={"temporary_password": "weak"}
    )
    assert weak.status_code == 422


def test_list_and_filter_users(admin_client, make_user) -> None:
    make_user("ops", role=Role.OPERATIONS)
    make_user("viewer1", role=Role.VIEWER)
    names = [u["username"] for u in admin_client.get("/api/users").json()]
    assert set(names) == {"boss", "ops", "viewer1"}
    assert [u["username"] for u in admin_client.get("/api/users?role=viewer").json()] == ["viewer1"]
    assert [u["username"] for u in admin_client.get("/api/users?q=OPS").json()] == ["ops"]
    assert admin_client.get("/api/users/999999").status_code in (404, 405)
    assert admin_client.patch("/api/users/999999", json={"role": "viewer"}).status_code == 404


@pytest.mark.parametrize(
    "role", [Role.OPERATIONS, Role.FLEET_MANAGER, Role.COMPLIANCE, Role.VIEWER]
)
def test_only_administrators_manage_users(client, make_user, role) -> None:
    target = make_user("target", role=Role.VIEWER)
    make_user("someone", role=role)
    login(client, "someone")
    assert client.get("/api/users").status_code == 403
    new = {
        "username": "x.y.z",
        "email": "xyz@example.com",
        "full_name": "X Y",
        "role": "admin",
        "temporary_password": TEMP,
    }
    assert client.post("/api/users", json=new).status_code == 403
    assert client.patch(f"/api/users/{target.id}", json={"role": "admin"}).status_code == 403
    assert (
        client.post(
            f"/api/users/{target.id}/reset-password", json={"temporary_password": TEMP}
        ).status_code
        == 403
    )


def test_user_endpoints_require_login(client) -> None:
    assert client.get("/api/users").status_code == 401
