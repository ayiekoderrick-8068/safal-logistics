"""Work orders and breakdowns (Maintenance workspace). Lifecycle rules: services/workorders.py.

Permissions: creating work orders `work_orders.create`; assigning, editing and cancelling
`work_orders.assign`; starting, pausing for parts and completing `work_orders.work` - and a
technician may only progress work orders assigned to them. Breakdowns: `breakdowns.log`.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..audit import record_event
from ..db import get_db
from ..deps import require_maintenance
from ..maintenance_permissions import MaintenancePermission as P
from ..maintenance_permissions import allows
from ..models import User
from ..models_maintenance import (
    Breakdown,
    Equipment,
    WorkOrder,
    WorkOrderEvent,
    WorkOrderStatus,
    WorkOrderType,
)
from ..schemas_maintenance import (
    BreakdownBrief,
    BreakdownIn,
    BreakdownOut,
    BreakdownRestore,
    BreakdownSummary,
    BreakdownUpdate,
    CategoryCount,
    EquipmentRef,
    Person,
    RankedEquipment,
    WorkOrderBrief,
    WorkOrderComplete,
    WorkOrderDetail,
    WorkOrderEventOut,
    WorkOrderIn,
    WorkOrderOut,
    WorkOrderSummary,
    WorkOrderTransition,
    WorkOrderUpdate,
)
from ..schemas_ops import Page
from ..services.operations import conflict, invalid, local_today, not_found, utcnow
from ..services.workorders import (
    ACTIVE,
    CLOSED,
    PRIORITY_FOR_SEVERITY,
    TRANSITIONS,
    allowed,
    next_number,
    on_breakdown_logged,
    on_work_started,
    release,
)
from .maintenance_equipment import _event, _technician

router = APIRouter(prefix="/api/maintenance", tags=["maintenance: work orders and breakdowns"])
DB = Annotated[Session, Depends(get_db)]
Reader = Annotated[User, Depends(require_maintenance(P.VIEW))]
Creator = Annotated[User, Depends(require_maintenance(P.CREATE_WORK_ORDERS))]
Assigner = Annotated[User, Depends(require_maintenance(P.ASSIGN_WORK_ORDERS))]
Worker = Annotated[User, Depends(require_maintenance(P.WORK_ON_ORDERS))]
Logger = Annotated[User, Depends(require_maintenance(P.LOG_BREAKDOWNS))]

S = WorkOrderStatus
CLOCK_SKEW = timedelta(minutes=5)  # tolerate small device clock differences
SUMMARY_DAYS_DEFAULT = 90


# ---------- helpers ----------
def _ref(e: Equipment) -> EquipmentRef:
    return EquipmentRef(id=e.id, code=e.code, name=e.name)


def _person(u: User | None) -> Person | None:
    return Person(id=u.id, full_name=u.full_name) if u else None


def _minutes(a: datetime, b: datetime) -> int:
    return max(0, int((b - a).total_seconds() // 60))


def _not_before(at: datetime, start: datetime, message: str) -> datetime:
    """Times are entered to the minute: a time within the start's own minute means "at the
    start" and is clamped to it; anything earlier is refused."""
    if at >= start:
        return at
    if at >= start.replace(second=0, microsecond=0):
        return start
    raise invalid(message)


def _not_future(at: datetime, label: str) -> datetime:
    if at.tzinfo is None:
        raise invalid(f"The {label} must include a time zone.")
    if at > utcnow() + CLOCK_SKEW:
        raise invalid(f"The {label} cannot be in the future.")
    return at


def _active_equipment(db: Session, equipment_id: int) -> Equipment:
    eq = db.get(Equipment, equipment_id)
    if eq is None:
        raise invalid("Equipment not found.")
    if eq.archived_at is not None:
        raise conflict(f"{eq.code} is archived. Restore it before recording maintenance work.")
    return eq


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if name == "uq_breakdowns_one_open_per_equipment":
            raise conflict("This equipment already has an open breakdown.") from None
        raise conflict("This record was changed by someone else. Refresh and try again.") from None


def _can(user: User, p: P) -> bool:
    return allows(user.effective_maintenance_role, p)


