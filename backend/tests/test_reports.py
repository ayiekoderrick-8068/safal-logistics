"""Operational reporting: calculations, filters, timezone boundaries, exports and permissions.

Scenario on Mon 2 Nov 2026 (Africa/Nairobi, UTC+3), target 120 min (bay B2: 90 min):
  L1  T1/B1  arrive 06:00 start 06:10 finish 07:10 depart 07:40  -> wait 10, load 60, post 30, TA 100
      dispatched R1 07:40, expected 08:40, delivered 08:50 (10 min late, within 15 min grace) -> on time
  L2  T2/B1  arrive 10:00 start 10:30 finish 12:00 depart 12:20  -> wait 30, load 90, post 20, TA 140
      dispatched R2 12:20, expected 15:20, delivered 16:00 (40 min late) -> late, flagged delayed
  L3  T1/B2  arrive 13:00 start 13:05 finish 14:20 depart 14:40  -> wait 5, load 75, post 20, TA 100 (> 90)
      dispatched R1 14:40, in transit -> pending
  L4  T2/B2  1 Nov 23:30 -> 23:50 local (20:30Z): belongs to 1 Nov, not 2 Nov
  L5  T3/B1  arrived 16:00, still on site (ongoing)
  Incidents: I1 L2 loading congestion 30 min impact, 10:10-10:50 resolved
             I2 dispatch L2 traffic 40 min, open
             I3 linked to BOTH L3 and its dispatch, documentation 15 min, open (count once)
"""

import csv
import io
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AuditEvent,
    DelayCause,
    DelayIncident,
    Dispatch,
    DispatchStatus,
    Driver,
    IncidentStatus,
    LoadingBay,
    LoadingSchedule,
    ReportRun,
    Role,
    Route,
    ScheduleStatus,
    Truck,
)
from app.services.exports import safe_cell, write_csv
from tests.conftest import TEST_PASSWORD

TZ = get_settings().tz
DAY = date(2026, 11, 2)
Q = "period=custom&start=2026-11-02&end=2026-11-02"


def at(h: int, m: int = 0, day: date = DAY) -> datetime:
    return datetime.combine(day, time(h, m), tzinfo=TZ)


