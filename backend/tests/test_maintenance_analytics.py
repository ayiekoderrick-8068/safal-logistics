"""Maintenance KPIs (exact arithmetic on a fixed past window), dashboard, reports and exports."""

import csv
import io
from datetime import UTC, date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.main import create_app
from app.models import MaintenanceRole, Role, User
from app.models_maintenance import (
    Breakdown,
    BreakdownSeverity,
    Equipment,
    EquipmentCategory,
    FaultCategory,
    MaintenanceTask,
    TaskStatus,
    WorkOrder,
    WorkOrderPriority,
    WorkOrderStatus,
    WorkOrderType,
)
from app.services import maintenance_analytics as ma
from tests.conftest import TEST_PASSWORD

UTC_ = UTC
D0, D9 = date(2026, 1, 1), date(2026, 1, 10)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """UTC timestamp on 2026-01-<day> (day 0 = 31 Dec 2025)."""
    base = datetime(2025, 12, 31, tzinfo=UTC)
    return base + timedelta(days=day, hours=hour, minutes=minute)


def fixed_window() -> ma.Window:
    tz = get_settings().tz
    return ma.Window(
        D0,
        D9,
        datetime.combine(D0, time.min, tz).astimezone(UTC),
        datetime.combine(D9 + timedelta(days=1), time.min, tz).astimezone(UTC),
    )


@pytest.fixture
def scenario(db: Session, make_user) -> dict:
    tech = make_user("tech", role=Role.VIEWER, maintenance_role=MaintenanceRole.TECHNICIAN)
    old = datetime(2025, 12, 1, tzinfo=UTC)
    a = Equipment(
        code="A-1",
        name="Conveyor A",
        category=EquipmentCategory.CONVEYOR,
        facility="Plant",
        created_at=old,
    )
    b = Equipment(
        code="B-1", name="Pump B", category=EquipmentCategory.PUMP, facility="Plant", created_at=old
    )
    db.add_all([a, b])
    db.flush()
    n = iter(range(1, 100))

    def bd(start, end, down=True, cat=FaultCategory.ELECTRICAL):
        db.add(
            Breakdown(
                number=f"BD-T-{next(n):05d}",
                equipment_id=a.id,
                started_at=start,
                restored_at=end,
                severity=BreakdownSeverity.MAJOR,
                category=cat,
                description="Test failure",
                equipment_down=down,
            )
        )

    # Window starts 2026-01-01 00:00 Nairobi = 2025-12-31 21:00 UTC.
    bd(at(0, 20), at(0, 22))  # started before the window: 60 min counted, not a failure
    bd(at(2, 8), at(2, 10))  # 120 min, failure
    bd(at(6, 12), at(6, 13), cat=FaultCategory.MECHANICAL)  # 60 min, failure
    bd(at(8, 9), at(8, 9, 30), down=False)  # did not stop the asset: no downtime, no failure

    def wo(kind, status, created, started=None, done=None, **kw):
        db.add(
            WorkOrder(
                number=f"WO-T-{next(n):05d}",
                equipment_id=a.id,
                maintenance_type=kind,
                priority=WorkOrderPriority.HIGH,
                status=status,
                fault_description="Test work",
                assigned_technician_id=tech.id if status is not WorkOrderStatus.OPEN else None,
                created_at=created,
                started_at=started,
                completed_at=done,
                **kw,
            )
        )

    C, P_ = WorkOrderType.CORRECTIVE, WorkOrderType.PREVENTIVE
    wo(
        C, WorkOrderStatus.COMPLETED, at(2, 8), at(2, 8, 30), at(2, 10), work_performed="Fixed"
    )  # 90 min
    wo(
        C,
        WorkOrderStatus.COMPLETED,
        at(6, 12),
        at(6, 12, 10),
        at(6, 12, 50),
        work_performed="Fixed",
    )  # 40 min
    wo(
        P_, WorkOrderStatus.COMPLETED, at(4, 8), at(4, 8), at(4, 8, 30), work_performed="Serviced"
    )  # not MTTR
    wo(C, WorkOrderStatus.OPEN, at(7, 8))
    wo(C, WorkOrderStatus.CANCELLED, at(7, 9), cancel_reason="Duplicate")

    def task(due, status=TaskStatus.SCHEDULED, done=None, **kw):
        db.add(
            MaintenanceTask(
                equipment_id=a.id, title="PM", due_on=due, status=status, completed_on=done, **kw
            )
        )

    task(date(2026, 1, 3), TaskStatus.COMPLETED, date(2026, 1, 3))  # on time
    task(date(2026, 1, 5), TaskStatus.COMPLETED, date(2026, 1, 7))  # late
    task(date(2026, 1, 8))  # missed
    task(date(2026, 1, 9), TaskStatus.CANCELLED, cancel_reason="Shutdown")  # excluded
    task(date(2026, 2, 1))  # outside the window
    db.commit()
    return {"a": a.id, "b": b.id}


