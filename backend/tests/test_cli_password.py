"""`set-password` CLI: resets a forgotten password safely and clears that account's lockout."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import cli
from app.models import AuditEvent, AuthThrottle
from app.services import throttle
from tests.conftest import TEST_PASSWORD

NEW = "Fresh-Pass-42!"


def login(client, username: str, password: str):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_set_password_then_sign_in(client, make_user, db, monkeypatch) -> None:
    user = make_user("derrick")
    monkeypatch.setenv("LOGITRACK_NEW_PASSWORD", NEW)
    assert cli.main(["set-password", "--username", "Derrick"]) == 0  # case-insensitive

    assert login(client, "derrick", TEST_PASSWORD).status_code == 401
    assert login(client, "derrick", NEW).status_code == 200
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "user.password_reset"))
    assert event is not None and event.entity_id == str(user.id)
    assert NEW not in repr(event.changes) and NEW not in event.summary


def test_set_password_by_email_and_clears_lockout(client, make_user, db, monkeypatch) -> None:
    user = make_user("derrick")
    locked = datetime.now(UTC) + timedelta(minutes=10)
    for ident in (user.username, user.email):
        db.add(
            AuthThrottle(
                key=throttle.account_key(ident),
                failures=5,
                window_started_at=datetime.now(UTC),
                locked_until=locked,
            )
        )
    db.add(
        AuthThrottle(
            key=throttle.account_key("someone-else"),
            failures=5,
            window_started_at=datetime.now(UTC),
            locked_until=locked,
        )
    )
    db.commit()

    monkeypatch.setenv("LOGITRACK_NEW_PASSWORD", NEW)
    assert cli.main(["set-password", "--username", user.email]) == 0
    db.expire_all()
    keys = set(db.scalars(select(AuthThrottle.key)))
    assert keys == {throttle.account_key("someone-else")}  # other accounts untouched
    assert login(client, "derrick", NEW).status_code == 200


@pytest.mark.parametrize(
    ("password", "message"),
    [("short1!", "at least 8"), ("lettersonly!", "letters and numbers"), ("Abcdefg123", "symbol")],
)
def test_set_password_rejects_weak_passwords(make_user, monkeypatch, capsys, password, message):
    make_user("derrick")
    monkeypatch.setenv("LOGITRACK_NEW_PASSWORD", password)
    assert cli.main(["set-password", "--username", "derrick"]) == 2
    assert message in capsys.readouterr().err


def test_set_password_prompts_twice_and_requires_a_match(client, make_user, monkeypatch) -> None:
    make_user("derrick")
    monkeypatch.delenv("LOGITRACK_NEW_PASSWORD", raising=False)
    answers = iter([NEW, "different-1!"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(answers))
    assert cli.main(["set-password", "--username", "derrick"]) == 2
    assert login(client, "derrick", TEST_PASSWORD).status_code == 200  # unchanged

    answers = iter([NEW, NEW])
    assert cli.main(["set-password", "--username", "derrick"]) == 0
    assert login(client, "derrick", NEW).status_code == 200


def test_set_password_unknown_user(monkeypatch, capsys) -> None:
    monkeypatch.setenv("LOGITRACK_NEW_PASSWORD", NEW)
    assert cli.main(["set-password", "--username", "nobody"]) == 1
    assert "No user" in capsys.readouterr().err
