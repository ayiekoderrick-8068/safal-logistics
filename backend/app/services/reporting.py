"""Operational reporting: one filter model, one set of definitions, used by the reports API,
CSV exports and PDF reports so every surface shows the same numbers.

Period anchors (local calendar days, Africa/Nairobi by default, half-open [start, end+1d)):
  * Loads / turnaround ...... loads whose truck DEPARTED in the period (completed only)
  * Ongoing loads ........... arrived, not yet departed (reported separately, never averaged)
  * Dispatch & delivery ..... dispatches DISPATCHED in the period (a cohort); deliveries
                              still in transit are "pending" and excluded from on-time %
  * Delays .................. incidents that STARTED (occurred_at) in the period
  * Schedules ............... bookings whose scheduled start is in the period
  * Bay utilisation ......... recorded occupancy (arrival -> departure, or now if ongoing)
                              clipped to the period / (days x operating hours) x 100

Durations (minutes, completed steps only):
  waiting      loading_started_at  - arrival_at
  loading      loading_finished_at - loading_started_at
  post-load    departed_at         - loading_finished_at
  turnaround   departed_at         - arrival_at        (yard turnaround)
  delivery     actual_arrival_at   - dispatched_at     (never mixed with turnaround)

On time: delivered with actual_arrival_at <= deadline, where deadline = expected arrival +
LOGITRACK_DELAY_GRACE_MINUTES (default 15).

Entity filters apply everywhere through the same relationships:
  truck -> the operation's truck; driver -> the driver assigned to that truck *at the time
  of the operation* (driver_assignments history: arrival/scheduled start for loads,
  dispatched_at for dispatches, occurred_at for incidents); bay -> the loading booking's
  bay; route -> the dispatch route; dispatch status -> the dispatch (``delayed`` = flagged delayed);
  delay category -> operations with at least one incident of that category.
"""

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from sqlalchemy import Integer, Select, and_, cast, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from ..config import get_settings
from ..models import (
    AuditEvent,
    DelayCause,
    DelayIncident,
    Dispatch,
    DispatchStatus,
    Driver,
    DriverAssignment,
    IncidentStatus,
    LoadingBay,
    LoadingSchedule,
    Route,
    ScheduleStatus,
    Truck,
    User,
)
from .app_settings import turnaround_target_minutes

Preset = Literal["today", "yesterday", "last_7_days", "last_30_days", "custom"]
MAX_DAYS = 366
DELAY_BUCKETS = [
    "On time or early",
    "Within grace",
    "15–30 min late",
    "30–60 min late",
    "1–2 h late",
    "Over 2 h late",
]


# ---------------------------------------------------------------- filters
@dataclass(frozen=True)
class ReportFilters:
    start: date
    end: date
    preset: str = "last_7_days"
    truck_id: int | None = None
    driver_id: int | None = None
    bay_id: int | None = None
    route_id: int | None = None
    dispatch_status: str | None = None  # pending|in_transit|delivered|cancelled|delayed
    delay_cause: DelayCause | None = None

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def bounds(self) -> tuple[datetime, datetime]:
        tz = get_settings().tz
        return (
            datetime.combine(self.start, time.min, tzinfo=tz),
            datetime.combine(self.end + timedelta(days=1), time.min, tzinfo=tz),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            k: (v.isoformat() if isinstance(v, date) else str(v) if v is not None else None)
            for k, v in self.__dict__.items()
        }


def resolve_period(
    preset: str, start: date | None, end: date | None, today: date
) -> tuple[date, date]:
    if preset == "today":
        return today, today
    if preset == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if preset == "last_7_days":
        return today - timedelta(days=6), today
    if preset == "last_30_days":
        return today - timedelta(days=29), today
    if preset == "custom":
        if start is None or end is None:
            raise ValueError("A custom range needs both a start and an end date.")
        if start > end:
            raise ValueError("The start date must be on or before the end date.")
        if (end - start).days + 1 > MAX_DAYS:
            raise ValueError(f"A report can cover at most {MAX_DAYS} days.")
        return start, end
    raise ValueError("Unknown period.")


