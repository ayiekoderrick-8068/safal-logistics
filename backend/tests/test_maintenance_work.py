"""Work orders (lifecycle, validation, permissions) and breakdowns (no double counting, downtime)."""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import MaintenanceRole, Role
from tests.conftest import TEST_PASSWORD

EQ = "/api/maintenance/equipment"
WO = "/api/maintenance/work-orders"
BD = "/api/maintenance/breakdowns"


def ago(**kw) -> str:
    return (datetime.now(UTC) - timedelta(**kw)).isoformat()


def _login(client, username="derrick"):
    r = client.post(
        "/api/auth/login",
        json={"username": username, "password": TEST_PASSWORD, "workspace": "maintenance"},
    )
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def maint(client, make_user) -> TestClient:
    make_user()
    return _login(client)


@pytest.fixture
def tech(make_user):
    return make_user("tech", role=Role.VIEWER, maintenance_role=MaintenanceRole.TECHNICIAN)


def _equipment(c, code="CNV-001"):
    r = c.post(
        EQ,
        json={
            "code": code,
            "name": f"{code} conveyor",
            "category": "conveyor",
            "facility": "Plant",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _wo(c, eq_id, **over):
    body = {
        "equipment_id": eq_id,
        "maintenance_type": "corrective",
        "priority": "high",
        "fault_description": "Drive belt slipping under load",
    }
    body.update(over)
    r = c.post(WO, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _go(c, wo_id, to, note=None):
    return c.post(f"{WO}/{wo_id}/transition", json={"to": to, "note": note})


def _done(c, wo_id, **over):
    body = {"work_performed": "Replaced drive belt and re-tensioned pulleys"}
    body.update(over)
    return c.post(f"{WO}/{wo_id}/complete", json=body)


def _status(c, eq_id):
    return c.get(f"{EQ}/{eq_id}").json()["status"]


def test_full_lifecycle_with_history_and_equipment_status(maint, tech) -> None:
    eq = _equipment(maint)
    wo = _wo(maint, eq, assigned_technician_id=tech.id)
    assert re.fullmatch(r"WO-\d{4}-\d{5}", wo["number"])
    assert wo["status"] == "assigned" and wo["allowed_transitions"] == [
        "open",
        "in_progress",
        "cancelled",
    ]
    assert _go(maint, wo["id"], "in_progress").json()["status"] == "in_progress"
    assert _status(maint, eq) == "under_maintenance"
    assert _go(maint, wo["id"], "awaiting_parts").status_code == 200
    assert _go(maint, wo["id"], "in_progress").status_code == 200
    done = _done(maint, wo["id"], completion_notes="Belt was glazed; monitor weekly")
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "completed" and body["allowed_transitions"] == []
    assert body["repair_minutes"] is not None
    assert _status(maint, eq) == "operational"
    history = maint.get(f"{WO}/{wo['id']}").json()["history"]
    assert [(h["from_status"], h["to_status"]) for h in history if h["to_status"]] == [
        (None, "assigned"),
        ("assigned", "in_progress"),
        ("in_progress", "awaiting_parts"),
        ("awaiting_parts", "in_progress"),
        ("in_progress", "completed"),
    ]
    assert all(h["actor"]["full_name"] == "Derrick" for h in history)


def test_invalid_transitions_are_refused(maint, tech) -> None:
    eq = _equipment(maint)
    wo = _wo(maint, eq)  # open, unassigned
    assert wo["status"] == "open"
    r = _go(maint, wo["id"], "in_progress")
    assert r.status_code == 409 and "cannot go from open to in progress" in r.json()["detail"]
    assert _go(maint, wo["id"], "completed").status_code == 422  # must use /complete
    assert _done(maint, wo["id"]).status_code == 409  # never started
    maint.patch(f"{WO}/{wo['id']}", json={"assigned_technician_id": tech.id})
    r = _done(maint, wo["id"])
    assert r.status_code == 409 and "Start the work" in r.json()["detail"]
    _go(maint, wo["id"], "in_progress")
    assert _done(maint, wo["id"], work_performed="short").status_code == 422
    assert _done(maint, wo["id"], completed_at=ago(days=-1)).status_code == 422  # future
    assert _done(maint, wo["id"], completed_at=ago(days=2)).status_code == 422  # before start
    assert _done(maint, wo["id"]).status_code == 200
    for target in ("in_progress", "cancelled", "awaiting_parts"):
        assert _go(maint, wo["id"], target, "x").status_code == 409  # completed is final
    assert maint.patch(f"{WO}/{wo['id']}", json={"priority": "low"}).status_code == 409


def test_minute_precision_times_are_clamped_not_refused(maint, tech) -> None:
    """Forms enter times to the minute; a completion stamped earlier in the start's own minute
    means 'at the start'. Anything before that minute is still refused."""
    eq = _equipment(maint)
    wo = _wo(maint, eq, assigned_technician_id=tech.id)
    started = datetime.fromisoformat(_go(maint, wo["id"], "in_progress").json()["started_at"])
    same_minute = started.replace(second=0, microsecond=0)
    earlier = same_minute - timedelta(seconds=1)
    if started == same_minute:  # started exactly on the minute: nothing to clamp
        pytest.skip("start fell exactly on a minute boundary")
    assert _done(maint, wo["id"], completed_at=earlier.isoformat()).status_code == 422
    r = _done(maint, wo["id"], completed_at=same_minute.isoformat())
    assert r.status_code == 200, r.text
    assert datetime.fromisoformat(r.json()["completed_at"]) == started
    assert r.json()["repair_minutes"] == 0


def test_assignment_rules(maint, tech) -> None:
    eq = _equipment(maint)
    wo = _wo(maint, eq, assigned_technician_id=tech.id)
    r = maint.patch(f"{WO}/{wo['id']}", json={"assigned_technician_id": None})
    assert r.json()["status"] == "open"
    maint.patch(f"{WO}/{wo['id']}", json={"assigned_technician_id": tech.id})
    _go(maint, wo["id"], "in_progress")
    r = maint.patch(f"{WO}/{wo['id']}", json={"assigned_technician_id": None})
    assert r.status_code == 409 and "cannot be unassigned" in r.json()["detail"]


def test_cancel_needs_reason_and_releases_equipment(maint, tech) -> None:
    eq = _equipment(maint)
    wo = _wo(maint, eq, assigned_technician_id=tech.id)
    _go(maint, wo["id"], "in_progress")
    assert _go(maint, wo["id"], "cancelled").status_code == 422
    r = _go(maint, wo["id"], "cancelled", "Raised against the wrong conveyor")
    assert r.status_code == 200 and r.json()["cancel_reason"] == "Raised against the wrong conveyor"
    assert _status(maint, eq) == "operational"


def test_technician_permissions(client, make_user, tech) -> None:
    make_user()
    other = make_user("tech2", role=Role.VIEWER, maintenance_role=MaintenanceRole.TECHNICIAN)
    make_user("viewer", role=Role.VIEWER, maintenance_role=MaintenanceRole.VIEWER)
    _login(client)
    eq = _equipment(client)
    theirs = _wo(client, eq, assigned_technician_id=other.id)
    with TestClient(create_app()) as t:
        _login(t, "tech")
        assert (
            t.post(
                WO,
                json={
                    "equipment_id": eq,
                    "maintenance_type": "corrective",
                    "priority": "low",
                    "fault_description": "Noise",
                    "assigned_technician_id": other.id,
                },
            ).status_code
            == 403
        )
        mine = _wo(t, eq, assigned_technician_id=tech.id, fault_description="Oil leak at gearbox")
        assert _go(t, theirs["id"], "in_progress").status_code == 403  # not theirs
        assert _go(t, mine["id"], "in_progress").status_code == 200
        assert _go(t, mine["id"], "cancelled", "no").status_code == 403  # planners/managers only
        assert t.patch(f"{WO}/{mine['id']}", json={"priority": "low"}).status_code == 403
        assert _done(t, mine["id"]).status_code == 200
        assert t.get(WO, params={"mine": True}).json()["total"] == 1
    with TestClient(create_app()) as v:
        _login(v, "viewer")
        assert v.get(WO).status_code == 200
        assert (
            v.post(
                WO,
                json={
                    "equipment_id": eq,
                    "maintenance_type": "inspection",
                    "priority": "low",
                    "fault_description": "Routine check",
                },
            ).status_code
            == 403
        )
        assert (
            v.post(
                BD,
                json={
                    "equipment_id": eq,
                    "started_at": ago(hours=1),
                    "severity": "minor",
                    "category": "mechanical",
                    "description": "Squeal",
                },
            ).status_code
            == 403
        )


def _breakdown(c, eq_id, **over):
    body = {
        "equipment_id": eq_id,
        "started_at": ago(hours=3),
        "severity": "critical",
        "category": "electrical",
        "description": "Motor tripped and will not restart",
    }
    body.update(over)
    return c.post(BD, json=body)


def test_breakdown_raises_work_order_and_cannot_be_logged_twice(maint) -> None:
    eq = _equipment(maint)
    r = _breakdown(maint, eq)
    assert r.status_code == 201, r.text
    bd = r.json()
    assert re.fullmatch(r"BD-\d{4}-\d{5}", bd["number"]) and bd["is_open"]
    assert 175 <= bd["downtime_minutes"] <= 185
    assert _status(maint, eq) == "out_of_service"
    [wo_brief] = bd["work_orders"]
    wo = maint.get(f"{WO}/{wo_brief['id']}").json()
    assert wo["priority"] == "critical" and wo["maintenance_type"] == "corrective"
    assert wo["breakdown"]["number"] == bd["number"]

    dup = _breakdown(maint, eq, started_at=ago(hours=1))
    assert dup.status_code == 409 and "already has an open breakdown" in dup.json()["detail"]
    assert maint.get(BD, params={"equipment_id": eq}).json()["total"] == 1


def test_restore_rules_and_no_overlap(maint) -> None:
    eq = _equipment(maint)
    bd = _breakdown(maint, eq, create_work_order=False).json()
    bad = maint.post(
        f"{BD}/{bd['id']}/restore",
        json={"restored_at": ago(hours=5), "actions_taken": "Reset breaker"},
    )
    assert bad.status_code == 422  # before the failure started
    assert (
        maint.post(
            f"{BD}/{bd['id']}/restore",
            json={"restored_at": ago(days=-1), "actions_taken": "Reset breaker"},
        ).status_code
        == 422
    )
    ok = maint.post(
        f"{BD}/{bd['id']}/restore",
        json={"restored_at": ago(hours=1), "actions_taken": "Reset breaker, replaced contactor"},
    )
    assert ok.status_code == 200 and not ok.json()["is_open"]
    assert 115 <= ok.json()["downtime_minutes"] <= 125
    assert _status(maint, eq) == "operational"
    again = maint.post(
        f"{BD}/{bd['id']}/restore", json={"restored_at": ago(minutes=1), "actions_taken": "Again"}
    )
    assert again.status_code == 409
    overlap = _breakdown(maint, eq, started_at=ago(hours=2), create_work_order=False)
    assert (
        overlap.status_code == 422 and "overlaps the previous breakdown" in overlap.json()["detail"]
    )
    assert (
        _breakdown(maint, eq, started_at=ago(minutes=30), create_work_order=False).status_code
        == 201
    )


def test_completing_the_repair_restores_the_breakdown(maint, tech) -> None:
    eq = _equipment(maint)
    bd = _breakdown(maint, eq).json()
    wo_id = bd["work_orders"][0]["id"]
    maint.patch(f"{WO}/{wo_id}", json={"assigned_technician_id": tech.id})
    _go(maint, wo_id, "in_progress")
    assert _status(maint, eq) == "out_of_service"  # still down: the breakdown is open
    r = _done(maint, wo_id, restore_breakdown=True)
    assert r.status_code == 200, r.text
    restored = maint.get(BD, params={"equipment_id": eq}).json()["items"][0]
    assert restored["is_open"] is False
    assert restored["actions_taken"] == "Replaced drive belt and re-tensioned pulleys"
    assert _status(maint, eq) == "operational"
    kinds = [h["kind"] for h in maint.get(f"{EQ}/{eq}").json()["history"]]
    assert {
        "breakdown_logged",
        "work_order_created",
        "breakdown_restored",
        "work_order_completed",
    } <= set(kinds)


def test_breakdown_summary_downtime_and_recurrence(maint) -> None:
    a, b = _equipment(maint, "A-1"), _equipment(maint, "B-1")
    # A fails twice (2 h + 1 h), B once and is still down (about 30 min so far).
    first = _breakdown(maint, a, started_at=ago(hours=10), create_work_order=False).json()
    maint.post(
        f"{BD}/{first['id']}/restore",
        json={"restored_at": ago(hours=8), "actions_taken": "Re-wired"},
    )
    second = _breakdown(
        maint, a, started_at=ago(hours=4), category="mechanical", create_work_order=False
    ).json()
    maint.post(
        f"{BD}/{second['id']}/restore",
        json={"restored_at": ago(hours=3), "actions_taken": "New bearing"},
    )
    _breakdown(maint, b, started_at=ago(minutes=30), create_work_order=False)
    # A failure that did not stop the asset counts as a breakdown but adds no downtime.
    _breakdown(
        maint,
        a,
        started_at=ago(minutes=20),
        equipment_down=False,
        severity="minor",
        create_work_order=False,
    )
    s = maint.get(f"{BD}/summary").json()
    assert (s["open"], s["breakdowns"], s["repeat_equipment"]) == (2, 4, 1)
    assert 205 <= s["downtime_minutes"] <= 215  # 120 + 60 + ~30
    assert s["top_equipment"][0]["equipment"]["code"] == "A-1"
    assert s["top_equipment"][0]["breakdowns"] == 3
    assert {c["category"]: c["breakdowns"] for c in s["categories"]} == {
        "electrical": 3,
        "mechanical": 1,
    }


def test_archive_refused_with_open_work(maint) -> None:
    eq = _equipment(maint)
    _wo(maint, eq)
    r = maint.post(f"{EQ}/{eq}/archive", json={"reason": "Scrapped"})
    assert r.status_code == 409 and "open work order" in r.json()["detail"]


def test_overdue_work_orders_and_summary(maint) -> None:
    eq = _equipment(maint)
    assert (
        maint.post(
            WO,
            json={
                "equipment_id": eq,
                "maintenance_type": "inspection",
                "priority": "low",
                "fault_description": "Guard inspection",
                "scheduled_on": "2020-01-01",
            },
        ).status_code
        == 422
    )
    _wo(maint, eq, priority="critical")
    s = maint.get(f"{WO}/summary").json()
    assert (s["open"], s["critical_open"], s["overdue"]) == (1, 1, 0)


def test_concurrent_completion_happens_once(maint, tech) -> None:
    eq = _equipment(maint)
    wo = _wo(maint, eq, assigned_technician_id=tech.id)
    _go(maint, wo["id"], "in_progress")
    clients = [_login(TestClient(create_app()).__enter__()) for _ in range(2)]
    barrier = Barrier(2)

    def go(c: TestClient) -> int:
        barrier.wait()
        return _done(c, wo["id"]).status_code

    try:
        with ThreadPoolExecutor(2) as pool:
            codes = sorted(pool.map(go, clients))
    finally:
        for c in clients:
            c.__exit__(None, None, None)
    assert codes == [200, 409]
    completed = [
        h for h in maint.get(f"{WO}/{wo['id']}").json()["history"] if h["to_status"] == "completed"
    ]
    assert len(completed) == 1
