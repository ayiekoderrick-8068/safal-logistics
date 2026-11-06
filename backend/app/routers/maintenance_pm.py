"""Preventive maintenance: recurring plans and the tasks they generate (see services/pm.py).

Planners and managers (`plans.manage`) create plans, schedule once-off services, reschedule,
reassign and cancel. Technicians (`work_orders.work`) complete tasks. Everyone in the
workspace can read.
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..audit import record_event
from ..db import get_db
from ..deps import require_maintenance
from ..maintenance_permissions import MaintenancePermission as P
from ..models import User
from ..models_maintenance import Equipment, MaintenancePlan, MaintenanceTask, TaskStatus
from ..schemas_maintenance import (
    EquipmentRef,
    Person,
    PlanActivate,
    PlanIn,
    PlanOut,
    PlanUpdate,
    PmCompliance,
    PmSummary,
    TaskBrief,
    TaskCancel,
    TaskComplete,
    TaskIn,
    TaskOut,
    TaskUpdate,
)
from ..schemas_ops import Page
from ..services.operations import conflict, invalid, local_today, not_found, utcnow
from ..services.pm import create_task_for_plan, next_due, sync_equipment_dates, task_state
from .maintenance_equipment import _event, _technician

router = APIRouter(prefix="/api/maintenance", tags=["maintenance: preventive"])
DB = Annotated[Session, Depends(get_db)]
Reader = Annotated[User, Depends(require_maintenance(P.VIEW))]
Planner = Annotated[User, Depends(require_maintenance(P.MANAGE_PLANS))]
Worker = Annotated[User, Depends(require_maintenance(P.WORK_ON_ORDERS))]

COMPLIANCE_WINDOW_DAYS = 90
UNIT_WORD = {"days": "day", "weeks": "week", "months": "month"}


def _ref(e: Equipment) -> EquipmentRef:
    return EquipmentRef(id=e.id, code=e.code, name=e.name)


def _person(u: User | None) -> Person | None:
    return Person(id=u.id, full_name=u.full_name) if u else None


def _every(plan: MaintenancePlan) -> str:
    word = UNIT_WORD[plan.interval_unit.value]
    return f"every {plan.interval_value} {word}{'' if plan.interval_value == 1 else 's'}"


def _active_equipment(db: Session, equipment_id: int) -> Equipment:
    eq = db.get(Equipment, equipment_id)
    if eq is None:
        raise invalid("Equipment not found.")
    if eq.archived_at is not None:
        raise conflict(f"{eq.code} is archived. Restore it before scheduling maintenance.")
    return eq


def _task_out(t: MaintenanceTask, today: date) -> TaskOut:
    on_time = None
    if t.status is TaskStatus.COMPLETED and t.completed_on:
        on_time = t.completed_on <= t.due_on
    return TaskOut(
        id=t.id,
        plan_id=t.plan_id,
        equipment=_ref(t.equipment),
        title=t.title,
        instructions=t.plan.instructions if t.plan else None,
        due_on=t.due_on,
        status=t.status,
        state=task_state(t, today),
        days_until_due=(t.due_on - today).days,
        assigned_technician=_person(t.assigned_technician),
        completed_on=t.completed_on,
        completed_by=_person(t.completed_by),
        completed_on_time=on_time,
        work_notes=t.work_notes,
        cancel_reason=t.cancel_reason,
    )


def _open_task(db: Session, plan_id: int) -> MaintenanceTask | None:
    return db.scalar(
        select(MaintenanceTask).where(
            MaintenanceTask.plan_id == plan_id, MaintenanceTask.status == TaskStatus.SCHEDULED
        )
    )


def _plan_out(db: Session, p: MaintenancePlan, today: date) -> PlanOut:
    nxt = _open_task(db, p.id)
    last = db.scalar(
        select(func.max(MaintenanceTask.completed_on)).where(
            MaintenanceTask.plan_id == p.id, MaintenanceTask.status == TaskStatus.COMPLETED
        )
    )
    return PlanOut(
        id=p.id,
        equipment=_ref(p.equipment),
        title=p.title,
        instructions=p.instructions,
        interval_value=p.interval_value,
        interval_unit=p.interval_unit,
        schedule_basis=p.schedule_basis,
        start_on=p.start_on,
        assigned_technician=_person(p.assigned_technician),
        is_active=p.is_active,
        next_task=TaskBrief(
            id=nxt.id,
            due_on=nxt.due_on,
            state=task_state(nxt, today),
            days_until_due=(nxt.due_on - today).days,
        )
        if nxt
        else None,
        last_completed_on=last,
        created_at=p.created_at,
    )


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("This task was changed by someone else. Refresh and try again.") from None


def _get_plan(db: Session, plan_id: int) -> MaintenancePlan:
    p = db.get(MaintenancePlan, plan_id, options=[joinedload(MaintenancePlan.equipment)])
    if p is None:
        raise not_found("Plan")
    return p


def _get_task(db: Session, task_id: int, lock: bool = False) -> MaintenanceTask:
    query = select(MaintenanceTask).where(MaintenanceTask.id == task_id)
    if lock:  # serialise concurrent completions/cancellations of the same task
        query = query.with_for_update()
    t = db.scalar(query)
    if t is None:
        raise not_found("Task")
    return t


def _close_and_continue(db: Session, task: MaintenanceTask, today: date) -> MaintenanceTask | None:
    """After closing a plan task, schedule the plan's next one (if the plan is active)."""
    if task.plan_id is None:
        return None
    plan = db.get(MaintenancePlan, task.plan_id)
    if plan is None or not plan.is_active:
        return None
    db.flush()  # the closed task must leave the "one open task" index first
    return create_task_for_plan(db, plan, next_due(plan, task))