@pytest.fixture
def ids(db: Session) -> dict[str, int]:
    d1, d2 = (
        Driver(full_name="Jane One", licence_number="L1"),
        Driver(full_name="Joe Two", licence_number="L2"),
    )
    t1 = Truck(registration="KAA 001A", capacity_tonnes=Decimal(10), driver=d1)
    t2 = Truck(registration="KBB 002B", capacity_tonnes=Decimal(10), driver=d2)
    t3 = Truck(registration="KCC 003C", capacity_tonnes=Decimal(10))
    b1 = LoadingBay(code="B1", name="Bay 01")
    b2 = LoadingBay(code="B2", name="Bay 02", target_turnaround_minutes=90)
    b3 = LoadingBay(code="B3", name="Bay 03")
    r1 = Route(
        origin="Nairobi", destination="Thika", distance_km=Decimal(45), expected_duration_minutes=60
    )
    r2 = Route(
        origin="Nairobi",
        destination="Nakuru",
        distance_km=Decimal(160),
        expected_duration_minutes=180,
    )

    def load(truck, bay, arrive, start, finish, depart, sched=None):
        s0 = sched or arrive
        return LoadingSchedule(
            truck=truck,
            bay=bay,
            scheduled_start=s0,
            scheduled_end=s0 + timedelta(hours=3),
            arrival_at=arrive,
            loading_started_at=start,
            loading_finished_at=finish,
            departed_at=depart,
            status=ScheduleStatus.DEPARTED if depart else ScheduleStatus.LOADING,
        )

    l1 = load(t1, b1, at(6), at(6, 10), at(7, 10), at(7, 40))
    l2 = load(t2, b1, at(10), at(10, 30), at(12), at(12, 20), sched=at(9, 15))
    l3 = load(t1, b2, at(13), at(13, 5), at(14, 20), at(14, 40))
    l4 = load(
        t2,
        b2,
        at(23, 30, DAY - timedelta(days=1)),
        at(23, 35, DAY - timedelta(days=1)),
        at(23, 45, DAY - timedelta(days=1)),
        at(23, 50, DAY - timedelta(days=1)),
    )
    l5 = load(t3, b1, at(16), None, None, None, sched=at(16))
    d1_ = Dispatch(
        load_ref="LD-1",
        schedule=l1,
        truck=t1,
        route=r1,
        dispatched_at=at(7, 40),
        expected_arrival_at=at(8, 40),
        actual_arrival_at=at(8, 50),
        status=DispatchStatus.DELIVERED,
    )
    d2_ = Dispatch(
        load_ref="LD-2",
        schedule=l2,
        truck=t2,
        route=r2,
        dispatched_at=at(12, 20),
        expected_arrival_at=at(15, 20),
        actual_arrival_at=at(16),
        status=DispatchStatus.DELIVERED,
        is_delayed=True,
    )
    d3_ = Dispatch(
        load_ref="LD-3",
        schedule=l3,
        truck=t1,
        route=r1,
        dispatched_at=at(14, 40),
        expected_arrival_at=at(15, 40),
        status=DispatchStatus.IN_TRANSIT,
    )
    i1 = DelayIncident(
        schedule=l2,
        cause=DelayCause.LOADING_CONGESTION,
        delay_minutes=30,
        occurred_at=at(10, 10),
        resolved_at=at(10, 50),
        status=IncidentStatus.RESOLVED,
        resolution_notes="ok",
    )
    i2 = DelayIncident(
        dispatch=d2_,
        cause=DelayCause.TRAFFIC,
        delay_minutes=40,
        occurred_at=at(15, 20),
        description='=HYPERLINK("http://evil","x")',
    )
    i3 = DelayIncident(
        schedule=l3,
        dispatch=d3_,
        cause=DelayCause.DOCUMENTATION,
        delay_minutes=15,
        occurred_at=at(14, 45),
    )
    db.add_all([b3, r1, r2, l1, l2, l3, l4, l5, d1_, d2_, d3_, i1, i2, i3])
    db.flush()
    db.add(
        AuditEvent(
            action="dispatch.blocked",
            entity_type="loading_schedule",
            entity_id=str(l3.id),
            summary="blocked",
            created_at=at(14, 30),
        )
    )
    db.commit()
    return {
        "t1": t1.id,
        "t2": t2.id,
        "d2": d2.id,
        "b1": b1.id,
        "b2": b2.id,
        "b3": b3.id,
        "r1": r1.id,
        "r2": r2.id,
    }


# ---------------------------------------------------------------- calculations
def test_summary_kpis(auth_client, ids) -> None:
    k = auth_client.get(f"/api/reports/summary?{Q}").json()["kpis"]
    assert k == {
        "loads_processed": 3,
        "completed_dispatches": 2,
        "pending_deliveries": 1,
        "on_time_pct": 50.0,
        "avg_turnaround_minutes": 113.3,
        "delayed_loads": 2,
        "bay_utilization_pct": k["bay_utilization_pct"],
        "compliance_interruptions": 1,
        "delay_incidents": 3,
    }
    # B1: 100 + 140 + ongoing 16:00-24:00 (480) = 720; B2: 100; B3: 0 -> 820 / (3 bays x 12 h) = 37.96%
    assert k["bay_utilization_pct"] == 38.0


def test_turnaround_components_and_ongoing_excluded(auth_client, ids) -> None:
    t = auth_client.get(f"/api/reports/turnaround?{Q}").json()
    c = t["components"]
    assert c["waiting"] == {"count": 3, "avg": 15.0, "median": 10.0, "min": 5.0, "max": 30.0}
    assert c["loading"] == {"count": 3, "avg": 75.0, "median": 75.0, "min": 60.0, "max": 90.0}
    assert c["post_load"]["avg"] == 23.3
    assert c["turnaround"] == {
        "count": 3,
        "avg": 113.3,
        "median": 100.0,
        "min": 100.0,
        "max": 140.0,
    }
    assert c["delivery"] == {"count": 2, "avg": 145.0, "median": 145.0, "min": 70.0, "max": 220.0}
    assert t["ongoing_loads"] == 1 and t["completed_loads"] == 3
    assert t["within_target_pct"] == 33.3  # L3 exceeds bay B2's 90 min target
    bays = {b["label"]: b for b in t["by_bay"]}
    assert bays["Bay 01"]["loads"] == 2 and bays["Bay 01"]["avg_minutes"] == 120.0
    assert {r["label"] for r in t["by_route"]} == {"Nairobi → Thika", "Nairobi → Nakuru"}
    assert [w["period"] for w in t["weekly"]] == ["2026-11-02"]  # ISO week starting Monday


