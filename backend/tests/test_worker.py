"""Background worker: scheduled alert checks, idempotency, failure logging and retries."""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import worker as worker_mod
from app.config import get_settings
from app.models import Alert, AuthThrottle, Truck
from app.services.app_settings import get_setting, set_setting
from app.worker import HEARTBEAT_KEY, Worker, backoff_seconds, main


@pytest.fixture
def truck(db: Session) -> Truck:
    t = Truck(registration="KWW 100W", capacity_tonnes=Decimal(10))  # no documents -> alerts
    db.add(t)
    db.commit()
    return t


def alert_count(db: Session) -> int:
    db.expire_all()
    return db.scalar(select(func.count(Alert.id))) or 0


def test_tick_creates_alerts_without_a_browser_and_writes_heartbeat(db, truck) -> None:
    w = Worker()
    assert w.tick() is True
    assert alert_count(db) == 3  # insurance, licence, inspection missing
    hb = get_setting(db, HEARTBEAT_KEY)
    assert hb["status"] == "ok" and hb["consecutive_failures"] == 0
    assert hb["last_stats"]["created"] == 3 and hb["last_success_at"] == hb["last_run_at"]


def test_repeated_runs_are_idempotent(db, truck) -> None:
    w = Worker()
    for _ in range(3):
        assert w.tick()
    assert alert_count(db) == 3
    assert get_setting(db, HEARTBEAT_KEY)["last_stats"]["updated"] == 3


def test_failures_are_logged_recorded_and_retried(db, truck, monkeypatch, caplog) -> None:
    real = worker_mod.refresh_alerts
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("database unavailable")
        return real(*args, **kwargs)

    monkeypatch.setattr(worker_mod, "refresh_alerts", flaky)
    w = Worker()
    with caplog.at_level(logging.ERROR, logger="logitrack.worker"):
        assert w.tick() is False
        assert w.tick() is False
    assert "Scheduled checks failed (attempt 2 in a row)" in caplog.text
    db.expire_all()
    hb = get_setting(db, HEARTBEAT_KEY)
    assert hb["status"] == "failed" and hb["consecutive_failures"] == 2
    assert "database unavailable" in hb["last_error"]
    assert alert_count(db) == 0

    assert w.tick() is True  # safe retry once the dependency recovers
    assert w.consecutive_failures == 0 and alert_count(db) == 3


def test_backoff_is_exponential_and_capped(monkeypatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "worker_interval_seconds", 60)
    monkeypatch.setattr(s, "worker_max_backoff_seconds", 600)
    assert [backoff_seconds(n) for n in range(6)] == [60, 120, 240, 480, 600, 600]


def test_run_loop_stops_cleanly(db, truck, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "worker_interval_seconds", 5)
    w = Worker()
    w.run(max_iterations=2)
    assert alert_count(db) == 3
    w2 = Worker()
    w2.stop()
    w2.run()  # already stopped: exits without running
    assert get_setting(db, HEARTBEAT_KEY)["status"] == "ok"


def test_once_mode_and_throttle_housekeeping(db, truck) -> None:
    old = datetime.now(UTC) - timedelta(hours=3)
    db.add(AuthThrottle(key="ip:9.9.9.9", failures=3, window_started_at=old))
    db.commit()
    assert main(["--once"]) == 0
    db.expire_all()
    assert db.get(AuthThrottle, "ip:9.9.9.9") is None
    assert get_setting(db, HEARTBEAT_KEY)["last_stats"]["throttle_counters_purged"] == 1


def test_worker_status_endpoint(auth_client, db, truck) -> None:
    assert auth_client.get("/api/alerts/worker-status").json()["status"] == "never_run"
    Worker().tick()
    st = auth_client.get("/api/alerts/worker-status").json()
    assert st["status"] == "ok" and st["last_stats"]["created"] == 3
    stale = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    set_setting(db, HEARTBEAT_KEY, {**get_setting(db, HEARTBEAT_KEY), "last_run_at": stale})
    db.commit()
    assert auth_client.get("/api/alerts/worker-status").json()["status"] == "stale"


def test_read_time_refresh_can_be_disabled(auth_client, db, truck, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "alert_refresh_on_read", False)
    assert auth_client.get("/api/alerts").json()["total"] == 0  # nothing generated on read
    Worker().tick()
    assert auth_client.get("/api/alerts").json()["total"] == 3