# ---------- summary ----------
@router.get("/pm/summary", response_model=PmSummary)
def pm_summary(db: DB, _: Reader) -> PmSummary:
    today = local_today()
    open_ = MaintenanceTask.status == TaskStatus.SCHEDULED
    active_eq = MaintenanceTask.equipment.has(Equipment.archived_at.is_(None))

    def count(*where) -> int:  # noqa: ANN002
        return db.scalar(select(func.count(MaintenanceTask.id)).where(*where)) or 0

    start = today - timedelta(days=COMPLIANCE_WINDOW_DAYS)
    in_window = [
        MaintenanceTask.due_on >= start,
        MaintenanceTask.due_on < today,
        MaintenanceTask.status != TaskStatus.CANCELLED,
    ]
    on_time = count(
        *in_window,
        MaintenanceTask.status == TaskStatus.COMPLETED,
        MaintenanceTask.completed_on <= MaintenanceTask.due_on,
    )
    late = count(
        *in_window,
        MaintenanceTask.status == TaskStatus.COMPLETED,
        MaintenanceTask.completed_on > MaintenanceTask.due_on,
    )
    due = count(*in_window)
    return PmSummary(
        overdue=count(open_, active_eq, MaintenanceTask.due_on < today),
        due_today=count(open_, active_eq, MaintenanceTask.due_on == today),
        due_next_7_days=count(
            open_,
            active_eq,
            MaintenanceTask.due_on > today,
            MaintenanceTask.due_on <= today + timedelta(days=7),
        ),
        open=count(open_, active_eq),
        active_plans=db.scalar(
            select(func.count(MaintenancePlan.id)).where(MaintenancePlan.is_active)
        )
        or 0,
        completed_last_30_days=count(
            MaintenanceTask.status == TaskStatus.COMPLETED,
            MaintenanceTask.completed_on > today - timedelta(days=30),
        ),
        compliance=PmCompliance(
            window_days=COMPLIANCE_WINDOW_DAYS,
            due=due,
            completed_on_time=on_time,
            completed_late=late,
            not_completed=due - on_time - late,
            pct=round(on_time / due * 100, 1) if due else None,
        ),
    )