def test_timezone_boundary(auth_client, ids) -> None:
    nov1 = auth_client.get(
        "/api/reports/turnaround?period=custom&start=2026-11-01&end=2026-11-01"
    ).json()
    assert nov1["completed_loads"] == 1 and nov1["components"]["turnaround"]["avg"] == 20.0


@pytest.mark.parametrize(
    ("extra", "loads"),
    [
        ("truck_id={t1}", 2),
        ("driver_id={d2}", 1),
        ("bay_id={b2}", 1),
        ("route_id={r2}", 1),
        ("dispatch_status=delivered", 2),
        ("dispatch_status=delayed", 1),
        ("dispatch_status=in_transit", 1),
        ("delay_cause=traffic", 1),
        ("delay_cause=documentation", 1),
        ("truck_id={t1}&bay_id={b1}", 1),
        ("truck_id={t2}&route_id={r1}", 0),
    ],
)
def test_combined_filters(auth_client, ids, extra, loads) -> None:
    body = auth_client.get(f"/api/reports/summary?{Q}&{extra.format(**ids)}").json()
    assert body["kpis"]["loads_processed"] == loads


def test_delay_analysis_counts_each_incident_once(auth_client, ids) -> None:
    d = auth_client.get(f"/api/reports/delays?{Q}").json()
    assert d["total"] == 3 and d["open"] == 2 and d["resolved"] == 1
    assert d["impact_minutes"] == 85 and d["avg_resolution_minutes"] == 40.0
    assert {c["cause"]: c["count"] for c in d["by_cause"]} == {
        "loading_congestion": 1,
        "traffic": 1,
        "documentation": 1,
    }
    assert {b["label"]: b["count"] for b in d["by_bay"]} == {"Bay 01": 2, "Bay 02": 1}
    assert {r["label"]: r["count"] for r in d["by_truck"]} == {"KBB 002B": 2, "KAA 001A": 1}
    assert d["repeat_patterns"] == []
    assert d["recent"][0]["cause"] == "traffic" and d["recent"][0]["ongoing"] is True
    only_traffic = auth_client.get(f"/api/reports/delays?{Q}&delay_cause=traffic").json()
    assert only_traffic["total"] == 1


def test_dispatch_performance(auth_client, ids) -> None:
    d = auth_client.get(f"/api/reports/dispatch?{Q}").json()
    assert (d["dispatched"], d["completed"], d["on_time"], d["late"], d["pending"]) == (
        3,
        2,
        1,
        1,
        1,
    )
    assert (
        d["on_time_pct"] == 50.0
        and d["avg_delivery_minutes"] == 145.0
        and d["avg_planned_minutes"] == 120.0
    )
    assert d["scheduled_loads"] == 4  # L1, L2, L3, L5 bookings start on 2 Nov
    dist = {x["bucket"]: x["count"] for x in d["delay_distribution"]}
    assert dist["Within grace"] == 1 and dist["30–60 min late"] == 1
    r1 = next(r for r in d["by_route"] if r["label"] == "Nairobi → Thika")
    assert (r1["dispatches"], r1["completed"], r1["pending"], r1["on_time_pct"]) == (2, 1, 1, 100.0)


