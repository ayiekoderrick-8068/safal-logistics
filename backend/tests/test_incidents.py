"""Delay incident reporting, assignment, resolution and duration accuracy."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, DelayIncident, Role, UserStatus
from app.routers.incidents import duration_minutes
from tests.conftest import TEST_PASSWORD
from tests.test_workflow import book, iso, load_through_finish, setup  # noqa: F401 - fixture


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


@pytest.fixture
def schedule_id(auth_client, setup, now) -> int:
    return book(auth_client, setup, now - timedelta(minutes=30)).json()["id"]


def report(c, **kw):
    body = {"cause": "loading_congestion", "description": "Queue at the bay", **kw}
    return c.post("/api/incidents", json=body)


def test_duration_is_computed_from_timestamps() -> None:
    t0 = datetime(2026, 11, 5, 6, 0, tzinfo=UTC)
    assert duration_minutes(t0, t0 + timedelta(hours=2, minutes=5), t0) == 125
    assert duration_minutes(t0, None, t0 + timedelta(minutes=47, seconds=59)) == 47  # ongoing


def test_report_assign_and_resolve_loading_delay(
    auth_client, schedule_id, make_user, now, db: Session
) -> None:
    c = auth_client
    ops = make_user("mary", role=Role.OPERATIONS)
    started = now - timedelta(minutes=90)
    r = report(
        c,
        schedule_id=schedule_id,
        started_at=iso(started),
        impact_minutes=25,
        assigned_to_id=ops.id,
    )
    assert r.status_code == 201, r.text
    inc = r.json()
    assert inc["source"] == "loading" and inc["truck"]["label"] == "KCA 204T"
    assert inc["operation"] == "Loading at Bay 01" and inc["status"] == "open" and inc["is_ongoing"]
    assert 89 <= inc["duration_minutes"] <= 91
    assert inc["assigned_to"]["label"] == "Mary" and inc["reported_by"] == "Derrick"

    # Resolving requires notes, then records an exact resolution time.
    resolved_at = started + timedelta(minutes=72)
    missing_notes = c.patch(
        f"/api/incidents/{inc['id']}", json={"status": "resolved", "resolved_at": iso(resolved_at)}
    )
    assert missing_notes.status_code == 422 and "resolution notes" in missing_notes.json()["detail"]
    done = c.patch(
        f"/api/incidents/{inc['id']}",
        json={
            "status": "resolved",
            "resolved_at": iso(resolved_at),
            "resolution_notes": "Second forklift deployed",
        },
    )
    assert done.status_code == 200, done.text
    assert done.json()["duration_minutes"] == 72 and done.json()["is_ongoing"] is False

    # Reopening clears the resolution time; duration runs again.
    reopened = c.patch(f"/api/incidents/{inc['id']}", json={"status": "in_progress"}).json()
    assert reopened["resolved_at"] is None and reopened["is_ongoing"] is True

    actions = list(
        db.scalars(select(AuditEvent.action).where(AuditEvent.entity_type == "delay_incident"))
    )
    assert actions == ["incident.reported", "incident.resolved", "incident.reopened"]


def test_resolution_time_validation(auth_client, schedule_id, now) -> None:
    c = auth_client
    inc = report(c, schedule_id=schedule_id, started_at=iso(now - timedelta(minutes=30))).json()
    before = c.patch(
        f"/api/incidents/{inc['id']}",
        json={
            "status": "resolved",
            "resolved_at": iso(now - timedelta(hours=1)),
            "resolution_notes": "x",
        },
    )
    assert before.status_code == 422
    future = c.patch(
        f"/api/incidents/{inc['id']}",
        json={
            "status": "resolved",
            "resolved_at": iso(now + timedelta(hours=1)),
            "resolution_notes": "x",
        },
    )
    assert future.status_code == 422
    stray = c.patch(f"/api/incidents/{inc['id']}", json={"resolved_at": iso(now)})
    assert stray.status_code == 422
    assert (
        report(c, schedule_id=schedule_id, started_at=iso(now + timedelta(hours=2))).status_code
        == 422
    )


def test_validation_of_links_and_assignees(auth_client, schedule_id, make_user) -> None:
    c = auth_client
    assert report(c).status_code == 422  # no operation
    assert report(c, schedule_id=schedule_id, dispatch_id=1).status_code == 422  # both
    viewer = make_user("vic", role=Role.VIEWER)
    gone = make_user("gone", role=Role.OPERATIONS, status=UserStatus.DEACTIVATED)
    for uid in (viewer.id, gone.id):
        assert report(c, schedule_id=schedule_id, assigned_to_id=uid).status_code == 422
    names = [u["label"] for u in c.get("/api/users/assignable").json()]
    assert "Vic" not in names and "Gone" not in names and "Derrick" in names


def test_dispatch_delay_marks_dispatch_and_filters(auth_client, setup, now) -> None:
    c = auth_client
    sid = load_through_finish(c, setup, now)
    did = c.post("/api/dispatches", json={"schedule_id": sid, "route_id": setup["route"]}).json()[
        "id"
    ]
    r = report(
        c,
        dispatch_id=did,
        cause="vehicle_breakdown",
        description="Puncture near Naivasha",
        impact_minutes=40,
    )
    assert r.status_code == 201
    assert r.json()["source"] == "dispatch" and r.json()["load_ref"].startswith("LD-")
    assert c.get("/api/dispatches").json()["items"][0]["is_delayed"] is True

    report(c, schedule_id=sid, description="Late paperwork", cause="documentation")
    assert c.get("/api/incidents?source=dispatch").json()["total"] == 1
    assert c.get("/api/incidents?cause=documentation").json()["total"] == 1
    assert c.get("/api/incidents?status=unresolved").json()["total"] == 2
    assert c.get("/api/incidents?q=Naivasha").json()["total"] == 1

    s = c.get("/api/incidents/summary").json()
    assert s["unresolved"] == 2 and s["unassigned"] == 2 and s["impact_minutes_7d"] == 40
    assert {x["cause"] for x in s["by_cause_30d"]} == {"vehicle_breakdown", "documentation"}


def test_late_delivery_incident_starts_at_missed_eta(auth_client, setup, now, db: Session) -> None:
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
    d = db.get(Dispatch, did)
    d.dispatched_at, d.expected_arrival_at = (
        now - timedelta(minutes=90),
        now - timedelta(minutes=50),
    )
    db.commit()
    c.post(
        f"/api/dispatches/{did}/deliver",
        json={"actual_arrival_at": iso(now), "delay_cause": "traffic"},
    )
    inc = db.scalar(select(DelayIncident))
    assert inc.occurred_at == now - timedelta(minutes=50) and inc.delay_minutes == 50


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.OPERATIONS, 201),
        (Role.FLEET_MANAGER, 201),
        (Role.COMPLIANCE, 201),
        (Role.VIEWER, 403),
    ],
)
def test_incident_permissions(client, make_user, db, role, expected) -> None:
    from decimal import Decimal

    from app.models import LoadingBay, LoadingSchedule, Truck

    now = datetime.now(UTC)
    s = LoadingSchedule(
        truck=Truck(registration="KZZ 2Z", capacity_tonnes=Decimal(5)),
        bay=LoadingBay(code="B9", name="Bay 9"),
        scheduled_start=now,
        scheduled_end=now + timedelta(hours=1),
    )
    db.add(s)
    db.commit()
    make_user("u", role=role)
    client.post("/api/auth/login", json={"username": "u", "password": TEST_PASSWORD})
    assert report(client, schedule_id=s.id).status_code == expected
    assert client.get("/api/incidents").status_code == 200