# ---------- plans ----------
@router.get("/plans", response_model=Page[PlanOut])
def list_plans(
    db: DB,
    _: Reader,
    equipment_id: int | None = None,
    active: bool | None = True,
    q: str | None = Query(None, max_length=80),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[PlanOut]:
    query = select(MaintenancePlan).join(MaintenancePlan.equipment)
    if equipment_id is not None:
        query = query.where(MaintenancePlan.equipment_id == equipment_id)
    if active is not None:
        query = query.where(MaintenancePlan.is_active.is_(active))
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                MaintenancePlan.title.ilike(like),
                Equipment.code.ilike(like),
                Equipment.name.ilike(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.options(
            joinedload(MaintenancePlan.equipment), joinedload(MaintenancePlan.assigned_technician)
        )
        .order_by(Equipment.code, MaintenancePlan.title)
        .limit(limit)
        .offset(offset)
    )
    today = local_today()
    return Page(
        items=[_plan_out(db, p, today) for p in rows], total=total, limit=limit, offset=offset
    )


@router.post("/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(body: PlanIn, request: Request, db: DB, user: Planner) -> PlanOut:
    eq = _active_equipment(db, body.equipment_id)
    if eq.installed_on and body.start_on < eq.installed_on:
        raise invalid("The first due date cannot be before the equipment was installed.")
    tech = _technician(db, body.assigned_technician_id)
    plan = MaintenancePlan(**body.model_dump(), created_by_id=user.id)
    plan.assigned_technician = tech
    db.add(plan)
    db.flush()
    create_task_for_plan(db, plan, body.start_on)
    _event(
        db,
        eq,
        "pm_plan_created",
        f"Preventive plan added: {plan.title}, {_every(plan)} (first due {body.start_on:%d %b %Y})",
        user,
    )
    sync_equipment_dates(db, eq)
    record_event(
        db,
        action="pm_plan.created",
        entity_type="maintenance_plan",
        entity_id=plan.id,
        actor=user,
        request=request,
        summary=f"PM plan '{plan.title}' for {eq.code}",
    )
    _commit(db)
    return _plan_out(db, plan, local_today())


@router.patch("/plans/{plan_id}", response_model=PlanOut)
def update_plan(plan_id: int, body: PlanUpdate, request: Request, db: DB, user: Planner) -> PlanOut:
    plan = _get_plan(db, plan_id)
    sent = body.model_fields_set
    for field in sent & {"title", "interval_value", "interval_unit", "schedule_basis"}:
        if getattr(body, field) is None:
            raise invalid(f"{field.replace('_', ' ').capitalize()} cannot be empty.")
    changes: dict[str, object] = {}
    for field in sent - {"assigned_technician_id"}:
        value = getattr(body, field)
        if getattr(plan, field) != value:
            changes[field] = value.value if hasattr(value, "value") else value
            setattr(plan, field, value)
    if (
        "assigned_technician_id" in sent
        and body.assigned_technician_id != plan.assigned_technician_id
    ):
        old_id = plan.assigned_technician_id
        plan.assigned_technician = _technician(db, body.assigned_technician_id)
        changes["assigned_technician"] = (
            plan.assigned_technician.full_name if plan.assigned_technician else None
        )
        open_task = _open_task(db, plan.id)
        if open_task and open_task.assigned_technician_id == old_id:  # follow the plan
            open_task.assigned_technician_id = body.assigned_technician_id
    if "title" in changes and (open_task := _open_task(db, plan.id)):
        open_task.title = plan.title
    if changes:
        _event(
            db,
            plan.equipment,
            "pm_plan_updated",
            f"Preventive plan updated: {plan.title}",
            user,
            changes,
        )
        record_event(
            db,
            action="pm_plan.updated",
            entity_type="maintenance_plan",
            entity_id=plan.id,
            actor=user,
            request=request,
            summary=f"PM plan '{plan.title}' updated",
            changes=changes,
        )
        _commit(db)
    return _plan_out(db, plan, local_today())


@router.post("/plans/{plan_id}/deactivate", response_model=PlanOut)
def deactivate_plan(
    plan_id: int, body: TaskCancel, request: Request, db: DB, user: Planner
) -> PlanOut:
    plan = _get_plan(db, plan_id)
    if not plan.is_active:
        raise conflict("This plan is already inactive.")
    plan.is_active = False
    if open_task := _open_task(db, plan.id):
        open_task.status = TaskStatus.CANCELLED
        open_task.cancel_reason = f"Plan deactivated: {body.reason}"[:255]
        open_task.cancelled_at = utcnow()
        open_task.cancelled_by_id = user.id
    _event(
        db,
        plan.equipment,
        "pm_plan_deactivated",
        f"Preventive plan stopped: {plan.title} ({body.reason})",
        user,
    )
    sync_equipment_dates(db, plan.equipment)
    record_event(
        db,
        action="pm_plan.deactivated",
        entity_type="maintenance_plan",
        entity_id=plan.id,
        actor=user,
        request=request,
        summary=f"PM plan '{plan.title}' deactivated",
        changes={"reason": body.reason},
    )
    _commit(db)
    return _plan_out(db, plan, local_today())


@router.post("/plans/{plan_id}/activate", response_model=PlanOut)
def activate_plan(
    plan_id: int, body: PlanActivate, request: Request, db: DB, user: Planner
) -> PlanOut:
    plan = _get_plan(db, plan_id)
    if plan.is_active:
        raise conflict("This plan is already active.")
    _active_equipment(db, plan.equipment_id)
    today = local_today()
    if body.next_due_on < today:
        raise invalid("The next due date cannot be in the past.")
    plan.is_active = True
    create_task_for_plan(db, plan, body.next_due_on)
    _event(
        db,
        plan.equipment,
        "pm_plan_activated",
        f"Preventive plan resumed: {plan.title} (next due {body.next_due_on:%d %b %Y})",
        user,
    )
    sync_equipment_dates(db, plan.equipment)
    record_event(
        db,
        action="pm_plan.activated",
        entity_type="maintenance_plan",
        entity_id=plan.id,
        actor=user,
        request=request,
        summary=f"PM plan '{plan.title}' reactivated",
    )
    _commit(db)
    return _plan_out(db, plan, today)


# ---------- tasks ----------
VIEWS = "^(overdue|due_today|upcoming|open|completed|cancelled|all)$"


@router.get("/tasks", response_model=Page[TaskOut])
def list_tasks(
    db: DB,
    user: Reader,
    view: str = Query("open", pattern=VIEWS),
    equipment_id: int | None = None,
    technician_id: int | None = None,
    mine: bool = False,
    within_days: int | None = Query(None, ge=1, le=366, description="Open tasks due within N days"),
    q: str | None = Query(None, max_length=80),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[TaskOut]:
    today = local_today()
    query = select(MaintenanceTask).join(MaintenanceTask.equipment)
    scheduled = MaintenanceTask.status == TaskStatus.SCHEDULED
    if view in ("overdue", "due_today", "upcoming", "open"):
        # Open work on archived equipment is cancelled on archive; hide any stragglers anyway.
        query = query.where(scheduled, Equipment.archived_at.is_(None))
        if view == "overdue":
            query = query.where(MaintenanceTask.due_on < today)
        elif view == "due_today":
            query = query.where(MaintenanceTask.due_on == today)
        elif view == "upcoming":
            query = query.where(MaintenanceTask.due_on > today)
        if within_days:
            query = query.where(MaintenanceTask.due_on <= today + timedelta(days=within_days))
        order = [MaintenanceTask.due_on, Equipment.code]
    elif view == "completed":
        query = query.where(MaintenanceTask.status == TaskStatus.COMPLETED)
        order = [MaintenanceTask.completed_on.desc(), MaintenanceTask.id.desc()]
    elif view == "cancelled":
        query = query.where(MaintenanceTask.status == TaskStatus.CANCELLED)
        order = [MaintenanceTask.cancelled_at.desc()]
    else:
        order = [MaintenanceTask.due_on.desc(), MaintenanceTask.id.desc()]
    if equipment_id is not None:
        query = query.where(MaintenanceTask.equipment_id == equipment_id)
    if mine:
        query = query.where(MaintenanceTask.assigned_technician_id == user.id)
    elif technician_id is not None:
        query = query.where(MaintenanceTask.assigned_technician_id == technician_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                MaintenanceTask.title.ilike(like),
                Equipment.code.ilike(like),
                Equipment.name.ilike(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.options(
            joinedload(MaintenanceTask.equipment),
            joinedload(MaintenanceTask.plan),
            joinedload(MaintenanceTask.assigned_technician),
            joinedload(MaintenanceTask.completed_by),
        )
        .order_by(*order)
        .limit(limit)
        .offset(offset)
    )
    return Page(items=[_task_out(t, today) for t in rows], total=total, limit=limit, offset=offset)


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def schedule_task(body: TaskIn, request: Request, db: DB, user: Planner) -> TaskOut:
    eq = _active_equipment(db, body.equipment_id)
    today = local_today()
    if body.due_on < today:
        raise invalid("A new service cannot be scheduled in the past.")
    tech = _technician(db, body.assigned_technician_id)
    task = MaintenanceTask(
        equipment_id=eq.id,
        title=body.title,
        due_on=body.due_on,
        assigned_technician_id=tech.id if tech else None,
    )
    db.add(task)
    db.flush()
    _event(
        db,
        eq,
        "pm_task_scheduled",
        f"Service scheduled: {task.title} (due {task.due_on:%d %b %Y})",
        user,
    )
    sync_equipment_dates(db, eq)
    record_event(
        db,
        action="pm_task.scheduled",
        entity_type="maintenance_task",
        entity_id=task.id,
        actor=user,
        request=request,
        summary=f"Service '{task.title}' scheduled for {eq.code}",
    )
    _commit(db)
    db.refresh(task)
    return _task_out(task, today)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, request: Request, db: DB, user: Planner) -> TaskOut:
    task = _get_task(db, task_id, lock=True)
    if task.status is not TaskStatus.SCHEDULED:
        raise conflict("Only open tasks can be rescheduled or reassigned.")
    today = local_today()
    sent = body.model_fields_set
    changes: dict[str, object] = {}
    if "due_on" in sent:
        if body.due_on is None:
            raise invalid("Due date cannot be empty.")
        if body.due_on != task.due_on:
            if body.due_on < today:
                raise invalid("A task cannot be rescheduled into the past.")
            changes["due_on"] = {"from": task.due_on.isoformat(), "to": body.due_on.isoformat()}
            task.due_on = body.due_on
    if (
        "assigned_technician_id" in sent
        and body.assigned_technician_id != task.assigned_technician_id
    ):
        tech = _technician(db, body.assigned_technician_id)
        task.assigned_technician_id = body.assigned_technician_id
        changes["assigned_technician"] = tech.full_name if tech else None
    if changes:
        summary = (
            f"Service rescheduled: {task.title} to {task.due_on:%d %b %Y}"
            if "due_on" in changes
            else f"Service reassigned: {task.title}"
        )
        _event(db, task.equipment, "pm_task_updated", summary, user, changes)
        sync_equipment_dates(db, task.equipment)
        record_event(
            db,
            action="pm_task.updated",
            entity_type="maintenance_task",
            entity_id=task.id,
            actor=user,
            request=request,
            summary=summary,
            changes=changes,
        )
        _commit(db)
        db.refresh(task)
    return _task_out(task, today)


@router.post("/tasks/{task_id}/complete", response_model=TaskOut)
def complete_task(
    task_id: int, body: TaskComplete, request: Request, db: DB, user: Worker
) -> TaskOut:
    task = _get_task(db, task_id, lock=True)
    if task.status is not TaskStatus.SCHEDULED:
        raise conflict(f"This task is already {task.status.value}.")
    today = local_today()
    if body.completed_on > today:
        raise invalid("The completion date cannot be in the future.")
    eq = task.equipment
    if eq.installed_on and body.completed_on < eq.installed_on:
        raise invalid("The completion date cannot be before the equipment was installed.")
    task.status = TaskStatus.COMPLETED
    task.completed_on = body.completed_on
    task.completed_at = utcnow()
    task.completed_by_id = user.id
    task.work_notes = body.work_notes
    nxt = _close_and_continue(db, task, today)
    late = body.completed_on > task.due_on
    summary = f"Preventive maintenance done: {task.title}" + (" (late)" if late else "")
    _event(
        db,
        eq,
        "pm_task_completed",
        summary,
        user,
        {
            "due_on": task.due_on.isoformat(),
            "completed_on": body.completed_on.isoformat(),
            "next_due_on": nxt.due_on.isoformat() if nxt else None,
        },
    )
    sync_equipment_dates(db, eq)
    record_event(
        db,
        action="pm_task.completed",
        entity_type="maintenance_task",
        entity_id=task.id,
        actor=user,
        request=request,
        summary=f"{eq.code}: {task.title} completed",
    )
    _commit(db)
    db.refresh(task)
    return _task_out(task, today)


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
def cancel_task(task_id: int, body: TaskCancel, request: Request, db: DB, user: Planner) -> TaskOut:
    task = _get_task(db, task_id, lock=True)
    if task.status is not TaskStatus.SCHEDULED:
        raise conflict(f"This task is already {task.status.value}.")
    today = local_today()
    task.status = TaskStatus.CANCELLED
    task.cancel_reason = body.reason
    task.cancelled_at = utcnow()
    task.cancelled_by_id = user.id
    nxt = _close_and_continue(db, task, today)
    eq = task.equipment
    _event(
        db,
        eq,
        "pm_task_cancelled",
        f"Service cancelled: {task.title} ({body.reason})",
        user,
        {"next_due_on": nxt.due_on.isoformat() if nxt else None},
    )
    sync_equipment_dates(db, eq)
    record_event(
        db,
        action="pm_task.cancelled",
        entity_type="maintenance_task",
        entity_id=task.id,
        actor=user,
        request=request,
        summary=f"{eq.code}: {task.title} cancelled",
        changes={"reason": body.reason},
    )
    _commit(db)
    db.refresh(task)
    return _task_out(task, today)
