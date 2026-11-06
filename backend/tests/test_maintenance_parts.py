"""Spare parts: stock ledger, no negative stock, no duplicate deductions, work-order consumption."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import MaintenanceRole, Role
from tests.conftest import TEST_PASSWORD

PARTS = "/api/maintenance/parts"
WO = "/api/maintenance/work-orders"


def rid() -> str:
    return uuid.uuid4().hex


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


def _part(c, **over):
    body = {
        "part_number": "brg-6205",
        "name": "Bearing 6205-2RS",
        "unit": "each",
        "reorder_level": "4",
        "unit_cost": "350.00",
        "opening_quantity": "10",
        "location": "Store A / Bin 3",
    }
    body.update(over)
    r = c.post(PARTS, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _work_order(c, technician_id, start=True):
    eq = c.post(
        "/api/maintenance/equipment",
        json={
            "code": f"CNV-{uuid.uuid4().hex[:4].upper()}",
            "name": "Conveyor",
            "category": "conveyor",
            "facility": "Plant",
        },
    ).json()["id"]
    wo = c.post(
        WO,
        json={
            "equipment_id": eq,
            "maintenance_type": "corrective",
            "priority": "high",
            "fault_description": "Noisy idler bearing",
            "assigned_technician_id": technician_id,
        },
    ).json()
    if start:
        c.post(f"{WO}/{wo['id']}/transition", json={"to": "in_progress"})
    return wo["id"]


def _issue(c, wo_id, part_id, qty, request_id=None):
    return c.post(
        f"{WO}/{wo_id}/parts",
        json={"part_id": part_id, "quantity": qty, "request_id": request_id or rid()},
    )


def _on_hand(c, part_id) -> float:
    return c.get(f"{PARTS}/{part_id}").json()["on_hand"]


def test_catalogue_with_opening_stock_and_ledger(maint) -> None:
    p = _part(maint)
    assert p["part_number"] == "BRG-6205" and p["on_hand"] == 10 and p["stock_state"] == "ok"
    assert p["stock_value"] == 3500
    detail = maint.get(f"{PARTS}/{p['id']}").json()
    [opening] = detail["movements"]
    assert (opening["kind"], opening["quantity"], opening["balance_after"]) == ("receipt", 10, 10)
    assert opening["note"] == "Opening stock"
    dup = maint.post(PARTS, json={"part_number": "BRG-6205", "name": "Dup", "unit": "each"})
    assert dup.status_code == 409
    # Stock never changes by editing the part.
    assert maint.patch(f"{PARTS}/{p['id']}", json={"on_hand": 999}).json()["on_hand"] == 10


def test_receipts_adjustments_and_summary(maint) -> None:
    p = _part(maint)
    oil = _part(
        maint,
        part_number="OIL-ISO68",
        name="Hydraulic oil ISO 68",
        unit="litre",
        reorder_level="20",
        unit_cost=None,
        opening_quantity="12.5",
    )
    r = maint.post(
        f"{PARTS}/{p['id']}/receive",
        json={"quantity": "6", "reference": "GRN-1042", "unit_cost": "360"},
    )
    assert r.status_code == 200 and r.json()["on_hand"] == 16 and r.json()["unit_cost"] == 360
    assert (
        maint.post(f"{PARTS}/{p['id']}/receive", json={"quantity": "1.5"}).status_code == 422
    )  # whole units
    assert (
        maint.post(
            f"{PARTS}/{p['id']}/adjust", json={"counted_quantity": "16", "reason": "Cycle count"}
        ).status_code
        == 422
    )
    assert (
        maint.post(
            f"{PARTS}/{p['id']}/adjust", json={"counted_quantity": "3", "reason": ""}
        ).status_code
        == 422
    )
    adj = maint.post(
        f"{PARTS}/{p['id']}/adjust",
        json={"counted_quantity": "3", "reason": "Cycle count: 13 missing"},
    )
    assert adj.json()["on_hand"] == 3 and adj.json()["stock_state"] == "low"
    moves = maint.get(f"{PARTS}/{p['id']}").json()["movements"]
    assert (moves[0]["kind"], moves[0]["quantity"], moves[0]["balance_after"]) == (
        "adjustment",
        -13,
        3,
    )
    s = maint.get(f"{PARTS}/summary").json()
    assert (s["active_parts"], s["low_stock"], s["out_of_stock"], s["parts_without_cost"]) == (
        2,
        2,
        0,
        1,
    )
    assert s["stock_value"] == 3 * 360  # the oil has no cost and is excluded
    low = maint.get(PARTS, params={"stock": "low"}).json()["items"]
    assert {x["part_number"] for x in low} == {"BRG-6205", "OIL-ISO68"}
    assert oil["on_hand"] == 12.5


def test_issue_and_return_against_a_work_order(maint, tech) -> None:
    p = _part(maint)
    oil = _part(
        maint,
        part_number="OIL-ISO68",
        name="Oil",
        unit="litre",
        unit_cost="420",
        opening_quantity="20",
    )
    wo = _work_order(maint, tech.id)
    assert _issue(maint, wo, p["id"], "2").status_code == 201
    assert _issue(maint, wo, oil["id"], "1.25").status_code == 201
    assert _issue(maint, wo, p["id"], "0.5").status_code == 422  # whole units only
    r = maint.post(
        f"{WO}/{wo}/parts/return", json={"part_id": p["id"], "quantity": "3", "request_id": rid()}
    )
    assert r.status_code == 422 and "Only 2 each" in r.json()["detail"]
    r = maint.post(
        f"{WO}/{wo}/parts/return", json={"part_id": p["id"], "quantity": "1", "request_id": rid()}
    )
    assert r.status_code == 200
    body = maint.get(f"{WO}/{wo}/parts").json()
    lines = {line["part"]["part_number"]: line for line in body["lines"]}
    assert (
        lines["BRG-6205"]["issued"],
        lines["BRG-6205"]["returned"],
        lines["BRG-6205"]["net"],
    ) == (2, 1, 1)
    assert lines["BRG-6205"]["cost"] == 350 and lines["OIL-ISO68"]["cost"] == 525
    assert body["total_cost"] == 875
    assert _on_hand(maint, p["id"]) == 9 and _on_hand(maint, oil["id"]) == 18.75


def test_never_negative(maint, tech) -> None:
    p = _part(maint, opening_quantity="3")
    wo = _work_order(maint, tech.id)
    r = _issue(maint, wo, p["id"], "4")
    assert r.status_code == 409 and "3 each on hand" in r.json()["detail"]
    assert _on_hand(maint, p["id"]) == 3
    assert _issue(maint, wo, p["id"], "3").status_code == 201
    assert maint.get(f"{PARTS}/{p['id']}").json()["stock_state"] == "out_of_stock"
    assert _issue(maint, wo, p["id"], "1").status_code == 409


def test_retries_do_not_deduct_twice(maint, tech) -> None:
    p = _part(maint)
    wo = _work_order(maint, tech.id)
    key = rid()
    first = _issue(maint, wo, p["id"], "2", key)
    again = _issue(maint, wo, p["id"], "2", key)  # double click / network retry
    assert first.status_code == 201 and again.status_code == 201
    assert _on_hand(maint, p["id"]) == 8
    assert len(again.json()["movements"]) == 1
    reused = _issue(maint, wo, p["id"], "5", key)  # same key, different request
    assert reused.status_code == 409
    rkey = rid()
    for _ in range(2):
        maint.post(f"{PARTS}/{p['id']}/receive", json={"quantity": "4", "request_id": rkey})
    assert _on_hand(maint, p["id"]) == 12


def _race(clients, fn):
    barrier = Barrier(len(clients))

    def go(c):
        barrier.wait()
        return fn(c)

    try:
        with ThreadPoolExecutor(len(clients)) as pool:
            return list(pool.map(go, clients))
    finally:
        for c in clients:
            c.__exit__(None, None, None)


def test_concurrent_issues_cannot_oversell(maint, tech) -> None:
    p = _part(maint, opening_quantity="5")
    wo = _work_order(maint, tech.id)
    clients = [_login(TestClient(create_app()).__enter__()) for _ in range(2)]
    codes = sorted(r.status_code for r in _race(clients, lambda c: _issue(c, wo, p["id"], "3")))
    assert codes == [201, 409]
    assert _on_hand(maint, p["id"]) == 2


def test_concurrent_duplicate_request_deducts_once(maint, tech) -> None:
    p = _part(maint, opening_quantity="10")
    wo = _work_order(maint, tech.id)
    key = rid()
    clients = [_login(TestClient(create_app()).__enter__()) for _ in range(2)]
    results = _race(clients, lambda c: _issue(c, wo, p["id"], "4", key))
    assert all(r.status_code in (201, 409) for r in results)
    assert any(r.status_code == 201 for r in results)
    assert _on_hand(maint, p["id"]) == 6
    issues = [
        m for m in maint.get(f"{PARTS}/{p['id']}").json()["movements"] if m["kind"] == "issue"
    ]
    assert len(issues) == 1


def test_issue_rules_by_work_order_state(maint, tech) -> None:
    p = _part(maint)
    open_wo = maint.post(
        WO,
        json={
            "equipment_id": maint.post(
                "/api/maintenance/equipment",
                json={"code": "X-1", "name": "Spare pump", "category": "pump", "facility": "Plant"},
            ).json()["id"],
            "maintenance_type": "corrective",
            "priority": "low",
            "fault_description": "Unassigned job",
        },
    ).json()
    assert _issue(maint, open_wo["id"], p["id"], "1").status_code == 409  # not assigned yet
    wo = _work_order(maint, tech.id)
    _issue(maint, wo, p["id"], "2")
    maint.post(f"{WO}/{wo}/complete", json={"work_performed": "Replaced both idler bearings"})
    assert _issue(maint, wo, p["id"], "1").status_code == 409  # completed: no more issues
    r = maint.post(
        f"{WO}/{wo}/parts/return", json={"part_id": p["id"], "quantity": "1", "request_id": rid()}
    )
    assert r.status_code == 200  # unused parts can still come back to the store


def test_permissions(client, make_user, tech) -> None:
    make_user()
    other = make_user("tech2", role=Role.VIEWER, maintenance_role=MaintenanceRole.TECHNICIAN)
    make_user("keeper", role=Role.VIEWER, maintenance_role=MaintenanceRole.STOREKEEPER)
    make_user("viewer", role=Role.VIEWER, maintenance_role=MaintenanceRole.VIEWER)
    _login(client)
    p = _part(client)
    mine, theirs = _work_order(client, tech.id), _work_order(client, other.id)
    with TestClient(create_app()) as t:
        _login(t, "tech")
        assert _issue(t, mine, p["id"], "1").status_code == 201
        assert _issue(t, theirs, p["id"], "1").status_code == 403
        assert t.post(f"{PARTS}/{p['id']}/receive", json={"quantity": "5"}).status_code == 403
        assert (
            t.post(PARTS, json={"part_number": "Z-1", "name": "Zed", "unit": "each"}).status_code
            == 403
        )
        assert t.get(f"{WO}/{mine}/parts").json()["can_issue"] is True
        assert t.get(f"{WO}/{theirs}/parts").json()["can_issue"] is False
    with TestClient(create_app()) as k:
        _login(k, "keeper")
        assert _issue(k, theirs, p["id"], "1").status_code == 201  # stores can issue to any job
        assert k.post(f"{PARTS}/{p['id']}/receive", json={"quantity": "5"}).status_code == 200
    with TestClient(create_app()) as v:
        _login(v, "viewer")
        assert v.get(PARTS).status_code == 200
        assert _issue(v, mine, p["id"], "1").status_code == 403
    assert _on_hand(client, p["id"]) == 13
