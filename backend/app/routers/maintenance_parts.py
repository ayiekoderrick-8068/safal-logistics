"""Spare parts inventory and parts consumed by work orders (stock rules: services/stock.py).

Permissions: catalogue, receipts and stock-count adjustments need `parts.manage` (managers and
storekeepers). Issuing to and returning from a work order needs `parts.consume`; technicians
may only do so for work orders assigned to them.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..audit import record_event
from ..db import get_db
from ..deps import require_maintenance
from ..maintenance_permissions import MaintenancePermission as P
from ..maintenance_permissions import allows
from ..models import User
from ..models_maintenance import (
    MovementKind,
    SparePart,
    StockMovement,
    WorkOrder,
    WorkOrderStatus,
)
from ..schemas_maintenance import (
    ConsumedPart,
    MovementOut,
    PartDetail,
    PartIn,
    PartIssue,
    PartOut,
    PartsSummary,
    PartUpdate,
    Person,
    StockAdjustment,
    StockReceipt,
    WorkOrderBrief,
    WorkOrderParts,
)
from ..schemas_ops import Page
from ..services import stock
from ..services.operations import conflict, invalid, not_found, utcnow

router = APIRouter(prefix="/api/maintenance", tags=["maintenance: spare parts"])
DB = Annotated[Session, Depends(get_db)]
Reader = Annotated[User, Depends(require_maintenance(P.VIEW))]
Storekeeper = Annotated[User, Depends(require_maintenance(P.MANAGE_PARTS))]
Consumer = Annotated[User, Depends(require_maintenance(P.CONSUME_PARTS))]

ISSUABLE = (WorkOrderStatus.ASSIGNED, WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.AWAITING_PARTS)


# ---------- helpers ----------
def _state(p: SparePart) -> str:
    if p.on_hand <= 0:
        return "out_of_stock"
    if p.reorder_level > 0 and p.on_hand <= p.reorder_level:
        return "low"
    return "ok"


def _part_out(p: SparePart) -> PartOut:
    return PartOut(
        id=p.id,
        part_number=p.part_number,
        name=p.name,
        description=p.description,
        category=p.category,
        unit=p.unit,
        on_hand=p.on_hand,
        reorder_level=p.reorder_level,
        reorder_quantity=p.reorder_quantity,
        location=p.location,
        supplier=p.supplier,
        unit_cost=p.unit_cost,
        is_active=p.is_active,
        stock_state=_state(p),
        stock_value=p.on_hand * p.unit_cost if p.unit_cost is not None else None,
    )


def _movement_out(m: StockMovement) -> MovementOut:
    wo = m.work_order
    return MovementOut(
        id=m.id,
        occurred_at=m.occurred_at,
        kind=m.kind,
        quantity=m.quantity,
        balance_after=m.balance_after,
        work_order=WorkOrderBrief(id=wo.id, number=wo.number, status=wo.status) if wo else None,
        reference=m.reference,
        note=m.note,
        actor=Person(id=m.actor.id, full_name=m.actor.full_name) if m.actor else None,
    )


def _get_part(db: Session, part_id: int, lock: bool = False) -> SparePart:
    query = select(SparePart).where(SparePart.id == part_id)
    if lock:
        query = query.with_for_update()
    p = db.scalar(query)
    if p is None:
        raise not_found("Spare part")
    return p


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if name == "uq_spare_parts_part_number":
            raise conflict("That part number is already in the catalogue.") from None
        if name == "uq_stock_movements_request_id":
            raise conflict("This request was already recorded. Refresh to see it.") from None
        raise conflict(
            "The stock record changed at the same time. Refresh and try again."
        ) from None


def _apply(db: Session, **kw) -> StockMovement:  # noqa: ANN003
    """Apply a movement; a replayed request returns the original movement unchanged."""
    try:
        return stock.apply(db, **kw)
    except stock.Replay as replay:
        return replay.movement


# ---------- catalogue ----------
@router.get("/parts/summary", response_model=PartsSummary)
def parts_summary(db: DB, _: Reader) -> PartsSummary:
    parts = db.scalars(select(SparePart).where(SparePart.is_active)).all()
    costed = [p for p in parts if p.unit_cost is not None]
    return PartsSummary(
        active_parts=len(parts),
        low_stock=sum(1 for p in parts if _state(p) == "low"),
        out_of_stock=sum(1 for p in parts if _state(p) == "out_of_stock"),
        stock_value=sum((p.on_hand * p.unit_cost for p in costed), Decimal(0)),
        parts_without_cost=len(parts) - len(costed),
    )


@router.get("/parts", response_model=Page[PartOut])
def list_parts(
    db: DB,
    _: Reader,
    q: str | None = Query(None, max_length=80),
    stock_: str | None = Query(None, alias="stock", pattern="^(low|out|attention)$"),
    category: str | None = Query(None, max_length=60),
    active: bool = True,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[PartOut]:
    query = select(SparePart).where(SparePart.is_active.is_(active))
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                SparePart.part_number.ilike(like),
                SparePart.name.ilike(like),
                SparePart.category.ilike(like),
                SparePart.location.ilike(like),
            )
        )
    low = (
        (SparePart.reorder_level > 0)
        & (SparePart.on_hand <= SparePart.reorder_level)
        & (SparePart.on_hand > 0)
    )
    if stock_ == "low":
        query = query.where(low)
    elif stock_ == "out":
        query = query.where(SparePart.on_hand <= 0)
    elif stock_ == "attention":  # low or out
        query = query.where(low | (SparePart.on_hand <= 0))
    if category:
        query = query.where(SparePart.category == category)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(SparePart.part_number).limit(limit).offset(offset))
    return Page(items=[_part_out(p) for p in rows], total=total, limit=limit, offset=offset)


@router.get("/parts/{part_id}", response_model=PartDetail)
def get_part(part_id: int, db: DB, _: Reader) -> PartDetail:
    p = _get_part(db, part_id)
    moves = db.scalars(
        select(StockMovement)
        .options(joinedload(StockMovement.work_order), joinedload(StockMovement.actor))
        .where(StockMovement.part_id == p.id)
        .order_by(StockMovement.occurred_at.desc(), StockMovement.id.desc())
        .limit(100)
    )
    issued = db.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
            StockMovement.part_id == p.id,
            StockMovement.kind.in_((MovementKind.ISSUE, MovementKind.RETURN)),
            StockMovement.occurred_at >= utcnow() - timedelta(days=90),
        )
    )
    return PartDetail(
        **_part_out(p).model_dump(),
        movements=[_movement_out(m) for m in moves],
        issued_last_90_days=-Decimal(issued),
    )


@router.post("/parts", response_model=PartOut, status_code=status.HTTP_201_CREATED)
def create_part(body: PartIn, request: Request, db: DB, user: Storekeeper) -> PartOut:
    if db.scalar(select(SparePart.id).where(func.upper(SparePart.part_number) == body.part_number)):
        raise conflict("That part number is already in the catalogue.")
    if body.reorder_level:
        stock.check_quantity(body.reorder_level, body.unit, "Reorder level")
    part = SparePart(**body.model_dump(exclude={"opening_quantity"}), on_hand=Decimal(0))
    db.add(part)
    db.flush()
    if body.opening_quantity:
        stock.check_quantity(body.opening_quantity, part.unit, "Opening quantity")
        _apply(
            db,
            part=part,
            kind=MovementKind.RECEIPT,
            delta=body.opening_quantity,
            actor=user,
            note="Opening stock",
        )
    record_event(
        db,
        action="spare_part.created",
        entity_type="spare_part",
        entity_id=part.id,
        actor=user,
        request=request,
        summary=f"Spare part {part.part_number} added",
    )
    _commit(db)
    return _part_out(part)


@router.patch("/parts/{part_id}", response_model=PartOut)
def update_part(
    part_id: int, body: PartUpdate, request: Request, db: DB, user: Storekeeper
) -> PartOut:
    p = _get_part(db, part_id, lock=True)
    changed = []
    for field in body.model_fields_set:
        value = getattr(body, field)
        if field in ("name", "reorder_level", "is_active") and value is None:
            raise invalid(f"{field.replace('_', ' ').capitalize()} cannot be empty.")
        if field == "reorder_level" and value:
            stock.check_quantity(value, p.unit, "Reorder level")
        if getattr(p, field) != value:
            setattr(p, field, value)
            changed.append(field)
    if changed:
        record_event(
            db,
            action="spare_part.updated",
            entity_type="spare_part",
            entity_id=p.id,
            actor=user,
            request=request,
            summary=f"Spare part {p.part_number} updated",
            changes={"fields": changed},
        )
        _commit(db)
    return _part_out(p)


@router.post("/parts/{part_id}/receive", response_model=PartOut)
def receive_stock(
    part_id: int, body: StockReceipt, request: Request, db: DB, user: Storekeeper
) -> PartOut:
    p = _get_part(db, part_id, lock=True)
    if not p.is_active:
        raise conflict(f"{p.part_number} is inactive. Reactivate it before receiving stock.")
    stock.check_quantity(body.quantity, p.unit)
    if body.unit_cost is not None:
        p.unit_cost = body.unit_cost  # latest purchase price
    m = _apply(
        db,
        part=p,
        kind=MovementKind.RECEIPT,
        delta=body.quantity,
        actor=user,
        reference=body.reference,
        note=body.note,
        unit_cost=body.unit_cost,
        request_id=body.request_id,
    )
    record_event(
        db,
        action="stock.received",
        entity_type="spare_part",
        entity_id=p.id,
        actor=user,
        request=request,
        summary=f"Received {stock.fmt(m.quantity, p.unit)} of {p.part_number}",
    )
    _commit(db)
    db.refresh(p)
    return _part_out(p)


@router.post("/parts/{part_id}/adjust", response_model=PartOut)
def adjust_stock(
    part_id: int, body: StockAdjustment, request: Request, db: DB, user: Storekeeper
) -> PartOut:
    """Record a physical stock count; the difference becomes an adjustment movement."""
    p = _get_part(db, part_id, lock=True)
    if body.counted_quantity:
        stock.check_quantity(body.counted_quantity, p.unit, "Counted quantity")
    if body.request_id:  # a retried count: the stock already reflects it
        done = db.scalar(select(StockMovement).where(StockMovement.request_id == body.request_id))
        if done is not None:
            if done.part_id != p.id or done.kind is not MovementKind.ADJUSTMENT:
                raise conflict("This request id was already used for a different movement.")
            return _part_out(p)
    delta = body.counted_quantity - p.on_hand
    if delta == 0:
        raise invalid(
            f"The count matches the recorded stock ({stock.fmt(p.on_hand, p.unit)}); "
            "nothing to adjust."
        )
    _apply(
        db,
        part=p,
        kind=MovementKind.ADJUSTMENT,
        delta=delta,
        actor=user,
        note=body.reason,
        request_id=body.request_id,
    )
    record_event(
        db,
        action="stock.adjusted",
        entity_type="spare_part",
        entity_id=p.id,
        actor=user,
        request=request,
        summary=f"{p.part_number} counted at {stock.fmt(body.counted_quantity, p.unit)}",
        changes={"delta": str(delta), "reason": body.reason},
    )
    _commit(db)
    db.refresh(p)
    return _part_out(p)


# ---------- parts consumed by work orders ----------
def _work_order(db: Session, wo_id: int, lock: bool = False) -> WorkOrder:
    query = select(WorkOrder).where(WorkOrder.id == wo_id)
    if lock:
        query = query.with_for_update()
    wo = db.scalar(query)
    if wo is None:
        raise not_found("Work order")
    return wo


def _may_touch(wo: WorkOrder, user: User) -> None:
    role = user.effective_maintenance_role
    if (
        wo.assigned_technician_id == user.id
        or allows(role, P.ASSIGN_WORK_ORDERS)
        or allows(role, P.MANAGE_PARTS)
    ):
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only the assigned technician can draw parts for this work order.",
    )


def _wo_parts(db: Session, wo: WorkOrder, user: User) -> WorkOrderParts:
    moves = db.scalars(
        select(StockMovement)
        .options(
            joinedload(StockMovement.part),
            joinedload(StockMovement.actor),
            joinedload(StockMovement.work_order),
        )
        .where(StockMovement.work_order_id == wo.id)
        .order_by(StockMovement.occurred_at, StockMovement.id)
    ).all()
    per: dict[int, dict] = defaultdict(
        lambda: {"issued": Decimal(0), "returned": Decimal(0), "cost": Decimal(0), "costed": True}
    )
    parts: dict[int, SparePart] = {}
    for m in moves:
        parts[m.part_id] = m.part
        line = per[m.part_id]
        if m.kind is MovementKind.ISSUE:
            line["issued"] += -m.quantity
        else:
            line["returned"] += m.quantity
        if m.unit_cost is None:
            line["costed"] = False
        else:
            line["cost"] += -m.quantity * m.unit_cost
    lines = [
        ConsumedPart(
            part=_part_out(parts[pid]),
            issued=v["issued"],
            returned=v["returned"],
            net=v["issued"] - v["returned"],
            cost=v["cost"] if v["costed"] else None,
        )
        for pid, v in per.items()
    ]
    total = (
        None
        if any(line.cost is None for line in lines)
        else sum((line.cost for line in lines), 0.0)
    )
    role = user.effective_maintenance_role
    return WorkOrderParts(
        work_order=WorkOrderBrief(id=wo.id, number=wo.number, status=wo.status),
        lines=sorted(lines, key=lambda x: x.part.part_number),
        movements=[_movement_out(m) for m in moves],
        total_cost=total,
        can_issue=wo.status in ISSUABLE
        and allows(role, P.CONSUME_PARTS)
        and (
            wo.assigned_technician_id == user.id
            or allows(role, P.ASSIGN_WORK_ORDERS)
            or allows(role, P.MANAGE_PARTS)
        ),
    )


@router.get("/work-orders/{wo_id}/parts", response_model=WorkOrderParts)
def work_order_parts(wo_id: int, db: DB, user: Reader) -> WorkOrderParts:
    return _wo_parts(db, _work_order(db, wo_id), user)


@router.post(
    "/work-orders/{wo_id}/parts", response_model=WorkOrderParts, status_code=status.HTTP_201_CREATED
)
def issue_parts(
    wo_id: int, body: PartIssue, request: Request, db: DB, user: Consumer
) -> WorkOrderParts:
    wo = _work_order(db, wo_id, lock=True)
    _may_touch(wo, user)
    part = _get_part(db, body.part_id, lock=True)
    replay = stock.find_replay(db, body.request_id, part.id, MovementKind.ISSUE, -body.quantity)
    if replay is None:
        if wo.status not in ISSUABLE:
            raise conflict(
                f"{wo.number} is {wo.status.value.replace('_', ' ')}; "
                "parts can only be issued to open work."
            )
        if not part.is_active:
            raise conflict(f"{part.part_number} is inactive.")
        stock.check_quantity(body.quantity, part.unit)
        m = _apply(
            db,
            part=part,
            kind=MovementKind.ISSUE,
            delta=-body.quantity,
            actor=user,
            work_order_id=wo.id,
            note=body.note,
            request_id=body.request_id,
        )
        record_event(
            db,
            action="stock.issued",
            entity_type="work_order",
            entity_id=wo.id,
            actor=user,
            request=request,
            summary=f"{stock.fmt(-m.quantity, part.unit)} of {part.part_number} "
            f"issued to {wo.number}",
        )
        _commit(db)
    return _wo_parts(db, wo, user)


@router.post("/work-orders/{wo_id}/parts/return", response_model=WorkOrderParts)
def return_parts(
    wo_id: int, body: PartIssue, request: Request, db: DB, user: Consumer
) -> WorkOrderParts:
    wo = _work_order(db, wo_id, lock=True)
    _may_touch(wo, user)
    part = _get_part(db, body.part_id, lock=True)
    replay = stock.find_replay(db, body.request_id, part.id, MovementKind.RETURN, body.quantity)
    if replay is None:
        stock.check_quantity(body.quantity, part.unit)
        outstanding = stock.net_issued(db, wo.id, part.id)
        if body.quantity > outstanding:
            raise invalid(
                f"Only {stock.fmt(outstanding, part.unit)} of {part.part_number} "
                f"is outstanding on {wo.number}."
            )
        _apply(
            db,
            part=part,
            kind=MovementKind.RETURN,
            delta=body.quantity,
            actor=user,
            work_order_id=wo.id,
            note=body.note,
            request_id=body.request_id,
        )
        record_event(
            db,
            action="stock.returned",
            entity_type="work_order",
            entity_id=wo.id,
            actor=user,
            request=request,
            summary=f"{stock.fmt(body.quantity, part.unit)} of {part.part_number} "
            f"returned from {wo.number}",
        )
        _commit(db)
    return _wo_parts(db, wo, user)