def test_kpis_exact(db: Session, scenario) -> None:
    k = ma.kpis(db, fixed_window())
    observed = 2 * 10 * 24 * 60  # two assets, ten days, 24 h assumption
    assert k["availability"] == {
        "pct": round((observed - 240) / observed * 100, 1),
        "observed_hours": observed / 60,
        "downtime_minutes": 240,
    }
    assert k["mtbf"] == {
        "hours": round((observed - 240) / 60 / 2, 2),
        "failures": 2,
        "operating_hours": round((observed - 240) / 60, 2),
    }
    assert k["mttr"] == {"minutes": 65.0, "repairs": 2}
    assert k["time_to_restore"] == {"minutes": 100.0, "restorations": 3}
    assert k["pm_compliance"] == {"due": 3, "on_time": 1, "late": 1, "missed": 1, "pct": 33.3}
    assert k["work_order_completion"] == {"pct": 75.0, "raised": 4, "completed": 3}


def test_per_equipment_rows(db: Session, scenario) -> None:
    rows = {r["code"]: r for r in ma.per_equipment(db, fixed_window())}
    a, b = rows["A-1"], rows["B-1"]
    assert (a["breakdowns"], a["failures"], a["downtime_minutes"]) == (3, 2, 240)
    assert a["availability_pct"] == round((14400 - 240) / 14400 * 100, 1)
    assert a["mtbf_hours"] == round((14400 - 240) / 60 / 2, 2)
    assert (a["mttr_minutes"], a["pm_due"], a["pm_on_time"], a["pm_compliance_pct"]) == (
        65.0,
        3,
        1,
        33.3,
    )
    assert (b["availability_pct"], b["mtbf_hours"], b["mttr_minutes"], b["pm_compliance_pct"]) == (
        100.0,
        None,
        None,
        None,
    )


def test_reports_have_rows(db: Session, scenario) -> None:
    w = fixed_window()
    faults = ma.REPORTS["fault-frequency"].rows(db, w, None)
    assert {(r["category"], r["breakdowns"], r["downtime_minutes"]) for r in faults} == {
        ("electrical", 2, 120),
        ("mechanical", 1, 60),
    }  # the pre-window failure is not counted
    repairs = ma.REPORTS["repair-duration"].rows(db, w, None)
    assert sorted(r["repair_minutes"] for r in repairs) == [30, 40, 90]
    completion = ma.REPORTS["maintenance-completion"].rows(db, w, None)
    assert [r["outcome"] for r in completion] == ["on time", "late", "not completed"]
    history = ma.REPORTS["maintenance-history"].rows(db, w, None)
    assert len(history) == 5  # three work orders + two preventive tasks


def test_insufficient_data_is_null_not_zero(db: Session) -> None:
    k = ma.kpis(db, fixed_window())
    assert k["availability"]["pct"] is None and k["mtbf"]["hours"] is None
    assert k["mttr"]["minutes"] is None and k["pm_compliance"]["pct"] is None
    assert k["work_order_completion"]["pct"] is None


