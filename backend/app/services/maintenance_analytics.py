"""Maintenance KPIs and report datasets. Definitions (also shown in the UI and every report):

* Reporting window: whole local days `start`..`end` (operations timezone), clipped to now.
* **Downtime** - minutes in the window during which a breakdown that stopped the asset was
  open (each breakdown clipped to the window; an asset's breakdowns never overlap).
* **Observed time** - window hours since the asset was registered, or since its first recorded
  breakdown if that started earlier (so downtime never exceeds observed time);
  there is no shift calendar, so equipment is assumed to be scheduled to run 24 h a day.
* **Availability** = (observed - downtime) / observed, over all assets with observed time.
* **MTBF** = operating time (observed - downtime) / number of failures (stopping breakdowns
  that started in the window). Calendar-based: no run-hour meters exist. Undefined (null)
  when there were no failures or no operating time.
* **MTTR** = mean repair duration (start to completion) of corrective work orders completed
  in the window. **Mean time to restore** = mean downtime of breakdowns restored in the window.
* **PM compliance** = preventive tasks due in the window (before today; cancelled excluded)
  completed on or before their due date, as a share of those due.
* **Work-order completion** = work orders raised in the window that are completed, as a share
  of those raised (cancelled excluded).
Every metric reports its sample size; a metric with no data is null and the UI says
"insufficient data" instead of showing 0 % or 100 %.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..models_maintenance import (
    Breakdown,
    Equipment,
    EquipmentEvent,
    EquipmentStatus,
    MaintenanceTask,
    MovementKind,
    StockMovement,
    TaskStatus,
    WorkOrder,
    WorkOrderStatus,
    WorkOrderType,
)
from .operations import local_today, utcnow

CLOSED = (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED)

DEFINITIONS = [
    "Window: whole local days in the operations timezone, clipped to now.",
    "Downtime: time a breakdown that stopped the asset was open, clipped to the window. "
    "Breakdowns of one asset never overlap, so nothing is counted twice.",
    "Observed time: window time since the asset was registered (or since its first recorded "
    "breakdown, if that started earlier). No shift calendar exists, "
    "so equipment is assumed scheduled 24 h a day.",
    "Availability = (observed − downtime) ÷ observed.",
    "MTBF = operating time (observed − downtime) ÷ failures (stopping breakdowns that started "
    "in the window). Calendar-based: there are no run-hour meters. Not defined with no failures "
    "or no operating time.",
    "MTTR = mean start-to-completion time of corrective work orders completed in the window "
    "(includes time awaiting parts). Mean time to restore = mean downtime of breakdowns "
    "restored in the window.",
    "PM compliance = preventive tasks due in the window (before today, cancelled excluded) "
    "completed on or before the due date.",
    "Work-order completion = work orders raised in the window and completed, of those raised "
    "(cancelled excluded).",
]


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    start_at: datetime
    end_at: datetime  # exclusive, clipped to now

    @property
    def minutes(self) -> float:
        return max(0.0, (self.end_at - self.start_at).total_seconds() / 60)


def make_window(start: date | None, end: date | None, default_days: int = 30) -> Window:
    tz = get_settings().tz
    today = local_today()
    end = min(end or today, today)
    start = start or end - timedelta(days=default_days - 1)
    if start > end:
        raise ValueError("The start date must be on or before the end date.")
    if (end - start).days > 366:
        raise ValueError("The reporting window can be at most 367 days.")
    start_at = datetime.combine(start, time.min, tz).astimezone(UTC)
    end_at = min(datetime.combine(end + timedelta(days=1), time.min, tz).astimezone(UTC), utcnow())
    return Window(start, end, start_at, end_at)


def _clip_minutes(a: datetime, b: datetime | None, w: Window) -> float:
    lo, hi = max(a, w.start_at), min(b or w.end_at, w.end_at)
    return max(0.0, (hi - lo).total_seconds() / 60)


def _downtime(b: Breakdown, w: Window) -> float:
    """Minutes inside the window during which this breakdown had the asset stopped."""
    return _clip_minutes(b.started_at, b.restored_at, w) if b.equipment_down else 0.0


def _pct(num: float, den: float) -> float | None:
    return round(num / den * 100, 1) if den else None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _equipment(db: Session, w: Window, facility: str | None) -> list[Equipment]:
    q = select(Equipment).where(
        Equipment.created_at < w.end_at,
        or_(Equipment.archived_at.is_(None), Equipment.archived_at > w.start_at),
    )
    if facility:
        q = q.where(Equipment.facility == facility)
    return list(db.scalars(q.order_by(Equipment.code)))


def _breakdowns(db: Session, w: Window, ids: list[int]) -> list[Breakdown]:
    if not ids:
        return []
    return list(
        db.scalars(
            select(Breakdown)
            .options(joinedload(Breakdown.equipment))
            .where(
                Breakdown.equipment_id.in_(ids),
                Breakdown.started_at < w.end_at,
                or_(Breakdown.restored_at.is_(None), Breakdown.restored_at > w.start_at),
            )
        )
    )


def _mtbf_hours(operating: float, failures: int) -> float | None:
    # No operating time (asset down or just registered) is no evidence of reliability.
    # Two decimals keep sub-hour values meaningful (the UI shows those in minutes).
    return round(operating / 60 / failures, 2) if failures and operating > 0 else None


def per_equipment(db: Session, w: Window, facility: str | None = None) -> list[dict[str, Any]]:
    return [row for row, _, _ in _per_equipment(db, w, facility)]


def _per_equipment(
    db: Session, w: Window, facility: str | None
) -> list[tuple[dict[str, Any], float, float]]:
    """Rows plus unrounded observed and operating minutes (so totals carry no rounding error)."""
    eqs = _equipment(db, w, facility)
    ids = [e.id for e in eqs]
    bds = _breakdowns(db, w, ids)
    down: dict[int, float] = defaultdict(float)
    failures: dict[int, int] = defaultdict(int)
    events: dict[int, int] = defaultdict(int)
    # Observation starts at registration, or earlier if a breakdown was recorded as starting
    # before it (an asset registered after it failed): downtime never exceeds observed time.
    since = {e.id: e.created_at for e in eqs}
    for b in bds:
        since[b.equipment_id] = min(since[b.equipment_id], b.started_at)
        if b.started_at >= w.start_at:
            events[b.equipment_id] += 1
        if b.equipment_down:
            down[b.equipment_id] += _downtime(b, w)
            if b.started_at >= w.start_at:
                failures[b.equipment_id] += 1
    repairs: dict[int, list[float]] = defaultdict(list)
    if ids:
        for wo in db.scalars(
            select(WorkOrder).where(
                WorkOrder.equipment_id.in_(ids),
                WorkOrder.status == WorkOrderStatus.COMPLETED,
                WorkOrder.maintenance_type == WorkOrderType.CORRECTIVE,
                WorkOrder.completed_at >= w.start_at,
                WorkOrder.completed_at < w.end_at,
            )
        ):
            repairs[wo.equipment_id].append((wo.completed_at - wo.started_at).total_seconds() / 60)
    pm = pm_compliance(db, w, ids, grouped=True)
    rows = []
    for e in eqs:
        observed = _clip_minutes(since[e.id], e.archived_at, w)  # archived: until archiving
        dt = down[e.id]
        operating = max(0.0, observed - dt)
        f = failures[e.id]
        p = pm.get(e.id, {"due": 0, "on_time": 0})
        rows.append(
            (
                {
                    "equipment_id": e.id,
                    "code": e.code,
                    "name": e.name,
                    "category": e.category.value,
                    "facility": e.facility,
                    "status": e.status.value,
                    "breakdowns": events[e.id],
                    "failures": f,
                    "downtime_minutes": round(dt),
                    "observed_hours": round(observed / 60, 1),
                    "availability_pct": _pct(operating, observed),
                    "mtbf_hours": _mtbf_hours(operating, f),
                    "repairs": len(repairs[e.id]),
                    "mttr_minutes": _mean(repairs[e.id]),
                    "pm_due": p["due"],
                    "pm_on_time": p["on_time"],
                    "pm_compliance_pct": _pct(p["on_time"], p["due"]),
                },
                observed,
                operating,
            )
        )
    return rows


def pm_compliance(
    db: Session, w: Window, ids: list[int] | None = None, grouped: bool = False
) -> Any:
    last_due = min(w.end, local_today() - timedelta(days=1))
    q = select(MaintenanceTask).where(
        MaintenanceTask.due_on >= w.start,
        MaintenanceTask.due_on <= last_due,
        MaintenanceTask.status != TaskStatus.CANCELLED,
    )
    if ids is not None:
        if not ids:
            return {} if grouped else {"due": 0, "on_time": 0, "late": 0, "missed": 0, "pct": None}
        q = q.where(MaintenanceTask.equipment_id.in_(ids))
    tasks = list(db.scalars(q))
    if grouped:
        out: dict[int, dict[str, int]] = defaultdict(lambda: {"due": 0, "on_time": 0})
        for t in tasks:
            out[t.equipment_id]["due"] += 1
            out[t.equipment_id]["on_time"] += int(
                bool(t.completed_on and t.completed_on <= t.due_on)
            )
        return out
    on_time = sum(1 for t in tasks if t.completed_on and t.completed_on <= t.due_on)
    late = sum(1 for t in tasks if t.completed_on and t.completed_on > t.due_on)
    return {
        "due": len(tasks),
        "on_time": on_time,
        "late": late,
        "missed": len(tasks) - on_time - late,
        "pct": _pct(on_time, len(tasks)),
    }


def kpis(db: Session, w: Window, facility: str | None = None) -> dict[str, Any]:
    raw = _per_equipment(db, w, facility)
    rows = [r for r, _, _ in raw]
    ids = [r["equipment_id"] for r in rows]
    observed = sum(o for _, o, _ in raw)
    operating = sum(op for _, _, op in raw)
    downtime = observed - operating
    failures = sum(r["failures"] for r in rows)
    repairs = [r["mttr_minutes"] * r["repairs"] for r in rows if r["mttr_minutes"] is not None]
    n_repairs = sum(r["repairs"] for r in rows)
    restored = [
        (b.restored_at - b.started_at).total_seconds() / 60
        for b in _breakdowns(db, w, ids)
        if b.equipment_down and b.restored_at and w.start_at <= b.restored_at < w.end_at
    ]
    raised = (
        list(
            db.scalars(
                select(WorkOrder).where(
                    WorkOrder.equipment_id.in_(ids),
                    WorkOrder.created_at >= w.start_at,
                    WorkOrder.created_at < w.end_at,
                    WorkOrder.status != WorkOrderStatus.CANCELLED,
                )
            )
        )
        if ids
        else []
    )
    done = sum(1 for wo in raised if wo.status is WorkOrderStatus.COMPLETED)
    return {
        "window": {"start": w.start, "end": w.end, "days": (w.end - w.start).days + 1},
        "equipment": len(rows),
        "availability": {
            "pct": _pct(operating, observed),
            "observed_hours": round(observed / 60, 1),
            "downtime_minutes": round(downtime),
        },
        "mtbf": {
            "hours": _mtbf_hours(operating, failures),
            "failures": failures,
            "operating_hours": round(operating / 60, 2),  # 2 dp: short spans shown in minutes
        },
        "mttr": {
            "minutes": round(sum(repairs) / n_repairs, 1) if n_repairs else None,
            "repairs": n_repairs,
        },
        "time_to_restore": {"minutes": _mean(restored), "restorations": len(restored)},
        "pm_compliance": pm_compliance(db, w, ids),
        "work_order_completion": {
            "pct": _pct(done, len(raised)),
            "raised": len(raised),
            "completed": done,
        },
        "definitions": DEFINITIONS,
    }


# ---------------------------------------------------------------- dashboard
def downtime_trend(db: Session, w: Window, ids: list[int]) -> list[dict[str, Any]]:
    tz = get_settings().tz
    days = [(w.start + timedelta(days=i)) for i in range((w.end - w.start).days + 1)]
    totals = dict.fromkeys(days, 0.0)
    for b in _breakdowns(db, w, ids):
        if not b.equipment_down:
            continue
        for d in days:
            lo = datetime.combine(d, time.min, tz).astimezone(UTC)
            hi = datetime.combine(d + timedelta(days=1), time.min, tz).astimezone(UTC)
            day_w = Window(d, d, max(lo, w.start_at), min(hi, w.end_at))
            if day_w.end_at > day_w.start_at:
                totals[d] += _downtime(b, day_w)
    return [{"day": d, "downtime_minutes": round(m)} for d, m in totals.items()]


def dashboard(db: Session, days: int = 30) -> dict[str, Any]:
    w = make_window(None, None, days)
    today = local_today()
    active = Equipment.archived_at.is_(None)
    by_status = dict(
        db.execute(
            select(Equipment.status, func.count()).where(active).group_by(Equipment.status)
        ).all()
    )
    ids = list(db.scalars(select(Equipment.id).where(active)))
    open_task = MaintenanceTask.status == TaskStatus.SCHEDULED
    on_active = MaintenanceTask.equipment.has(Equipment.archived_at.is_(None))

    def tasks(*where: Any) -> int:
        return (
            db.scalar(select(func.count(MaintenanceTask.id)).where(open_task, on_active, *where))
            or 0
        )

    wo_counts = dict(
        db.execute(select(WorkOrder.status, func.count()).group_by(WorkOrder.status)).all()
    )
    overdue_wo = (
        db.scalar(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.status.not_in(CLOSED), WorkOrder.scheduled_on < today
            )
        )
        or 0
    )
    k = kpis(db, w)
    rows = per_equipment(db, w)
    top = sorted(
        (r for r in rows if r["breakdowns"]),
        key=lambda r: (-r["breakdowns"], -r["downtime_minutes"]),
    )[:5]
    cats: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for b in _breakdowns(db, w, ids):
        if b.started_at >= w.start_at:
            cats[b.category.value][0] += 1
            cats[b.category.value][1] += _downtime(b, w)
    recent = db.scalars(
        select(EquipmentEvent)
        .options(joinedload(EquipmentEvent.equipment), joinedload(EquipmentEvent.actor))
        .where(
            EquipmentEvent.kind.in_(
                (
                    "pm_task_completed",
                    "breakdown_logged",
                    "breakdown_restored",
                    "work_order_created",
                    "work_order_completed",
                    "status_changed",
                    "technician_assigned",
                )
            )
        )
        .order_by(EquipmentEvent.occurred_at.desc(), EquipmentEvent.id.desc())
        .limit(12)
    )
    return {
        "window_days": days,
        "kpis": {
            "equipment_total": sum(by_status.values()),
            "operational": by_status.get(EquipmentStatus.OPERATIONAL, 0),
            "under_maintenance": by_status.get(EquipmentStatus.UNDER_MAINTENANCE, 0),
            "out_of_service": by_status.get(EquipmentStatus.OUT_OF_SERVICE, 0),
            "open_work_orders": sum(v for s, v in wo_counts.items() if s not in CLOSED),
            "overdue_tasks": tasks(MaintenanceTask.due_on < today) + overdue_wo,
            "overdue_pm_tasks": tasks(MaintenanceTask.due_on < today),
            "overdue_work_orders": overdue_wo,
            "scheduled_pm_next_30_days": tasks(
                MaintenanceTask.due_on >= today,
                MaintenanceTask.due_on <= today + timedelta(days=30),
            ),
            "downtime_minutes": k["availability"]["downtime_minutes"],
            "completion_rate_pct": k["work_order_completion"]["pct"],
            "completion_sample": k["work_order_completion"]["raised"],
        },
        "schedule": {
            "overdue": tasks(MaintenanceTask.due_on < today),
            "due_today": tasks(MaintenanceTask.due_on == today),
            "next_7_days": tasks(
                MaintenanceTask.due_on > today, MaintenanceTask.due_on <= today + timedelta(days=7)
            ),
        },
        "work_orders": {
            "open": wo_counts.get(WorkOrderStatus.OPEN, 0),
            "assigned": wo_counts.get(WorkOrderStatus.ASSIGNED, 0),
            "in_progress": wo_counts.get(WorkOrderStatus.IN_PROGRESS, 0),
            "awaiting_parts": wo_counts.get(WorkOrderStatus.AWAITING_PARTS, 0),
            "completed_in_window": db.scalar(
                select(func.count(WorkOrder.id)).where(
                    WorkOrder.status == WorkOrderStatus.COMPLETED,
                    WorkOrder.completed_at >= w.start_at,
                )
            )
            or 0,
        },
        "metrics": {key: k[key] for key in ("availability", "mtbf", "mttr", "pm_compliance")},
        "top_failing": [
            {
                "code": r["code"],
                "name": r["name"],
                "breakdowns": r["breakdowns"],
                "downtime_minutes": r["downtime_minutes"],
            }
            for r in top
        ],
        "fault_categories": [
            {"category": c, "breakdowns": int(v[0]), "downtime_minutes": round(v[1])}
            for c, v in sorted(cats.items(), key=lambda kv: (-kv[1][0], kv[0]))
        ],
        "downtime_trend": downtime_trend(db, w, ids),
        "recent_activity": [
            {
                "id": e.id,
                "occurred_at": e.occurred_at,
                "kind": e.kind,
                "summary": e.summary,
                "equipment": {
                    "id": e.equipment.id,
                    "code": e.equipment.code,
                    "name": e.equipment.name,
                },
                "actor": e.actor.full_name if e.actor else None,
            }
            for e in recent
        ],
        "definitions": DEFINITIONS,
    }


# ---------------------------------------------------------------- report datasets
Col = tuple[str, str]  # (heading, key)


@dataclass(frozen=True)
class Report:
    title: str
    description: str
    columns: list[Col]
    rows: Callable[[Session, Window, str | None], list[dict[str, Any]]]


def _minutes(a: datetime | None, b: datetime | None) -> int | None:
    return round((b - a).total_seconds() / 60) if a and b else None


def _history(db: Session, w: Window, facility: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    q = (
        select(WorkOrder)
        .join(WorkOrder.equipment)
        .options(joinedload(WorkOrder.equipment), joinedload(WorkOrder.assigned_technician))
        .where(
            WorkOrder.status == WorkOrderStatus.COMPLETED,
            WorkOrder.completed_at >= w.start_at,
            WorkOrder.completed_at < w.end_at,
        )
    )
    if facility:
        q = q.where(Equipment.facility == facility)
    for wo in db.scalars(q):
        out.append(
            {
                "completed": wo.completed_at,
                "kind": f"Work order ({wo.maintenance_type.value})",
                "reference": wo.number,
                "equipment": wo.equipment.code,
                "equipment_name": wo.equipment.name,
                "description": wo.fault_description,
                "work": wo.work_performed,
                "technician": wo.assigned_technician.full_name if wo.assigned_technician else None,
                "duration_minutes": _minutes(wo.started_at, wo.completed_at),
            }
        )
    q = (
        select(MaintenanceTask)
        .join(MaintenanceTask.equipment)
        .options(joinedload(MaintenanceTask.equipment), joinedload(MaintenanceTask.completed_by))
        .where(
            MaintenanceTask.status == TaskStatus.COMPLETED,
            MaintenanceTask.completed_on >= w.start,
            MaintenanceTask.completed_on <= w.end,
        )
    )
    if facility:
        q = q.where(Equipment.facility == facility)
    for t in db.scalars(q):
        out.append(
            {
                "completed": t.completed_on,
                "kind": "Preventive task",
                "reference": f"PM-{t.id}",
                "equipment": t.equipment.code,
                "equipment_name": t.equipment.name,
                "description": t.title,
                "work": t.work_notes,
                "technician": t.completed_by.full_name if t.completed_by else None,
                "duration_minutes": None,
            }
        )
    return sorted(out, key=lambda r: str(r["completed"]), reverse=True)


def _faults(db: Session, w: Window, facility: str | None) -> list[dict[str, Any]]:
    eqs = _equipment(db, w, facility)
    agg: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0, 0.0])
    names = {e.code: e.name for e in eqs}
    for b in _breakdowns(db, w, [e.id for e in eqs]):
        if b.started_at < w.start_at:
            continue
        key = (b.equipment.code, b.category.value)
        agg[key][0] += 1
        agg[key][1] += _downtime(b, w)
    return [
        {
            "equipment": code,
            "equipment_name": names.get(code),
            "category": cat,
            "breakdowns": int(v[0]),
            "downtime_minutes": round(v[1]),
        }
        for (code, cat), v in sorted(agg.items(), key=lambda kv: (-kv[1][0], kv[0]))
    ]


def _repairs(db: Session, w: Window, facility: str | None) -> list[dict[str, Any]]:
    q = (
        select(WorkOrder)
        .join(WorkOrder.equipment)
        .options(joinedload(WorkOrder.equipment), joinedload(WorkOrder.assigned_technician))
        .where(
            WorkOrder.status == WorkOrderStatus.COMPLETED,
            WorkOrder.completed_at >= w.start_at,
            WorkOrder.completed_at < w.end_at,
        )
    )
    if facility:
        q = q.where(Equipment.facility == facility)
    return [
        {
            "reference": wo.number,
            "equipment": wo.equipment.code,
            "type": wo.maintenance_type.value,
            "priority": wo.priority.value,
            "started": wo.started_at,
            "completed": wo.completed_at,
            "repair_minutes": _minutes(wo.started_at, wo.completed_at),
            "technician": wo.assigned_technician.full_name if wo.assigned_technician else None,
        }
        for wo in db.scalars(q.order_by(WorkOrder.completed_at.desc()))
    ]


def _completion(db: Session, w: Window, facility: str | None) -> list[dict[str, Any]]:
    last_due = min(w.end, local_today() - timedelta(days=1))
    q = (
        select(MaintenanceTask)
        .join(MaintenanceTask.equipment)
        .options(joinedload(MaintenanceTask.equipment))
        .where(
            MaintenanceTask.due_on >= w.start,
            MaintenanceTask.due_on <= last_due,
            MaintenanceTask.status != TaskStatus.CANCELLED,
        )
    )
    if facility:
        q = q.where(Equipment.facility == facility)
    out = []
    for t in db.scalars(q.order_by(MaintenanceTask.due_on)):
        outcome = (
            "not completed"
            if not t.completed_on
            else "on time"
            if t.completed_on <= t.due_on
            else "late"
        )
        out.append(
            {
                "equipment": t.equipment.code,
                "task": t.title,
                "due": t.due_on,
                "completed": t.completed_on,
                "outcome": outcome,
                "days_late": (t.completed_on - t.due_on).days
                if t.completed_on and t.completed_on > t.due_on
                else ((local_today() - t.due_on).days if not t.completed_on else 0),
            }
        )
    return out


def _parts(db: Session, w: Window, facility: str | None) -> list[dict[str, Any]]:
    q = (
        select(StockMovement)
        .options(joinedload(StockMovement.part), joinedload(StockMovement.work_order))
        .where(
            StockMovement.kind.in_((MovementKind.ISSUE, MovementKind.RETURN)),
            StockMovement.occurred_at >= w.start_at,
            StockMovement.occurred_at < w.end_at,
        )
    )
    if facility:
        q = (
            q.join(StockMovement.work_order)
            .join(WorkOrder.equipment)
            .where(Equipment.facility == facility)
        )
    agg: dict[int, dict[str, Any]] = {}
    for m in db.scalars(q):
        a = agg.setdefault(
            m.part_id,
            {
                "part_number": m.part.part_number,
                "name": m.part.name,
                "unit": m.part.unit.value,
                "issued": 0.0,
                "returned": 0.0,
                "work_orders": set(),
                "cost": 0.0,
                "costed": True,
            },
        )
        qty = float(m.quantity)
        if m.kind is MovementKind.ISSUE:
            a["issued"] += -qty
        else:
            a["returned"] += qty
        a["work_orders"].add(m.work_order_id)
        if m.unit_cost is None:
            a["costed"] = False
        else:
            a["cost"] += -qty * float(m.unit_cost)
    return [
        {
            "part_number": a["part_number"],
            "name": a["name"],
            "unit": a["unit"],
            "issued": round(a["issued"], 3),
            "returned": round(a["returned"], 3),
            "net": round(a["issued"] - a["returned"], 3),
            "work_orders": len(a["work_orders"]),
            "cost_kes": round(a["cost"], 2) if a["costed"] else None,
        }
        for a in sorted(agg.values(), key=lambda a: -(a["issued"] - a["returned"]))
    ]


def _overdue(db: Session, w: Window, facility: str | None) -> list[dict[str, Any]]:
    today = local_today()
    q = (
        select(WorkOrder)
        .join(WorkOrder.equipment)
        .options(joinedload(WorkOrder.equipment), joinedload(WorkOrder.assigned_technician))
        .where(WorkOrder.status.not_in(CLOSED), WorkOrder.scheduled_on < today)
    )
    if facility:
        q = q.where(Equipment.facility == facility)
    return [
        {
            "reference": wo.number,
            "equipment": wo.equipment.code,
            "priority": wo.priority.value,
            "status": wo.status.value,
            "scheduled": wo.scheduled_on,
            "days_overdue": (today - wo.scheduled_on).days,
            "technician": wo.assigned_technician.full_name if wo.assigned_technician else None,
            "description": wo.fault_description,
        }
        for wo in db.scalars(q.order_by(WorkOrder.scheduled_on))
    ]


REPORTS: dict[str, Report] = {
    "equipment-downtime": Report(
        "Equipment downtime and availability",
        "Downtime, availability, MTBF and MTTR per asset.",
        [
            ("Equipment", "code"),
            ("Name", "name"),
            ("Facility", "facility"),
            ("Status", "status"),
            ("Breakdowns", "breakdowns"),
            ("Failures (stopped)", "failures"),
            ("Downtime (min)", "downtime_minutes"),
            ("Observed (h)", "observed_hours"),
            ("Availability %", "availability_pct"),
            ("MTBF (h)", "mtbf_hours"),
            ("Repairs", "repairs"),
            ("MTTR (min)", "mttr_minutes"),
            ("PM due", "pm_due"),
            ("PM on time", "pm_on_time"),
            ("PM compliance %", "pm_compliance_pct"),
        ],
        per_equipment,
    ),
    "maintenance-history": Report(
        "Maintenance history",
        "Completed work orders and preventive tasks.",
        [
            ("Completed", "completed"),
            ("Type", "kind"),
            ("Reference", "reference"),
            ("Equipment", "equipment"),
            ("Equipment name", "equipment_name"),
            ("Description", "description"),
            ("Work performed", "work"),
            ("Technician", "technician"),
            ("Duration (min)", "duration_minutes"),
        ],
        _history,
    ),
    "fault-frequency": Report(
        "Fault frequency",
        "Breakdowns that started in the window, by asset and fault category.",
        [
            ("Equipment", "equipment"),
            ("Name", "equipment_name"),
            ("Fault category", "category"),
            ("Breakdowns", "breakdowns"),
            ("Downtime (min)", "downtime_minutes"),
        ],
        _faults,
    ),
    "repair-duration": Report(
        "Repair duration",
        "Completed work orders with start-to-completion time.",
        [
            ("Work order", "reference"),
            ("Equipment", "equipment"),
            ("Type", "type"),
            ("Priority", "priority"),
            ("Started", "started"),
            ("Completed", "completed"),
            ("Repair (min)", "repair_minutes"),
            ("Technician", "technician"),
        ],
        _repairs,
    ),
    "maintenance-completion": Report(
        "Preventive maintenance completion",
        "Preventive tasks due in the window and whether they were done on time.",
        [
            ("Equipment", "equipment"),
            ("Task", "task"),
            ("Due", "due"),
            ("Completed", "completed"),
            ("Outcome", "outcome"),
            ("Days late", "days_late"),
        ],
        _completion,
    ),
    "parts-consumption": Report(
        "Spare-parts consumption",
        "Parts issued to and returned from work orders, priced at movement cost.",
        [
            ("Part number", "part_number"),
            ("Name", "name"),
            ("Unit", "unit"),
            ("Issued", "issued"),
            ("Returned", "returned"),
            ("Net used", "net"),
            ("Work orders", "work_orders"),
            ("Cost (KES)", "cost_kes"),
        ],
        _parts,
    ),
    "overdue-work-orders": Report(
        "Overdue work orders",
        "Open work orders past their scheduled date (current, not windowed).",
        [
            ("Work order", "reference"),
            ("Equipment", "equipment"),
            ("Priority", "priority"),
            ("Status", "status"),
            ("Scheduled", "scheduled"),
            ("Days overdue", "days_overdue"),
            ("Technician", "technician"),
            ("Description", "description"),
        ],
        _overdue,
    ),
}
