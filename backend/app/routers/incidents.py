"""Delay incident management for loading and dispatch operations.

Duration is derived from stored timestamps: (resolved_at or now) - occurred_at.
"""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..audit import record_event
from ..db import get_db
from ..deps import get_current_user, require_roles
from ..models import (
    DelayCause,
    DelayIncident,
    Dispatch,
    DispatchStatus,
    IncidentStatus,
    LoadingSchedule,
    Role,
    Truck,
    User,
    UserStatus,
)
from ..schemas_incidents import (
    AssignableUser,
    CauseCount,
    IncidentIn,
    IncidentOut,
    IncidentSummary,
    IncidentUpdate,
)
from ..schemas_ops import Page, Ref
from ..services.app_settings import is_sample_data
from ..services.operations import commit, conflict, invalid, not_found, not_in_future, utcnow

router = APIRouter(prefix="/api", tags=["incidents"])
DB = Annotated[Session, Depends(get_db)]
Reader = Annotated[User, Depends(get_current_user)]
# Any operational staff member may report and work delays; viewers are read-only.
Staff = Annotated[
    User, Depends(require_roles(Role.OPERATIONS, Role.FLEET_MANAGER, Role.COMPLIANCE))
]

_OPTIONS = (
    joinedload(DelayIncident.dispatch).joinedload(Dispatch.truck),
    joinedload(DelayIncident.dispatch).joinedload(Dispatch.route),
    joinedload(DelayIncident.schedule).joinedload(LoadingSchedule.truck),
    joinedload(DelayIncident.schedule).joinedload(LoadingSchedule.bay),
    joinedload(DelayIncident.assigned_to),
    joinedload(DelayIncident.reported_by),
)
UNRESOLVED = (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING, IncidentStatus.IN_PROGRESS)


