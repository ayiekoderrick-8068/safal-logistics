"""End-to-end API tests of the core workflow:
register truck -> schedule loading -> record loading times -> dispatch -> deliver -> turnaround.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, DelayIncident, Role
from tests.conftest import TEST_PASSWORD


def iso(dt: datetime) -> str:
    return dt.isoformat()


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


@pytest.fixture
def setup(auth_client: TestClient) -> dict[str, int]:
    """Reference data created through the API (admin)."""
    c = auth_client
    driver = c.post("/api/drivers", json={"full_name": "James Otieno", "licence_number": "dl-1001"})
    assert driver.status_code == 201, driver.text
    truck = c.post(
        "/api/trucks",
        json={
            "registration": " kca  204t ",
            "make": "Isuzu",
            "capacity_tonnes": 10,
            "driver_id": driver.json()["id"],
        },
    )
    assert truck.status_code == 201, truck.text
    bay = c.post("/api/bays", json={"code": "bay 01", "name": "Bay 01"})
    assert bay.status_code == 201, bay.text
    route = c.post(
        "/api/routes",
        json={
            "origin": "nairobi",
            "destination": "nakuru",
            "distance_km": 160,
            "expected_duration_minutes": 75,
        },
    )
    assert route.status_code == 201, route.text
    return {
        "driver": driver.json()["id"],
        "truck": truck.json()["id"],
        "bay": bay.json()["id"],
        "route": route.json()["id"],
    }


def book(c: TestClient, setup: dict[str, int], start: datetime, minutes: int = 120, **kw):
    return c.post(
        "/api/schedules",
        json={
            "truck_id": kw.get("truck", setup["truck"]),
            "bay_id": kw.get("bay", setup["bay"]),
            "scheduled_start": iso(start),
            "scheduled_end": iso(start + timedelta(minutes=minutes)),
        },
    )


def event(c: TestClient, sid: int, name: str, at: datetime):
    return c.post(f"/api/schedules/{sid}/events", json={"event": name, "at": iso(at)})


def load_through_finish(c: TestClient, setup, now: datetime) -> int:
    sid = book(c, setup, now - timedelta(minutes=30)).json()["id"]
    assert event(c, sid, "arrived", now - timedelta(minutes=25)).status_code == 200
    assert event(c, sid, "loading_started", now - timedelta(minutes=20)).status_code == 200
    assert event(c, sid, "loading_finished", now - timedelta(minutes=5)).status_code == 200
    return sid


def test_reference_data_is_normalised(auth_client, setup) -> None:
    truck = auth_client.get(f"/api/trucks/{setup['truck']}").json()
    assert truck["registration"] == "KCA 204T"
    assert truck["driver"]["label"] == "James Otieno"
    assert truck["compliance"]["status"] == "missing"
    routes = auth_client.get("/api/routes").json()
    assert routes[0]["label"] == "Nairobi → Nakuru"
    assert auth_client.get("/api/bays").json()[0]["code"] == "BAY-01"


def test_full_workflow_calculates_turnaround(auth_client, setup, now, db: Session) -> None:
    c = auth_client
    sid = load_through_finish(c, setup, now)
    assert c.get(f"/api/trucks/{setup['truck']}").json()["status"] == "loading"
    assert [s["id"] for s in c.get("/api/dispatches/ready").json()] == [sid]

    d = c.post(
        "/api/dispatches",
        json={
            "schedule_id": sid,
            "route_id": setup["route"],
            "dispatched_at": iso(now - timedelta(minutes=2)),
        },
    )
    assert d.status_code == 201, d.text
    dispatch = d.json()
    assert dispatch["status"] == "in_transit"
    assert dispatch["load_ref"].startswith("LD-")
    assert dispatch["turnaround_minutes"] == 23.0  # arrival -25 min -> departure -2 min
    assert c.get(f"/api/trucks/{setup['truck']}").json()["status"] == "in_transit"
    assert c.get("/api/dispatches/ready").json() == []

    done = c.post(f"/api/dispatches/{dispatch['id']}/deliver", json={"actual_arrival_at": iso(now)})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "delivered" and done.json()["is_delayed"] is False
    assert c.get(f"/api/trucks/{setup['truck']}").json()["status"] == "available"

    schedule = c.get("/api/schedules").json()["items"][0]
    assert schedule["status"] == "departed"
    assert schedule["loading_minutes"] == 15.0
    assert schedule["turnaround_minutes"] == 23.0
    assert schedule["within_target"] is True
    assert schedule["load_ref"] == dispatch["load_ref"]

    detail = c.get(f"/api/trucks/{setup['truck']}").json()
    assert detail["loads_completed_30d"] == 1 and detail["avg_turnaround_30d"] == 23.0
    assert detail["last_route"] == "Nairobi → Nakuru"

    overview = c.get("/api/dashboard/overview").json()
    assert overview["kpis"]["loads_processed"]["current"] == 1
    assert overview["kpis"]["avg_turnaround_minutes"]["current"] == 23.0

    actions = set(db.scalars(select(AuditEvent.action)))
    assert {
        "truck.created",
        "schedule.created",
        "schedule.arrived",
        "schedule.loading_started",
        "schedule.loading_finished",
        "dispatch.created",
        "dispatch.delivered",
    } <= actions


def test_overlapping_bookings_rejected(auth_client, setup, now) -> None:
    c = auth_client
    assert book(c, setup, now + timedelta(hours=1)).status_code == 201
    clash = book(c, setup, now + timedelta(hours=2))  # same bay, overlaps
    assert clash.status_code == 409
    assert "Bay 01 is already booked by KCA 204T" in clash.json()["detail"]

    other_bay = c.post("/api/bays", json={"code": "BAY-02", "name": "Bay 02"}).json()["id"]
    same_truck = book(c, setup, now + timedelta(hours=2), bay=other_bay)
    assert same_truck.status_code == 409
    assert "KCA 204T is already booked" in same_truck.json()["detail"]
    assert (
        book(c, setup, now + timedelta(hours=3), bay=other_bay).status_code == 201
    )  # back-to-back


def test_events_must_follow_order_and_time(auth_client, setup, now) -> None:
    c = auth_client
    sid = book(c, setup, now - timedelta(minutes=30)).json()["id"]
    assert event(c, sid, "loading_started", now).status_code == 409  # not arrived yet
    assert event(c, sid, "arrived", now + timedelta(hours=1)).status_code == 422  # future
    assert event(c, sid, "arrived", now - timedelta(minutes=10)).status_code == 200
    early = event(c, sid, "loading_started", now - timedelta(minutes=20))
    assert early.status_code == 422 and "earlier than the previous step" in early.json()["detail"]
    assert event(c, sid, "arrived", now).status_code == 409  # cannot repeat


def test_dispatch_requires_finished_loading(auth_client, setup, now) -> None:
    sid = book(auth_client, setup, now - timedelta(minutes=30)).json()["id"]
    resp = auth_client.post(
        "/api/dispatches", json={"schedule_id": sid, "route_id": setup["route"]}
    )
    assert resp.status_code == 409


def test_flag_delay_in_transit(auth_client, setup, now, db: Session) -> None:
    c = auth_client
    sid = load_through_finish(c, setup, now)
    did = c.post(
        "/api/dispatches",
        json={
            "schedule_id": sid,
            "route_id": setup["route"],
            "dispatched_at": iso(now - timedelta(minutes=4)),
        },
    ).json()["id"]
    assert c.get("/api/dispatches").json()["items"][0]["is_overdue"] is False

    flagged = c.post(
        f"/api/dispatches/{did}/flag-delay",
        json={"cause": "traffic", "estimated_delay_minutes": 30},
    )
    assert flagged.status_code == 200
    assert flagged.json()["is_delayed"] is True and flagged.json()["delay_cause"] == "traffic"
    assert db.scalar(select(DelayIncident.cause)) == "traffic"


def test_late_delivery_without_cause_is_rejected(auth_client, setup, now, db: Session) -> None:
    from app.models import Dispatch

    c = auth_client
    sid = load_through_finish(c, setup, now)
    did = c.post(
        "/api/dispatches",
        json={
            "schedule_id": sid,
            "route_id": setup["route"],
            "dispatched_at": iso(now - timedelta(minutes=4)),
        },
    ).json()["id"]
    # Simulate a long-running trip: expected arrival 40 minutes ago.
    d = db.get(Dispatch, did)
    d.dispatched_at = now - timedelta(minutes=60)
    d.expected_arrival_at = now - timedelta(minutes=40)
    db.commit()

    assert c.get("/api/dispatches").json()["items"][0]["is_overdue"] is True
    missing = c.post(f"/api/dispatches/{did}/deliver", json={"actual_arrival_at": iso(now)})
    assert missing.status_code == 422 and "select a delay cause" in missing.json()["detail"]

    ok = c.post(
        f"/api/dispatches/{did}/deliver",
        json={"actual_arrival_at": iso(now), "delay_cause": "documentation"},
    )
    assert ok.status_code == 200
    assert ok.json()["is_delayed"] is True and ok.json()["delay_minutes"] == 40
    assert ok.json()["delay_cause"] == "documentation"
    overview = c.get("/api/dispatch/overview").json()
    assert overview["delivered_today"] == 1
    assert overview["on_time_rate_7d"] == 0.0


def test_maintenance_blocks_scheduling_and_busy_trucks_keep_status(auth_client, setup, now) -> None:
    c = auth_client
    assert (
        c.patch(f"/api/trucks/{setup['truck']}", json={"status": "maintenance"}).status_code == 200
    )
    blocked = book(c, setup, now + timedelta(hours=1))
    assert blocked.status_code == 409 and "maintenance" in blocked.json()["detail"]

    assert c.patch(f"/api/trucks/{setup['truck']}", json={"status": "available"}).status_code == 200
    sid = book(c, setup, now - timedelta(minutes=30)).json()["id"]
    event(c, sid, "arrived", now - timedelta(minutes=5))
    busy = c.patch(f"/api/trucks/{setup['truck']}", json={"status": "maintenance"})
    assert busy.status_code == 409


def test_cancel_returns_truck_and_frees_bay(auth_client, setup, now) -> None:
    c = auth_client
    sid = book(c, setup, now - timedelta(minutes=30)).json()["id"]
    event(c, sid, "arrived", now - timedelta(minutes=5))
    assert c.post(f"/api/schedules/{sid}/cancel").json()["status"] == "cancelled"
    assert c.get(f"/api/trucks/{setup['truck']}").json()["status"] == "available"
    assert book(c, setup, now - timedelta(minutes=30)).status_code == 201


def test_driver_and_registration_conflicts(auth_client, setup) -> None:
    c = auth_client
    dup = c.post("/api/trucks", json={"registration": "KCA 204T", "capacity_tonnes": 5})
    assert dup.status_code == 409
    taken = c.post(
        "/api/trucks",
        json={"registration": "KDB 118M", "capacity_tonnes": 5, "driver_id": setup["driver"]},
    )
    assert taken.status_code == 409 and "already assigned" in taken.json()["detail"]
    bad = c.post("/api/trucks", json={"registration": "KD@ 1", "capacity_tonnes": 5})
    assert bad.status_code == 422

    unassign = c.patch(f"/api/trucks/{setup['truck']}", json={"driver_id": None})
    assert unassign.json()["driver"] is None
    assert len(c.get("/api/drivers?unassigned=true").json()) == 1


@pytest.mark.parametrize(
    ("role", "method", "path", "expected"),
    [
        (Role.VIEWER, "post", "/api/trucks", 403),
        (Role.OPERATIONS, "post", "/api/trucks", 403),
        (Role.FLEET_MANAGER, "post", "/api/trucks", 422),  # allowed; fails validation only
        (Role.FLEET_MANAGER, "post", "/api/schedules", 403),
        (Role.OPERATIONS, "post", "/api/schedules", 422),
        (Role.VIEWER, "post", "/api/dispatches", 403),
        (Role.VIEWER, "get", "/api/trucks", 200),
        (Role.VIEWER, "get", "/api/loading/overview", 200),
        (Role.VIEWER, "get", "/api/dispatch/overview", 200),
    ],
)
def test_role_permissions(client, make_user, role, method, path, expected) -> None:
    make_user("someone", role=role)
    client.post("/api/auth/login", json={"username": "someone", "password": TEST_PASSWORD})
    resp = getattr(client, method)(path, **({"json": {}} if method == "post" else {}))
    assert resp.status_code == expected, resp.text


def test_page_overviews(auth_client, setup, now) -> None:
    c = auth_client
    load_through_finish(c, setup, now)
    lo = c.get("/api/loading/overview").json()
    assert lo["scheduled_count"] == 1 and lo["completed_count"] == 1
    assert lo["avg_loading_minutes"] == 15.0
    assert lo["bay_board"][0]["state"] == "in_use" and lo["bay_board"][0]["progress_pct"] == 100
    summary = c.get("/api/trucks/summary").json()
    assert summary == {
        "total": 1,
        "available": 0,
        "loading": 1,
        "in_transit": 0,
        "maintenance": 0,
        "out_of_service": 0,
        "compliance_due": 0,
        "availability_pct": 0.0,
    }
