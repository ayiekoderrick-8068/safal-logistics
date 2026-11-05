"""Database-level business rules (enforced even if the API layer has a bug)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import LoadingBay, LoadingSchedule, ScheduleStatus, Truck

T0 = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)


@pytest.fixture
def bay_and_trucks(db: Session) -> tuple[LoadingBay, Truck, Truck]:
    bay = LoadingBay(code="BAY-01", name="Bay 01")
    t1 = Truck(registration="KDG 752R", capacity_tonnes=Decimal(16))
    t2 = Truck(registration="KCF 903P", capacity_tonnes=Decimal(28))
    db.add_all([bay, t1, t2])
    db.commit()
    return bay, t1, t2


def _book(
    bay: LoadingBay, truck: Truck, start: datetime, hours: float = 2, **kw
) -> LoadingSchedule:
    return LoadingSchedule(
        bay=bay,
        truck=truck,
        scheduled_start=start,
        scheduled_end=start + timedelta(hours=hours),
        **kw,
    )


def test_overlapping_bay_bookings_are_rejected(db: Session, bay_and_trucks) -> None:
    bay, t1, t2 = bay_and_trucks
    db.add(_book(bay, t1, T0))
    db.commit()
    db.add(_book(bay, t2, T0 + timedelta(hours=1)))
    with pytest.raises(IntegrityError, match="ex_loading_schedules_bay_overlap"):
        db.commit()


def test_back_to_back_bookings_are_allowed(db: Session, bay_and_trucks) -> None:
    bay, t1, t2 = bay_and_trucks
    db.add_all([_book(bay, t1, T0), _book(bay, t2, T0 + timedelta(hours=2))])
    db.commit()


def test_cancelled_booking_does_not_block_bay(db: Session, bay_and_trucks) -> None:
    bay, t1, t2 = bay_and_trucks
    db.add(_book(bay, t1, T0, status=ScheduleStatus.CANCELLED))
    db.add(_book(bay, t2, T0))
    db.commit()


def test_departure_before_arrival_is_rejected(db: Session, bay_and_trucks) -> None:
    bay, t1, _ = bay_and_trucks
    db.add(_book(bay, t1, T0, arrival_at=T0, departed_at=T0 - timedelta(minutes=5)))
    with pytest.raises(IntegrityError, match="departure_after_loading"):
        db.commit()


def test_loading_cannot_start_without_arrival(db: Session, bay_and_trucks) -> None:
    bay, t1, _ = bay_and_trucks
    db.add(_book(bay, t1, T0, loading_started_at=T0))
    with pytest.raises(IntegrityError, match="loading_start_after_arrival"):
        db.commit()


def test_registration_is_unique(db: Session, bay_and_trucks) -> None:
    db.add(Truck(registration="KDG 752R", capacity_tonnes=Decimal(10)))
    with pytest.raises(IntegrityError):
        db.commit()