def _wo_event(
    db: Session,
    wo: WorkOrder,
    summary: str,
    actor: User,
    frm: S | None = None,
    to: S | None = None,
    note: str | None = None,
) -> None:
    db.add(
        WorkOrderEvent(
            work_order_id=wo.id,
            from_status=frm.value if frm else None,
            to_status=to.value if to else None,
            summary=summary[:255],
            note=note,
            actor_id=actor.id,
        )
    )


def _wo_out(wo: WorkOrder, today, model=WorkOrderOut, **extra) -> WorkOrderOut:  # noqa: ANN001
    bd = wo.breakdown
    return model(
        id=wo.id,
        number=wo.number,
        equipment=_ref(wo.equipment),
        maintenance_type=wo.maintenance_type,
        priority=wo.priority,
        status=wo.status,
        fault_description=wo.fault_description,
        assigned_technician=_person(wo.assigned_technician),
        scheduled_on=wo.scheduled_on,
        overdue=bool(wo.scheduled_on and wo.scheduled_on < today and wo.status not in CLOSED),
        created_at=wo.created_at,
        created_by=_person(wo.created_by),
        started_at=wo.started_at,
        completed_at=wo.completed_at,
        repair_minutes=_minutes(wo.started_at, wo.completed_at)
        if wo.started_at and wo.completed_at
        else None,
        work_performed=wo.work_performed,
        completion_notes=wo.completion_notes,
        cancel_reason=wo.cancel_reason,
        breakdown=BreakdownBrief(
            id=bd.id,
            number=bd.number,
            is_open=bd.restored_at is None,
            started_at=bd.started_at,
            restored_at=bd.restored_at,
        )
        if bd
        else None,
        allowed_transitions=sorted(TRANSITIONS[wo.status], key=list(S).index),
        **extra,
    )


def _bd_out(db: Session, bd: Breakdown) -> BreakdownOut:
    now = utcnow()
    orders = db.scalars(
        select(WorkOrder).where(WorkOrder.breakdown_id == bd.id).order_by(WorkOrder.id)
    )
    return BreakdownOut(
        id=bd.id,
        number=bd.number,
        equipment=_ref(bd.equipment),
        started_at=bd.started_at,
        restored_at=bd.restored_at,
        is_open=bd.restored_at is None,
        downtime_minutes=_minutes(bd.started_at, bd.restored_at or now) if bd.equipment_down else 0,
        severity=bd.severity,
        category=bd.category,
        description=bd.description,
        possible_cause=bd.possible_cause,
        actions_taken=bd.actions_taken,
        equipment_down=bd.equipment_down,
        reported_by=_person(bd.reported_by),
        restored_by=_person(bd.restored_by),
        work_orders=[WorkOrderBrief(id=w.id, number=w.number, status=w.status) for w in orders],
    )


def _get_wo(db: Session, wo_id: int, lock: bool = False) -> WorkOrder:
    query = select(WorkOrder).where(WorkOrder.id == wo_id)
    if lock:  # serialise concurrent transitions of the same work order
        query = query.with_for_update()
    wo = db.scalar(query)
    if wo is None:
        raise not_found("Work order")
    return wo


def _get_bd(db: Session, bd_id: int, lock: bool = False) -> Breakdown:
    query = select(Breakdown).where(Breakdown.id == bd_id)
    if lock:
        query = query.with_for_update()
    bd = db.scalar(query)
    if bd is None:
        raise not_found("Breakdown")
    return bd


def _own_or_assigner(wo: WorkOrder, user: User) -> None:
    """Technicians may only progress their own work; planners/managers may act on any."""
    if wo.assigned_technician_id != user.id and not _can(user, P.ASSIGN_WORK_ORDERS):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the assigned technician can update this work order."
        )


def _create_work_order(
    db: Session,
    *,
    eq: Equipment,
    kind: WorkOrderType,
    priority,
    description: str,  # noqa: ANN001
    actor: User,
    technician: User | None = None,
    scheduled_on=None,  # noqa: ANN001
    breakdown: Breakdown | None = None,
) -> WorkOrder:
    wo = WorkOrder(
        number=next_number(db, "WO", "work_order_number_seq"),
        equipment_id=eq.id,
        maintenance_type=kind,
        priority=priority,
        fault_description=description,
        scheduled_on=scheduled_on,
        assigned_technician_id=technician.id if technician else None,
        status=S.ASSIGNED if technician else S.OPEN,
        created_by_id=actor.id,
        breakdown_id=breakdown.id if breakdown else None,
    )
    db.add(wo)
    db.flush()
    _wo_event(db, wo, "Work order raised", actor, to=wo.status)
    if technician:
        _wo_event(db, wo, f"Assigned to {technician.full_name}", actor)
    _event(
        db, eq, "work_order_created", f"Work order {wo.number} raised: {description[:120]}", actor
    )
    return wo