def test_bay_performance_and_utilisation(auth_client, ids) -> None:
    b = auth_client.get(f"/api/reports/bays?{Q}&hours_per_day=12").json()
    bays = {x["code"]: x for x in b["bays"]}
    assert (
        bays["B1"]["loads"] == 2
        and bays["B1"]["delayed"] == 1
        and bays["B1"]["avg_waiting_minutes"] == 20.0
    )
    assert bays["B1"]["utilization_pct"] == 100.0  # 720 occupied min / 720 available
    assert bays["B2"]["utilization_pct"] == round(100 / 720 * 100, 1)
    assert bays["B3"]["utilization_pct"] is None  # no recorded occupancy -> no figure, not 0
    assert bays["B1"]["peak_hour"] in ("06:00", "10:00", "16:00")
    assert sum(p["arrivals"] for p in b["peak_hours"]) == 4
    wider = auth_client.get(f"/api/reports/bays?{Q}&hours_per_day=24").json()
    assert {x["code"]: x for x in wider["bays"]}["B2"]["utilization_pct"] == round(
        100 / 1440 * 100, 1
    )


def test_records_pagination(auth_client, ids) -> None:
    p1 = auth_client.get(f"/api/reports/records?{Q}&type=turnaround&limit=2&offset=0").json()
    p2 = auth_client.get(f"/api/reports/records?{Q}&type=turnaround&limit=2&offset=2").json()
    assert p1["total"] == 3 and len(p1["items"]) == 2 and len(p2["items"]) == 1
    assert p1["items"][0]["departed_at"] > p1["items"][1]["departed_at"]
    assert {r["load_ref"] for r in p1["items"] + p2["items"]} == {"LD-1", "LD-2", "LD-3"}
    disp = auth_client.get(f"/api/reports/records?{Q}&type=dispatches").json()
    assert {r["outcome"] for r in disp["items"]} == {"on_time", "late", "pending"}


def test_empty_dataset_and_validation(auth_client) -> None:
    s = auth_client.get("/api/reports/summary?period=today").json()
    assert s["kpis"]["loads_processed"] == 0 and s["kpis"]["on_time_pct"] is None
    assert s["kpis"]["bay_utilization_pct"] is None
    assert (
        auth_client.get("/api/reports/turnaround?period=yesterday").json()["components"][
            "turnaround"
        ]["avg"]
        is None
    )
    assert auth_client.get("/api/reports/summary?period=custom&start=2026-11-05").status_code == 422
    assert (
        auth_client.get(
            "/api/reports/summary?period=custom&start=2026-11-05&end=2026-11-01"
        ).status_code
        == 422
    )
    assert (
        auth_client.get(
            "/api/reports/summary?period=custom&start=2024-01-01&end=2026-11-01"
        ).status_code
        == 422
    )
    csv_resp = auth_client.get("/api/reports/export/dispatches.csv?period=today")
    assert csv_resp.status_code == 200 and "Load ref,Truck" in csv_resp.text
    assert auth_client.get("/api/reports/export/executive.pdf?period=today").content.startswith(
        b"%PDF-"
    )


# ---------------------------------------------------------------- CSV
def test_safe_cell_blocks_formula_injection() -> None:
    for bad in ("=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tx", "\rx"):
        assert safe_cell(bad).startswith("'")
    assert safe_cell(-5) == -5 and safe_cell(12.5) == 12.5  # real numbers untouched
    assert safe_cell("Nairobi → Thika") == "Nairobi → Thika"
    assert safe_cell(None) == "" and safe_cell(True) == "yes"
    text, n = write_csv(
        [("A", lambda r: r["a"]), ("B", lambda r: r["b"])], [{"a": 'x,"y"', "b": "=bad"}]
    )
    assert n == 1 and list(csv.reader(io.StringIO(text.lstrip("﻿")))) == [
        ["A", "B"],
        ['x,"y"', "'=bad"],
    ]


