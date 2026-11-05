"""Operations overview metrics, computed from recorded database rows only.

Definitions (also documented in README):
- Loads processed: loading schedules that departed within the period (not cancelled).
- Turnaround: departed_at - arrival_at. Target is the bay override or the global target.
- On-time delivery: delivered dispatches arriving within the period whose actual arrival
  is no later than expected arrival + the configured grace (default 15 min).
- Bay utilisation: occupied bay time (arrival -> departure, clipped to the period) divided
  by active bays x days x configured operating hours per day. Capped at 100%.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    ComplianceDocument,
    DelayIncident,
    Dispatch,
    DispatchStatus,
    IncidentStatus,
    LoadingBay,
    LoadingSchedule,
    Route,
    ScheduleStatus,
    Truck,
)
from ..schemas import (
    DashboardKpis,
    DashboardOverview,
    ExpiryAlert,
    KpiValue,
    RecentDispatch,
    StatusCount,
    TrendPoint,
)
from .app_settings import is_sample_data, turnaround_target_minutes
from .turnaround import percent

MAX_RANGE_DAYS = 92
EXPIRY_WINDOW_DAYS = 30


def local_bounds(start: date, end: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Inclusive local dates -> half-open [start, end) aware datetimes."""
    return (
        datetime.combine(start, time.min, tzinfo=tz),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz),
    )


def _turnaround_expr() -> ColumnElement[float]:
    return func.extract("epoch", LoadingSchedule.departed_at - LoadingSchedule.arrival_at) / 60


def _completed_loads(s: datetime, e: datetime) -> list[ColumnElement[bool]]:
    return [
        LoadingSchedule.departed_at >= s,
        LoadingSchedule.departed_at < e,
        LoadingSchedule.arrival_at.is_not(None),
        LoadingSchedule.status != ScheduleStatus.CANCELLED,
    ]


def _on_time() -> ColumnElement[bool]:
    grace = timedelta(minutes=get_settings().delay_grace_minutes)
    return Dispatch.actual_arrival_at <= Dispatch.expected_arrival_at + grace


def _f(value: object) -> float | None:
    return None if value is None else round(float(value), 1)  # type: ignore[arg-type]


def _period_kpis(db: Session, s: datetime, e: datetime, target: int) -> dict[str, float | None]:
    settings = get_settings()
    ta = _turnaround_expr()
    effective_target = func.coalesce(LoadingBay.target_turnaround_minutes, target)

    loads, avg_ta, within = db.execute(
        select(
            func.count(LoadingSchedule.id),
            func.avg(ta),
            func.count(LoadingSchedule.id).filter(ta <= effective_target),
        )
        .join(LoadingBay, LoadingBay.id == LoadingSchedule.bay_id)
        .where(*_completed_loads(s, e))
    ).one()

    delivered, on_time = db.execute(
        select(
            func.count(Dispatch.id),
            func.count(Dispatch.id).filter(_on_time()),
        ).where(
            Dispatch.status == DispatchStatus.DELIVERED,
            Dispatch.actual_arrival_at >= s,
            Dispatch.actual_arrival_at < e,
        )
    ).one()

    delays = db.scalar(
        select(func.count(DelayIncident.id)).where(
            DelayIncident.occurred_at >= s, DelayIncident.occurred_at < e
        )
    )

    occupied_seconds = db.scalar(
        select(
            func.coalesce(
                func.sum(
                    func.extract(
                        "epoch",
                        func.least(LoadingSchedule.departed_at, e)
                        - func.greatest(LoadingSchedule.arrival_at, s),
                    )
                ),
                0,
            )
        ).where(
            LoadingSchedule.arrival_at < e,
            LoadingSchedule.departed_at > s,
            LoadingSchedule.status != ScheduleStatus.CANCELLED,
        )
    )
    active_bays = db.scalar(select(func.count(LoadingBay.id)).where(LoadingBay.is_active)) or 0
    days = (e - s).total_seconds() / 86400
    capacity_seconds = active_bays * days * settings.bay_operating_hours_per_day * 3600
    utilisation = (
        min(100.0, round(float(occupied_seconds) / capacity_seconds * 100, 1))
        if capacity_seconds
        else None
    )

    return {
        "loads_processed": float(loads),
        "avg_turnaround_minutes": _f(avg_ta),
        "within_target_pct": percent(within, loads),
        "on_time_delivery_pct": percent(on_time, delivered),
        "delay_incidents": float(delays or 0),
        "bay_utilization_pct": utilisation,
    }