def describe_filters(db: Session, f: ReportFilters) -> list[tuple[str, str]]:
    """Human-readable applied filters (for PDF/CSV headers)."""
    out = [
        (
            "Period",
            f"{f.start:%d %b %Y} – {f.end:%d %b %Y} ({f.days} day{'s' if f.days != 1 else ''}, "
            f"{get_settings().timezone})",
        )
    ]
    lookups = [
        ("Truck", Truck, f.truck_id, lambda t: t.registration),
        ("Driver", Driver, f.driver_id, lambda d: d.full_name),
        ("Loading bay", LoadingBay, f.bay_id, lambda b: b.name),
        ("Route", Route, f.route_id, lambda r: r.label),
    ]
    for label, model, ident, name in lookups:
        if ident is not None:
            obj = db.get(model, ident)
            out.append((label, name(obj) if obj else f"#{ident} (not found)"))
    if f.dispatch_status:
        out.append(("Dispatch status", f.dispatch_status.replace("_", " ")))
    if f.delay_cause:
        out.append(("Delay category", f.delay_cause.value.replace("_", " ")))
    return out


# ---------------------------------------------------------------- helpers
def minutes(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None or b < a:
        return None
    return (b - a).total_seconds() / 60


def stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "avg": None, "median": None, "min": None, "max": None}
    return {
        "count": len(values),
        "avg": round(statistics.fmean(values), 1),
        "median": round(statistics.median(values), 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
    }


def mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 1) if values else None


def pct(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 1) if whole else None


def local_day(dt: datetime) -> date:
    return dt.astimezone(get_settings().tz).date()


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def days_in(f: ReportFilters) -> list[date]:
    return [f.start + timedelta(days=i) for i in range(f.days)]


# ---------------------------------------------------------------- row loaders
DispatchAlias = aliased(Dispatch)


def _cause_exists(f: ReportFilters, schedule_id_col, dispatch_id_col):
    return exists().where(
        DelayIncident.cause == f.delay_cause,
        or_(
            DelayIncident.schedule_id == schedule_id_col,
            and_(dispatch_id_col.is_not(None), DelayIncident.dispatch_id == dispatch_id_col),
        ),
    )


def _dispatch_status_clause(f: ReportFilters, d):
    if f.dispatch_status == "delayed":
        return d.is_delayed.is_(True)
    return d.status == DispatchStatus(f.dispatch_status)


def _assignment_at(truck_col, at_col):
    """Alias + join condition for the driver assigned to `truck_col` at moment `at_col`.

    Assignment periods never overlap (exclusion constraint), so this matches at most one row.
    """
    da = aliased(DriverAssignment)
    cond = and_(
        da.truck_id == truck_col,
        da.assigned_at <= at_col,
        or_(da.released_at.is_(None), da.released_at > at_col),
    )
    return da, cond


def _driver_was_assigned(driver_id: int, truck_col, at_col):
    """True when `driver_id` was assigned to the truck at the time of the operation."""
    return exists().where(
        DriverAssignment.driver_id == driver_id,
        DriverAssignment.truck_id == truck_col,
        DriverAssignment.assigned_at <= at_col,
        or_(DriverAssignment.released_at.is_(None), DriverAssignment.released_at > at_col),
    )


def load_query(f: ReportFilters, anchor: Literal["departed", "scheduled", "occupancy"]) -> Select:
    """One row per loading booking (with its dispatch, if any), filtered consistently."""
    s, e = f.bounds()
    S, D = LoadingSchedule, DispatchAlias
    op_time = func.coalesce(S.arrival_at, S.scheduled_start)
    DA, da_cond = _assignment_at(S.truck_id, op_time)
    Dr = aliased(Driver)
    q = (
        select(
            S.id.label("schedule_id"),
            S.truck_id,
            Truck.registration,
            Dr.full_name.label("driver"),
            S.bay_id,
            LoadingBay.name.label("bay"),
            LoadingBay.target_turnaround_minutes.label("bay_target"),
            S.scheduled_start,
            S.scheduled_end,
            S.arrival_at,
            S.loading_started_at,
            S.loading_finished_at,
            S.departed_at,
            S.status,
            D.id.label("dispatch_id"),
            D.load_ref,
            D.route_id,
            Route.origin,
            Route.destination,
            D.status.label("dispatch_status"),
            D.is_delayed,
            D.dispatched_at,
            D.expected_arrival_at,
            D.actual_arrival_at,
        )
        .join(Truck, Truck.id == S.truck_id)
        .outerjoin(DA, da_cond)
        .outerjoin(Dr, Dr.id == DA.driver_id)
        .join(LoadingBay, LoadingBay.id == S.bay_id)
        .outerjoin(D, D.schedule_id == S.id)
        .outerjoin(Route, Route.id == D.route_id)
        .where(S.status != ScheduleStatus.CANCELLED)
    )
    if anchor == "departed":
        q = q.where(S.departed_at >= s, S.departed_at < e, S.arrival_at.is_not(None))
    elif anchor == "scheduled":
        q = q.where(S.scheduled_start >= s, S.scheduled_start < e)
    else:  # occupancy overlapping the period
        q = q.where(
            S.arrival_at.is_not(None),
            S.arrival_at < e,
            or_(S.departed_at.is_(None), S.departed_at > s),
        )
    if f.truck_id:
        q = q.where(S.truck_id == f.truck_id)
    if f.driver_id:
        q = q.where(_driver_was_assigned(f.driver_id, S.truck_id, op_time))
    if f.bay_id:
        q = q.where(S.bay_id == f.bay_id)
    if f.route_id:
        q = q.where(D.route_id == f.route_id)
    if f.dispatch_status:
        q = q.where(_dispatch_status_clause(f, D))
    if f.delay_cause:
        q = q.where(_cause_exists(f, S.id, D.id))
    return q