def test_downtime_never_exceeds_observed_time(db: Session) -> None:
    """An asset registered after it failed: the recorded downtime is kept and observation starts
    at the breakdown, so availability is 0 % (not negative) and MTBF is undefined (no operating
    time) instead of a misleading 0 h."""
    reg = at(5, 0)
    e = Equipment(
        code="N-1",
        name="New press",
        category=EquipmentCategory.OTHER,
        facility="Plant",
        created_at=reg,
    )
    db.add(e)
    db.flush()
    db.add(
        Breakdown(
            number="BD-T-90001",
            equipment_id=e.id,
            started_at=at(3, 0),
            restored_at=None,
            severity=BreakdownSeverity.CRITICAL,
            category=FaultCategory.MECHANICAL,
            description="Back-dated failure",
            equipment_down=True,
        )
    )
    db.commit()
    w = fixed_window()
    (row,) = ma.per_equipment(db, w)
    observed_min = (w.end_at - at(3, 0)).total_seconds() / 60  # from the breakdown, not `reg`
    assert row["downtime_minutes"] == round(observed_min)
    assert row["observed_hours"] == round(observed_min / 60, 1)
    assert row["availability_pct"] == 0.0 and row["mtbf_hours"] is None
    k = ma.kpis(db, w)
    assert k["availability"]["downtime_minutes"] == round(observed_min)
    assert k["mtbf"] == {"hours": None, "failures": 1, "operating_hours": 0.0}
    assert sum(p["downtime_minutes"] for p in ma.downtime_trend(db, w, [e.id])) == pytest.approx(
        observed_min, abs=2
    )


def test_archived_asset_observed_until_archived(db: Session) -> None:
    e = Equipment(
        code="R-1",
        name="Retired fan",
        category=EquipmentCategory.OTHER,
        facility="Plant",
        created_at=datetime(2025, 12, 1, tzinfo=UTC),
        archived_at=at(3, 21),  # 2026-01-04 00:00 Nairobi: three whole days into the window
    )
    db.add(e)
    db.commit()
    (row,) = ma.per_equipment(db, fixed_window())
    assert row["observed_hours"] == 72.0 and row["availability_pct"] == 100.0


def test_short_mtbf_is_not_rounded_to_zero(db: Session) -> None:
    """One minute of operating time and one failure: MTBF is ~1 min, never a misleading 0."""
    w = fixed_window()
    reg = w.end_at - timedelta(minutes=61)
    e = Equipment(
        code="S-1", name="Short", category=EquipmentCategory.OTHER, facility="Plant", created_at=reg
    )
    db.add(e)
    db.flush()
    db.add(
        Breakdown(
            number="BD-T-90002",
            equipment_id=e.id,
            started_at=reg + timedelta(minutes=1),
            restored_at=w.end_at,
            severity=BreakdownSeverity.MAJOR,
            category=FaultCategory.MECHANICAL,
            description="Immediate failure",
            equipment_down=True,
        )
    )
    db.commit()
    (row,) = ma.per_equipment(db, w)
    assert row["mtbf_hours"] == round(1 / 60, 2) and row["mtbf_hours"] > 0


def test_window_validation() -> None:
    with pytest.raises(ValueError):
        ma.make_window(date(2026, 1, 10), date(2026, 1, 1))
    with pytest.raises(ValueError):
        ma.make_window(date(2024, 1, 1), date(2026, 1, 1))


def _login(client, username="derrick"):
    r = client.post(
        "/api/auth/login",
        json={"username": username, "password": TEST_PASSWORD, "workspace": "maintenance"},
    )
    assert r.status_code == 200, r.text
    return client


