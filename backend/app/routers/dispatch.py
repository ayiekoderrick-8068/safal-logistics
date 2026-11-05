from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..audit import record_event
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user, require_roles
from ..models import (
    DelayIncident,
    Dispatch,
    DispatchStatus,
    IncidentStatus,
    LoadingSchedule,
    Role,
    Route,
    ScheduleStatus,
    Truck,
    TruckStatus,
    User,
)
from ..schemas_ops import (
    DeliverIn,
    DispatchHourBucket,
    DispatchIn,
    DispatchOut,
    DispatchOverview,
    FlagDelayIn,
    Page,
    ScheduleOut,
)
from ..services.app_settings import is_sample_data
from ..services.compliance import dispatch_blockers
from ..services.dashboard import local_bounds
from ..services.operations import (
    commit,
    conflict,
    default_target,
    dispatch_out,
    invalid,
    latest_delay_causes,
    local_today,
    next_load_ref,
    not_found,
    not_in_future,
    schedule_out,
    utcnow,
)
from ..services.turnaround import percent

router = APIRouter(prefix="/api", tags=["dispatch"])
OpsWriter = Annotated[User, Depends(require_roles(Role.OPERATIONS))]
Reader = Annotated[User, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]

_OPTIONS = (
    joinedload(Dispatch.truck).joinedload(Truck.driver),
    joinedload(Dispatch.route),
    joinedload(Dispatch.schedule),
)


def _get(db: Session, dispatch_id: int) -> Dispatch:
    d = db.get(Dispatch, dispatch_id, options=list(_OPTIONS))
    if d is None:
        raise not_found("Dispatch")
    return d


def _outs(db: Session, rows: list[Dispatch]) -> list[DispatchOut]:
    causes = latest_delay_causes(db, [d.id for d in rows])
    now = utcnow()
    return [dispatch_out(d, now, causes) for d in rows]