def dispatch_query(f: ReportFilters) -> Select:
    """One row per dispatch dispatched in the period."""
    s, e = f.bounds()
    D = Dispatch
    DA, da_cond = _assignment_at(D.truck_id, D.dispatched_at)
    Dr = aliased(Driver)
    q = (
        select(
            D.id.label("dispatch_id"),
            D.load_ref,
            D.truck_id,
            Truck.registration,
            Dr.full_name.label("driver"),
            D.route_id,
            Route.origin,
            Route.destination,
            Route.expected_duration_minutes,
            D.status.label("dispatch_status"),
            D.is_delayed,
            D.dispatched_at,
            D.expected_arrival_at,
            D.actual_arrival_at,
            LoadingSchedule.id.label("schedule_id"),
            LoadingSchedule.bay_id,
            LoadingBay.name.label("bay"),
        )
        .join(Truck, Truck.id == D.truck_id)
        .outerjoin(DA, da_cond)
        .outerjoin(Dr, Dr.id == DA.driver_id)
        .join(Route, Route.id == D.route_id)
        .outerjoin(LoadingSchedule, LoadingSchedule.id == D.schedule_id)
        .outerjoin(LoadingBay, LoadingBay.id == LoadingSchedule.bay_id)
        .where(D.dispatched_at >= s, D.dispatched_at < e)
    )
    if f.truck_id:
        q = q.where(D.truck_id == f.truck_id)
    if f.driver_id:
        q = q.where(_driver_was_assigned(f.driver_id, D.truck_id, D.dispatched_at))
    if f.bay_id:
        q = q.where(LoadingSchedule.bay_id == f.bay_id)
    if f.route_id:
        q = q.where(D.route_id == f.route_id)
    if f.dispatch_status:
        q = q.where(_dispatch_status_clause(f, D))
    if f.delay_cause:
        q = q.where(_cause_exists(f, D.schedule_id, D.id))
    return q


def incident_query(f: ReportFilters) -> Select:
    """One row per delay incident (never duplicated across linked records)."""
    s, e = f.bounds()
    I = DelayIncident  # noqa: E741
    D = DispatchAlias
    S_direct = aliased(LoadingSchedule)
    S_via = aliased(LoadingSchedule)
    T = aliased(Truck)
    B = aliased(LoadingBay)
    A = aliased(User)
    truck_id = func.coalesce(D.truck_id, S_direct.truck_id)
    bay_id = func.coalesce(S_direct.bay_id, S_via.bay_id)
    q = (
        select(
            I.id.label("incident_id"),
            I.cause,
            I.status,
            I.occurred_at,
            I.resolved_at,
            I.delay_minutes,
            I.description,
            I.dispatch_id,
            I.schedule_id,
            truck_id.label("truck_id"),
            T.registration,
            bay_id.label("bay_id"),
            B.name.label("bay"),
            D.route_id,
            D.load_ref,
            Route.origin,
            Route.destination,
            A.full_name.label("assigned_to"),
        )
        .outerjoin(D, D.id == I.dispatch_id)
        .outerjoin(S_direct, S_direct.id == I.schedule_id)
        .outerjoin(S_via, S_via.id == D.schedule_id)
        .outerjoin(T, T.id == truck_id)
        .outerjoin(B, B.id == bay_id)
        .outerjoin(Route, Route.id == D.route_id)
        .outerjoin(A, A.id == I.assigned_to_id)
        .where(I.occurred_at >= s, I.occurred_at < e)
    )
    if f.truck_id:
        q = q.where(truck_id == f.truck_id)
    if f.driver_id:
        q = q.where(_driver_was_assigned(f.driver_id, truck_id, I.occurred_at))
    if f.bay_id:
        q = q.where(bay_id == f.bay_id)
    if f.route_id:
        q = q.where(D.route_id == f.route_id)
    if f.dispatch_status:
        q = q.where(_dispatch_status_clause(f, D))
    if f.delay_cause:
        q = q.where(I.cause == f.delay_cause)
    return q


