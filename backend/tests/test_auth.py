from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Role, UserStatus
from app.security import SESSION_COOKIE
from tests.conftest import TEST_PASSWORD


def test_health(client) -> None:
    assert client.get("/api/health").json() == {"status": "ok", "database": "ok"}


def test_protected_endpoints_require_auth(client) -> None:
    for path in ("/api/auth/me", "/api/meta", "/api/dashboard/overview"):
        assert client.get(path).status_code == 401, path


def test_login_sets_httponly_cookie_and_records_audit(client, make_user, db: Session) -> None:
    make_user()
    resp = client.post("/api/auth/login", json={"username": "DERRICK", "password": TEST_PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "admin"
    set_cookie = resp.headers["set-cookie"].lower()
    assert (
        SESSION_COOKIE in set_cookie
        and "httponly" in set_cookie
        and "samesite=strict" in set_cookie
    )

    assert client.get("/api/auth/me").json()["username"] == "derrick"
    actions = db.scalars(select(AuditEvent.action)).all()
    assert "auth.login" in actions


def test_login_by_email(client, make_user) -> None:
    make_user()
    resp = client.post(
        "/api/auth/login", json={"username": "derrick@example.com", "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200


def test_wrong_password_and_unknown_user_give_same_error(client, make_user, db: Session) -> None:
    make_user()
    bad = client.post("/api/auth/login", json={"username": "derrick", "password": "nope-nope-1!"})
    unknown = client.post("/api/auth/login", json={"username": "ghost", "password": "x"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()
    assert db.scalars(select(AuditEvent.action)).all().count("auth.login_failed") == 2


def test_inactive_users_cannot_login(client, make_user) -> None:
    make_user("pending", status=UserStatus.PENDING)
    make_user("gone", status=UserStatus.DEACTIVATED)
    for name in ("pending", "gone"):
        resp = client.post("/api/auth/login", json={"username": name, "password": TEST_PASSWORD})
        assert resp.status_code == 403


def test_deactivation_revokes_existing_session(auth_client, db: Session) -> None:
    from app.models import User

    user = db.scalar(select(User).where(User.username == "derrick"))
    user.status = UserStatus.DEACTIVATED
    db.commit()
    assert auth_client.get("/api/auth/me").status_code == 401


def test_logout_clears_cookie(auth_client) -> None:
    assert auth_client.post("/api/auth/logout").status_code == 204
    assert auth_client.get("/api/auth/me").status_code == 401


def test_tampered_token_rejected(client, make_user) -> None:
    make_user(role=Role.VIEWER)
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer abc.def.ghi"})
    assert resp.status_code == 401
