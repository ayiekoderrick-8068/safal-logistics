"""Work-order lifecycle and breakdown rules.

Lifecycle (anything else is refused with 409):

    open ──► assigned ──► in_progress ◄──► awaiting_parts
      │         │  ▲           │                 │
      │         └──┘ (unassign)└──► completed    │
      └─────────┴──────────────┴─────► cancelled ◄┘

* assigned / in progress / awaiting parts / completed require a technician (also a CHECK).
* completed and cancelled are final.
* Completing needs a start time, the work performed, and a completion time that is neither
  in the future nor before the start (the order also has a CHECK).

Equipment status follows the work, and every automatic change is written to its history:
a breakdown that stops the asset -> out of service; starting work -> under maintenance (unless
out of service); restoring the breakdown or completing the last active work order -> back to
operational when nothing else keeps it down.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..models import User
from ..models_maintenance import (
    Breakdown,
    BreakdownSeverity,
    Equipment,
    EquipmentEvent,
    EquipmentStatus,
    WorkOrder,
    WorkOrderPriority,
    WorkOrderStatus,
)

S = WorkOrderStatus
TRANSITIONS: dict[S, frozenset[S]] = {
    S.OPEN: frozenset({S.ASSIGNED, S.CANCELLED}),
    S.ASSIGNED: frozenset({S.OPEN, S.IN_PROGRESS, S.CANCELLED}),
    S.IN_PROGRESS: frozenset({S.AWAITING_PARTS, S.COMPLETED, S.CANCELLED}),
    S.AWAITING_PARTS: frozenset({S.IN_PROGRESS, S.CANCELLED}),
    S.COMPLETED: frozenset(),
    S.CANCELLED: frozenset(),
}
ACTIVE = (S.IN_PROGRESS, S.AWAITING_PARTS)
CLOSED = (S.COMPLETED, S.CANCELLED)
PRIORITY_FOR_SEVERITY = {
    BreakdownSeverity.CRITICAL: WorkOrderPriority.CRITICAL,
    BreakdownSeverity.MAJOR: WorkOrderPriority.HIGH,
    BreakdownSeverity.MINOR: WorkOrderPriority.MEDIUM,
}


def allowed(current: S, target: S) -> bool:
    return target in TRANSITIONS[current]


def next_number(db: Session, prefix: str, sequence: str) -> str:
    """Human-readable, never reused: WO-2026-00042. Sequences are not rolled back, so
    numbers can have gaps (normal for document numbering)."""
    n = db.scalar(text(f"SELECT nextval('{sequence}')"))
    return f"{prefix}-{datetime.now(UTC).year}-{n:05d}"


def _status_event(db: Session, eq: Equipment, new: EquipmentStatus, why: str, actor: User) -> None:
    if eq.status is new:
        return
    old = eq.status
    eq.status = new
    db.add(
        EquipmentEvent(
            equipment_id=eq.id,
            kind="status_changed",
            summary=f"Status changed to {new.value.replace('_', ' ')} ({why})"[:255],
            changes={"status": {"from": old.value, "to": new.value}},
            actor_id=actor.id,
        )
    )


def _keeps_down(db: Session, eq: Equipment, ignore_wo: int | None = None) -> EquipmentStatus | None:
    """What still holds the asset down, if anything."""
    db.flush()
    if db.scalar(
        select(func.count(Breakdown.id)).where(
            Breakdown.equipment_id == eq.id,
            Breakdown.restored_at.is_(None),
            Breakdown.equipment_down,
        )
    ):
        return EquipmentStatus.OUT_OF_SERVICE
    active = select(func.count(WorkOrder.id)).where(
        WorkOrder.equipment_id == eq.id, WorkOrder.status.in_(ACTIVE)
    )
    if ignore_wo is not None:
        active = active.where(WorkOrder.id != ignore_wo)
    if db.scalar(active):
        return EquipmentStatus.UNDER_MAINTENANCE
    return None


def on_breakdown_logged(db: Session, bd: Breakdown, actor: User) -> None:
    if bd.equipment_down:
        _status_event(
            db, bd.equipment, EquipmentStatus.OUT_OF_SERVICE, f"breakdown {bd.number}", actor
        )


def on_work_started(db: Session, wo: WorkOrder, actor: User) -> None:
    if wo.equipment.status is EquipmentStatus.OPERATIONAL:
        _status_event(
            db,
            wo.equipment,
            EquipmentStatus.UNDER_MAINTENANCE,
            f"work order {wo.number} started",
            actor,
        )


def release(
    db: Session, eq: Equipment, why: str, actor: User, ignore_wo: int | None = None
) -> None:
    """After a restoration or the end of work: return the asset to the state the remaining
    open work implies. Only statuses this module sets are relaxed back to operational."""
    if eq.status not in (EquipmentStatus.OUT_OF_SERVICE, EquipmentStatus.UNDER_MAINTENANCE):
        return
    holding = _keeps_down(db, eq, ignore_wo)
    _status_event(db, eq, holding or EquipmentStatus.OPERATIONAL, why, actor)