def rows(db: Session, q: Select) -> list[Any]:
    return list(db.execute(q).mappings())


def page(db: Session, q: Select, order_by, limit: int, offset: int) -> tuple[int, list[Any]]:
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
    return total, list(db.execute(q.order_by(*order_by).limit(limit).offset(offset)).mappings())


# ---------------------------------------------------------------- derived values per record
def route_label(r: Any) -> str | None:
    return f"{r['origin']} → {r['destination']}" if r.get("origin") else None


def load_durations(r: Any) -> dict[str, float | None]:
    return {
        "waiting": minutes(r["arrival_at"], r["loading_started_at"]),
        "loading": minutes(r["loading_started_at"], r["loading_finished_at"]),
        "post_load": minutes(r["loading_finished_at"], r["departed_at"]),
        "turnaround": minutes(r["arrival_at"], r["departed_at"]),
        "delivery": minutes(r.get("dispatched_at"), r.get("actual_arrival_at")),
    }


def deadline(r: Any) -> datetime | None:
    exp = r.get("expected_arrival_at")
    return exp + timedelta(minutes=get_settings().delay_grace_minutes) if exp else None


def delivery_outcome(r: Any) -> Literal["on_time", "late", "pending", "cancelled", None]:
    st = r.get("dispatch_status")
    if st is None:
        return None
    if st == DispatchStatus.CANCELLED:
        return "cancelled"
    if st != DispatchStatus.DELIVERED or r.get("actual_arrival_at") is None:
        return "pending"
    return "on_time" if r["actual_arrival_at"] <= deadline(r) else "late"


def lateness(r: Any) -> float | None:
    """Minutes after the expected arrival (negative = early); delivered only."""
    if r.get("actual_arrival_at") is None or r.get("expected_arrival_at") is None:
        return None
    return (r["actual_arrival_at"] - r["expected_arrival_at"]).total_seconds() / 60


def bucket(late_min: float) -> str:
    grace = get_settings().delay_grace_minutes
    if late_min <= 0:
        return DELAY_BUCKETS[0]
    if late_min <= grace:
        return DELAY_BUCKETS[1]
    if late_min <= 30:
        return DELAY_BUCKETS[2]
    if late_min <= 60:
        return DELAY_BUCKETS[3]
    if late_min <= 120:
        return DELAY_BUCKETS[4]
    return DELAY_BUCKETS[5]


def incident_duration(r: Any, now: datetime) -> float:
    return max(0.0, ((r["resolved_at"] or now) - r["occurred_at"]).total_seconds() / 60)


# ---------------------------------------------------------------- reports
@dataclass
class Context:
    db: Session
    f: ReportFilters
    target: int = field(init=False)
    now: datetime = field(init=False)

    def __post_init__(self) -> None:
        self.target = turnaround_target_minutes(self.db)
        self.now = datetime.now(UTC)

    def target_for(self, r: Any) -> int:
        return r.get("bay_target") or self.target


def _occupancy_by_bay(ctx: Context) -> dict[int, float]:
    s, e = ctx.f.bounds()
    end_cap = min(e, ctx.now)
    occ: dict[int, float] = defaultdict(float)
    for r in rows(ctx.db, load_query(ctx.f, "occupancy")):
        start = max(r["arrival_at"], s)
        stop = min(r["departed_at"] or end_cap, e)
        if stop > start:
            occ[r["bay_id"]] += (stop - start).total_seconds()
    return occ


def _active_bays(ctx: Context) -> list[LoadingBay]:
    q = select(LoadingBay).where(LoadingBay.is_active).order_by(LoadingBay.code)
    if ctx.f.bay_id:
        q = q.where(LoadingBay.id == ctx.f.bay_id)
    return list(ctx.db.scalars(q))


def utilisation(
    occupied_seconds: float, f: ReportFilters, hours_per_day: int, bays: int = 1
) -> float | None:
    available = f.days * hours_per_day * 3600 * bays
    return min(100.0, round(occupied_seconds / available * 100, 1)) if available else None


