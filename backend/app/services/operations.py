"""Business rules for the operational workflow.

    register truck -> schedule loading -> arrived -> loading started -> loading finished
    -> dispatch (= departure) -> delivered.  Turnaround = departure - arrival.

Truck status is derived from the workflow: a truck is LOADING from arrival until it is
dispatched, IN_TRANSIT until delivery, then AVAILABLE again. MAINTENANCE / OUT_OF_SERVICE
are set manually and block new bookings.
"""

from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    ComplianceDocument,
    DelayIncident,
    Dispatch,
    DispatchStatus,
    LoadingBay,
    LoadingSchedule,
    ScheduleStatus,
    Truck,
    TruckStatus,
)
from ..schemas_ops import (
    BayOut,
    ComplianceSummary,
    DispatchOut,
    Ref,
    ScheduleOut,
    TruckOut,
)
from .app_settings import turnaround_target_minutes
from .turnaround import loading_minutes, minutes_between, turnaround_minutes

FUTURE_TOLERANCE = timedelta(minutes=5)
EXPIRY_WINDOW_DAYS = 30

CONSTRAINT_MESSAGES = {
    "ex_loading_schedules_bay_overlap": "That bay is already booked for an overlapping time.",
    "uq_trucks_registration": "A truck with that registration already exists.",
    "uq_trucks_driver_id": "That driver is already assigned to another truck.",
    "uq_drivers_licence_number": "A driver with that licence number already exists.",
    "uq_routes_origin_destination": "That route already exists.",
    "uq_loading_bays_code": "A bay with that code already exists.",
    "uq_dispatches_schedule_id": "This load has already been dispatched.",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def local_today() -> date:
    return datetime.now(get_settings().tz).date()


def conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def invalid(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def not_found(entity: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{entity} not found")


def commit(db: Session, fallback: str = "The change conflicts with existing records.") -> None:
    """Commit, translating constraint violations into readable 409 responses."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        diag = getattr(exc.orig, "diag", None)
        name = getattr(diag, "constraint_name", None)
        raise conflict(CONSTRAINT_MESSAGES.get(name or "", fallback)) from None


def not_in_future(at: datetime, label: str) -> datetime:
    if at > utcnow() + FUTURE_TOLERANCE:
        raise invalid(f"{label} cannot be in the future")
    return at


# ---------- serialisers ----------
def bay_out(bay: LoadingBay, default_target: int) -> BayOut:
    return BayOut(
        id=bay.id,
        code=bay.code,
        name=bay.name,
        target_turnaround_minutes=bay.target_turnaround_minutes,
        effective_target_minutes=bay.target_turnaround_minutes or default_target,
        is_active=bay.is_active,
    )


def schedule_out(s: LoadingSchedule, default_target: int, now: datetime) -> ScheduleOut:
    grace = timedelta(minutes=get_settings().delay_grace_minutes)
    target = s.bay.target_turnaround_minutes or default_target
    ta = turnaround_minutes(s.arrival_at, s.departed_at)

    late_minutes = 0
    if s.status == ScheduleStatus.SCHEDULED and now > s.scheduled_start + grace:
        late_minutes = int((now - s.scheduled_start).total_seconds() // 60)  # missed start
    elif (
        s.status in (ScheduleStatus.ARRIVED, ScheduleStatus.LOADING)
        and now > s.scheduled_end + grace
    ):
        late_minutes = int((now - s.scheduled_end).total_seconds() // 60)  # overrunning
    elif s.arrival_at and s.arrival_at > s.scheduled_start + grace:
        late_minutes = int((s.arrival_at - s.scheduled_start).total_seconds() // 60)

    driver = s.truck.driver
    return ScheduleOut(
        id=s.id,
        truck=Ref(id=s.truck.id, label=s.truck.registration),
        driver_name=driver.full_name if driver else None,
        bay=Ref(id=s.bay.id, label=s.bay.name),
        scheduled_start=s.scheduled_start,
        scheduled_end=s.scheduled_end,
        arrival_at=s.arrival_at,
        loading_started_at=s.loading_started_at,
        loading_finished_at=s.loading_finished_at,
        departed_at=s.departed_at,
        status=s.status,
        notes=s.notes,
        loading_minutes=_round(loading_minutes(s.loading_started_at, s.loading_finished_at)),
        turnaround_minutes=_round(ta),
        target_minutes=target,
        within_target=None if ta is None else ta <= target,
        is_late=late_minutes > 0 and s.status != ScheduleStatus.CANCELLED,
        late_minutes=late_minutes if s.status != ScheduleStatus.CANCELLED else 0,
        dispatch_id=s.dispatch.id if s.dispatch else None,
        load_ref=s.dispatch.load_ref if s.dispatch else None,
    )


def dispatch_out(
    d: Dispatch, now: datetime, cause_by_dispatch: dict[int, str] | None = None
) -> DispatchOut:
    grace = timedelta(minutes=get_settings().delay_grace_minutes)
    if d.actual_arrival_at is not None:
        late = d.actual_arrival_at - d.expected_arrival_at
        overdue = False
    else:
        late = (
            now - d.expected_arrival_at if d.status == DispatchStatus.IN_TRANSIT else timedelta(0)
        )
        overdue = late > grace
    delay_minutes = max(0, int(late.total_seconds() // 60))
    schedule = d.schedule
    driver = d.truck.driver
    return DispatchOut(
        id=d.id,
        load_ref=d.load_ref,
        schedule_id=d.schedule_id,
        truck=Ref(id=d.truck.id, label=d.truck.registration),
        driver_name=driver.full_name if driver else None,
        route=Ref(id=d.route.id, label=d.route.label),
        dispatched_at=d.dispatched_at,
        expected_arrival_at=d.expected_arrival_at,
        actual_arrival_at=d.actual_arrival_at,
        status=d.status,
        is_delayed=d.is_delayed,
        is_overdue=overdue,
        delay_minutes=delay_minutes if (d.is_delayed or overdue) else 0,
        delivery_minutes=_round(minutes_between(d.dispatched_at, d.actual_arrival_at)),
        turnaround_minutes=_round(
            turnaround_minutes(schedule.arrival_at, schedule.departed_at) if schedule else None
        ),
        delay_cause=(cause_by_dispatch or {}).get(d.id),  # type: ignore[arg-type]
    )


def _round(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def compliance_by_truck(db: Session, truck_ids: list[int]) -> dict[int, ComplianceSummary]:
    """Latest document per (truck, type) -> overall status: overdue > expiring > valid."""
    result: dict[int, ComplianceSummary] = {}
    if not truck_ids:
        return result
    today = local_today()
    latest = (
        select(
            ComplianceDocument.truck_id, ComplianceDocument.doc_type, ComplianceDocument.expires_on
        )
        .where(ComplianceDocument.truck_id.in_(truck_ids))
        .ext(distinct_on(ComplianceDocument.truck_id, ComplianceDocument.doc_type))
        .order_by(
            ComplianceDocument.truck_id,
            ComplianceDocument.doc_type,
            ComplianceDocument.expires_on.desc(),
        )
    )
    soonest: dict[int, tuple] = {}
    for truck_id, doc_type, expires_on in db.execute(latest):
        if truck_id not in soonest or expires_on < soonest[truck_id][1]:
            soonest[truck_id] = (doc_type, expires_on)
    for truck_id in truck_ids:
        if truck_id not in soonest:
            result[truck_id] = ComplianceSummary(status="missing")
            continue
        doc_type, expires_on = soonest[truck_id]
        if expires_on < today:
            state = "overdue"
        elif expires_on <= today + timedelta(days=EXPIRY_WINDOW_DAYS):
            state = "expiring"
        else:
            state = "valid"
        result[truck_id] = ComplianceSummary(
            status=state, next_expiry=expires_on, next_expiry_type=doc_type
        )
    return result


def trucks_out(db: Session, trucks: list[Truck]) -> list[TruckOut]:
    ids = [t.id for t in trucks]
    compliance = compliance_by_truck(db, ids)
    last: dict[int, tuple[str, datetime]] = {}
    if ids:
        rows = db.execute(
            select(Dispatch)
            .where(Dispatch.truck_id.in_(ids))
            .ext(distinct_on(Dispatch.truck_id))
            .order_by(Dispatch.truck_id, Dispatch.dispatched_at.desc())
        ).scalars()
        for d in rows:
            last[d.truck_id] = (d.route.label, d.dispatched_at)
    return [
        TruckOut(
            id=t.id,
            registration=t.registration,
            make=t.make,
            model=t.model,
            capacity_tonnes=float(t.capacity_tonnes),
            status=t.status,
            driver=Ref(id=t.driver.id, label=t.driver.full_name) if t.driver else None,
            last_route=last.get(t.id, (None, None))[0],
            last_dispatched_at=last.get(t.id, (None, None))[1],
            compliance=compliance[t.id],
        )
        for t in trucks
    ]


# ---------- workflow ----------
def check_schedule_conflicts(
    db: Session, truck: Truck, bay: LoadingBay, start: datetime, end: datetime
) -> None:
    active = LoadingSchedule.status != ScheduleStatus.CANCELLED
    overlaps = (LoadingSchedule.scheduled_start < end) & (LoadingSchedule.scheduled_end > start)
    clash = db.scalar(
        select(LoadingSchedule).where(LoadingSchedule.bay_id == bay.id, active, overlaps).limit(1)
    )
    if clash:
        raise conflict(
            f"{bay.name} is already booked by {clash.truck.registration} "
            f"from {_fmt(clash.scheduled_start)} to {_fmt(clash.scheduled_end)}."
        )
    clash = db.scalar(
        select(LoadingSchedule)
        .where(
            LoadingSchedule.truck_id == truck.id,
            LoadingSchedule.status.in_(
                [
                    ScheduleStatus.SCHEDULED,
                    ScheduleStatus.ARRIVED,
                    ScheduleStatus.LOADING,
                    ScheduleStatus.LOADED,
                ]
            ),
            overlaps,
        )
        .limit(1)
    )
    if clash:
        raise conflict(
            f"{truck.registration} is already booked at {clash.bay.name} "
            f"from {_fmt(clash.scheduled_start)} to {_fmt(clash.scheduled_end)}."
        )


def _fmt(dt: datetime) -> str:
    return dt.astimezone(get_settings().tz).strftime("%d %b %H:%M")


TRANSITIONS: dict[str, tuple[ScheduleStatus, ScheduleStatus, str]] = {
    # event: (required current status, new status, timestamp attribute)
    "arrived": (ScheduleStatus.SCHEDULED, ScheduleStatus.ARRIVED, "arrival_at"),
    "loading_started": (ScheduleStatus.ARRIVED, ScheduleStatus.LOADING, "loading_started_at"),
    "loading_finished": (ScheduleStatus.LOADING, ScheduleStatus.LOADED, "loading_finished_at"),
}
_PREVIOUS = {"loading_started": "arrival_at", "loading_finished": "loading_started_at"}
_LABEL = {
    "arrived": "Arrival",
    "loading_started": "Loading start",
    "loading_finished": "Loading finish",
}


def apply_schedule_event(s: LoadingSchedule, event: str, at: datetime) -> None:
    required, new_status, attr = TRANSITIONS[event]
    if s.status != required:
        raise conflict(
            f"Cannot record {_LABEL[event].lower()}: load is {s.status.value.replace('_', ' ')}."
        )
    not_in_future(at, _LABEL[event])
    if event in _PREVIOUS:
        previous = getattr(s, _PREVIOUS[event])
        if at < previous:
            raise invalid(
                f"{_LABEL[event]} cannot be earlier than the previous step ({_fmt(previous)})."
            )
    setattr(s, attr, at)
    s.status = new_status
    if event == "arrived" and s.truck.status == TruckStatus.AVAILABLE:
        s.truck.status = TruckStatus.LOADING


def cancel_schedule(s: LoadingSchedule) -> None:
    if s.status not in (ScheduleStatus.SCHEDULED, ScheduleStatus.ARRIVED):
        raise conflict("Only loads that have not started loading can be cancelled.")
    if s.status == ScheduleStatus.ARRIVED and s.truck.status == TruckStatus.LOADING:
        s.truck.status = TruckStatus.AVAILABLE
    s.status = ScheduleStatus.CANCELLED


def next_load_ref(db: Session, at: datetime) -> str:
    prefix = f"LD-{at.astimezone(get_settings().tz):%y%m%d}-"
    count = db.scalar(select(func.count(Dispatch.id)).where(Dispatch.load_ref.like(f"{prefix}%")))
    return f"{prefix}{(count or 0) + 1:03d}"


def latest_delay_causes(db: Session, dispatch_ids: list[int]) -> dict[int, str]:
    if not dispatch_ids:
        return {}
    rows = db.execute(
        select(DelayIncident.dispatch_id, DelayIncident.cause)
        .where(DelayIncident.dispatch_id.in_(dispatch_ids))
        .ext(distinct_on(DelayIncident.dispatch_id))
        .order_by(DelayIncident.dispatch_id, DelayIncident.occurred_at.desc())
    )
    return {dispatch_id: cause for dispatch_id, cause in rows}


def default_target(db: Session) -> int:
    return turnaround_target_minutes(db)
