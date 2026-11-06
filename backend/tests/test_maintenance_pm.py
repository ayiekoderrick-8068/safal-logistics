"""Preventive maintenance: recurring plans, generated tasks, overdue rules and compliance."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import MaintenanceRole, Role
from app.models_maintenance import IntervalUnit
from app.services.operations import local_today
from app.services.pm import add_interval
from tests.conftest import TEST_PASSWORD

EQ = "/api/maintenance/equipment"
PLANS = "/api/maintenance/plans"
TASKS = "/api/maintenance/tasks"
TODAY = local_today()


def d(days: int) -> str:
    return str(TODAY + timedelta(days=days))


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
def eq_id(maint) -> int:
    r = maint.post(
        EQ,
        json={
            "code": "CMP-001",
            "name": "Air compressor",
            "category": "compressor",
            "facility": "Nairobi Plant",
            "installed_on": d(-400),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _plan(maint, eq_id, **over):
    body = {
        "equipment_id": eq_id,
        "title": "Monthly compressor service",
        "interval_value": 1,
        "interval_unit": "months",
        "start_on": d(5),
    }
    body.update(over)
    r = maint.post(PLANS, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _open_tasks(maint, eq_id):
    return maint.get(TASKS, params={"view": "open", "equipment_id": eq_id}).json()["items"]


def _complete(maint, task_id, on=None, notes="Changed oil and filters"):
    return maint.post(
        f"{TASKS}/{task_id}/complete", json={"completed_on": on or d(0), "work_notes": notes}
    )


@pytest.mark.parametrize(
    ("start", "value", "unit", "expected"),
    [
        (date(2026, 1, 31), 1, IntervalUnit.MONTHS, date(2026, 2, 28)),
        (date(2028, 1, 31), 1, IntervalUnit.MONTHS, date(2028, 2, 29)),
        (date(2026, 11, 30), 3, IntervalUnit.MONTHS, date(2027, 2, 28)),
        (date(2026, 12, 15), 12, IntervalUnit.MONTHS, date(2027, 12, 15)),
        (date(2026, 11, 6), 2, IntervalUnit.WEEKS, date(2026, 11, 20)),
        (date(2026, 12, 30), 5, IntervalUnit.DAYS, date(2027, 1, 4)),
    ],
)
def test_add_interval(start, value, unit, expected) -> None:
    assert add_interval(start, value, unit) == expected


def test_plan_generates_first_task_and_drives_equipment_dates(maint, eq_id) -> None:
    plan = _plan(maint, eq_id)
    assert plan["next_task"]["due_on"] == d(5) and plan["next_task"]["state"] == "upcoming"
    assert len(_open_tasks(maint, eq_id)) == 1
    equipment = maint.get(f"{EQ}/{eq_id}").json()
    assert equipment["next_service_on"] == d(5) and equipment["schedule_managed"] is True
    assert equipment["history"][0]["kind"] == "pm_plan_created"
    # Hand edits of plan-driven dates are refused.
    r = maint.patch(f"{EQ}/{eq_id}", json={"next_service_on": d(60)})
    assert r.status_code == 409 and "preventive-maintenance schedule" in r.json()["detail"]


def test_fixed_schedule_completion_generates_next_from_due_date(maint, eq_id) -> None:
    _plan(maint, eq_id, start_on=d(-3), interval_value=2, interval_unit="weeks")
    task = _open_tasks(maint, eq_id)[0]
    assert task["state"] == "overdue"  # derived, never auto-completed
    done = _complete(maint, task["id"])
    assert done.status_code == 200, done.text
    assert done.json()["state"] == "completed" and done.json()["completed_on_time"] is False
    nxt = _open_tasks(maint, eq_id)
    assert [t["due_on"] for t in nxt] == [d(-3 + 14)]  # previous due + 2 weeks
    equipment = maint.get(f"{EQ}/{eq_id}").json()
    assert equipment["last_service_on"] == d(0) and equipment["next_service_on"] == d(11)
    assert (
        equipment["history"][0]["summary"]
        == "Preventive maintenance done: Monthly compressor service (late)"
    )


def test_floating_schedule_counts_from_completion(maint, eq_id) -> None:
    _plan(
        maint,
        eq_id,
        start_on=d(-10),
        interval_value=30,
        interval_unit="days",
        schedule_basis="completion_date",
    )
    task = _open_tasks(maint, eq_id)[0]
    _complete(maint, task["id"], on=d(-2))
    assert [t["due_on"] for t in _open_tasks(maint, eq_id)] == [d(28)]


def test_completion_validation_and_no_double_completion(maint, eq_id) -> None:
    _plan(maint, eq_id)
    task = _open_tasks(maint, eq_id)[0]
    assert _complete(maint, task["id"], on=d(1)).status_code == 422  # future
    assert _complete(maint, task["id"], on=d(-500)).status_code == 422  # before installation
    assert _complete(maint, task["id"], notes="").status_code == 422  # work performed required
    assert _complete(maint, task["id"]).status_code == 200
    again = _complete(maint, task["id"])
    assert again.status_code == 409 and "already completed" in again.json()["detail"]
    assert len(_open_tasks(maint, eq_id)) == 1  # exactly one next task, not two


def test_cancel_needs_reason_and_still_advances(maint, eq_id) -> None:
    _plan(maint, eq_id, start_on=d(2), interval_value=7, interval_unit="days")
    task = _open_tasks(maint, eq_id)[0]
    assert maint.post(f"{TASKS}/{task['id']}/cancel", json={"reason": " "}).status_code == 422
    r = maint.post(f"{TASKS}/{task['id']}/cancel", json={"reason": "Plant shutdown week"})
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    assert [t["due_on"] for t in _open_tasks(maint, eq_id)] == [d(9)]
    cancelled = maint.get(TASKS, params={"view": "cancelled"}).json()["items"]
    assert cancelled[0]["cancel_reason"] == "Plant shutdown week"


def test_summary_and_compliance(maint, eq_id) -> None:
    # Weekly plan that started 20 days ago: due -20 (done on time), -13 (done late), -6 (open).
    _plan(maint, eq_id, start_on=d(-20), interval_value=7, interval_unit="days")
    _complete(maint, _open_tasks(maint, eq_id)[0]["id"], on=d(-20))
    _complete(maint, _open_tasks(maint, eq_id)[0]["id"], on=d(-1))
    assert [t["due_on"] for t in _open_tasks(maint, eq_id)] == [d(-6)]
    # A once-off service due today.
    r = maint.post(
        TASKS, json={"equipment_id": eq_id, "title": "Safety valve test", "due_on": d(0)}
    )
    assert r.status_code == 201
    s = maint.get("/api/maintenance/pm/summary").json()
    assert (s["overdue"], s["due_today"], s["open"], s["active_plans"]) == (1, 1, 2, 1)
    c = s["compliance"]
    assert (c["due"], c["completed_on_time"], c["completed_late"], c["not_completed"]) == (
        3,
        1,
        1,
        1,
    )
    assert c["pct"] == 33.3
    assert [t["title"] for t in maint.get(TASKS, params={"view": "overdue"}).json()["items"]] == [
        "Monthly compressor service"
    ]
    assert len(maint.get(TASKS, params={"view": "due_today"}).json()["items"]) == 1


def test_compliance_reports_insufficient_data(maint) -> None:
    c = maint.get("/api/maintenance/pm/summary").json()["compliance"]
    assert c["due"] == 0 and c["pct"] is None


def test_once_off_task_rules(maint, eq_id) -> None:
    past = maint.post(TASKS, json={"equipment_id": eq_id, "title": "Belt check", "due_on": d(-1)})
    assert past.status_code == 422
    task = maint.post(
        TASKS, json={"equipment_id": eq_id, "title": "Belt check", "due_on": d(3)}
    ).json()
    assert maint.patch(f"{TASKS}/{task['id']}", json={"due_on": d(-2)}).status_code == 422
    moved = maint.patch(f"{TASKS}/{task['id']}", json={"due_on": d(10)})
    assert moved.status_code == 200 and moved.json()["due_on"] == d(10)
    assert maint.get(f"{EQ}/{eq_id}").json()["next_service_on"] == d(10)
    assert _complete(maint, task["id"]).status_code == 200
    assert _open_tasks(maint, eq_id) == []  # once-off: nothing generated
    assert maint.patch(f"{TASKS}/{task['id']}", json={"due_on": d(12)}).status_code == 409


def test_deactivate_and_reactivate_plan(maint, eq_id) -> None:
    plan = _plan(maint, eq_id)
    r = maint.post(f"{PLANS}/{plan['id']}/deactivate", json={"reason": "Asset on standby"})
    assert r.status_code == 200 and r.json()["is_active"] is False and r.json()["next_task"] is None
    assert maint.get(f"{EQ}/{eq_id}").json()["next_service_on"] is None
    assert (
        maint.post(f"{PLANS}/{plan['id']}/activate", json={"next_due_on": d(-1)}).status_code == 422
    )
    r = maint.post(f"{PLANS}/{plan['id']}/activate", json={"next_due_on": d(14)})
    assert r.json()["next_task"]["due_on"] == d(14)


def test_plan_update_follows_open_task(maint, eq_id, make_user) -> None:
    tech = make_user("tech", role=Role.VIEWER, maintenance_role=MaintenanceRole.TECHNICIAN)
    plan = _plan(maint, eq_id)
    r = maint.patch(
        f"{PLANS}/{plan['id']}",
        json={
            "title": "Quarterly compressor service",
            "interval_value": 3,
            "assigned_technician_id": tech.id,
        },
    )
    assert r.status_code == 200 and r.json()["interval_value"] == 3
    task = _open_tasks(maint, eq_id)[0]
    assert task["title"] == "Quarterly compressor service"
    assert task["assigned_technician"]["full_name"] == "Tech"
    assert maint.patch(f"{PLANS}/{plan['id']}", json={"interval_value": 0}).status_code == 422


def test_archiving_equipment_stops_its_maintenance(maint, eq_id) -> None:
    _plan(maint, eq_id)
    assert maint.post(f"{EQ}/{eq_id}/archive", json={"reason": "Decommissioned"}).status_code == 200
    assert maint.get(PLANS, params={"equipment_id": eq_id}).json()["total"] == 0  # none active
    cancelled = maint.get(TASKS, params={"view": "cancelled", "equipment_id": eq_id}).json()[
        "items"
    ]
    assert cancelled[0]["cancel_reason"] == "Equipment archived: Decommissioned"
    r = maint.post(TASKS, json={"equipment_id": eq_id, "title": "Late check", "due_on": d(1)})
    assert r.status_code == 409


def test_permissions(client, make_user) -> None:
    make_user()
    make_user("tech", role=Role.VIEWER, maintenance_role=MaintenanceRole.TECHNICIAN)
    make_user("keeper", role=Role.VIEWER, maintenance_role=MaintenanceRole.STOREKEEPER)
    _login(client)
    eq = client.post(
        EQ, json={"code": "PMP-1", "name": "Pump", "category": "pump", "facility": "Plant"}
    ).json()
    plan = _plan(client, eq["id"])
    task_id = _open_tasks(client, eq["id"])[0]["id"]

    with TestClient(create_app()) as keeper:
        _login(keeper, "keeper")
        assert keeper.get(TASKS).status_code == 200
        assert _complete(keeper, task_id).status_code == 403
    with TestClient(create_app()) as tech:
        _login(tech, "tech")
        assert (
            tech.post(
                PLANS,
                json={
                    "equipment_id": eq["id"],
                    "title": "Nope",
                    "interval_value": 1,
                    "interval_unit": "days",
                    "start_on": d(1),
                },
            ).status_code
            == 403
        )
        assert tech.post(f"{TASKS}/{task_id}/cancel", json={"reason": "no"}).status_code == 403
        assert (
            tech.post(f"{PLANS}/{plan['id']}/deactivate", json={"reason": "no"}).status_code == 403
        )
        done = _complete(tech, task_id)
        assert done.status_code == 200 and done.json()["completed_by"]["full_name"] == "Tech"
        mine = tech.get(TASKS, params={"mine": True}).json()["total"]
        assert mine == 0  # nothing assigned to the technician


def test_concurrent_completions_close_the_task_once(maint, eq_id) -> None:
    """Two people completing the same task at the same moment: one wins, one gets 409, and
    exactly one next task is generated (row lock + one-open-task-per-plan index)."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    _plan(maint, eq_id, interval_value=7, interval_unit="days")
    task_id = _open_tasks(maint, eq_id)[0]["id"]
    clients = [_login(TestClient(create_app()).__enter__()) for _ in range(2)]
    barrier = Barrier(2)

    def go(c: TestClient) -> int:
        barrier.wait()
        return _complete(c, task_id).status_code

    try:
        with ThreadPoolExecutor(2) as pool:
            codes = sorted(pool.map(go, clients))
    finally:
        for c in clients:
            c.__exit__(None, None, None)
    assert codes == [200, 409]
    assert len(_open_tasks(maint, eq_id)) == 1
    done = maint.get(TASKS, params={"view": "completed", "equipment_id": eq_id}).json()
    assert done["total"] == 1