def compliance_interruptions(ctx: Context) -> int:
    s, e = ctx.f.bounds()
    q = (
        select(func.count(AuditEvent.id))
        .join(LoadingSchedule, LoadingSchedule.id == cast(AuditEvent.entity_id, Integer))
        .join(Truck, Truck.id == LoadingSchedule.truck_id)
        .where(
            AuditEvent.action == "dispatch.blocked",
            AuditEvent.entity_type == "loading_schedule",
            AuditEvent.created_at >= s,
            AuditEvent.created_at < e,
        )
    )
    if ctx.f.truck_id:
        q = q.where(LoadingSchedule.truck_id == ctx.f.truck_id)
    if ctx.f.driver_id:
        q = q.where(_driver_was_assigned(ctx.f.driver_id, Truck.id, AuditEvent.created_at))
    if ctx.f.bay_id:
        q = q.where(LoadingSchedule.bay_id == ctx.f.bay_id)
    return ctx.db.scalar(q) or 0


def summary_report(db: Session, f: ReportFilters, hours_per_day: int) -> dict[str, Any]:
    ctx = Context(db, f)
    loads = rows(db, load_query(f, "departed"))
    dispatches = rows(db, dispatch_query(f))
    incidents = rows(db, incident_query(f))
    outcomes = Counter(delivery_outcome(d) for d in dispatches)
    completed = outcomes["on_time"] + outcomes["late"]
    turnarounds = [t for r in loads if (t := load_durations(r)["turnaround"]) is not None]
    delayed_loads = sum(
        1
        for r in loads
        if (load_durations(r)["turnaround"] or 0) > ctx.target_for(r)
        or delivery_outcome(r) == "late"
        or r["is_delayed"]
    )
    bays = _active_bays(ctx)
    occ = _occupancy_by_bay(ctx)
    occupied = sum(occ.get(b.id, 0.0) for b in bays)

    by_day_loads: dict[date, list[float]] = defaultdict(list)
    for r in loads:
        if (t := load_durations(r)["turnaround"]) is not None:
            by_day_loads[local_day(r["departed_at"])].append(t)
    by_day_disp: dict[date, Counter] = defaultdict(Counter)
    for d in dispatches:
        by_day_disp[local_day(d["dispatched_at"])][delivery_outcome(d)] += 1
    by_day_inc = Counter(local_day(i["occurred_at"]) for i in incidents)
    trend = [
        {
            "day": day.isoformat(),
            "loads": len(by_day_loads.get(day, [])),
            "avg_turnaround_minutes": mean(by_day_loads.get(day, [])),
            "on_time_pct": pct(
                by_day_disp[day]["on_time"], by_day_disp[day]["on_time"] + by_day_disp[day]["late"]
            ),
            "delays": by_day_inc.get(day, 0),
        }
        for day in days_in(f)
    ]

    return {
        "kpis": {
            "loads_processed": len(loads),
            "completed_dispatches": completed,
            "pending_deliveries": outcomes["pending"],
            "on_time_pct": pct(outcomes["on_time"], completed),
            "avg_turnaround_minutes": mean(turnarounds),
            "delayed_loads": delayed_loads,
            "bay_utilization_pct": utilisation(occupied, f, hours_per_day, len(bays))
            if occ
            else None,
            "compliance_interruptions": compliance_interruptions(ctx),
            "delay_incidents": len(incidents),
        },
        "dispatch_outcomes": [
            {"status": k, "count": outcomes[k]}
            for k in ("on_time", "late", "pending", "cancelled")
            if outcomes[k]
        ],
        "trend": trend,
        "target_minutes": ctx.target,
    }


