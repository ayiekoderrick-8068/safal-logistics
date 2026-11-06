"""Spare-parts stock ledger. Every change to `spare_parts.on_hand` goes through `apply()`.

Guarantees:
* **No negative stock** - the balance is changed by a single conditional UPDATE
  (`... WHERE on_hand + delta >= 0 RETURNING on_hand`) on a row that is locked for the rest of
  the transaction; the database CHECKs `on_hand >= 0` and `balance_after >= 0` back it up.
* **No duplicate deductions** - a movement may carry a client-generated `request_id`. A retry
  or double submission with the same id returns the movement already recorded instead of
  applying it again; a concurrent duplicate loses on the unique constraint and its whole
  transaction (including its stock update) is rolled back.
* **Audit** - each movement stores the signed quantity, the balance right after it, who made
  it and when; the ledger is append-only.
"""

from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import User
from ..models_maintenance import WHOLE_UNITS, MovementKind, SparePart, StockMovement, StockUnit


class Replay(Exception):  # noqa: N818 - control flow, not an error
    """The request was already applied; carries the original movement."""

    def __init__(self, movement: StockMovement) -> None:
        self.movement = movement


def check_quantity(value: Decimal, unit: StockUnit, label: str = "Quantity") -> Decimal:
    if value <= 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{label} must be more than zero."
        )
    if value.as_tuple().exponent < -3:  # type: ignore[operator]
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{label} allows at most 3 decimals."
        )
    if unit in WHOLE_UNITS and value != value.to_integral_value():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{label} must be a whole number of {unit.value}.",
        )
    return value


def fmt(q: Decimal, unit: StockUnit) -> str:
    n = q.normalize()
    text = (
        f"{n:f}" if n == n.to_integral_value() else f"{n.quantize(Decimal('0.001')):f}".rstrip("0")
    )
    return f"{text} {unit.value}"


def find_replay(
    db: Session, request_id: str | None, part_id: int, kind: MovementKind, quantity: Decimal
) -> StockMovement | None:
    if not request_id:
        return None
    existing = db.scalar(select(StockMovement).where(StockMovement.request_id == request_id))
    if existing is None:
        return None
    if existing.part_id != part_id or existing.kind is not kind or existing.quantity != quantity:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This request id was already used for a different movement."
        )
    return existing


def apply(
    db: Session,
    *,
    part: SparePart,
    kind: MovementKind,
    delta: Decimal,
    actor: User,
    work_order_id: int | None = None,
    reference: str | None = None,
    note: str | None = None,
    unit_cost: Decimal | None = None,
    request_id: str | None = None,
) -> StockMovement:
    if (replayed := find_replay(db, request_id, part.id, kind, delta)) is not None:
        raise Replay(replayed)
    new_balance = db.scalar(
        update(SparePart)
        .where(SparePart.id == part.id, SparePart.on_hand + delta >= 0)
        .values(on_hand=SparePart.on_hand + delta)
        .returning(SparePart.on_hand)
    )
    if new_balance is None:
        available = db.scalar(select(SparePart.on_hand).where(SparePart.id == part.id))
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Not enough stock of {part.part_number}: {fmt(available, part.unit)} on hand.",
        )
    movement = StockMovement(
        part_id=part.id,
        kind=kind,
        quantity=delta,
        balance_after=new_balance,
        work_order_id=work_order_id,
        reference=reference,
        note=note,
        unit_cost=unit_cost if unit_cost is not None else part.unit_cost,
        request_id=request_id,
        actor_id=actor.id,
    )
    db.add(movement)
    db.flush()
    db.refresh(part)
    return movement


def net_issued(db: Session, work_order_id: int, part_id: int) -> Decimal:
    """Issued minus returned for one part on one work order (a positive number)."""
    total = db.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
            StockMovement.work_order_id == work_order_id,
            StockMovement.part_id == part_id,
            StockMovement.kind.in_((MovementKind.ISSUE, MovementKind.RETURN)),
        )
    )
    return -Decimal(total)
