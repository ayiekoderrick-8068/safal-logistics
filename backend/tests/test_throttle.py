"""Sign-in rate limiting: brute force, credential stuffing, no enumeration, recovery."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.cli import main as cli
from app.config import get_settings
from app.models import AuditEvent, AuthThrottle
from app.services import throttle
from tests.conftest import TEST_PASSWORD

WRONG = "wrong-Pass-1!"


def login(client, username: str, password: str):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_account_locks_after_repeated_failures_even_for_correct_password(
    client, make_user, db: Session
) -> None:
    make_user()
    for _ in range(get_settings().login_max_failures - 1):
        assert login(client, "derrick", WRONG).status_code == 401
    locked = login(client, "derrick", WRONG)
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) == get_settings().login_lockout_minutes * 60
    assert "Too many sign-in attempts" in locked.json()["detail"]

    right = login(client, "DERRICK", TEST_PASSWORD)  # case-insensitive identifier, still locked
    assert right.status_code == 429 and 0 < int(right.headers["retry-after"]) <= 900
    actions = list(db.scalars(select(AuditEvent.action)))
    assert actions.count("auth.locked") == 1 and "auth.login_throttled" in actions
    # Identifiers are stored hashed, never as typed.
    assert all("derrick" not in k for k in db.scalars(select(AuthThrottle.key)))


def test_unknown_and_real_accounts_are_indistinguishable(client, make_user) -> None:
    make_user()
    real = [login(client, "derrick", WRONG) for _ in range(5)]
    ghost = [login(client, "nobody-here", WRONG) for _ in range(5)]
    assert [r.status_code for r in real] == [r.status_code for r in ghost] == [401] * 4 + [429]
    assert real[0].json() == ghost[0].json() and real[-1].json() == ghost[-1].json()


def test_lock_expires_and_success_resets_counter(client, make_user, db: Session) -> None:
    make_user()
    for _ in range(5):
        login(client, "derrick", WRONG)
    assert login(client, "derrick", TEST_PASSWORD).status_code == 429
    db.execute(update(AuthThrottle).values(locked_until=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    assert login(client, "derrick", TEST_PASSWORD).status_code == 200  # legitimate user recovers
    acct = throttle.account_key("derrick")
    assert db.scalar(select(AuthThrottle).where(AuthThrottle.key == acct)) is None
    # Counter starts fresh: 4 more failures do not lock.
    for _ in range(4):
        assert login(client, "derrick", WRONG).status_code == 401


def test_failures_outside_the_window_are_forgotten(make_user, db: Session) -> None:
    acct = throttle.account_key("derrick")
    t0 = datetime(2026, 11, 5, 8, 0, tzinfo=UTC)
    for i in range(4):
        assert throttle.register_failure(db, acct, None, t0 + timedelta(minutes=i)) is None
    # 20 minutes later the 15-minute window has passed: counting restarts.
    assert throttle.register_failure(db, acct, None, t0 + timedelta(minutes=20)) is None
    assert db.get(AuthThrottle, acct).failures == 1


def test_credential_stuffing_is_limited_per_ip(client, make_user, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "login_ip_max_failures", 6)
    make_user()
    codes = [login(client, f"user{i}@example.com", WRONG).status_code for i in range(6)]
    assert codes == [401] * 5 + [429]  # different usernames, same client
    assert login(client, "derrick", TEST_PASSWORD).status_code == 429


def test_admin_can_clear_a_lock(client, make_user, db: Session, capsys) -> None:
    make_user()
    for _ in range(5):
        login(client, "derrick", WRONG)
    assert cli(["unlock-login", "--username", "Derrick", "--ip", "testclient"]) == 0
    assert "Cleared" in capsys.readouterr().out
    assert login(client, "derrick", TEST_PASSWORD).status_code == 200
    assert cli(["unlock-login"]) == 2


def test_purge_expired(db: Session) -> None:
    old = datetime.now(UTC) - timedelta(hours=2)
    db.add_all(
        [
            AuthThrottle(key="ip:1", failures=2, window_started_at=old),
            AuthThrottle(
                key="ip:2",
                failures=0,
                window_started_at=old,
                locked_until=datetime.now(UTC) + timedelta(minutes=5),
            ),
        ]
    )
    db.commit()
    assert throttle.purge_expired(db) == 1
    db.commit()
    assert [r.key for r in db.scalars(select(AuthThrottle))] == ["ip:2"]


@pytest.mark.parametrize("payload", [{"username": "", "password": "x"}, {"username": "a"}])
def test_malformed_requests_do_not_count(client, payload, db: Session) -> None:
    assert client.post("/api/auth/login", json=payload).status_code == 422
    assert db.scalars(select(AuthThrottle)).all() == []