def duration_minutes(started: datetime, resolved: datetime | None, now: datetime) -> int:
    return max(0, int(((resolved or now) - started).total_seconds() // 60))


def incident_out(i: DelayIncident, now: datetime) -> IncidentOut:
    if i.dispatch is not None:
        truck = i.dispatch.truck
        source, operation, load_ref = (
            "dispatch",
            f"{i.dispatch.load_ref} · {i.dispatch.route.label}",
            i.dispatch.load_ref,
        )
    else:
        truck = i.schedule.truck if i.schedule else None
        source, operation, load_ref = (
            "loading",
            f"Loading at {i.schedule.bay.name}" if i.schedule else "Loading",
            None,
        )
    return IncidentOut(
        id=i.id,
        source=source,  # type: ignore[arg-type]
        truck=Ref(id=truck.id, label=truck.registration) if truck else None,
        operation=operation,
        load_ref=load_ref,
        schedule_id=i.schedule_id,
        dispatch_id=i.dispatch_id,
        cause=i.cause,
        status=i.status,
        started_at=i.occurred_at,
        resolved_at=i.resolved_at,
        duration_minutes=duration_minutes(i.occurred_at, i.resolved_at, now),
        is_ongoing=i.resolved_at is None,
        impact_minutes=i.delay_minutes,
        description=i.description,
        resolution_notes=i.resolution_notes,
        assigned_to=Ref(id=i.assigned_to.id, label=i.assigned_to.full_name)
        if i.assigned_to
        else None,
        reported_by=i.reported_by.full_name if i.reported_by else None,
        created_at=i.created_at,
    )


def _get(db: Session, incident_id: int) -> DelayIncident:
    i = db.get(DelayIncident, incident_id, options=list(_OPTIONS))
    if i is None:
        raise not_found("Delay incident")
    return i


def _assignee(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE or user.role == Role.VIEWER:
        raise invalid("Assignee must be an active staff member (not a read-only viewer).")
    return user


@router.get("/users/assignable", response_model=list[AssignableUser])
def assignable_users(db: DB, _: Reader) -> list[AssignableUser]:
    rows = db.scalars(
        select(User)
        .where(User.status == UserStatus.ACTIVE, User.role != Role.VIEWER)
        .order_by(User.full_name)
    )
    return [AssignableUser(id=u.id, label=u.full_name, role=u.role) for u in rows]


@router.get("/incidents", response_model=Page[IncidentOut])
def list_incidents(
    db: DB,
    user: Reader,
    status_: str | None = Query(
        None, alias="status", pattern="^(open|investigating|in_progress|resolved|unresolved)$"
    ),
    cause: DelayCause | None = None,
    source: str | None = Query(None, pattern="^(loading|dispatch)$"),
    mine: bool = False,
    q: str | None = Query(None, max_length=80),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[IncidentOut]:
    query = (
        select(DelayIncident)
        .outerjoin(Dispatch, Dispatch.id == DelayIncident.dispatch_id)
        .outerjoin(LoadingSchedule, LoadingSchedule.id == DelayIncident.schedule_id)
        .outerjoin(Truck, Truck.id == func.coalesce(Dispatch.truck_id, LoadingSchedule.truck_id))
    )
    if status_ == "unresolved":
        query = query.where(DelayIncident.status.in_(UNRESOLVED))
    elif status_:
        query = query.where(DelayIncident.status == IncidentStatus(status_))
    if cause:
        query = query.where(DelayIncident.cause == cause)
    if source == "dispatch":
        query = query.where(DelayIncident.dispatch_id.is_not(None))
    elif source == "loading":
        query = query.where(DelayIncident.dispatch_id.is_(None))
    if mine:
        query = query.where(DelayIncident.assigned_to_id == user.id)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                Truck.registration.ilike(like),
                Dispatch.load_ref.ilike(like),
                DelayIncident.description.ilike(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.options(*_OPTIONS)
        .order_by(DelayIncident.occurred_at.desc(), DelayIncident.id.desc())
        .limit(limit)
        .offset(offset)
    ).unique()
    now = utcnow()
    return Page(items=[incident_out(i, now) for i in rows], total=total, limit=limit, offset=offset)


@router.get("/incidents/summary", response_model=IncidentSummary)
def summary(db: DB, _: Reader) -> IncidentSummary:
    now = utcnow()
    unresolved = db.execute(
        select(
            func.count(DelayIncident.id),
            func.count(DelayIncident.id).filter(DelayIncident.assigned_to_id.is_(None)),
            func.min(DelayIncident.occurred_at),
        ).where(DelayIncident.status.in_(UNRESOLVED))
    ).one()
    resolution = func.extract("epoch", DelayIncident.resolved_at - DelayIncident.occurred_at) / 60
    resolved_7d, avg_res = db.execute(
        select(
            func.count(DelayIncident.id).filter(
                DelayIncident.resolved_at >= now - timedelta(days=7)
            ),
            func.avg(resolution).filter(DelayIncident.resolved_at >= now - timedelta(days=30)),
        ).where(DelayIncident.status == IncidentStatus.RESOLVED)
    ).one()
    impact_7d = db.scalar(
        select(func.coalesce(func.sum(DelayIncident.delay_minutes), 0)).where(
            DelayIncident.occurred_at >= now - timedelta(days=7)
        )
    )
    by_cause = db.execute(
        select(
            DelayIncident.cause,
            func.count(DelayIncident.id),
            func.coalesce(func.sum(DelayIncident.delay_minutes), 0),
        )
        .where(DelayIncident.occurred_at >= now - timedelta(days=30))
        .group_by(DelayIncident.cause)
        .order_by(func.count(DelayIncident.id).desc())
    ).all()
    return IncidentSummary(
        unresolved=unresolved[0],
        unassigned=unresolved[1],
        resolved_7d=resolved_7d,
        avg_resolution_minutes_30d=round(float(avg_res), 1) if avg_res is not None else None,
        impact_minutes_7d=int(impact_7d or 0),
        oldest_unresolved_minutes=duration_minutes(unresolved[2], None, now)
        if unresolved[2]
        else None,
        by_cause_30d=[CauseCount(cause=c, count=n, impact_minutes=int(m)) for c, n, m in by_cause],
        sample_data=is_sample_data(db),
    )


@router.post("/incidents", response_model=IncidentOut, status_code=status.HTTP_201_CREATED)
def report_incident(body: IncidentIn, request: Request, db: DB, user: Staff) -> IncidentOut:
    started = not_in_future(body.started_at or utcnow(), "Delay start")
    if body.dispatch_id is not None:
        dispatch = db.get(Dispatch, body.dispatch_id)
        if dispatch is None:
            raise invalid("Dispatch not found")
        if started < dispatch.dispatched_at - timedelta(hours=24):
            raise invalid("Delay start is too long before the dispatch.")
        if dispatch.status == DispatchStatus.IN_TRANSIT:
            dispatch.is_delayed = True
        label = dispatch.load_ref
    else:
        schedule = db.get(LoadingSchedule, body.schedule_id)
        if schedule is None:
            raise invalid("Loading schedule not found")
        label = f"loading schedule {schedule.id}"
    assignee = _assignee(db, body.assigned_to_id) if body.assigned_to_id else None
    incident = DelayIncident(
        dispatch_id=body.dispatch_id,
        schedule_id=body.schedule_id,
        cause=body.cause,
        delay_minutes=body.impact_minutes,
        description=body.description.strip(),
        occurred_at=started,
        status=IncidentStatus.OPEN,
        reported_by_id=user.id,
        assigned_to_id=assignee.id if assignee else None,
    )
    db.add(incident)
    db.flush()
    record_event(
        db,
        action="incident.reported",
        entity_type="delay_incident",
        entity_id=incident.id,
        actor=user,
        request=request,
        summary=f"Delay reported for {label}: {body.cause.value.replace('_', ' ')}",
        changes=body.model_dump(mode="json"),
    )
    commit(db)
    return incident_out(_get(db, incident.id), utcnow())


@router.patch("/incidents/{incident_id}", response_model=IncidentOut)
def update_incident(
    incident_id: int, body: IncidentUpdate, request: Request, db: DB, user: Staff
) -> IncidentOut:
    i = _get(db, incident_id)
    fields = body.model_fields_set
    changes: dict[str, object] = {}
    now = utcnow()

    if "assigned_to_id" in fields and body.assigned_to_id != i.assigned_to_id:
        i.assigned_to = _assignee(db, body.assigned_to_id) if body.assigned_to_id else None
        changes["assigned_to"] = i.assigned_to.full_name if i.assigned_to else None
    if body.cause is not None and body.cause != i.cause:
        changes["cause"] = body.cause
        i.cause = body.cause
    if body.impact_minutes is not None and body.impact_minutes != i.delay_minutes:
        changes["impact_minutes"] = body.impact_minutes
        i.delay_minutes = body.impact_minutes
    if "resolution_notes" in fields:
        i.resolution_notes = (body.resolution_notes or "").strip() or None

    target = body.status or i.status
    if target == IncidentStatus.RESOLVED:
        resolved_at = body.resolved_at or (
            i.resolved_at if i.status == IncidentStatus.RESOLVED else now
        )
        not_in_future(resolved_at, "Resolution time")
        if resolved_at < i.occurred_at:
            raise invalid("Resolution time cannot be before the delay started.")
        if not i.resolution_notes:
            raise invalid("Add resolution notes describing how the delay was resolved.")
        if i.status != IncidentStatus.RESOLVED or resolved_at != i.resolved_at:
            changes["resolved_at"] = resolved_at.isoformat()
        i.resolved_at = resolved_at
    elif body.resolved_at is not None:
        raise invalid("A resolution time can only be set when resolving the incident.")
    else:
        if i.status == IncidentStatus.RESOLVED:
            changes["reopened"] = True
        i.resolved_at = None
    if target != i.status:
        changes["status"] = f"{i.status.value} -> {target.value}"
        i.status = target

    if not changes and "resolution_notes" not in fields:
        raise conflict("Nothing to update.")
    action = (
        "incident.resolved"
        if target == IncidentStatus.RESOLVED and "status" in changes
        else "incident.reopened"
        if changes.get("reopened")
        else "incident.updated"
    )
    record_event(
        db,
        action=action,
        entity_type="delay_incident",
        entity_id=i.id,
        actor=user,
        request=request,
        summary=f"Delay incident #{i.id} {action.split('.')[1]}",
        changes={k: str(v) for k, v in changes.items()} or {"resolution_notes": "updated"},
    )
    commit(db)
    return incident_out(_get(db, i.id), utcnow())
