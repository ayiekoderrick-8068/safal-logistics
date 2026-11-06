"""Equipment register (Maintenance workspace).

Reading needs any maintenance role; adding, editing, archiving and restoring need
`equipment.manage` (managers and planners). Every change is written to the asset's own
history and to the audit log.
"""

from datetime import date
from enum import Enum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..audit import record_event
from ..db import get_db
from ..deps import require_maintenance
from ..maintenance_permissions import MaintenancePermission as P
from ..models import MaintenanceRole, Role, User, UserStatus
from ..models_maintenance import (
    Breakdown,
    Equipment,
    EquipmentCategory,
    EquipmentEvent,
    EquipmentStatus,
    MaintenancePlan,
    MaintenanceTask,
    TaskStatus,
    WorkOrder,
    WorkOrderStatus,
)
from ..schemas_maintenance import (
    EquipmentDetail,
    EquipmentEventOut,
    EquipmentIn,
    EquipmentOptions,
    EquipmentOut,
    EquipmentSummary,
    EquipmentUpdate,
    Person,
    Technician,
    check_service_dates,
)
from ..schemas_ops import Page
from ..services.operations import (
    CONSTRAINT_MESSAGES,
    commit,
    conflict,
    invalid,
    local_today,
    not_found,
    utcnow,
)
from ..services.pm import is_plan_driven, sync_equipment_dates

router = APIRouter(prefix="/api/maintenance", tags=["maintenance: equipment"])
DB = Annotated[Session, Depends(get_db)]
Reader = Annotated[User, Depends(require_maintenance(P.VIEW))]
Manager = Annotated[User, Depends(require_maintenance(P.MANAGE_EQUIPMENT))]

DUE_SOON_DAYS = 14
# Roles that can be the responsible technician for an asset.
TECHNICIAN_ROLES = (MaintenanceRole.TECHNICIAN, MaintenanceRole.PLANNER, MaintenanceRole.MANAGER)
# Readable 409 messages for this module's unique constraints (used by `commit`).
CONSTRAINT_MESSAGES.update(
    {
        "uq_equipment_code": "That Equipment ID is already registered.",
        "uq_equipment_serial_number": "That serial number is already registered to other "
        "equipment.",
    }
)


# ---------- helpers ----------
def service_state(next_on: date | None, today: date) -> tuple[str, int | None]:
    if next_on is None:
        return "not_scheduled", None
    days = (next_on - today).days
    if days < 0:
        return "overdue", days
    return ("due_soon" if days <= DUE_SOON_DAYS else "scheduled"), days


def _person(u: User | None) -> Person | None:
    return Person(id=u.id, full_name=u.full_name) if u else None


def _out(eq: Equipment, today: date) -> dict[str, Any]:
    state, days = service_state(eq.next_service_on, today)
    data = {c: getattr(eq, c) for c in EquipmentOut.model_fields if hasattr(eq, c)}
    data.update(
        assigned_technician=_person(eq.assigned_technician),
        service_state=state,
        days_until_service=days,
    )
    return data


def _get(db: Session, equipment_id: int) -> Equipment:
    eq = db.get(Equipment, equipment_id, options=[joinedload(Equipment.assigned_technician)])
    if eq is None:
        raise not_found("Equipment")
    return eq


def _technician(db: Session, user_id: int | None) -> User | None:
    if user_id is None:
        return None
    u = db.get(User, user_id)
    eligible = (
        u is not None
        and u.status == UserStatus.ACTIVE
        and (u.role == Role.ADMIN or u.maintenance_role in TECHNICIAN_ROLES)
    )
    if not eligible:
        raise invalid("Choose an active technician, planner or maintenance manager.")
    return u


def _not_future(value: date | None, label: str, today: date) -> None:
    if value and value > today:
        raise invalid(f"The {label} cannot be in the future.")


def _plain(v: object) -> object:
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, date):
        return v.isoformat()
    return v


def _event(
    db: Session, eq: Equipment, kind: str, summary: str, actor: User, changes: dict | None = None
) -> None:
    db.add(
        EquipmentEvent(
            equipment_id=eq.id, kind=kind, summary=summary[:255], changes=changes, actor_id=actor.id
        )
    )


def _commit(db: Session) -> None:
    commit(db, "That Equipment ID or serial number is already registered.")


