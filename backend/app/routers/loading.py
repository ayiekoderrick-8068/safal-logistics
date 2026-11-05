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
    LoadingBay,
    LoadingSchedule,
    Role,
    Route,
    ScheduleStatus,
    Truck,
    TruckStatus,
    User,
)
from ..schemas_ops import (
    BayBoardItem,
    BayIn,
    BayOut,
    HourBucket,
    LoadingOverview,
    Page,
    RouteIn,
    RouteOut,
    ScheduleEventIn,
    ScheduleIn,
    ScheduleOut,
)
from ..services.app_settings import is_sample_data
from ..services.dashboard import local_bounds
from ..services.operations import (
    apply_schedule_event,
    bay_out,
    cancel_schedule,
    check_schedule_conflicts,
    commit,
    conflict,
    default_target,
    invalid,
    local_today,
    not_found,
    schedule_out,
    utcnow,
)

router = APIRouter(prefix="/api", tags=["loading"])
OpsWriter = Annotated[User, Depends(require_roles(Role.OPERATIONS))]
Reader = Annotated[User, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]

_SCHEDULE_OPTIONS = (
    joinedload(LoadingSchedule.truck).joinedload(Truck.driver),
    joinedload(LoadingSchedule.bay),
    joinedload(LoadingSchedule.dispatch),
)


def _route_out(r: Route) -> RouteOut:
    return RouteOut(
        id=r.id,
        origin=r.origin,
        destination=r.destination,
        label=r.label,
        distance_km=float(r.distance_km),
        expected_duration_minutes=r.expected_duration_minutes,
        is_active=r.is_active,
    )


# ---------- routes ----------
@router.get("/routes", response_model=list[RouteOut])
def list_routes(db: DB, _: Reader) -> list[RouteOut]:
    return [
        _route_out(r) for r in db.scalars(select(Route).order_by(Route.origin, Route.destination))
    ]


@router.post("/routes", response_model=RouteOut, status_code=status.HTTP_201_CREATED)
def create_route(body: RouteIn, request: Request, db: DB, user: OpsWriter) -> RouteOut:
    route = Route(**body.model_dump())
    db.add(route)
    db.flush()
    record_event(
        db,
        action="route.created",
        entity_type="route",
        entity_id=route.id,
        actor=user,
        request=request,
        summary=f"Route {route.label} created",
    )
    commit(db)
    return _route_out(route)


# ---------- bays ----------
@router.get("/bays", response_model=list[BayOut])
def list_bays(db: DB, _: Reader) -> list[BayOut]:
    target = default_target(db)
    return [bay_out(b, target) for b in db.scalars(select(LoadingBay).order_by(LoadingBay.code))]


@router.post("/bays", response_model=BayOut, status_code=status.HTTP_201_CREATED)
def create_bay(body: BayIn, request: Request, db: DB, user: OpsWriter) -> BayOut:
    bay = LoadingBay(**body.model_dump())
    db.add(bay)
    db.flush()
    record_event(
        db,
        action="bay.created",
        entity_type="loading_bay",
        entity_id=bay.id,
        actor=user,
        request=request,
        summary=f"Loading bay {bay.code} created",
    )
    commit(db)
    return bay_out(bay, default_target(db))


# ---------- schedules ----------
def _get_schedule(db: Session, schedule_id: int) -> LoadingSchedule:
    s = db.get(LoadingSchedule, schedule_id, options=list(_SCHEDULE_OPTIONS))
    if s is None:
        raise not_found("Loading schedule")
    return s