@router.get("/dispatches", response_model=Page[DispatchOut])
def list_dispatches(
    db: DB,
    _: Reader,
    status_: DispatchStatus | None = Query(None, alias="status"),
    route_id: int | None = None,
    delayed: bool | None = None,
    day: date | None = Query(None, alias="date", description="Local day dispatched"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[DispatchOut]:
    query = select(Dispatch)
    if status_:
        query = query.where(Dispatch.status == status_)
    if route_id:
        query = query.where(Dispatch.route_id == route_id)
    if delayed is not None:
        query = query.where(Dispatch.is_delayed.is_(delayed))
    if day:
        s, e = local_bounds(day, day, get_settings().tz)
        query = query.where(Dispatch.dispatched_at >= s, Dispatch.dispatched_at < e)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(
        db.scalars(
            query.options(*_OPTIONS)
            .order_by(Dispatch.dispatched_at.desc(), Dispatch.id.desc())
            .limit(limit)
            .offset(offset)
        ).unique()
    )
    return Page(items=_outs(db, rows), total=total, limit=limit, offset=offset)


@router.get("/dispatches/ready", response_model=list[ScheduleOut])
def ready_for_dispatch(db: DB, _: Reader) -> list[ScheduleOut]:
    """Loads that finished loading and are waiting to be dispatched."""
    rows = db.scalars(
        select(LoadingSchedule)
        .options(
            joinedload(LoadingSchedule.truck).joinedload(Truck.driver),
            joinedload(LoadingSchedule.bay),
            joinedload(LoadingSchedule.dispatch),
        )
        .where(LoadingSchedule.status == ScheduleStatus.LOADED)
        .order_by(LoadingSchedule.loading_finished_at)
    ).unique()
    target, now = default_target(db), utcnow()
    return [schedule_out(s, target, now) for s in rows]


@router.post("/dispatches", response_model=DispatchOut, status_code=status.HTTP_201_CREATED)
def create_dispatch(body: DispatchIn, request: Request, db: DB, user: OpsWriter) -> DispatchOut:
    schedule = db.get(
        LoadingSchedule,
        body.schedule_id,
        options=[joinedload(LoadingSchedule.truck), joinedload(LoadingSchedule.dispatch)],
    )
    if schedule is None:
        raise invalid("Loading schedule not found")
    if schedule.dispatch is not None:
        raise conflict(f"This load was already dispatched as {schedule.dispatch.load_ref}.")
    if schedule.status != ScheduleStatus.LOADED:
        raise conflict("Loading must be finished before the truck can be dispatched.")
    route = db.get(Route, body.route_id)
    if route is None or not route.is_active:
        raise invalid("Route not found or inactive")

    # Compliance & availability are re-validated here, at the moment of dispatch, on the
    # server: a client cannot bypass them and a document that lapsed after booking blocks.
    # The row lock serialises against a concurrent status change of the same truck.
    db.execute(select(Truck.id).where(Truck.id == schedule.truck_id).with_for_update())
    blockers = dispatch_blockers(db, schedule.truck, local_today())
    if blockers:
        record_event(
            db,
            action="dispatch.blocked",
            entity_type="loading_schedule",
            entity_id=schedule.id,
            actor=user,
            request=request,
            summary=f"Dispatch of {schedule.truck.registration} blocked",
            changes={"reasons": blockers},
        )
        db.commit()
        raise conflict(f"Dispatch blocked for {schedule.truck.registration}: " + " ".join(blockers))

    at = not_in_future(body.dispatched_at or utcnow(), "Dispatch time")
    if schedule.loading_finished_at and at < schedule.loading_finished_at:
        raise invalid("Dispatch time cannot be earlier than the loading finish time.")

    schedule.departed_at = at  # leaving the site ends the turnaround clock
    schedule.status = ScheduleStatus.DEPARTED
    d = Dispatch(
        load_ref=next_load_ref(db, at),
        schedule=schedule,
        truck=schedule.truck,
        route=route,
        dispatched_at=at,
        expected_arrival_at=at + timedelta(minutes=route.expected_duration_minutes),
        status=DispatchStatus.IN_TRANSIT,
        notes=body.notes,
        created_by_id=user.id,
    )
    schedule.truck.status = TruckStatus.IN_TRANSIT
    db.add(d)
    db.flush()
    record_event(
        db,
        action="dispatch.created",
        entity_type="dispatch",
        entity_id=d.id,
        actor=user,
        request=request,
        summary=f"{d.load_ref}: {schedule.truck.registration} dispatched on {route.label}",
    )
    commit(db)
    return _outs(db, [_get(db, d.id)])[0]


@router.post("/dispatches/{dispatch_id}/deliver", response_model=DispatchOut)
def deliver(
    dispatch_id: int, body: DeliverIn, request: Request, db: DB, user: OpsWriter
) -> DispatchOut:
    d = _get(db, dispatch_id)
    if d.status != DispatchStatus.IN_TRANSIT:
        raise conflict(f"{d.load_ref} is {d.status.value.replace('_', ' ')}, not in transit.")
    at = not_in_future(body.actual_arrival_at or utcnow(), "Arrival time")
    if at < d.dispatched_at:
        raise invalid("Arrival cannot be earlier than the dispatch time.")

    late_minutes = int((at - d.expected_arrival_at).total_seconds() // 60)
    delayed = late_minutes > get_settings().delay_grace_minutes
    already_explained = db.scalar(
        select(func.count(DelayIncident.id)).where(DelayIncident.dispatch_id == d.id)
    )
    if delayed and body.delay_cause is None and not already_explained:
        raise invalid(f"This delivery is {late_minutes} min late: select a delay cause.")

    d.actual_arrival_at, d.status, d.is_delayed = at, DispatchStatus.DELIVERED, delayed
    if delayed and body.delay_cause is not None:
        db.add(
            DelayIncident(
                dispatch=d,
                cause=body.delay_cause,
                delay_minutes=late_minutes,
                description=body.delay_notes,
                # The delay began when the ETA was missed; it is still open for follow-up.
                occurred_at=d.expected_arrival_at,
                status=IncidentStatus.OPEN,
                reported_by_id=user.id,
            )
        )
    if d.truck.status == TruckStatus.IN_TRANSIT:
        d.truck.status = TruckStatus.AVAILABLE
    record_event(
        db,
        action="dispatch.delivered",
        entity_type="dispatch",
        entity_id=d.id,
        actor=user,
        request=request,
        summary=f"{d.load_ref} delivered" + (f" {late_minutes} min late" if delayed else ""),
        changes={"actual_arrival_at": at.isoformat(), "late_minutes": late_minutes},
    )
    commit(db)
    return _outs(db, [d])[0]


@router.post("/dispatches/{dispatch_id}/flag-delay", response_model=DispatchOut)
def flag_delay(
    dispatch_id: int, body: FlagDelayIn, request: Request, db: DB, user: OpsWriter
) -> DispatchOut:
    d = _get(db, dispatch_id)
    if d.status != DispatchStatus.IN_TRANSIT:
        raise conflict("Only dispatches in transit can be flagged as delayed.")
    d.is_delayed = True
    db.add(
        DelayIncident(
            dispatch=d,
            cause=body.cause,
            delay_minutes=body.estimated_delay_minutes,
            description=body.description,
            occurred_at=utcnow(),
            status=IncidentStatus.OPEN,
            reported_by_id=user.id,
        )
    )
    record_event(
        db,
        action="dispatch.delay_flagged",
        entity_type="dispatch",
        entity_id=d.id,
        actor=user,
        request=request,
        summary=f"{d.load_ref} flagged delayed ({body.cause.value.replace('_', ' ')})",
    )
    commit(db)
    return _outs(db, [d])[0]


@router.get("/dispatch/overview", response_model=DispatchOverview)
def dispatch_overview(
    db: DB, _: Reader, day: date | None = Query(None, alias="date")
) -> DispatchOverview:
    settings = get_settings()
    tz, grace = settings.tz, timedelta(minutes=settings.delay_grace_minutes)
    day = day or local_today()

    active_rows = list(
        db.scalars(
            select(Dispatch)
            .options(*_OPTIONS)
            .where(Dispatch.status.in_([DispatchStatus.PENDING, DispatchStatus.IN_TRANSIT]))
        ).unique()
    )
    active = _outs(db, active_rows)
    in_transit = [o for o in active if o.status == DispatchStatus.IN_TRANSIT]

    def delivered_between(start: date, end: date) -> list[Dispatch]:
        s, e = local_bounds(start, end, tz)
        return list(
            db.scalars(
                select(Dispatch).where(
                    Dispatch.status == DispatchStatus.DELIVERED,
                    Dispatch.actual_arrival_at >= s,
                    Dispatch.actual_arrival_at < e,
                )
            )
        )

    def on_time(rows: list[Dispatch]) -> float | None:
        return percent(
            sum(1 for d in rows if d.actual_arrival_at <= d.expected_arrival_at + grace), len(rows)
        )

    week = delivered_between(day - timedelta(days=6), day)
    prev_week = delivered_between(day - timedelta(days=13), day - timedelta(days=7))
    durations = [(d.actual_arrival_at - d.dispatched_at).total_seconds() / 60 for d in week]

    s, e = local_bounds(day, day, tz)
    todays = _outs(
        db,
        list(
            db.scalars(
                select(Dispatch)
                .options(*_OPTIONS)
                .where(Dispatch.dispatched_at >= s, Dispatch.dispatched_at < e)
                .order_by(Dispatch.dispatched_at)
            ).unique()
        ),
    )

    def bucket(o: DispatchOut) -> str:
        if o.is_delayed or o.is_overdue:
            return "delayed"
        return o.status.value

    breakdown: dict[str, int] = {}
    for o in todays:
        breakdown[bucket(o)] = breakdown.get(bucket(o), 0) + 1

    def hour(dt: datetime) -> int:
        return dt.astimezone(tz).hour

    hours = {hour(o.dispatched_at) for o in todays}
    hourly = [
        DispatchHourBucket(
            hour=h,
            delivered=sum(
                1 for o in todays if hour(o.dispatched_at) == h and bucket(o) == "delivered"
            ),
            in_transit=sum(
                1 for o in todays if hour(o.dispatched_at) == h and bucket(o) == "in_transit"
            ),
            delayed=sum(1 for o in todays if hour(o.dispatched_at) == h and bucket(o) == "delayed"),
        )
        for h in range(min(hours | {6}), max(hours | {18}) + 1)
    ]

    late_today = [o for o in todays if o.status == DispatchStatus.DELIVERED and o.is_delayed]
    alerts = sorted(
        [o for o in in_transit if o.is_delayed or o.is_overdue] + late_today,
        key=lambda o: o.delay_minutes,
        reverse=True,
    )[:6]

    return DispatchOverview(
        date=day,
        active=len(active),
        in_transit=len(in_transit),
        delayed_active=sum(1 for o in in_transit if o.is_delayed or o.is_overdue),
        delivered_today=len(delivered_between(day, day)),
        delivered_previous_day=len(
            delivered_between(day - timedelta(days=1), day - timedelta(days=1))
        ),
        on_time_rate_7d=on_time(week),
        on_time_rate_prev_7d=on_time(prev_week),
        delayed_rate_7d=percent(sum(1 for d in week if d.is_delayed), len(week)),
        avg_delivery_minutes_7d=round(sum(durations) / len(durations), 1) if durations else None,
        status_breakdown=[
            {"status": k, "count": v} for k, v in sorted(breakdown.items(), key=lambda kv: -kv[1])
        ],
        hourly=hourly,
        alerts=alerts,
        sample_data=is_sample_data(db),
    )