# ---------- work orders ----------
@router.get("/work-orders/summary", response_model=WorkOrderSummary)
def work_order_summary(db: DB, _: Reader) -> WorkOrderSummary:
    today = local_today()
    counts = dict(
        db.execute(
            select(WorkOrder.status, func.count(WorkOrder.id)).group_by(WorkOrder.status)
        ).all()
    )
    open_ = WorkOrder.status.not_in(CLOSED)
    return WorkOrderSummary(
        open=counts.get(S.OPEN, 0),
        assigned=counts.get(S.ASSIGNED, 0),
        in_progress=counts.get(S.IN_PROGRESS, 0),
        awaiting_parts=counts.get(S.AWAITING_PARTS, 0),
        completed_last_30_days=db.scalar(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.status == S.COMPLETED,
                WorkOrder.completed_at >= utcnow() - timedelta(days=30),
            )
        )
        or 0,
        overdue=db.scalar(
            select(func.count(WorkOrder.id)).where(open_, WorkOrder.scheduled_on < today)
        )
        or 0,
        critical_open=db.scalar(
            select(func.count(WorkOrder.id)).where(open_, WorkOrder.priority == "critical")
        )
        or 0,
    )


@router.get("/work-orders", response_model=Page[WorkOrderOut])
def list_work_orders(
    db: DB,
    user: Reader,
    status_: list[WorkOrderStatus] | None = Query(None, alias="status"),
    active: bool = Query(False, description="Only work that is not completed or cancelled"),
    priority: str | None = Query(None, pattern="^(low|medium|high|critical)$"),
    equipment_id: int | None = None,
    mine: bool = False,
    overdue: bool = False,
    q: str | None = Query(None, max_length=80),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[WorkOrderOut]:
    today = local_today()
    query = select(WorkOrder).join(WorkOrder.equipment)
    if status_:
        query = query.where(WorkOrder.status.in_(status_))
    if active or overdue:
        query = query.where(WorkOrder.status.not_in(CLOSED))
    if overdue:
        query = query.where(WorkOrder.scheduled_on < today)
    if priority:
        query = query.where(WorkOrder.priority == priority)
    if equipment_id is not None:
        query = query.where(WorkOrder.equipment_id == equipment_id)
    if mine:
        query = query.where(WorkOrder.assigned_technician_id == user.id)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                WorkOrder.number.ilike(like),
                WorkOrder.fault_description.ilike(like),
                Equipment.code.ilike(like),
                Equipment.name.ilike(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    # Most urgent first: critical > high > ..., then oldest.
    rank = case({"critical": 0, "high": 1, "medium": 2, "low": 3}, value=WorkOrder.priority)
    rows = db.scalars(
        query.options(
            joinedload(WorkOrder.equipment),
            joinedload(WorkOrder.assigned_technician),
            joinedload(WorkOrder.created_by),
            joinedload(WorkOrder.breakdown),
        )
        .order_by(WorkOrder.status.in_(CLOSED), rank, WorkOrder.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return Page(items=[_wo_out(w, today) for w in rows], total=total, limit=limit, offset=offset)


@router.get("/work-orders/{wo_id}", response_model=WorkOrderDetail)
def get_work_order(wo_id: int, db: DB, _: Reader) -> WorkOrderDetail:
    wo = _get_wo(db, wo_id)
    events = db.scalars(
        select(WorkOrderEvent)
        .options(joinedload(WorkOrderEvent.actor))
        .where(WorkOrderEvent.work_order_id == wo.id)
        .order_by(WorkOrderEvent.occurred_at, WorkOrderEvent.id)
    )
    history = [
        WorkOrderEventOut(
            id=e.id,
            occurred_at=e.occurred_at,
            from_status=S(e.from_status) if e.from_status else None,
            to_status=S(e.to_status) if e.to_status else None,
            summary=e.summary,
            note=e.note,
            actor=_person(e.actor),
        )
        for e in events
    ]
    return _wo_out(wo, local_today(), WorkOrderDetail, history=history)


@router.post("/work-orders", response_model=WorkOrderOut, status_code=status.HTTP_201_CREATED)
def create_work_order(body: WorkOrderIn, request: Request, db: DB, user: Creator) -> WorkOrderOut:
    eq = _active_equipment(db, body.equipment_id)
    if body.assigned_technician_id not in (None, user.id) and not _can(user, P.ASSIGN_WORK_ORDERS):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can only assign work orders to yourself."
        )
    tech = _technician(db, body.assigned_technician_id)
    if body.scheduled_on and body.scheduled_on < local_today():
        raise invalid("The scheduled date cannot be in the past.")
    bd = None
    if body.breakdown_id is not None:
        bd = db.get(Breakdown, body.breakdown_id)
        if bd is None or bd.equipment_id != eq.id:
            raise invalid("That breakdown belongs to different equipment.")
    wo = _create_work_order(
        db,
        eq=eq,
        kind=body.maintenance_type,
        priority=body.priority,
        description=body.fault_description,
        actor=user,
        technician=tech,
        scheduled_on=body.scheduled_on,
        breakdown=bd,
    )
    record_event(
        db,
        action="work_order.created",
        entity_type="work_order",
        entity_id=wo.id,
        actor=user,
        request=request,
        summary=f"{wo.number} raised for {eq.code}",
    )
    _commit(db)
    db.refresh(wo)
    return _wo_out(wo, local_today())


@router.patch("/work-orders/{wo_id}", response_model=WorkOrderOut)
def update_work_order(
    wo_id: int, body: WorkOrderUpdate, request: Request, db: DB, user: Assigner
) -> WorkOrderOut:
    wo = _get_wo(db, wo_id, lock=True)
    if wo.status in CLOSED:
        raise conflict(f"{wo.number} is {wo.status.value} and can no longer be changed.")
    sent = body.model_fields_set
    changes: list[str] = []
    if "priority" in sent and body.priority and body.priority != wo.priority:
        changes.append(f"priority {wo.priority.value} → {body.priority.value}")
        wo.priority = body.priority
    if (
        "fault_description" in sent
        and body.fault_description
        and body.fault_description != wo.fault_description
    ):
        wo.fault_description = body.fault_description
        changes.append("description updated")
    if "scheduled_on" in sent and body.scheduled_on != wo.scheduled_on:
        if body.scheduled_on and body.scheduled_on < local_today():
            raise invalid("The scheduled date cannot be in the past.")
        wo.scheduled_on = body.scheduled_on
        changes.append(
            f"scheduled {body.scheduled_on:%d %b %Y}" if body.scheduled_on else "schedule cleared"
        )
    if (
        "assigned_technician_id" in sent
        and body.assigned_technician_id != wo.assigned_technician_id
    ):
        tech = _technician(db, body.assigned_technician_id)
        before = wo.status
        if tech is None:
            if wo.status is not S.ASSIGNED:
                raise conflict("Work that has started cannot be unassigned. Reassign it instead.")
            wo.status = S.OPEN
        elif wo.status is S.OPEN:
            wo.status = S.ASSIGNED
        wo.assigned_technician_id = tech.id if tech else None
        _wo_event(
            db,
            wo,
            f"Assigned to {tech.full_name}" if tech else "Technician unassigned",
            user,
            frm=before if before != wo.status else None,
            to=wo.status if before != wo.status else None,
        )
    if changes:
        _wo_event(db, wo, "Updated: " + "; ".join(changes), user)
    if changes or "assigned_technician_id" in sent:
        record_event(
            db,
            action="work_order.updated",
            entity_type="work_order",
            entity_id=wo.id,
            actor=user,
            request=request,
            summary=f"{wo.number} updated",
        )
        _commit(db)
        db.refresh(wo)
    return _wo_out(wo, local_today())


@router.post("/work-orders/{wo_id}/transition", response_model=WorkOrderOut)
def transition_work_order(
    wo_id: int, body: WorkOrderTransition, request: Request, db: DB, user: Reader
) -> WorkOrderOut:
    """Start, pause for parts, resume or cancel. Completion has its own endpoint (validation)."""
    wo = _get_wo(db, wo_id, lock=True)
    target = body.to
    if target is S.COMPLETED:
        raise invalid("Use the complete action, which records the work performed.")
    if target in (S.OPEN, S.ASSIGNED):
        raise invalid("Assign or unassign a technician to change between open and assigned.")
    if not allowed(wo.status, target):
        raise conflict(
            f"{wo.number} cannot go from {wo.status.value.replace('_', ' ')} to "
            f"{target.value.replace('_', ' ')}."
        )
    if target is S.CANCELLED:
        if not _can(user, P.ASSIGN_WORK_ORDERS):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You do not have permission to cancel work orders."
            )
        if not body.note or len(body.note) < 3:
            raise invalid("Give the reason for cancelling.")
    else:
        if not _can(user, P.WORK_ON_ORDERS):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You do not have permission for this action"
            )
        _own_or_assigner(wo, user)
    before = wo.status
    wo.status = target
    eq = wo.equipment
    if target is S.IN_PROGRESS:
        if wo.started_at is None:
            wo.started_at = utcnow()
        on_work_started(db, wo, user)
        summary = "Work started" if before is S.ASSIGNED else "Work resumed"
    elif target is S.AWAITING_PARTS:
        summary = "Waiting for parts"
    else:
        wo.cancel_reason = body.note[:255] if body.note else None
        summary = f"Cancelled: {body.note}"
        if before in ACTIVE:
            release(db, eq, f"work order {wo.number} cancelled", user, ignore_wo=wo.id)
        _event(
            db, eq, "work_order_cancelled", f"Work order {wo.number} cancelled: {body.note}", user
        )
    _wo_event(db, wo, summary, user, frm=before, to=target, note=body.note)
    record_event(
        db,
        action=f"work_order.{target.value}",
        entity_type="work_order",
        entity_id=wo.id,
        actor=user,
        request=request,
        summary=f"{wo.number}: {summary}",
    )
    _commit(db)
    db.refresh(wo)
    return _wo_out(wo, local_today())


@router.post("/work-orders/{wo_id}/complete", response_model=WorkOrderOut)
def complete_work_order(
    wo_id: int, body: WorkOrderComplete, request: Request, db: DB, user: Worker
) -> WorkOrderOut:
    wo = _get_wo(db, wo_id, lock=True)
    if wo.status is S.COMPLETED:
        raise conflict(f"{wo.number} is already completed.")
    if not allowed(wo.status, S.COMPLETED):
        raise conflict(
            f"{wo.number} is {wo.status.value.replace('_', ' ')}. "
            "Start the work before completing it."
        )
    _own_or_assigner(wo, user)
    completed_at = _not_future(body.completed_at or utcnow(), "completion time")
    if wo.started_at:
        completed_at = _not_before(
            completed_at, wo.started_at, "The completion time cannot be before the work started."
        )
    eq = wo.equipment
    wo.status = S.COMPLETED
    wo.completed_at = completed_at
    wo.completed_by_id = user.id
    wo.work_performed = body.work_performed
    wo.completion_notes = body.completion_notes
    bd = wo.breakdown
    if body.restore_breakdown:
        if bd is None or bd.restored_at is not None:
            raise invalid("This work order has no open breakdown to restore.")
        bd = _get_bd(db, bd.id, lock=True)
        bd.restored_at = completed_at
        bd.restored_by_id = user.id
        bd.actions_taken = bd.actions_taken or body.work_performed
        _event(
            db,
            eq,
            "breakdown_restored",
            f"Breakdown {bd.number} restored "
            f"({_minutes(bd.started_at, completed_at)} min downtime)",
            user,
        )
    _wo_event(
        db, wo, "Completed", user, frm=S.IN_PROGRESS, to=S.COMPLETED, note=body.completion_notes
    )
    _event(
        db,
        eq,
        "work_order_completed",
        f"Work order {wo.number} completed: {body.work_performed[:120]}",
        user,
    )
    release(db, eq, f"work order {wo.number} completed", user, ignore_wo=wo.id)
    record_event(
        db,
        action="work_order.completed",
        entity_type="work_order",
        entity_id=wo.id,
        actor=user,
        request=request,
        summary=f"{wo.number} completed",
    )
    _commit(db)
    db.refresh(wo)
    return _wo_out(wo, local_today())


# ---------- breakdowns ----------
@router.get("/breakdowns/summary", response_model=BreakdownSummary)
def breakdown_summary(
    db: DB, _: Reader, days: int = Query(SUMMARY_DAYS_DEFAULT, ge=7, le=366)
) -> BreakdownSummary:
    now = utcnow()
    start = now - timedelta(days=days)
    rows = db.scalars(
        select(Breakdown)
        .options(joinedload(Breakdown.equipment))
        .where(
            Breakdown.started_at < now,
            or_(Breakdown.restored_at.is_(None), Breakdown.restored_at > start),
        )
    ).all()
    per_eq: dict[int, list] = defaultdict(lambda: [None, 0, 0])
    per_cat: dict = defaultdict(lambda: [0, 0])
    total = 0
    for bd in rows:
        # Clip to the window; non-overlapping per asset, so the sum is exact.
        mins = (
            _minutes(max(bd.started_at, start), min(bd.restored_at or now, now))
            if bd.equipment_down
            else 0
        )
        total += mins
        entry = per_eq[bd.equipment_id]
        entry[0] = bd.equipment
        entry[1] += 1
        entry[2] += mins
        per_cat[bd.category][0] += 1
        per_cat[bd.category][1] += mins
    ranked = sorted(per_eq.values(), key=lambda e: (-e[1], -e[2], e[0].code))
    return BreakdownSummary(
        window_days=days,
        open=db.scalar(select(func.count(Breakdown.id)).where(Breakdown.restored_at.is_(None)))
        or 0,
        breakdowns=len(rows),
        downtime_minutes=total,
        repeat_equipment=sum(1 for e in ranked if e[1] >= 2),
        top_equipment=[
            RankedEquipment(equipment=_ref(e[0]), breakdowns=e[1], downtime_minutes=e[2])
            for e in ranked[:5]
        ],
        categories=[
            CategoryCount(category=c, breakdowns=v[0], downtime_minutes=v[1])
            for c, v in sorted(per_cat.items(), key=lambda kv: (-kv[1][0], kv[0].value))
        ],
    )


@router.get("/breakdowns", response_model=Page[BreakdownOut])
def list_breakdowns(
    db: DB,
    _: Reader,
    open_: bool | None = Query(None, alias="open"),
    equipment_id: int | None = None,
    severity: str | None = Query(None, pattern="^(minor|major|critical)$"),
    category: str | None = Query(None, max_length=32),
    q: str | None = Query(None, max_length=80),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[BreakdownOut]:
    query = select(Breakdown).join(Breakdown.equipment)
    if open_ is True:
        query = query.where(Breakdown.restored_at.is_(None))
    elif open_ is False:
        query = query.where(Breakdown.restored_at.is_not(None))
    if equipment_id is not None:
        query = query.where(Breakdown.equipment_id == equipment_id)
    if severity:
        query = query.where(Breakdown.severity == severity)
    if category:
        query = query.where(Breakdown.category == category)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                Breakdown.number.ilike(like),
                Breakdown.description.ilike(like),
                Equipment.code.ilike(like),
                Equipment.name.ilike(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.options(
            joinedload(Breakdown.equipment),
            joinedload(Breakdown.reported_by),
            joinedload(Breakdown.restored_by),
        )
        .order_by(Breakdown.restored_at.is_not(None), Breakdown.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return Page(items=[_bd_out(db, b) for b in rows], total=total, limit=limit, offset=offset)


@router.post("/breakdowns", response_model=BreakdownOut, status_code=status.HTTP_201_CREATED)
def log_breakdown(body: BreakdownIn, request: Request, db: DB, user: Logger) -> BreakdownOut:
    eq = _active_equipment(db, body.equipment_id)
    started = _not_future(body.started_at, "failure time")
    if eq.installed_on and started.date() < eq.installed_on:
        raise invalid("The failure time cannot be before the equipment was installed.")
    open_bd = db.scalar(
        select(Breakdown).where(Breakdown.equipment_id == eq.id, Breakdown.restored_at.is_(None))
    )
    if open_bd:
        raise conflict(
            f"{eq.code} already has an open breakdown ({open_bd.number}). Update or restore it "
            "instead of logging the same failure twice."
        )
    last_restored = db.scalar(
        select(func.max(Breakdown.restored_at)).where(Breakdown.equipment_id == eq.id)
    )
    if last_restored and started < last_restored:
        raise invalid(
            "The failure time overlaps the previous breakdown of this equipment, which was "
            f"restored at {last_restored:%d %b %Y %H:%M} UTC."
        )
    if body.create_work_order and not _can(user, P.CREATE_WORK_ORDERS):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You do not have permission to raise work orders."
        )
    bd = Breakdown(
        number=next_number(db, "BD", "breakdown_number_seq"),
        equipment_id=eq.id,
        started_at=started,
        severity=body.severity,
        category=body.category,
        description=body.description,
        possible_cause=body.possible_cause,
        equipment_down=body.equipment_down,
        reported_by_id=user.id,
    )
    db.add(bd)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict(f"{eq.code} already has an open breakdown.") from None
    bd.equipment = eq
    _event(
        db,
        eq,
        "breakdown_logged",
        f"Breakdown {bd.number} ({bd.severity.value}, {bd.category.value}): "
        f"{body.description[:120]}",
        user,
    )
    on_breakdown_logged(db, bd, user)
    if body.create_work_order:
        _create_work_order(
            db,
            eq=eq,
            kind=WorkOrderType.CORRECTIVE,
            priority=PRIORITY_FOR_SEVERITY[bd.severity],
            description=body.description,
            actor=user,
            breakdown=bd,
        )
    record_event(
        db,
        action="breakdown.logged",
        entity_type="breakdown",
        entity_id=bd.id,
        actor=user,
        request=request,
        summary=f"{bd.number} on {eq.code}",
    )
    _commit(db)
    db.refresh(bd)
    return _bd_out(db, bd)


@router.patch("/breakdowns/{bd_id}", response_model=BreakdownOut)
def update_breakdown(
    bd_id: int, body: BreakdownUpdate, request: Request, db: DB, user: Logger
) -> BreakdownOut:
    bd = _get_bd(db, bd_id, lock=True)
    changed = []
    for field in body.model_fields_set:
        value = getattr(body, field)
        if field in ("severity", "category", "description") and value is None:
            raise invalid(f"{field.capitalize()} cannot be empty.")
        if getattr(bd, field) != value:
            setattr(bd, field, value)
            changed.append(field.replace("_", " "))
    if changed:
        _event(
            db,
            bd.equipment,
            "breakdown_updated",
            f"Breakdown {bd.number} updated: {', '.join(changed)}",
            user,
        )
        record_event(
            db,
            action="breakdown.updated",
            entity_type="breakdown",
            entity_id=bd.id,
            actor=user,
            request=request,
            summary=f"{bd.number} updated",
        )
        _commit(db)
        db.refresh(bd)
    return _bd_out(db, bd)


@router.post("/breakdowns/{bd_id}/restore", response_model=BreakdownOut)
def restore_breakdown(
    bd_id: int, body: BreakdownRestore, request: Request, db: DB, user: Logger
) -> BreakdownOut:
    bd = _get_bd(db, bd_id, lock=True)
    if bd.restored_at is not None:
        raise conflict(f"{bd.number} was already restored.")
    restored = _not_before(
        _not_future(body.restored_at, "restoration time"),
        bd.started_at,
        "The restoration time cannot be before the failure started.",
    )
    bd.restored_at = restored
    bd.restored_by_id = user.id
    bd.actions_taken = body.actions_taken
    eq = bd.equipment
    _event(
        db,
        eq,
        "breakdown_restored",
        f"Breakdown {bd.number} restored ({_minutes(bd.started_at, restored)} min downtime)",
        user,
    )
    release(db, eq, f"breakdown {bd.number} restored", user)
    record_event(
        db,
        action="breakdown.restored",
        entity_type="breakdown",
        entity_id=bd.id,
        actor=user,
        request=request,
        summary=f"{bd.number} restored",
    )
    _commit(db)
    db.refresh(bd)
    return _bd_out(db, bd)
