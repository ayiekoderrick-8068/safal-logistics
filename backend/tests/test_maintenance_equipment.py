"""Equipment register: validation, permissions, history and archiving."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import MaintenanceRole, Role
from app.services.operations import local_today
from tests.conftest import TEST_PASSWORD

API = "/api/maintenance/equipment"


def _login(client, username="derrick", workspace="maintenance"):
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": TEST_PASSWORD, "workspace": workspace},
    )
    assert resp.status_code == 200, resp.text
    return client


@pytest.fixture
def maint(client, make_user) -> TestClient:
    make_user()  # admin -> maintenance manager
    return _login(client)


def _body(**over):
    body = {
        "code": "cnv-001",
        "name": "Main line conveyor motor",
        "category": "conveyor",
        "manufacturer": "Siemens",
        "model": "1LE1",
        "serial_number": "SN-1001",
        "facility": "Nairobi Plant",
        "department": "Packaging",
        "location": "Line 2",
        "installed_on": str(local_today() - timedelta(days=400)),
        "status": "operational",
    }
    body.update(over)
    return body


def test_create_normalises_and_records_history(maint) -> None:
    resp = maint.post(API, json=_body(name="  Main   line conveyor  "))
    assert resp.status_code == 201, resp.text
    eq = resp.json()
    assert eq["code"] == "CNV-001" and eq["name"] == "Main line conveyor"
    assert eq["service_state"] == "not_scheduled"
    detail = maint.get(f"{API}/{eq['id']}").json()
    assert [h["kind"] for h in detail["history"]] == ["created"]
    assert detail["history"][0]["actor"]["full_name"] == "Derrick"


@pytest.mark.parametrize(
    ("over", "fragment"),
    [
        ({"code": "bad code!"}, "string should match pattern"),
        (
            {"installed_on": str(local_today() + timedelta(days=1))},
            "installation date cannot be in the future",
        ),
        (
            {"last_service_on": str(local_today() + timedelta(days=1))},
            "last service date cannot be in the future",
        ),
        (
            {
                "last_service_on": str(local_today() - timedelta(days=5)),
                "next_service_on": str(local_today() - timedelta(days=10)),
            },
            "next service date cannot be before",
        ),
        (
            {
                "installed_on": str(local_today() - timedelta(days=5)),
                "last_service_on": str(local_today() - timedelta(days=10)),
            },
            "cannot be before the installation date",
        ),
        ({"facility": " "}, "facility"),
        ({"category": "spaceship"}, "category"),
    ],
)
def test_server_side_validation(maint, over, fragment) -> None:
    resp = maint.post(API, json=_body(**over))
    assert resp.status_code == 422, resp.text
    assert fragment.lower() in resp.text.lower()


def test_duplicate_code_and_serial_are_refused(maint) -> None:
    assert maint.post(API, json=_body()).status_code == 201
    dup_code = maint.post(API, json=_body(code="CNV-001", serial_number="SN-2"))
    assert dup_code.status_code == 409 and "Equipment ID" in dup_code.json()["detail"]
    dup_serial = maint.post(API, json=_body(code="CNV-002"))
    assert dup_serial.status_code == 409 and "serial number" in dup_serial.json()["detail"]


def test_permissions(client, make_user) -> None:
    make_user()
    make_user("tech", role=Role.VIEWER, maintenance_role=MaintenanceRole.TECHNICIAN)
    make_user("viewer", role=Role.VIEWER, maintenance_role=MaintenanceRole.VIEWER)
    _login(client)
    eq_id = client.post(API, json=_body()).json()["id"]

    for name in ("tech", "viewer"):
        with TestClient(create_app()) as c:
            _login(c, name)
            assert c.get(API).status_code == 200
            assert c.get(f"{API}/{eq_id}").status_code == 200
            assert c.post(API, json=_body(code="X-1", serial_number=None)).status_code == 403
            assert c.patch(f"{API}/{eq_id}", json={"name": "Renamed"}).status_code == 403
            assert c.post(f"{API}/{eq_id}/archive", json={"reason": "gone"}).status_code == 403

    with TestClient(create_app()) as c:  # admin, but a logistics session
        _login(c, workspace="logistics")
        assert c.get(API).status_code == 403


def test_update_records_changes_and_status_history(maint) -> None:
    eq_id = maint.post(API, json=_body()).json()["id"]
    resp = maint.patch(f"{API}/{eq_id}", json={"status": "under_maintenance", "location": "Line 3"})
    assert resp.status_code == 200 and resp.json()["status"] == "under_maintenance"
    no_op = maint.patch(f"{API}/{eq_id}", json={"location": "Line 3"})
    assert no_op.status_code == 200
    history = maint.get(f"{API}/{eq_id}").json()["history"]
    assert [h["kind"] for h in history] == ["status_changed", "created"]  # no-op adds nothing
    assert history[0]["changes"]["status"] == {"from": "operational", "to": "under_maintenance"}
    assert history[0]["changes"]["location"] == {"from": "Line 2", "to": "Line 3"}
    assert maint.patch(f"{API}/{eq_id}", json={"name": None}).status_code == 422


def test_technician_must_be_eligible(maint, make_user, db) -> None:
    tech = make_user("tech", role=Role.VIEWER, maintenance_role=MaintenanceRole.TECHNICIAN)
    ops = make_user("ops", role=Role.OPERATIONS)
    keeper = make_user("keeper", role=Role.VIEWER, maintenance_role=MaintenanceRole.STOREKEEPER)
    eq_id = maint.post(API, json=_body()).json()["id"]
    for bad in (ops.id, keeper.id, 99999):
        assert (
            maint.patch(f"{API}/{eq_id}", json={"assigned_technician_id": bad}).status_code == 422
        )
    ok = maint.patch(f"{API}/{eq_id}", json={"assigned_technician_id": tech.id})
    assert ok.json()["assigned_technician"]["full_name"] == "Tech"
    history = maint.get(f"{API}/{eq_id}").json()["history"]
    assert (
        history[0]["kind"] == "technician_assigned" and history[0]["summary"] == "Assigned to Tech"
    )
    names = [t["full_name"] for t in maint.get(f"{API}/options").json()["technicians"]]
    assert "Tech" in names and "Ops" not in names and "Keeper" not in names


def test_archive_and_restore(maint) -> None:
    eq_id = maint.post(API, json=_body()).json()["id"]
    assert maint.post(f"{API}/{eq_id}/archive", json={"reason": ""}).status_code == 422
    assert (
        maint.post(f"{API}/{eq_id}/archive", json={"reason": "Replaced by CNV-009"}).status_code
        == 200
    )
    assert maint.get(API).json()["total"] == 0
    assert maint.get(API, params={"archived": True}).json()["total"] == 1
    assert maint.get(f"{API}/summary").json()["archived"] == 1
    assert maint.patch(f"{API}/{eq_id}", json={"name": "Nope"}).status_code == 409
    assert maint.post(f"{API}/{eq_id}/archive", json={"reason": "again"}).status_code == 409
    assert maint.post(f"{API}/{eq_id}/restore").status_code == 200
    assert maint.get(API).json()["total"] == 1
    kinds = [h["kind"] for h in maint.get(f"{API}/{eq_id}").json()["history"]]
    assert kinds == ["restored", "archived", "created"]


def test_service_state_summary_and_filters(maint) -> None:
    today = local_today()
    maint.post(
        API,
        json=_body(code="A-1", serial_number="S1", next_service_on=str(today - timedelta(days=1))),
    )
    maint.post(
        API,
        json=_body(code="A-2", serial_number="S2", next_service_on=str(today + timedelta(days=3))),
    )
    maint.post(
        API,
        json=_body(code="A-3", serial_number="S3", next_service_on=str(today + timedelta(days=60))),
    )
    maint.post(API, json=_body(code="A-4", serial_number="S4", status="out_of_service"))
    states = {e["code"]: e["service_state"] for e in maint.get(API).json()["items"]}
    assert states == {
        "A-1": "overdue",
        "A-2": "due_soon",
        "A-3": "scheduled",
        "A-4": "not_scheduled",
    }
    s = maint.get(f"{API}/summary").json()
    assert (s["total"], s["operational"], s["out_of_service"]) == (4, 3, 1)
    assert (s["service_overdue"], s["service_due_soon"]) == (1, 1)
    assert [e["code"] for e in maint.get(API, params={"service": "overdue"}).json()["items"]] == [
        "A-1"
    ]
    assert maint.get(API, params={"status": "out_of_service"}).json()["total"] == 1
    assert maint.get(API, params={"q": "a-3"}).json()["total"] == 1
