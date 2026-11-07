"""The labelled maintenance sample dataset obeys the same rules as real records and is flagged."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.maintenance_sample import clear_maintenance_sample, load_maintenance_sample
from app.models import User, UserStatus
from app.models_maintenance import (
    Breakdown,
    Equipment,
    EquipmentStatus,
    MaintenancePlan,
    MaintenanceTask,
    SparePart,
    StockMovement,
    TaskStatus,
    WorkOrder,
    WorkOrderStatus,
)
from app.services import maintenance_analytics as ma
from app.services.app_settings import is_maintenance_sample
from tests.conftest import TEST_PASSWORD

NOW = datetime(2026, 11, 6, 9, 30, tzinfo=UTC)


@pytest.fixture
def loaded(db: Session) -> dict[str, int]:
    return load_maintenance_sample(db, now=NOW)


def test_flagged_and_consistent(db: Session, loaded) -> None:
    assert is_maintenance_sample(db)
    assert loaded["equipment"] == 15 and loaded["breakdowns"] > 20 and loaded["movements"] > 30

    # Sample technicians are labelled and cannot sign in.
    people = db.scalars(select(User).where(User.username.startswith("sample."))).all()
    assert len(people) == 4
    assert all(u.status is UserStatus.DEACTIVATED and "(sample)" in u.full_name for u in people)

    # Breakdowns of one asset never overlap; at most one open per asset.
    by_eq: dict[int, list[Breakdown]] = {}
    for b in db.scalars(select(Breakdown).order_by(Breakdown.started_at)):
        by_eq.setdefault(b.equipment_id, []).append(b)
    for bds in by_eq.values():
        assert sum(b.restored_at is None for b in bds) <= 1
        for a, b in zip(bds, bds[1:], strict=False):
            assert a.restored_at is not None and a.restored_at <= b.started_at
        assert all(b.started_at <= NOW for b in bds)

    # One open task per plan; nothing completed in the future.
    for plan in db.scalars(select(MaintenancePlan)):
        open_tasks = db.scalar(
            select(func.count(MaintenanceTask.id)).where(
                MaintenanceTask.plan_id == plan.id, MaintenanceTask.status == TaskStatus.SCHEDULED
            )
        )
        assert open_tasks == 1
    assert not db.scalar(
        select(func.count(MaintenanceTask.id)).where(MaintenanceTask.completed_at > NOW)
    )

    # Equipment status follows the open work.
    eqs = {e.code: e for e in db.scalars(select(Equipment))}
    assert eqs["PRD-601"].status is EquipmentStatus.OUT_OF_SERVICE
    assert eqs["HYD-401"].status is EquipmentStatus.OUT_OF_SERVICE
    assert eqs["CMP-302"].status is EquipmentStatus.UNDER_MAINTENANCE
    statuses = {wo.status for wo in db.scalars(select(WorkOrder))}
    assert {
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.AWAITING_PARTS,
        WorkOrderStatus.OPEN,
    } <= statuses
    assert all(e.next_service_on is not None for e in eqs.values())
    overdue = {e.code for e in eqs.values() if e.next_service_on < NOW.date()}
    assert {"CNV-151", "PMP-502", "MTR-201"} <= overdue

    # The stock ledger replays to each part's balance and never goes negative.
    for part in db.scalars(select(SparePart)):
        running = Decimal(0)
        for m in db.scalars(
            select(StockMovement)
            .where(StockMovement.part_id == part.id)
            .order_by(StockMovement.occurred_at, StockMovement.id)
        ):
            running += m.quantity
            assert running == m.balance_after >= 0
        assert running == part.on_hand
    seal = db.scalar(select(SparePart).where(SparePart.part_number == "KIT-SEAL-ABP"))
    assert seal.on_hand == 0  # why the press is awaiting parts


def test_metrics_have_real_samples(db: Session, loaded) -> None:
    k = ma.kpis(db, ma.make_window(date(2026, 10, 8), date(2026, 11, 5)))
    for metric in ("availability", "mtbf", "mttr", "pm_compliance"):
        value = k[metric].get("pct", k[metric].get("hours", k[metric].get("minutes")))
        assert value is not None, metric
    assert 0 < k["availability"]["pct"] < 100
    assert 0 < k["pm_compliance"]["pct"] <= 100


def test_refuses_real_data_and_clears(db: Session, loaded) -> None:
    with pytest.raises(RuntimeError):
        load_maintenance_sample(db, now=NOW)
    clear_maintenance_sample(db)
    assert not is_maintenance_sample(db)
    assert not db.scalar(select(func.count(Equipment.id)))
    assert not db.scalar(select(func.count(User.id)).where(User.username.startswith("sample.")))
    with pytest.raises(RuntimeError):
        clear_maintenance_sample(db)  # not a sample dataset any more


def test_api_and_exports_say_sample(client, make_user, db: Session) -> None:
    make_user()
    r = client.post(
        "/api/auth/login",
        json={"username": "derrick", "password": TEST_PASSWORD, "workspace": "maintenance"},
    )
    assert r.status_code == 200
    assert client.get("/api/maintenance/access").json()["sample_data"] is False
    load_maintenance_sample(db)
    assert client.get("/api/maintenance/access").json()["sample_data"] is True
    assert client.get("/api/maintenance/dashboard").json()["sample_data"] is True
    csv_r = client.get("/api/maintenance/reports/equipment-downtime", params={"format": "csv"})
    assert "SAMPLE demonstration data" in csv_r.content.decode("utf-8-sig")