def test_dashboard_endpoint_live_counts(client, make_user) -> None:
    make_user()
    _login(client)
    eq = client.post(
        "/api/maintenance/equipment",
        json={"code": "C-1", "name": "Compressor", "category": "compressor", "facility": "Plant"},
    ).json()["id"]
    client.post(
        "/api/maintenance/equipment",
        json={
            "code": "C-2",
            "name": "Spare compressor",
            "category": "compressor",
            "facility": "Plant",
            "status": "out_of_service",
        },
    )
    bd = client.post(
        "/api/maintenance/breakdowns",
        json={
            "equipment_id": eq,
            "started_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            "severity": "critical",
            "category": "electrical",
            "description": "Motor tripped",
        },
    ).json()
    assert bd["work_orders"]
    d = client.get("/api/maintenance/dashboard").json()
    k = d["kpis"]
    assert (k["equipment_total"], k["operational"], k["out_of_service"], k["open_work_orders"]) == (
        2,
        0,
        2,
        1,
    )
    assert 115 <= k["downtime_minutes"] <= 125
    assert d["top_failing"][0]["code"] == "C-1"
    assert d["fault_categories"][0]["category"] == "electrical"
    assert sum(p["downtime_minutes"] for p in d["downtime_trend"]) == pytest.approx(
        k["downtime_minutes"], abs=2
    )
    assert d["recent_activity"] and d["recent_activity"][0]["equipment"]["code"] == "C-1"
    assert d["metrics"]["mttr"]["minutes"] is None  # no completed repairs yet: insufficient data


def test_report_endpoints_and_exports(client, make_user, db: Session) -> None:
    make_user()
    make_user("tech", role=Role.VIEWER, maintenance_role=MaintenanceRole.TECHNICIAN)
    make_user("keeper", role=Role.VIEWER, maintenance_role=MaintenanceRole.STOREKEEPER)
    _login(client)
    client.post(
        "/api/maintenance/equipment",
        json={"code": "=HACK", "name": "Formula test", "category": "other", "facility": "Plant"},
    )  # rejected by the code pattern
    client.post(
        "/api/maintenance/equipment",
        json={
            "code": "E-1",
            "name": "=cmd|' /C calc'!A0",
            "category": "other",
            "facility": "Plant",
        },
    )
    keys = [r["key"] for r in client.get("/api/maintenance/reports").json()]
    assert len(keys) == 7
    for key in keys:
        r = client.get(f"/api/maintenance/reports/{key}")
        assert r.status_code == 200, (key, r.text)
        assert {"columns", "rows", "kpis", "total"} <= r.json().keys()
    assert client.get("/api/maintenance/reports/nope").status_code == 404
    assert (
        client.get(
            "/api/maintenance/reports/equipment-downtime",
            params={"start": "2026-02-01", "end": "2026-01-01"},
        ).status_code
        == 422
    )

    csv_r = client.get("/api/maintenance/reports/equipment-downtime", params={"format": "csv"})
    assert csv_r.status_code == 200 and csv_r.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv_r.headers["content-disposition"]
    text = csv_r.content.decode("utf-8-sig")
    assert "'=cmd" in text  # formula neutralised
    rows = list(csv.reader(io.StringIO(text)))
    assert ["# Report", "Equipment downtime and availability"] in rows
    x = client.get("/api/maintenance/reports/repair-duration", params={"format": "xlsx"})
    assert x.status_code == 200 and x.content[:2] == b"PK"
    pdf = client.get("/api/maintenance/reports/maintenance-history", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"

    with TestClient(create_app()) as t:
        _login(t, "tech")
        assert t.get("/api/maintenance/reports/equipment-downtime").status_code == 200  # can view
        assert (
            t.get(
                "/api/maintenance/reports/equipment-downtime", params={"format": "csv"}
            ).status_code
            == 403
        )
    with TestClient(create_app()) as k:
        _login(k, "keeper")
        assert (
            k.get(
                "/api/maintenance/reports/parts-consumption", params={"format": "pdf"}
            ).status_code
            == 200
        )
    assert db.query(User).count() == 3