def _csv_table(text: str) -> list[dict[str, str]]:
    lines = [ln for ln in text.lstrip("﻿").splitlines() if ln and not ln.startswith("# ")]
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def test_csv_exports_respect_filters_and_format(auth_client, ids, db: Session) -> None:
    r = auth_client.get(f"/api/reports/export/turnaround.csv?{Q}&truck_id={ids['t1']}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert (
        'filename="logitrack-turnaround-20261102-20261102.csv"' in r.headers["content-disposition"]
    )
    assert "# Truck,KAA 001A" in r.text  # applied filters recorded in the file
    data = _csv_table(r.text)
    assert [row["Load ref"] for row in data] == ["LD-1", "LD-3"]
    assert (
        data[0]["Arrival"] == "2026-11-02T06:00:00+03:00"
        and data[0]["Yard turnaround (min)"] == "100.0"
    )
    assert data[0]["Within target"] == "yes" and data[1]["Within target"] == "no"

    delays = _csv_table(auth_client.get(f"/api/reports/export/delays.csv?{Q}").text)
    assert len(delays) == 3
    assert next(d for d in delays if d["Category"] == "traffic")["Description"].startswith(
        "'=HYPERLINK"
    )

    for dataset in ("operations", "schedules", "dispatches", "fleet", "compliance"):
        resp = auth_client.get(f"/api/reports/export/{dataset}.csv?{Q}")
        assert resp.status_code == 200, dataset
    fleet = auth_client.get("/api/reports/export/fleet.csv").text
    assert (
        "Registration" in fleet and "L1" not in fleet.split("\n", 6)[-1]
    )  # no licence numbers exported
    assert auth_client.get("/api/reports/export/nope.csv").status_code == 404

    runs = db.scalars(select(ReportRun).order_by(ReportRun.id)).all()
    assert (
        runs[0].report_type == "turnaround" and runs[0].format == "csv" and runs[0].row_count == 2
    )
    assert runs[0].filters["truck_id"] == str(ids["t1"]) and runs[0].status == "success"


# ---------------------------------------------------------------- PDF
@pytest.mark.parametrize(
    "report", ["executive", "turnaround", "bays", "dispatch", "delays", "compliance"]
)
def test_pdf_reports_generate(auth_client, ids, report) -> None:
    r = auth_client.get(f"/api/reports/export/{report}.pdf?{Q}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-") and r.content.rstrip().endswith(b"%%EOF")
    assert len(re.findall(rb"/Type /Page\b", r.content)) >= 1
    assert b"LogiTrack" in r.content  # document metadata / branding


def test_history_lists_own_runs(auth_client, client, make_user, ids) -> None:
    auth_client.get(f"/api/reports/export/executive.pdf?{Q}")
    h = auth_client.get("/api/reports/history").json()
    assert h[0]["report_type"] == "executive" and h[0]["title"] == "Executive Operations Summary"
    assert h[0]["format"] == "pdf" and h[0]["requested_by"] == "Derrick"


# ---------------------------------------------------------------- permissions
@pytest.mark.parametrize(
    ("role", "view", "ops_csv", "ops_pdf", "fleet_csv", "compliance_pdf"),
    [
        (Role.ADMIN, 200, 200, 200, 200, 200),
        (Role.OPERATIONS, 200, 200, 200, 200, 403),
        (Role.FLEET_MANAGER, 200, 200, 200, 200, 200),
        (Role.COMPLIANCE, 403, 403, 403, 403, 200),
        (Role.VIEWER, 200, 403, 403, 403, 403),
    ],
)
def test_report_permissions(
    client, make_user, role, view, ops_csv, ops_pdf, fleet_csv, compliance_pdf
) -> None:
    make_user("u", role=role)
    client.post("/api/auth/login", json={"username": "u", "password": TEST_PASSWORD})
    assert client.get("/api/reports/summary").status_code == view
    assert client.get("/api/reports/records").status_code == view
    assert client.get("/api/reports/export/dispatches.csv").status_code == ops_csv
    assert client.get("/api/reports/export/delays.pdf").status_code == ops_pdf
    assert client.get("/api/reports/export/fleet.csv").status_code == fleet_csv
    assert client.get("/api/reports/export/compliance.pdf").status_code == compliance_pdf
    keys = {c["key"] for c in client.get("/api/reports/catalogue").json()}
    assert ("compliance" in keys) == (compliance_pdf == 200)
    assert ("executive" in keys) == (ops_pdf == 200)


def test_reports_require_login(client) -> None:
    assert client.get("/api/reports/summary").status_code == 401
    assert client.get("/api/reports/export/fleet.csv").status_code == 401