def turnaround_report(db: Session, f: ReportFilters) -> dict[str, Any]:
    ctx = Context(db, f)
    loads = rows(db, load_query(f, "departed"))
    durs = [load_durations(r) for r in loads]
    components = {
        k: stats([d[k] for d in durs if d[k] is not None])
        for k in ("waiting", "loading", "post_load", "turnaround", "delivery")
    }
    within = sum(
        1
        for r, d in zip(loads, durs, strict=True)
        if d["turnaround"] is not None and d["turnaround"] <= ctx.target_for(r)
    )

    def series(key_fn) -> list[dict[str, Any]]:
        groups: dict[date, list[float]] = defaultdict(list)
        for r, d in zip(loads, durs, strict=True):
            if d["turnaround"] is not None:
                groups[key_fn(local_day(r["departed_at"]))].append(d["turnaround"])
        keys = sorted({key_fn(day) for day in days_in(f)})
        return [
            {
                "period": k.isoformat(),
                "loads": len(groups.get(k, [])),
                **{f"{m}_minutes": v for m, v in stats(groups.get(k, [])).items() if m != "count"},
            }
            for k in keys
        ]

    def by(dim: str, label_fn) -> list[dict[str, Any]]:
        groups: dict[Any, list[tuple[Any, dict]]] = defaultdict(list)
        for r, d in zip(loads, durs, strict=True):
            key = r[dim] if dim != "route_id" else r["route_id"]
            groups[key].append((r, d))
        out = []
        for key, items in groups.items():
            ta = [d["turnaround"] for _, d in items if d["turnaround"] is not None]
            out.append(
                {
                    "id": key,
                    "label": label_fn(items[0][0]) or "Not dispatched",
                    "loads": len(items),
                    **{f"{m}_minutes": v for m, v in stats(ta).items() if m != "count"},
                    "avg_loading_minutes": mean(
                        [d["loading"] for _, d in items if d["loading"] is not None]
                    ),
                    "within_target_pct": pct(
                        sum(
                            1
                            for r, d in items
                            if d["turnaround"] is not None and d["turnaround"] <= ctx.target_for(r)
                        ),
                        len(items),
                    ),
                }
            )
        return sorted(out, key=lambda x: -(x["avg_minutes"] or 0))

    ongoing = sum(1 for r in rows(db, load_query(f, "occupancy")) if r["departed_at"] is None)
    return {
        "target_minutes": ctx.target,
        "completed_loads": len(loads),
        "ongoing_loads": ongoing,
        "within_target_pct": pct(within, len(loads)),
        "components": components,
        "daily": series(lambda d: d),
        "weekly": series(week_start),
        "by_truck": by("truck_id", lambda r: r["registration"]),
        "by_route": by("route_id", route_label),
        "by_bay": by("bay_id", lambda r: r["bay"]),
    }


def delay_report(db: Session, f: ReportFilters) -> dict[str, Any]:
    ctx = Context(db, f)
    inc = rows(db, incident_query(f))
    resolved = [i for i in inc if i["status"] == IncidentStatus.RESOLVED]

    def group(key_fn, label_fn) -> list[dict[str, Any]]:
        g: dict[Any, list[Any]] = defaultdict(list)
        for i in inc:
            if (k := key_fn(i)) is not None:
                g[k].append(i)
        return sorted(
            (
                {
                    "id": k,
                    "label": label_fn(v[0]),
                    "count": len(v),
                    "impact_minutes": sum(x["delay_minutes"] for x in v),
                    "open": sum(1 for x in v if x["status"] != IncidentStatus.RESOLVED),
                }
                for k, v in g.items()
            ),
            key=lambda x: -x["count"],
        )

    by_cause = []
    for c in DelayCause:
        items = [i for i in inc if i["cause"] == c]
        if items:
            res = [
                incident_duration(i, ctx.now)
                for i in items
                if i["status"] == IncidentStatus.RESOLVED
            ]
            by_cause.append(
                {
                    "cause": c.value,
                    "count": len(items),
                    "impact_minutes": sum(i["delay_minutes"] for i in items),
                    "avg_impact_minutes": mean([i["delay_minutes"] for i in items]),
                    "avg_resolution_minutes": mean(res),
                }
            )
    by_cause.sort(key=lambda x: -x["count"])

    def trend(key_fn) -> list[dict[str, Any]]:
        c = Counter(key_fn(local_day(i["occurred_at"])) for i in inc)
        m: dict[date, int] = defaultdict(int)
        for i in inc:
            m[key_fn(local_day(i["occurred_at"]))] += i["delay_minutes"]
        return [
            {"period": k.isoformat(), "count": c.get(k, 0), "impact_minutes": m.get(k, 0)}
            for k in sorted({key_fn(d) for d in days_in(f)})
        ]

    pairs = Counter((i["registration"], i["cause"].value) for i in inc if i["registration"])
    repeats = [{"truck": t, "cause": c, "count": n} for (t, c), n in pairs.most_common() if n >= 2][
        :10
    ]
    recent = sorted(inc, key=lambda i: i["occurred_at"], reverse=True)[:10]
    return {
        "total": len(inc),
        "open": len(inc) - len(resolved),
        "resolved": len(resolved),
        "impact_minutes": sum(i["delay_minutes"] for i in inc),
        "avg_impact_minutes": mean([i["delay_minutes"] for i in inc]),
        "avg_resolution_minutes": mean([incident_duration(i, ctx.now) for i in resolved]),
        "by_cause": by_cause,
        "by_bay": group(lambda i: i["bay_id"], lambda i: i["bay"]),
        "by_route": group(lambda i: i["route_id"], route_label),
        "by_truck": group(lambda i: i["truck_id"], lambda i: i["registration"]),
        "daily": trend(lambda d: d),
        "weekly": trend(week_start),
        "repeat_patterns": repeats,
        "recent": [incident_record(i, ctx.now) for i in recent],
    }