def _flush(db: Session) -> None:
    """Flush, turning a unique-constraint race into the same readable 409 as `commit`."""
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        raise conflict(CONSTRAINT_MESSAGES.get(name or "", "That record already exists.")) from None


def _serial_free(db: Session, serial: str | None, exclude_id: int | None = None) -> None:
    if not serial:
        return
    query = select(Equipment.id).where(func.upper(Equipment.serial_number) == serial.upper())
    if exclude_id is not None:
        query = query.where(Equipment.id != exclude_id)
    if db.scalar(query):
        raise conflict(CONSTRAINT_MESSAGES["uq_equipment_serial_number"])


# ---------- read ----------
@router.get("/equipment/summary", response_model=EquipmentSummary)
def summary(db: DB, _: Reader) -> EquipmentSummary:
    today = local_today()
    active = Equipment.archived_at.is_(None)
    by_status = dict(
        db.execute(
            select(Equipment.status, func.count(Equipment.id))
            .where(active)
            .group_by(Equipment.status)
        ).all()
    )
    overdue = db.scalar(
        select(func.count(Equipment.id)).where(active, Equipment.next_service_on < today)
    )
    due_soon = db.scalar(
        select(func.count(Equipment.id)).where(
            active,
            Equipment.next_service_on >= today,
            Equipment.next_service_on <= date.fromordinal(today.toordinal() + DUE_SOON_DAYS),
        )
    )
    archived = db.scalar(select(func.count(Equipment.id)).where(Equipment.archived_at.is_not(None)))
    return EquipmentSummary(
        total=sum(by_status.values()),
        operational=by_status.get(EquipmentStatus.OPERATIONAL, 0),
        under_maintenance=by_status.get(EquipmentStatus.UNDER_MAINTENANCE, 0),
        out_of_service=by_status.get(EquipmentStatus.OUT_OF_SERVICE, 0),
        service_overdue=overdue or 0,
        service_due_soon=due_soon or 0,
        archived=archived or 0,
        due_soon_days=DUE_SOON_DAYS,
    )


@router.get("/equipment/options", response_model=EquipmentOptions)
def options(db: DB, _: Reader) -> EquipmentOptions:
    def distinct(col: Any) -> list[str]:
        return list(db.scalars(select(col).where(col.is_not(None)).distinct().order_by(col)))

    techs = db.scalars(
        select(User)
        .where(
            User.status == UserStatus.ACTIVE,
            or_(User.role == Role.ADMIN, User.maintenance_role.in_(TECHNICIAN_ROLES)),
        )
        .order_by(User.full_name)
    )
    return EquipmentOptions(
        facilities=distinct(Equipment.facility),
        departments=distinct(Equipment.department),
        locations=distinct(Equipment.location),
        technicians=[
            Technician(
                id=u.id, full_name=u.full_name, maintenance_role=u.effective_maintenance_role
            )
            for u in techs
        ],
    )


