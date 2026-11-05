"""Driver-to-truck assignments with full history.

All driver changes go through ``set_driver`` so the history table and the denormalised
``trucks.driver_id`` (current driver) never disagree.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Driver, DriverAssignment, Truck, User


def active_assignment(db: Session, truck: Truck, lock: bool = False) -> DriverAssignment | None:
    q = select(DriverAssignment).where(
        DriverAssignment.truck_id == truck.id, DriverAssignment.released_at.is_(None)
    )
    return db.scalar(q.with_for_update() if lock else q)


def set_driver(
    db: Session,
    truck: Truck,
    driver: Driver | None,
    actor: User | None,
    at: datetime | None = None,
    note: str | None = None,
    source: str = "manual",
) -> bool:
    """Release the current assignment (if any) and start a new one. Returns True if changed."""
    if (truck.driver_id or None) == (driver.id if driver else None) and truck.id is not None:
        return False
    at = at or datetime.now(UTC)
    if truck.id is not None:
        current = active_assignment(db, truck, lock=True)
        if current is not None:
            current.released_at = at
            current.released_by_id = actor.id if actor else None
            db.flush()  # free the period before the new assignment is inserted
    truck.driver = driver
    if driver is not None:
        db.add(
            DriverAssignment(
                driver=driver,
                truck=truck,
                assigned_at=at,
                source=source,
                note=note,
                assigned_by_id=actor.id if actor else None,
            )
        )
    return True