def incident_record(i: Any, now: datetime) -> dict[str, Any]:
    return {
        "id": i["incident_id"],
        "started_at": i["occurred_at"],
        "resolved_at": i["resolved_at"],
        "status": i["status"].value,
        "cause": i["cause"].value,
        "truck": i["registration"],
        "bay": i["bay"],
        "route": route_label(i),
        "load_ref": i["load_ref"],
        "impact_minutes": i["delay_minutes"],
        "duration_minutes": round(incident_duration(i, now), 1),
        "ongoing": i["resolved_at"] is None,
        "assigned_to": i["assigned_to"],
        "description": i["description"],
    }


def bay_report(db: Session, f: ReportFilters, hours_per_day: int) -> dict[str, Any]:
    ctx = Context(db, f)
    loads = rows(db, load_query(f, "departed"))
    occ = _occupancy_by_bay(ctx)
    tz = get_settings().tz
    arrivals = rows(db, load_query(f, "occupancy"))
    s, _ = f.bounds()
    peak = Counter(r["arrival_at"].astimezone(tz).hour for r in arrivals if r["arrival_at"] >= s)
    out = []
    for bay in _active_bays(ctx):
        items = [r for r in loads if r["bay_id"] == bay.id]
        durs = [load_durations(r) for r in items]
        target = bay.target_turnaround_minutes or ctx.target
        delayed = sum(1 for d in durs if (d["turnaround"] or 0) > target)
        bay_peak = Counter(
            r["arrival_at"].astimezone(tz).hour
            for r in arrivals
            if r["bay_id"] == bay.id and r["arrival_at"] >= s
        )
        out.append(
            {
                "id": bay.id,
                "code": bay.code,
                "name": bay.name,
                "target_minutes": target,
                "loads": len(items),
                "completed_within_target": len(items) - delayed,
                "delayed": delayed,
                "avg_loading_minutes": mean(
                    [d["loading"] for d in durs if d["loading"] is not None]
                ),
                "avg_waiting_minutes": mean(
                    [d["waiting"] for d in durs if d["waiting"] is not None]
                ),
                "avg_turnaround_minutes": mean(
                    [d["turnaround"] for d in durs if d["turnaround"] is not None]
                ),
                "throughput_per_day": round(len(items) / f.days, 2),
                "throughput_per_operating_hour": round(len(items) / (f.days * hours_per_day), 3),
                "occupied_hours": round(occ.get(bay.id, 0.0) / 3600, 1),
                # No recorded occupancy -> no utilisation figure (never assumed).
                "utilization_pct": utilisation(occ[bay.id], f, hours_per_day)
                if bay.id in occ
                else None,
                "peak_hour": f"{bay_peak.most_common(1)[0][0]:02d}:00" if bay_peak else None,
            }
        )
    return {
        "hours_per_day": hours_per_day,
        "days": f.days,
        "bays": out,
        "peak_hours": [{"hour": h, "arrivals": peak.get(h, 0)} for h in range(24)],
    }


def dispatch_report(db: Session, f: ReportFilters) -> dict[str, Any]:
    disp = rows(db, dispatch_query(f))
    scheduled = (
        db.scalar(select(func.count()).select_from(load_query(f, "scheduled").subquery())) or 0
    )
    outcomes = Counter(delivery_outcome(d) for d in disp)
    completed = [d for d in disp if delivery_outcome(d) in ("on_time", "late")]
    durations = [
        m
        for d in completed
        if (m := minutes(d["dispatched_at"], d["actual_arrival_at"])) is not None
    ]
    planned = [minutes(d["dispatched_at"], d["expected_arrival_at"]) or 0 for d in completed]
    dist = Counter(bucket(lateness(d)) for d in completed)
    routes: dict[int, list[Any]] = defaultdict(list)
    for d in disp:
        routes[d["route_id"]].append(d)
    by_route = []
    for rid, items in routes.items():
        done = [d for d in items if delivery_outcome(d) in ("on_time", "late")]
        by_route.append(
            {
                "id": rid,
                "label": route_label(items[0]),
                "dispatches": len(items),
                "completed": len(done),
                "pending": sum(1 for d in items if delivery_outcome(d) == "pending"),
                "on_time_pct": pct(
                    sum(1 for d in done if delivery_outcome(d) == "on_time"), len(done)
                ),
                "avg_planned_minutes": mean(
                    [minutes(d["dispatched_at"], d["expected_arrival_at"]) or 0 for d in done]
                ),
                "avg_actual_minutes": mean(
                    [minutes(d["dispatched_at"], d["actual_arrival_at"]) or 0 for d in done]
                ),
                "avg_lateness_minutes": mean([lateness(d) or 0 for d in done]),
            }
        )
    by_route.sort(key=lambda x: -x["dispatches"])
    return {
        "grace_minutes": get_settings().delay_grace_minutes,
        "scheduled_loads": scheduled,
        "dispatched": len(disp),
        "dispatched_trucks": len({d["truck_id"] for d in disp}),
        "completed": len(completed),
        "pending": outcomes["pending"],
        "cancelled": outcomes["cancelled"],
        "on_time": outcomes["on_time"],
        "late": outcomes["late"],
        "on_time_pct": pct(outcomes["on_time"], len(completed)),
        "avg_delivery_minutes": mean(durations),
        "avg_planned_minutes": mean(planned),
        "delay_distribution": [{"bucket": b, "count": dist.get(b, 0)} for b in DELAY_BUCKETS],
        "by_route": by_route,
    }


