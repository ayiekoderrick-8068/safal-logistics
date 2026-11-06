"""Workspace security: each session is bound to one workspace, entering either one needs the
password, and switching always re-verifies it."""

from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditEvent, MaintenanceRole, Role, User
from app.security import SESSION_COOKIE
from tests.conftest import TEST_PASSWORD

LOGISTICS_PROBE = "/api/dashboard/overview"
MAINT_PROBE = "/api/maintenance/access"


def _login(client, username="derrick", workspace=None, password=TEST_PASSWORD):
    body = {"username": username, "password": password}
    if workspace:
        body["workspace"] = workspace
    return client.post("/api/auth/login", json=body)


def test_login_defaults_to_logistics_for_existing_clients(client, make_user) -> None:
    make_user()
    resp = _login(client)
    assert resp.status_code == 200
    assert resp.json()["user"]["workspace"] == "logistics"
    assert client.get("/api/auth/me").json()["workspace"] == "logistics"
    assert client.get(LOGISTICS_PROBE).status_code == 200


def test_logistics_session_cannot_use_maintenance_api(client, make_user) -> None:
    make_user()  # admin: allowed into both, but this session is logistics
    _login(client, workspace="logistics")
    resp = client.get(MAINT_PROBE)
    assert resp.status_code == 403
    assert resp.headers["x-workspace-required"] == "maintenance"


def test_maintenance_session_cannot_use_logistics_api(client, make_user) -> None:
    make_user()
    assert _login(client, workspace="maintenance").status_code == 200
    assert client.get(MAINT_PROBE).status_code == 200
    for path in (LOGISTICS_PROBE, "/api/trucks", "/api/alerts", "/api/reports/overview"):
        assert client.get(path).status_code in (403, 404, 405), path
    assert client.get(LOGISTICS_PROBE).status_code == 403


def test_admin_is_a_maintenance_manager(client, make_user) -> None:
    make_user()
    _login(client, workspace="maintenance")
    body = client.get(MAINT_PROBE).json()
    assert body["maintenance_role"] == "manager"
    assert "settings.manage" in body["permissions"]


def test_user_without_maintenance_role_is_refused_after_password_check(
    client, make_user, db: Session
) -> None:
    make_user("ops", role=Role.OPERATIONS)
    wrong = _login(client, "ops", "maintenance", password="Wrong-pass-1!")
    assert wrong.status_code == 401  # bad password: same error as always, no hint
    resp = _login(client, "ops", "maintenance")
    assert resp.status_code == 403
    assert "does not have access to Maintenance Operations" in resp.json()["detail"]
    assert SESSION_COOKIE not in resp.headers.get("set-cookie", "")
    assert client.get("/api/auth/me").status_code == 401  # no session was issued
    assert "auth.workspace_denied" in db.scalars(select(AuditEvent.action)).all()


def test_technician_gets_only_technician_permissions(client, make_user) -> None:
    make_user("tech", role=Role.VIEWER, maintenance_role=MaintenanceRole.TECHNICIAN)
    assert _login(client, "tech", "maintenance").status_code == 200
    perms = client.get(MAINT_PROBE).json()["permissions"]
    assert "work_orders.work" in perms and "breakdowns.log" in perms
    assert "equipment.manage" not in perms and "settings.manage" not in perms


def test_switch_requires_correct_password(client, make_user, db: Session) -> None:
    make_user()
    _login(client)
    bad = client.post(
        "/api/auth/switch-workspace", json={"workspace": "maintenance", "password": "nope-1!"}
    )
    assert bad.status_code == 400  # not 401: the logistics session stays valid
    assert client.get("/api/auth/me").json()["workspace"] == "logistics"
    assert client.get(MAINT_PROBE).status_code == 403

    ok = client.post(
        "/api/auth/switch-workspace", json={"workspace": "maintenance", "password": TEST_PASSWORD}
    )
    assert ok.status_code == 200 and ok.json()["user"]["workspace"] == "maintenance"
    assert client.get(MAINT_PROBE).status_code == 200
    assert client.get(LOGISTICS_PROBE).status_code == 403  # the old workspace is closed now

    actions = db.scalars(select(AuditEvent.action)).all()
    assert "auth.workspace_switch_failed" in actions and "auth.workspace_switched" in actions


