from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    DelayCause,
    DelayIncident,
    Dispatch,
    DispatchStatus,
    LoadingBay,
    LoadingSchedule,
    Route,
    ScheduleStatus,
    Truck,
)
from app.sample_data import clear_sample_data, load_sample_data

TZ = get_settings().tz
DAY = date(2026, 11, 2)


def at(hh: int, mm: int = 0, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=TZ)


def test_empty_database_reports_no_data_not_zeros(auth_client) -> None:
    body = auth_client.get("/api/dashboard/overview?start=2026-11-01&end=2026-11-07").json()
    assert body["sample_data"] is False
    kpis = body["kpis"]
    assert kpis["loads_processed"]["current"] == 0
    assert kpis["avg_turnaround_minutes"]["current"] is None
    assert kpis["on_time_delivery_pct"]["current"] is None
    assert len(body["trend"]) == 7
    assert body["recent_dispatches"] == []


def test_invalid_ranges_rejected(auth_client) -> None:
    assert (
        auth_client.get("/api/dashboard/overview?start=2026-11-07&end=2026-11-01").status_code
        == 422
    )
    assert (
        auth_client.get("/api/dashboard/overview?start=2026-01-01&end=2026-11-01").status_code
        == 422
    )


@pytest.fixture
def two_loads(db: Session) -> None:
    """Two completed loads on Nov 2: 100 min (on target) and 160 min (over target)."""
    bay = LoadingBay(code="BAY-01", name="Bay 01")
    t1 = Truck(registration="KDG 752R", capacity_tonnes=Decimal(16))
    t2 = Truck(registration="KCF 903P", capacity_tonnes=Decimal(28))
    route = Route(
        origin="Nairobi", destination="Thika", distance_km=Decimal(45), expected_duration_minutes=75
    )
    s1 = LoadingSchedule(
        bay=bay,
        truck=t1,
        scheduled_start=at(6),
        scheduled_end=at(8),
        arrival_at=at(6),
        loading_started_at=at(6, 10),
        loading_finished_at=at(7, 30),
        departed_at=at(7, 40),
        status=ScheduleStatus.DEPARTED,
    )
    s2 = LoadingSchedule(
        bay=bay,
        truck=t2,
        scheduled_start=at(8),
        scheduled_end=at(10),
        arrival_at=at(8),
        loading_started_at=at(8, 20),
        loading_finished_at=at(10, 30),
        departed_at=at(10, 40),
        status=ScheduleStatus.DEPARTED,
    )
    d1 = Dispatch(
        load_ref="LD-1",
        schedule=s1,
        truck=t1,
        route=route,
        dispatched_at=at(7, 40),
        expected_arrival_at=at(8, 55),
        actual_arrival_at=at(8, 50),
        status=DispatchStatus.DELIVERED,
    )
    d2 = Dispatch(
        load_ref="LD-2",
        schedule=s2,
        truck=t2,
        route=route,
        dispatched_at=at(10, 40),
        expected_arrival_at=at(11, 55),
        actual_arrival_at=at(12, 45),
        status=DispatchStatus.DELIVERED,
        is_delayed=True,
    )
    inc = DelayIncident(
        dispatch=d2, cause=DelayCause.LOADING_CONGESTION, delay_minutes=40, occurred_at=at(10, 40)
    )
    db.add_all([bay, t1, t2, route, s1, s2, d1, d2, inc])
    db.commit()


def test_kpis_are_computed_from_records(auth_client, two_loads) -> None:
    body = auth_client.get("/api/dashboard/overview?start=2026-11-01&end=2026-11-07").json()
    k = body["kpis"]
    assert k["loads_processed"]["current"] == 2
    assert k["avg_turnaround_minutes"]["current"] == 130.0  # (100 + 160) / 2
    assert k["within_target_pct"]["current"] == 50.0  # only the 100-min load <= 120
    assert k["on_time_delivery_pct"]["current"] == 50.0
    assert k["delay_incidents"]["current"] == 1
    # 260 occupied minutes / (1 bay x 7 days x 12h)
    assert k["bay_utilization_pct"]["current"] == round(260 / (7 * 12 * 60) * 100, 1)
    assert k["loads_processed"]["previous"] == 0

    nov2 = next(p for p in body["trend"] if p["day"] == "2026-11-02")
    assert nov2 == {
        "day": "2026-11-02",
        "loads_processed": 2,
        "avg_turnaround_minutes": 130.0,
        "on_time_delivery_pct": 50.0,
    }
    assert body["delayed_dispatches"] == 1
    assert body["open_delay_incidents"] == 1
    assert [d["load_ref"] for d in body["recent_dispatches"]] == ["LD-2", "LD-1"]
    assert body["recent_dispatches"][0]["route"] == "Nairobi → Thika"


def test_bay_target_override_is_used(auth_client, two_loads, db: Session) -> None:
    bay = db.query(LoadingBay).one()
    bay.target_turnaround_minutes = 180
    db.commit()
    body = auth_client.get("/api/dashboard/overview?start=2026-11-01&end=2026-11-07").json()
    assert body["kpis"]["within_target_pct"]["current"] == 100.0


def test_sample_data_is_flagged_and_guarded(auth_client, db: Session) -> None:
    counts = load_sample_data(db, today=DAY + timedelta(days=5))
    assert counts["schedules"] > 0 and counts["dispatches"] > 0
    body = auth_client.get("/api/dashboard/overview").json()
    assert body["sample_data"] is True
    assert auth_client.get("/api/meta").json()["sample_data"] is True

    with pytest.raises(RuntimeError):
        load_sample_data(db)
    clear_sample_data(db)
    assert auth_client.get("/api/meta").json()["sample_data"] is False


def test_clear_refuses_real_data(db: Session) -> None:
    db.add(LoadingBay(code="BAY-01", name="Real bay"))
    db.commit()
    with pytest.raises(RuntimeError):
        clear_sample_data(db)
    with pytest.raises(RuntimeError):
        load_sample_data(db)