# ---------------------------------------------------------------- record listings
def load_record(r: Any, ctx_target: int) -> dict[str, Any]:
    d = load_durations(r)
    target = r.get("bay_target") or ctx_target
    return {
        "schedule_id": r["schedule_id"],
        "truck": r["registration"],
        "driver": r["driver"],
        "bay": r["bay"],
        "route": route_label(r),
        "load_ref": r["load_ref"],
        "scheduled_start": r["scheduled_start"],
        "arrival_at": r["arrival_at"],
        "loading_started_at": r["loading_started_at"],
        "loading_finished_at": r["loading_finished_at"],
        "departed_at": r["departed_at"],
        "status": r["status"].value,
        "waiting_minutes": _r1(d["waiting"]),
        "loading_minutes": _r1(d["loading"]),
        "post_load_minutes": _r1(d["post_load"]),
        "turnaround_minutes": _r1(d["turnaround"]),
        "target_minutes": target,
        "within_target": None if d["turnaround"] is None else d["turnaround"] <= target,
        "dispatched_at": r["dispatched_at"],
        "expected_arrival_at": r["expected_arrival_at"],
        "actual_arrival_at": r["actual_arrival_at"],
        "delivery_minutes": _r1(d["delivery"]),
        "delivery_outcome": delivery_outcome(r),
    }


def dispatch_record(d: Any) -> dict[str, Any]:
    late = lateness(d)
    return {
        "dispatch_id": d["dispatch_id"],
        "load_ref": d["load_ref"],
        "truck": d["registration"],
        "driver": d["driver"],
        "route": route_label(d),
        "bay": d["bay"],
        "dispatched_at": d["dispatched_at"],
        "expected_arrival_at": d["expected_arrival_at"],
        "deadline_at": deadline(d),
        "actual_arrival_at": d["actual_arrival_at"],
        "status": d["dispatch_status"].value,
        "flagged_delayed": d["is_delayed"],
        "planned_minutes": _r1(minutes(d["dispatched_at"], d["expected_arrival_at"])),
        "delivery_minutes": _r1(minutes(d["dispatched_at"], d["actual_arrival_at"])),
        "lateness_minutes": _r1(late),
        "outcome": delivery_outcome(d),
    }


def _r1(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


RECORD_TYPES = ("turnaround", "schedules", "dispatches", "delays")


def records(
    db: Session, f: ReportFilters, kind: str, limit: int, offset: int
) -> tuple[int, list[dict]]:
    ctx = Context(db, f)
    if kind == "turnaround":
        total, rs = page(
            db, load_query(f, "departed"), [LoadingSchedule.departed_at.desc()], limit, offset
        )
        return total, [load_record(r, ctx.target) for r in rs]
    if kind == "schedules":
        total, rs = page(
            db, load_query(f, "scheduled"), [LoadingSchedule.scheduled_start.desc()], limit, offset
        )
        return total, [load_record(r, ctx.target) for r in rs]
    if kind == "dispatches":
        total, rs = page(db, dispatch_query(f), [Dispatch.dispatched_at.desc()], limit, offset)
        return total, [dispatch_record(r) for r in rs]
    total, rs = page(db, incident_query(f), [DelayIncident.occurred_at.desc()], limit, offset)
    return total, [incident_record(r, ctx.now) for r in rs]