def test_switch_without_access_or_to_same_workspace(client, make_user) -> None:
    make_user("ops", role=Role.OPERATIONS)
    _login(client, "ops")
    same = client.post(
        "/api/auth/switch-workspace", json={"workspace": "logistics", "password": TEST_PASSWORD}
    )
    assert same.status_code == 409
    denied = client.post(
        "/api/auth/switch-workspace", json={"workspace": "maintenance", "password": TEST_PASSWORD}
    )
    assert denied.status_code == 403
    assert client.get("/api/auth/me").json()["workspace"] == "logistics"


def test_switch_attempts_are_rate_limited(client, make_user) -> None:
    make_user()
    _login(client)
    codes = [
        client.post(
            "/api/auth/switch-workspace", json={"workspace": "maintenance", "password": f"bad-{i}!"}
        ).status_code
        for i in range(12)
    ]
    assert codes[0] == 400 and 429 in codes
    # Once locked, even the right password is refused until the lock expires.
    locked = client.post(
        "/api/auth/switch-workspace", json={"workspace": "maintenance", "password": TEST_PASSWORD}
    )
    assert locked.status_code == 429


def test_switch_requires_a_session(client) -> None:
    resp = client.post(
        "/api/auth/switch-workspace", json={"workspace": "maintenance", "password": "x"}
    )
    assert resp.status_code == 401


def test_forged_workspace_claim_is_rejected(client, make_user, db: Session) -> None:
    """A token edited to claim another workspace fails signature verification."""
    user = make_user()
    _login(client)
    token = client.cookies.get(SESSION_COOKIE)
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["ws"] = "maintenance"
    forged = jwt.encode(claims, "an-attacker-chosen-secret-of-32-bytes!", algorithm="HS256")
    resp = client.get(MAINT_PROBE, headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401
    assert user.id


def test_unknown_workspace_claim_is_rejected(client, make_user) -> None:
    user = make_user()
    settings = get_settings()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "tv": 0,
            "ws": "finance",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    )


def test_pre_workspace_tokens_still_work_as_logistics(client, make_user) -> None:
    """Sessions issued before this release carry no `ws` claim; they stay logistics sessions."""
    user = make_user()
    settings = get_settings()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "role": "admin",
            "tv": 0,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).json()["workspace"] == "logistics"
    assert client.get(MAINT_PROBE, headers=headers).status_code == 403


def test_revoking_maintenance_role_ends_maintenance_sessions(
    client, make_user, db: Session
) -> None:
    make_user()  # admin
    make_user("tech", role=Role.VIEWER, maintenance_role=MaintenanceRole.TECHNICIAN)
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as tech:
        assert _login(tech, "tech", "maintenance").status_code == 200
        _login(client)  # admin, logistics
        tech_id = db.scalar(select(User.id).where(User.username == "tech"))
        resp = client.patch(f"/api/users/{tech_id}", json={"maintenance_role": None})
        assert resp.status_code == 200 and resp.json()["maintenance_role"] is None
        assert tech.get(MAINT_PROBE).status_code == 401  # session revoked immediately
        assert _login(tech, "tech", "maintenance").status_code == 403


def test_admin_can_grant_maintenance_role_on_create(client, make_user) -> None:
    make_user()
    _login(client)
    resp = client.post(
        "/api/users",
        json={
            "username": "planner1",
            "email": "planner1@example.com",
            "full_name": "Pat Planner",
            "role": "viewer",
            "maintenance_role": "planner",
            "temporary_password": "Temp-pass-123!",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["maintenance_role"] == "planner"
    assert resp.json()["workspaces"] == ["logistics", "maintenance"]