@router.get("/schedules", response_model=Page[ScheduleOut])
def list_schedules(
    db: DB,
    _: Reader,
    day: date | None = Query(None, alias="date", description="Local calendar day"),
    bay_id: int | None = None,
    status_: ScheduleStatus | None = Query(None, alias="status"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[ScheduleOut]:
    query = select(LoadingSchedule)
    if day:
        s, e = local_bounds(day, day, get_settings().tz)
        query = query.where(
            LoadingSchedule.scheduled_start >= s, LoadingSchedule.scheduled_start < e
        )
    if bay_id:
        query = query.where(LoadingSchedule.bay_id == bay_id)
    if status_:
        query = query.where(LoadingSchedule.status == status_)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.options(*_SCHEDULE_OPTIONS)
        .order_by(LoadingSchedule.scheduled_start, LoadingSchedule.id)
        .limit(limit)
        .offset(offset)
    ).unique()
    target, now = default_target(db), utcnow()
    return Page(
        items=[schedule_out(s, target, now) for s in rows], total=total, limit=limit, offset=offset
    )


@router.post("/schedules", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
def create_schedule(body: ScheduleIn, request: Request, db: DB, user: OpsWriter) -> ScheduleOut:
    truck = db.get(Truck, body.truck_id)
    bay = db.get(LoadingBay, body.bay_id)
    if truck is None:
        raise invalid("Truck not found")
    if bay is None or not bay.is_active:
        raise invalid("Loading bay not found or inactive")
    if truck.status in (TruckStatus.MAINTENANCE, TruckStatus.OUT_OF_SERVICE):
        raise conflict(
            f"{truck.registration} is {truck.status.value.replace('_', ' ')} "
            "and cannot be scheduled."
        )
    if body.scheduled_end < utcnow() - timedelta(hours=1):
        raise invalid("Cannot create a booking that ended in the past")
    check_schedule_conflicts(db, truck, bay, body.scheduled_start, body.scheduled_end)

    s = LoadingSchedule(
        truck=truck,
        bay=bay,
        scheduled_start=body.scheduled_start,
        scheduled_end=body.scheduled_end,
        notes=body.notes,
        status=ScheduleStatus.SCHEDULED,
        created_by_id=user.id,
    )
    db.add(s)
    db.flush()
    record_event(
        db,
        action="schedule.created",
        entity_type="loading_schedule",
        entity_id=s.id,
        actor=user,
        request=request,
        summary=f"{truck.registration} booked at {bay.name}",
        changes=body.model_dump(mode="json"),
    )
    commit(db)  # the exclusion constraint still guards against concurrent double-booking
    return schedule_out(_get_schedule(db, s.id), default_target(db), utcnow())


@router.post("/schedules/{schedule_id}/events", response_model=ScheduleOut)
def record_schedule_event(
    schedule_id: int, body: ScheduleEventIn, request: Request, db: DB, user: OpsWriter
) -> ScheduleOut:
    s = _get_schedule(db, schedule_id)
    at = body.at or utcnow()
    apply_schedule_event(s, body.event, at)
    record_event(
        db,
        action=f"schedule.{body.event}",
        entity_type="loading_schedule",
        entity_id=s.id,
        actor=user,
        request=request,
        summary=f"{s.truck.registration}: {body.event.replace('_', ' ')} at {s.bay.name}",
        changes={"at": at.isoformat()},
    )
    commit(db)
    return schedule_out(s, default_target(db), utcnow())


@router.post("/schedules/{schedule_id}/cancel", response_model=ScheduleOut)
def cancel(schedule_id: int, request: Request, db: DB, user: OpsWriter) -> ScheduleOut:
    s = _get_schedule(db, schedule_id)
    cancel_schedule(s)
    record_event(
        db,
        action="schedule.cancelled",
        entity_type="loading_schedule",
        entity_id=s.id,
        actor=user,
        request=request,
        summary=f"{s.truck.registration} booking at {s.bay.name} cancelled",
    )
    commit(db)
    return schedule_out(s, default_target(db), utcnow())


# ---------- page overview ----------
def _local_hour(dt: datetime) -> int:
    return dt.astimezone(get_settings().tz).hour


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


@router.get("/loading/overview", response_model=LoadingOverview)
def loading_overview(
    db: DB, _: Reader, day: date | None = Query(None, alias="date")
) -> LoadingOverview:
    tz = get_settings().tz
    day = day or local_today()
    target, now = default_target(db), utcnow()

    def day_schedules(d: date) -> list[LoadingSchedule]:
        s, e = local_bounds(d, d, tz)
        return list(
            db.scalars(
                select(LoadingSchedule)
                .options(*_SCHEDULE_OPTIONS)
                .where(
                    LoadingSchedule.scheduled_start >= s,
                    LoadingSchedule.scheduled_start < e,
                    LoadingSchedule.status != ScheduleStatus.CANCELLED,
                )
                .order_by(LoadingSchedule.scheduled_start)
            ).unique()
        )

    todays = [schedule_out(s, target, now) for s in day_schedules(day)]
    yesterdays = [schedule_out(s, target, now) for s in day_schedules(day - timedelta(days=1))]

    hours = {_local_hour(o.scheduled_start) for o in todays} | {
        _local_hour(o.loading_finished_at) for o in todays if o.loading_finished_at
    }
    span = range(min(hours | {6}), max(hours | {18}) + 1)
    hourly = [
        HourBucket(
            hour=h,
            scheduled=sum(1 for o in todays if _local_hour(o.scheduled_start) == h),
            completed=sum(
                1
                for o in todays
                if o.loading_finished_at and _local_hour(o.loading_finished_at) == h
            ),
        )
        for h in span
    ]

    # Current state of every bay (independent of the selected day).
    bays = list(db.scalars(select(LoadingBay).order_by(LoadingBay.code)))
    in_progress = {
        s.bay_id: s
        for s in db.scalars(
            select(LoadingSchedule)
            .options(*_SCHEDULE_OPTIONS)
            .where(
                LoadingSchedule.status.in_(
                    [ScheduleStatus.ARRIVED, ScheduleStatus.LOADING, ScheduleStatus.LOADED]
                )
            )
            .order_by(LoadingSchedule.scheduled_start)
        ).unique()
    }
    soon = {
        s.bay_id: s
        for s in db.scalars(
            select(LoadingSchedule)
            .options(*_SCHEDULE_OPTIONS)
            .where(
                LoadingSchedule.status == ScheduleStatus.SCHEDULED,
                LoadingSchedule.scheduled_start <= now + timedelta(hours=1),
                LoadingSchedule.scheduled_end > now,
            )
            .order_by(LoadingSchedule.scheduled_start.desc())
        ).unique()
    }
    board: list[BayBoardItem] = []
    for bay in bays:
        out = bay_out(bay, target)
        if not bay.is_active:
            board.append(BayBoardItem(bay=out, state="inactive", schedule=None, progress_pct=None))
        elif bay.id in in_progress:
            s = in_progress[bay.id]
            if s.status == ScheduleStatus.LOADED:
                pct = 100
            else:
                window = (s.scheduled_end - s.scheduled_start).total_seconds()
                pct = int(max(0, min(99, (now - s.scheduled_start).total_seconds() / window * 100)))
            board.append(
                BayBoardItem(
                    bay=out, state="in_use", schedule=schedule_out(s, target, now), progress_pct=pct
                )
            )
        elif bay.id in soon:
            board.append(
                BayBoardItem(
                    bay=out,
                    state="reserved",
                    schedule=schedule_out(soon[bay.id], target, now),
                    progress_pct=None,
                )
            )
        else:
            board.append(BayBoardItem(bay=out, state="available", schedule=None, progress_pct=None))

    grace = timedelta(minutes=get_settings().delay_grace_minutes)
    finished = [o.loading_minutes for o in todays if o.loading_minutes is not None]
    finished_prev = [o.loading_minutes for o in yesterdays if o.loading_minutes is not None]
    return LoadingOverview(
        date=day,
        active_bays=sum(1 for b in bays if b.is_active),
        total_bays=len(bays),
        scheduled_count=len(todays),
        completed_count=sum(1 for o in todays if o.loading_finished_at),
        avg_loading_minutes=_mean(finished),
        avg_loading_minutes_previous_day=_mean(finished_prev),
        avg_turnaround_minutes=_mean(
            [o.turnaround_minutes for o in todays if o.turnaround_minutes is not None]
        ),
        late_count=sum(1 for o in todays if o.is_late),
        hourly=hourly,
        bay_board=board,
        upcoming=[
            o
            for o in todays
            if o.status == ScheduleStatus.SCHEDULED and o.scheduled_start >= now - grace
        ][:6],
        late=[o for o in todays if o.is_late and o.status != ScheduleStatus.DEPARTED][:6],
        sample_data=is_sample_data(db),
    )