def _trend(
    db: Session, start: date, end: date, s: datetime, e: datetime, tz: str
) -> list[TrendPoint]:
    ta = _turnaround_expr()
    load_day = func.date(func.timezone(tz, LoadingSchedule.departed_at)).label("day")
    load_rows = {
        row.day: row
        for row in db.execute(
            select(load_day, func.count(LoadingSchedule.id).label("n"), func.avg(ta).label("avg"))
            .where(*_completed_loads(s, e))
            .group_by(load_day)
        )
    }
    arr_day = func.date(func.timezone(tz, Dispatch.actual_arrival_at)).label("day")
    delivery_rows = {
        row.day: row
        for row in db.execute(
            select(
                arr_day,
                func.count(Dispatch.id).label("n"),
                func.count(Dispatch.id).filter(_on_time()).label("on_time"),
            )
            .where(
                Dispatch.status == DispatchStatus.DELIVERED,
                Dispatch.actual_arrival_at >= s,
                Dispatch.actual_arrival_at < e,
            )
            .group_by(arr_day)
        )
    }

    points: list[TrendPoint] = []
    day = start
    while day <= end:
        lr, dr = load_rows.get(day), delivery_rows.get(day)
        points.append(
            TrendPoint(
                day=day,
                loads_processed=lr.n if lr else 0,
                avg_turnaround_minutes=_f(lr.avg) if lr else None,
                on_time_delivery_pct=percent(dr.on_time, dr.n) if dr else None,
            )
        )
        day += timedelta(days=1)
    return points


def build_overview(db: Session, start: date, end: date) -> DashboardOverview:
    settings = get_settings()
    tz = settings.tz
    target = turnaround_target_minutes(db)
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)

    s, e = local_bounds(start, end, tz)
    ps, pe = local_bounds(prev_start, prev_end, tz)
    current = _period_kpis(db, s, e, target)
    previous = _period_kpis(db, ps, pe, target)
    kpis = DashboardKpis(**{k: KpiValue(current=current[k], previous=previous[k]) for k in current})

    dispatch_status = [
        StatusCount(status=str(status), count=n)
        for status, n in db.execute(
            select(Dispatch.status, func.count(Dispatch.id))
            .where(Dispatch.dispatched_at >= s, Dispatch.dispatched_at < e)
            .group_by(Dispatch.status)
            .order_by(func.count(Dispatch.id).desc())
        )
    ]
    delayed = db.scalar(
        select(func.count(Dispatch.id)).where(
            Dispatch.dispatched_at >= s, Dispatch.dispatched_at < e, Dispatch.is_delayed
        )
    )

    fleet_status = [
        StatusCount(status=str(status), count=n)
        for status, n in db.execute(
            select(Truck.status, func.count(Truck.id))
            .group_by(Truck.status)
            .order_by(func.count(Truck.id).desc())
        )
    ]

    open_delays = db.scalar(
        select(func.count(DelayIncident.id)).where(DelayIncident.status != IncidentStatus.RESOLVED)
    )

    recent = [
        RecentDispatch(
            id=d.id,
            load_ref=d.load_ref,
            truck_registration=reg,
            route=f"{origin} → {destination}",
            dispatched_at=d.dispatched_at,
            expected_arrival_at=d.expected_arrival_at,
            actual_arrival_at=d.actual_arrival_at,
            status=d.status,
            is_delayed=d.is_delayed,
        )
        for d, reg, origin, destination in db.execute(
            select(Dispatch, Truck.registration, Route.origin, Route.destination)
            .join(Truck, Truck.id == Dispatch.truck_id)
            .join(Route, Route.id == Dispatch.route_id)
            .where(Dispatch.dispatched_at < e)
            .order_by(Dispatch.dispatched_at.desc())
            .limit(6)
        )
    ]

    # Only the most recent document per truck & type counts (older ones were renewed).
    latest = (
        select(ComplianceDocument)
        .ext(distinct_on(ComplianceDocument.truck_id, ComplianceDocument.doc_type))
        .order_by(
            ComplianceDocument.truck_id,
            ComplianceDocument.doc_type,
            ComplianceDocument.expires_on.desc(),
        )
        .subquery()
    )
    today = datetime.now(tz).date()
    alerts = [
        ExpiryAlert(
            truck_registration=reg,
            doc_type=doc_type,
            expires_on=expires_on,
            days_remaining=(expires_on - today).days,
        )
        for reg, doc_type, expires_on in db.execute(
            select(Truck.registration, latest.c.doc_type, latest.c.expires_on)
            .join(Truck, Truck.id == latest.c.truck_id)
            .where(latest.c.expires_on <= today + timedelta(days=EXPIRY_WINDOW_DAYS))
            .order_by(latest.c.expires_on)
            .limit(8)
        )
    ]

    return DashboardOverview(
        period_start=start,
        period_end=end,
        previous_period_start=prev_start,
        previous_period_end=prev_end,
        sample_data=is_sample_data(db),
        turnaround_target_minutes=target,
        kpis=kpis,
        trend=_trend(db, start, end, s, e, settings.timezone),
        dispatch_status=dispatch_status,
        delayed_dispatches=delayed or 0,
        fleet_status=fleet_status,
        fleet_total=sum(f.count for f in fleet_status),
        open_delay_incidents=open_delays or 0,
        recent_dispatches=recent,
        expiry_alerts=alerts,
    )
