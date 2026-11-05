"""Turnaround analytics computed from recorded timestamps."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    DelayCause,
    DelayIncident,
    LoadingBay,
    LoadingSchedule,
    ScheduleStatus,
    Truck,
)

TZ = get_settings().tz
DAY = date(2026, 11, 2)


def at(h: int, m: int = 0) -> datetime:
    return datetime.combine(DAY, time(h, m), tzinfo=TZ)


def _seed(db: Session) -> None:
    b1 = LoadingBay(code="B1", name="Bay 01")
    b2 = LoadingBay(code="B2", name="Bay 02", target_turnaround_minutes=90)
    b3 = LoadingBay(code="B3", name="Bay 03")  # no loads
    t = Truck(registration="KCA 1A", capacity_tonnes=Decimal(10))
    u = Truck(registration="KCB 2B", capacity_tonnes=Decimal(10))

    def load(truck, bay, arrive, start, finish, depart) -> LoadingSchedule:
        return LoadingSchedule(
            truck=truck,
            bay=bay,
            scheduled_start=arrive,
            scheduled_end=arrive + timedelta(hours=3),
            arrival_at=arrive,
            loading_started_at=start,
            loading_finished_at=finish,
            departed_at=depart,
            status=ScheduleStatus.DEPARTED,
        )

    s1 = load(t, b1, at(6), at(6, 10), at(7, 10), at(7, 40))  # 100 min, loading 60
    s2 = load(u, b1, at(10), at(10, 20), at(12, 0), at(12, 20))  # 140 min, loading 100
    s3 = load(t, b2, at(13), at(13, 5), at(14, 20), at(14, 40))  # 100 min > 90 target
    inc = DelayIncident(
        schedule=s2, cause=DelayCause.LOADING_CONGESTION, delay_minutes=20, occurred_at=at(10, 5)
    )
    db.add_all([b1, b2, b3, s1, s2, s3, inc])
    db.commit()


def test_turnaround_analytics(auth_client, db: Session) -> None:
    _seed(db)
    body = auth_client.get("/api/analytics/turnaround?start=2026-11-01&end=2026-11-07").json()
    assert body["target_minutes"] == 120
    k = body["kpis"]
    assert k["loads_processed"]["current"] == 3
    assert k["avg_turnaround_minutes"]["current"] == 113.3  # (100+140+100)/3
    assert k["within_target_pct"]["current"] == 33.3  # only s1 (bay 2 target is 90)

    bays = {b["bay"]["code"]: b for b in body["bays"]}
    assert bays["B1"]["loads"] == 2 and bays["B1"]["avg_turnaround_minutes"] == 120.0
    assert bays["B1"]["avg_loading_minutes"] == 80.0 and bays["B1"]["status"] == "within"
    assert bays["B1"]["within_target_pct"] == 50.0
    assert bays["B1"]["utilization_pct"] == round(240 / (7 * 12 * 60) * 100, 1)
    assert bays["B2"]["status"] == "above" and bays["B2"]["bay"]["effective_target_minutes"] == 90
    assert bays["B3"]["status"] == "no_data" and bays["B3"]["loads"] == 0

    assert body["causes"] == [{"cause": "loading_congestion", "count": 1, "impact_minutes": 20}]
    assert body["recent_incidents"][0]["truck"]["label"] == "KCB 2B"
    nov2 = next(p for p in body["trend"] if p["day"] == "2026-11-02")
    assert nov2["loads_processed"] == 3


def test_turnaround_analytics_validation(auth_client) -> None:
    assert (
        auth_client.get("/api/analytics/turnaround?start=2026-11-07&end=2026-11-01").status_code
        == 422
    )
    empty = auth_client.get("/api/analytics/turnaround").json()
    assert empty["kpis"]["avg_turnaround_minutes"]["current"] is None and empty["bays"] == []