@router.get("/equipment", response_model=Page[EquipmentOut])
def list_equipment(
    db: DB,
    _: Reader,
    q: str | None = Query(
        None, max_length=80, description="ID, name, serial, make, model, location"
    ),
    category: EquipmentCategory | None = None,
    status_: EquipmentStatus | None = Query(None, alias="status"),
    facility: str | None = Query(None, max_length=80),
    service: str | None = Query(None, pattern="^(overdue|due_soon|not_scheduled)$"),
    archived: bool = False,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[EquipmentOut]:
    today = local_today()
    query = select(Equipment).where(
        Equipment.archived_at.is_not(None) if archived else Equipment.archived_at.is_(None)
    )
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                Equipment.code.ilike(like),
                Equipment.name.ilike(like),
                Equipment.serial_number.ilike(like),
                Equipment.manufacturer.ilike(like),
                Equipment.model.ilike(like),
                Equipment.location.ilike(like),
            )
        )
    if category:
        query = query.where(Equipment.category == category)
    if status_:
        query = query.where(Equipment.status == status_)
    if facility:
        query = query.where(Equipment.facility == facility)
    if service == "overdue":
        query = query.where(Equipment.next_service_on < today)
    elif service == "due_soon":
        query = query.where(
            Equipment.next_service_on >= today,
            Equipment.next_service_on <= date.fromordinal(today.toordinal() + DUE_SOON_DAYS),
        )
    elif service == "not_scheduled":
        query = query.where(Equipment.next_service_on.is_(None))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.options(joinedload(Equipment.assigned_technician))
        .order_by(Equipment.code)
        .limit(limit)
        .offset(offset)
    )
    return Page(
        items=[EquipmentOut(**_out(e, today)) for e in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/equipment/{equipment_id}", response_model=EquipmentDetail)
def get_equipment(equipment_id: int, db: DB, _: Reader) -> EquipmentDetail:
    eq = _get(db, equipment_id)
    events = db.scalars(
        select(EquipmentEvent)
        .options(joinedload(EquipmentEvent.actor))
        .where(EquipmentEvent.equipment_id == eq.id)
        .order_by(EquipmentEvent.occurred_at.desc(), EquipmentEvent.id.desc())
        .limit(200)
    )
    history = [
        EquipmentEventOut(
            id=e.id,
            occurred_at=e.occurred_at,
            kind=e.kind,
            summary=e.summary,
            changes=e.changes,
            actor=_person(e.actor),
        )
        for e in events
    ]
    return EquipmentDetail(
        **_out(eq, local_today()), history=history, schedule_managed=is_plan_driven(db, eq.id)
    )


# ---------- write ----------
@router.post("/equipment", response_model=EquipmentOut, status_code=status.HTTP_201_CREATED)
def create_equipment(body: EquipmentIn, request: Request, db: DB, user: Manager) -> EquipmentOut:
    today = local_today()
    _not_future(body.installed_on, "installation date", today)
    _not_future(body.last_service_on, "last service date", today)
    tech = _technician(db, body.assigned_technician_id)
    if db.scalar(select(Equipment.id).where(func.upper(Equipment.code) == body.code)):
        raise conflict(CONSTRAINT_MESSAGES["uq_equipment_code"])
    _serial_free(db, body.serial_number)
    eq = Equipment(**body.model_dump())
    eq.assigned_technician = tech
    db.add(eq)
    _flush(db)
    _event(db, eq, "created", f"{eq.code} registered ({eq.status.value.replace('_', ' ')})", user)
    record_event(
        db,
        action="equipment.created",
        entity_type="equipment",
        entity_id=eq.id,
        actor=user,
        request=request,
        summary=f"Equipment {eq.code} registered",
    )
    _commit(db)
    return EquipmentOut(**_out(eq, today))


@router.patch("/equipment/{equipment_id}", response_model=EquipmentOut)
def update_equipment(
    equipment_id: int, body: EquipmentUpdate, request: Request, db: DB, user: Manager
) -> EquipmentOut:
    eq = _get(db, equipment_id)
    if eq.archived_at is not None:
        raise conflict("Archived equipment cannot be edited. Restore it first.")
    today = local_today()
    sent = body.model_fields_set
    required = {"name", "category", "facility", "status"}
    for field in sent & required:
        if getattr(body, field) is None:
            raise invalid(f"{field.replace('_', ' ').capitalize()} cannot be empty.")

    new = {f: getattr(body, f) for f in sent}
    service_edits = {
        f for f in ("last_service_on", "next_service_on") if f in new and new[f] != getattr(eq, f)
    }
    if service_edits and is_plan_driven(db, eq.id):
        raise conflict(
            "Service dates for this equipment are set by its preventive-maintenance schedule. "
            "Complete or reschedule its tasks instead."
        )
    installed = new.get("installed_on", eq.installed_on)
    last = new.get("last_service_on", eq.last_service_on)
    nxt = new.get("next_service_on", eq.next_service_on)
    _not_future(installed, "installation date", today)
    _not_future(last, "last service date", today)
    try:
        check_service_dates(installed, last, nxt)
    except ValueError as exc:
        raise invalid(str(exc)) from None

    changes: dict[str, dict[str, object]] = {}
    for field, value in new.items():
        if field == "assigned_technician_id":
            continue
        old = getattr(eq, field)
        if old != value:
            changes[field] = {"from": _plain(old), "to": _plain(value)}
            setattr(eq, field, value)

    if "serial_number" in sent:
        _serial_free(db, body.serial_number, exclude_id=eq.id)
    tech_changed = False
    new_tech = body.assigned_technician_id
    if "assigned_technician_id" in sent and new_tech != eq.assigned_technician_id:
        before = eq.assigned_technician.full_name if eq.assigned_technician else None
        eq.assigned_technician = _technician(db, body.assigned_technician_id)
        after = eq.assigned_technician.full_name if eq.assigned_technician else None
        changes["assigned_technician"] = {"from": before, "to": after}
        tech_changed = True

    if not changes:
        return EquipmentOut(**_out(eq, today))
    if "status" in changes:
        kind, summary = "status_changed", f"Status changed to {eq.status.value.replace('_', ' ')}"
    elif tech_changed and len(changes) == 1:
        after = changes["assigned_technician"]["to"]
        kind, summary = (
            "technician_assigned",
            (f"Assigned to {after}" if after else "Technician unassigned"),
        )
    else:
        kind, summary = (
            "updated",
            "Details updated: " + ", ".join(f.replace("_", " ") for f in changes),
        )
    _event(db, eq, kind, summary, user, changes)
    record_event(
        db,
        action="equipment.updated",
        entity_type="equipment",
        entity_id=eq.id,
        actor=user,
        request=request,
        summary=f"Equipment {eq.code}: {summary}",
        changes=changes,
    )
    _commit(db)
    return EquipmentOut(**_out(eq, today))


class ArchiveIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


@router.post("/equipment/{equipment_id}/archive", response_model=EquipmentOut)
def archive_equipment(
    equipment_id: int, body: ArchiveIn, request: Request, db: DB, user: Manager
) -> EquipmentOut:
    eq = _get(db, equipment_id)
    if eq.archived_at is not None:
        raise conflict("This equipment is already archived.")
    # Repairs in flight are never silently cancelled: finish or cancel them first.
    open_work = db.scalar(
        select(func.count(WorkOrder.id)).where(
            WorkOrder.equipment_id == eq.id,
            WorkOrder.status.not_in((WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED)),
        )
    )
    open_breakdown = db.scalar(
        select(func.count(Breakdown.id)).where(
            Breakdown.equipment_id == eq.id, Breakdown.restored_at.is_(None)
        )
    )
    if open_work or open_breakdown:
        raise conflict(
            f"{eq.code} has {open_work} open work order(s) and {open_breakdown} open "
            "breakdown(s). Complete or cancel them before archiving."
        )
    eq.archived_at = utcnow()
    eq.archived_by_id = user.id
    reason = " ".join(body.reason.split())
    # Archived equipment gets no further maintenance: stop its plans, cancel open tasks.
    stopped = 0
    for plan in db.scalars(
        select(MaintenancePlan).where(
            MaintenancePlan.equipment_id == eq.id, MaintenancePlan.is_active
        )
    ):
        plan.is_active = False
        stopped += 1
    cancelled = 0
    for task in db.scalars(
        select(MaintenanceTask)
        .where(
            MaintenanceTask.equipment_id == eq.id, MaintenanceTask.status == TaskStatus.SCHEDULED
        )
        .with_for_update()
    ):
        task.status = TaskStatus.CANCELLED
        task.cancel_reason = f"Equipment archived: {reason}"[:255]
        task.cancelled_at = eq.archived_at
        task.cancelled_by_id = user.id
        cancelled += 1
    if stopped or cancelled:
        sync_equipment_dates(db, eq)
    _event(
        db,
        eq,
        "archived",
        f"Archived: {reason}",
        user,
        {"reason": reason, "plans_stopped": stopped, "tasks_cancelled": cancelled},
    )
    record_event(
        db,
        action="equipment.archived",
        entity_type="equipment",
        entity_id=eq.id,
        actor=user,
        request=request,
        summary=f"Equipment {eq.code} archived",
        changes={"reason": reason},
    )
    _commit(db)
    return EquipmentOut(**_out(eq, local_today()))


@router.post("/equipment/{equipment_id}/restore", response_model=EquipmentOut)
def restore_equipment(equipment_id: int, request: Request, db: DB, user: Manager) -> EquipmentOut:
    eq = _get(db, equipment_id)
    if eq.archived_at is None:
        raise conflict("This equipment is not archived.")
    eq.archived_at = None
    eq.archived_by_id = None
    _event(db, eq, "restored", "Restored to the active register", user)
    record_event(
        db,
        action="equipment.restored",
        entity_type="equipment",
        entity_id=eq.id,
        actor=user,
        request=request,
        summary=f"Equipment {eq.code} restored",
    )
    _commit(db)
    return EquipmentOut(**_out(eq, local_today()))
