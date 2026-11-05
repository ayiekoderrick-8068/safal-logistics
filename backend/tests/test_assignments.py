"""Driver-assignment history: recording, release, conflicts, permissions and reporting."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Dispatch,
    DispatchStatus,
    Driver,
    DriverAssignment,
    LoadingBay,
    LoadingSchedule,
    Role,
    Route,
    ScheduleStatus,
    Truck,
)
from tests.conftest import TEST_PASSWORD


def login(client, make_user, role: Role, username: str = "user") -> None:
    make_user(username, role=role)
    r = client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
    assert r.status_code == 200, r.text


@pytest.fixture
def fleet(db: Session) -> dict[str, int]:
    drivers = [Driver(full_name=n, licence_number=f"L{i}") for i, n in enumerate(["Ann", "Ben"])]
    db.add_all(drivers)
    db.commit()
    return {"ann": drivers[0].id, "ben": drivers[1].id}


def history(db: Session, truck_id: int) -> list[DriverAssignment]:
    return list(
        db.scalars(
            select(DriverAssignment)
            .where(DriverAssignment.truck_id == truck_id)
            .order_by(DriverAssignment.assigned_at)
        )
    )


def test_create_reassign_and_release_record_history(client, make_user, db, fleet) -> None:
    login(client, make_user, Role.FLEET_MANAGER)
    r = client.post(
        "/api/trucks",
        json={"registration": "KAA 100A", "capacity_tonnes": 10, "driver_id": fleet["ann"]},
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert len(history(db, tid)) == 1

    r = client.patch(
        f"/api/trucks/{tid}", json={"driver_id": fleet["ben"], "assignment_note": "Shift swap"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["driver"]["label"] == "Ben"

    # Re-sending the same driver is a no-op (no duplicate history row).
    client.patch(f"/api/trucks/{tid}", json={"driver_id": fleet["ben"]})
    r = client.patch(f"/api/trucks/{tid}", json={"driver_id": None})
    assert r.status_code == 200 and r.json()["driver"] is None

    db.expire_all()
    rows = history(db, tid)
    assert [a.driver_id for a in rows] == [fleet["ann"], fleet["ben"]]
    assert all(a.released_at is not None for a in rows)
    assert rows[0].released_at <= rows[1].assigned_at
    assert rows[1].note == "Shift swap"
    assert rows[0].assigned_by_id is not None and rows[1].released_by_id is not None


def test_history_endpoint_is_newest_first(client, make_user, db, fleet) -> None:
    login(client, make_user, Role.FLEET_MANAGER)
    tid = client.post(
        "/api/trucks",
        json={"registration": "KAA 101A", "capacity_tonnes": 10, "driver_id": fleet["ann"]},
    ).json()["id"]
    client.patch(f"/api/trucks/{tid}", json={"driver_id": fleet["ben"]})

    body = client.get(f"/api/trucks/{tid}/assignments").json()
    assert [a["driver"]["label"] for a in body] == ["Ben", "Ann"]
    assert body[0]["is_current"] and not body[1]["is_current"]
    assert body[0]["assigned_by"] and body[1]["released_by"] == body[0]["assigned_by"]

    by_driver = client.get(f"/api/drivers/{fleet['ann']}/assignments").json()
    assert [a["truck"]["label"] for a in by_driver] == ["KAA 101A"]


def test_driver_cannot_hold_two_trucks(client, make_user, fleet) -> None:
    login(client, make_user, Role.FLEET_MANAGER)
    client.post(
        "/api/trucks",
        json={"registration": "KAA 102A", "capacity_tonnes": 10, "driver_id": fleet["ann"]},
    )
    r = client.post(
        "/api/trucks",
        json={"registration": "KAA 103A", "capacity_tonnes": 10, "driver_id": fleet["ann"]},
    )
    assert r.status_code == 409


def test_database_rejects_overlapping_periods(db, fleet) -> None:
    t1 = Truck(registration="KAA 104A", capacity_tonnes=Decimal(10))
    t2 = Truck(registration="KAA 105A", capacity_tonnes=Decimal(10))
    db.add_all([t1, t2])
    db.flush()
    start = datetime(2026, 10, 1, tzinfo=UTC)
    db.add(DriverAssignment(driver_id=fleet["ann"], truck_id=t1.id, assigned_at=start))
    db.flush()
    # Same driver on another truck while still active -> rejected.
    db.add(
        DriverAssignment(
            driver_id=fleet["ann"], truck_id=t2.id, assigned_at=start + timedelta(days=1)
        )
    )
    with pytest.raises(IntegrityError, match="ex_driver_assignments_driver_overlap"):
        db.flush()
    db.rollback()

    db.add_all([t1 := Truck(registration="KAA 106A", capacity_tonnes=Decimal(10))])
    db.flush()
    db.add(DriverAssignment(driver_id=fleet["ann"], truck_id=t1.id, assigned_at=start))
    db.add(
        DriverAssignment(
            driver_id=fleet["ben"], truck_id=t1.id, assigned_at=start + timedelta(hours=1)
        )
    )
    with pytest.raises(IntegrityError, match="ex_driver_assignments_truck_overlap"):
        db.flush()
    db.rollback()


def test_release_before_assign_is_rejected(db, fleet) -> None:
    t = Truck(registration="KAA 107A", capacity_tonnes=Decimal(10))
    db.add(t)
    db.flush()
    start = datetime(2026, 10, 1, tzinfo=UTC)
    db.add(
        DriverAssignment(
            driver_id=fleet["ann"],
            truck_id=t.id,
            assigned_at=start,
            released_at=start - timedelta(minutes=1),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.ADMIN, 200),
        (Role.OPERATIONS, 200),
        (Role.FLEET_MANAGER, 200),
        (Role.COMPLIANCE, 200),
        (Role.VIEWER, 403),
    ],
)
def test_history_permissions(client, make_user, db, fleet, role, expected) -> None:
    t = Truck(registration="KAA 108A", capacity_tonnes=Decimal(10))
    db.add(t)
    db.commit()
    login(client, make_user, role)
    assert client.get(f"/api/trucks/{t.id}/assignments").status_code == expected
    assert client.get(f"/api/drivers/{fleet['ann']}/assignments").status_code == expected


def test_history_404(client, make_user) -> None:
    login(client, make_user, Role.OPERATIONS)
    assert client.get("/api/trucks/999999/assignments").status_code == 404
    assert client.get("/api/drivers/999999/assignments").status_code == 404


def test_reports_attribute_operations_to_driver_at_the_time(client, make_user, db, fleet) -> None:
    """A dispatch made while Ann drove the truck stays Ann's after Ben takes over."""
    t = Truck(registration="KAA 109A", capacity_tonnes=Decimal(10))
    bay = LoadingBay(code="BX", name="Bay X")
    route = Route(
        origin="Nairobi", destination="Thika", distance_km=Decimal(45), expected_duration_minutes=60
    )
    db.add_all([t, bay, route])
    db.flush()
    swap = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
    db.add_all(
        [
            DriverAssignment(
                driver_id=fleet["ann"],
                truck_id=t.id,
                assigned_at=swap - timedelta(days=10),
                released_at=swap,
            ),
            DriverAssignment(driver_id=fleet["ben"], truck_id=t.id, assigned_at=swap),
        ]
    )
    t.driver_id = fleet["ben"]
    for ref, hour in (("LD-A", 6), ("LD-B", 12)):  # 06:00Z before the swap, 12:00Z after
        go = datetime(2026, 11, 2, hour, 0, tzinfo=UTC)
        s = LoadingSchedule(
            truck=t,
            bay=bay,
            scheduled_start=go - timedelta(hours=1),
            scheduled_end=go,
            arrival_at=go - timedelta(hours=1),
            loading_started_at=go - timedelta(minutes=50),
            loading_finished_at=go - timedelta(minutes=10),
            departed_at=go,
            status=ScheduleStatus.DEPARTED,
        )
        db.add(
            Dispatch(
                load_ref=ref,
                schedule=s,
                truck=t,
                route=route,
                dispatched_at=go,
                expected_arrival_at=go + timedelta(hours=1),
                status=DispatchStatus.IN_TRANSIT,
            )
        )
    db.commit()

    login(client, make_user, Role.OPERATIONS)
    q = "period=custom&start=2026-11-02&end=2026-11-02"
    csv_all = client.get(f"/api/reports/export/dispatches.csv?{q}").text
    assert "LD-A" in csv_all and "LD-B" in csv_all
    line_a = next(line for line in csv_all.splitlines() if "LD-A" in line)
    line_b = next(line for line in csv_all.splitlines() if "LD-B" in line)
    assert "Ann" in line_a and "Ben" in line_b

    ann = client.get(f"/api/reports/export/dispatches.csv?{q}&driver_id={fleet['ann']}").text
    assert "LD-A" in ann and "LD-B" not in ann
    ben_loads = client.get(f"/api/reports/export/turnaround.csv?{q}&driver_id={fleet['ben']}").text
    assert "LD-B" in ben_loads and "LD-A" not in ben_loads
