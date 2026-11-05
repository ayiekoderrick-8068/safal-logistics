"""Operational alerts.

Alerts are derived from live data by `refresh_alerts`, which is idempotent:
- each condition has a stable dedup key, and the database allows at most one
  unresolved alert per key (partial unique index), so repeats never duplicate;
- an existing alert is updated in place (severity may escalate, which re-opens an
  acknowledged alert);
- alerts whose condition has cleared are auto-resolved, and kept as history;
- a manually resolved alert is not re-raised for SUPPRESS_AFTER_MANUAL_RESOLVE while the
  same condition persists (an operator explicitly closed it).

Refresh runs on read (throttled by LOGITRACK_ALERT_REFRESH_SECONDS) and via
`python -m app.cli refresh-alerts` for scheduled use. No SMS / email is sent.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..models import (
    Alert,
    AlertSeverity,
    AlertStatus,
    AlertType,
    DelayIncident,
    Dispatch,
    DispatchStatus,
    DocumentType,
    IncidentStatus,
    LoadingSchedule,
    ScheduleStatus,
    Truck,
    TruckStatus,
)
from .app_settings import get_setting, set_setting, turnaround_target_minutes
from .compliance import DOC_LABELS, evaluate_trucks

REFRESHED_AT_KEY = "alerts_refreshed_at"
SUPPRESS_AFTER_MANUAL_RESOLVE = timedelta(hours=24)
_LOCK_ID = 7_351_001  # pg advisory lock: one refresher at a time
_RANK = {AlertSeverity.INFO: 0, AlertSeverity.WARNING: 1, AlertSeverity.CRITICAL: 2}


@dataclass
class Candidate:
    key: str
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    truck_id: int | None = None
    schedule_id: int | None = None
    dispatch_id: int | None = None
    document_id: int | None = None
    incident_id: int | None = None


def _mins(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def _fmt_minutes(m: int) -> str:
    return f"{m} min" if m < 120 else f"{m / 60:.1f} h"


def collect_candidates(db: Session, now: datetime) -> list[Candidate]:
    settings = get_settings()
    today = now.astimezone(settings.tz).date()
    grace = timedelta(minutes=settings.delay_grace_minutes)
    out: list[Candidate] = []

    # --- compliance & vehicle state ---
    trucks = list(db.scalars(select(Truck)))
    for tc in evaluate_trucks(db, trucks, today).values():
        t = tc.truck
        for item in tc.items:
            label = DOC_LABELS[item.doc_type]
            doc = item.document
            if item.state == "missing":
                out.append(
                    Candidate(
                        f"document_missing:{t.id}:{item.doc_type.value}",
                        AlertType.DOCUMENT_MISSING,
                        AlertSeverity.CRITICAL,
                        f"{t.registration} – {label} missing",
                        f"No current {label.lower()} on record. "
                        "It is mandatory, so dispatch is blocked.",
                        truck_id=t.id,
                    )
                )
            elif doc is not None and item.state == "expired":
                days = -(item.days_remaining or 0)
                out.append(
                    Candidate(
                        f"document_expired:{doc.id}",
                        AlertType.DOCUMENT_EXPIRED,
                        AlertSeverity.CRITICAL if item.mandatory else AlertSeverity.WARNING,
                        f"{t.registration} – {label} expired",
                        f"{label} {doc.reference_number} expired {days} day(s) ago"
                        + (" — dispatch is blocked." if item.mandatory else "."),
                        truck_id=t.id,
                        document_id=doc.id,
                    )
                )
            elif doc is not None and item.state == "expiring":
                days = item.days_remaining or 0
                is_inspection = item.doc_type == DocumentType.INSPECTION
                kind = AlertType.INSPECTION_DUE if is_inspection else AlertType.DOCUMENT_EXPIRING
                what = "inspection due" if is_inspection else f"{label} expiring"
                out.append(
                    Candidate(
                        f"{kind.value}:{doc.id}",
                        kind,
                        AlertSeverity.WARNING if days <= 7 else AlertSeverity.INFO,
                        f"{t.registration} – {what}",
                        f"{label} {doc.reference_number} expires in {days} day(s) "
                        f"on {doc.expires_on:%d %b %Y}.",
                        truck_id=t.id,
                        document_id=doc.id,
                    )
                )
        if t.status in (TruckStatus.MAINTENANCE, TruckStatus.OUT_OF_SERVICE):
            maintenance = t.status == TruckStatus.MAINTENANCE
            state = "under maintenance" if maintenance else "out of service"
            out.append(
                Candidate(
                    f"maintenance_required:{t.id}",
                    AlertType.MAINTENANCE_REQUIRED,
                    AlertSeverity.WARNING if maintenance else AlertSeverity.INFO,
                    f"{t.registration} – {state}",
                    "Vehicle is unavailable for loading and dispatch until returned to service.",
                    truck_id=t.id,
                )
            )

    # --- loading operations ---
    default_target = turnaround_target_minutes(db)
    active = db.scalars(
        select(LoadingSchedule)
        .options(joinedload(LoadingSchedule.truck), joinedload(LoadingSchedule.bay))
        .where(
            LoadingSchedule.status.in_(
                [ScheduleStatus.ARRIVED, ScheduleStatus.LOADING, ScheduleStatus.LOADED]
            )
        )
    ).unique()
    for s in active:
        reg, bay = s.truck.registration, s.bay.name
        if s.arrival_at is not None:
            target = s.bay.target_turnaround_minutes or default_target
            elapsed = _mins(now - s.arrival_at)
            if elapsed > target:
                out.append(
                    Candidate(
                        f"loading_over_target:{s.id}",
                        AlertType.LOADING_OVER_TARGET,
                        AlertSeverity.CRITICAL if elapsed > target * 1.5 else AlertSeverity.WARNING,
                        f"{reg} – over turnaround target at {bay}",
                        f"On site for {_fmt_minutes(elapsed)} "
                        f"against a {_fmt_minutes(target)} target.",
                        truck_id=s.truck_id,
                        schedule_id=s.id,
                    )
                )
        if now > s.scheduled_end + grace:
            late = _mins(now - s.scheduled_end)
            out.append(
                Candidate(
                    f"missed_dispatch:{s.id}",
                    AlertType.MISSED_DISPATCH,
                    AlertSeverity.CRITICAL if late > 120 else AlertSeverity.WARNING,
                    f"{reg} – missed dispatch time",
                    f"Booking at {bay} ended {_fmt_minutes(late)} ago and the truck "
                    f"has not been dispatched ({s.status.value}).",
                    truck_id=s.truck_id,
                    schedule_id=s.id,
                )
            )

    # --- deliveries ---
    for d in db.scalars(
        select(Dispatch)
        .options(joinedload(Dispatch.truck), joinedload(Dispatch.route))
        .where(
            Dispatch.status == DispatchStatus.IN_TRANSIT, Dispatch.expected_arrival_at + grace < now
        )
    ).unique():
        late = _mins(now - d.expected_arrival_at)
        out.append(
            Candidate(
                f"delivery_overdue:{d.id}",
                AlertType.DELIVERY_OVERDUE,
                AlertSeverity.CRITICAL if late > 120 else AlertSeverity.WARNING,
                f"{d.truck.registration} – delivery overdue",
                f"{d.load_ref} on {d.route.label} is {_fmt_minutes(late)} past its ETA.",
                truck_id=d.truck_id,
                dispatch_id=d.id,
            )
        )

    # --- delay incidents left open ---
    for i in db.scalars(
        select(DelayIncident)
        .options(
            joinedload(DelayIncident.dispatch).joinedload(Dispatch.truck),
            joinedload(DelayIncident.schedule).joinedload(LoadingSchedule.truck),
        )
        .where(
            DelayIncident.status.in_(
                [IncidentStatus.OPEN, IncidentStatus.INVESTIGATING, IncidentStatus.IN_PROGRESS]
            ),
            DelayIncident.occurred_at < now - timedelta(hours=4),
        )
    ).unique():
        age = now - i.occurred_at
        truck = i.dispatch.truck if i.dispatch else i.schedule.truck if i.schedule else None
        out.append(
            Candidate(
                f"incident_unresolved:{i.id}",
                AlertType.INCIDENT_UNRESOLVED,
                AlertSeverity.CRITICAL if age > timedelta(hours=24) else AlertSeverity.WARNING,
                f"{truck.registration if truck else 'Operation'} – delay unresolved",
                f"Delay #{i.id} ({i.cause.value.replace('_', ' ')}) has been open for "
                f"{_fmt_minutes(_mins(age))}{'' if i.assigned_to_id else ' and is unassigned'}.",
                truck_id=truck.id if truck else None,
                incident_id=i.id,
            )
        )
    return out


def refresh_alerts(db: Session, now: datetime | None = None, force: bool = False) -> dict[str, int]:
    now = now or datetime.now(UTC)
    if not force:
        last = get_setting(db, REFRESHED_AT_KEY)
        interval = get_settings().alert_refresh_seconds
        if last and now - datetime.fromisoformat(last) < timedelta(seconds=interval):
            return {"skipped": 1}
    # Serialise concurrent refreshes; the partial unique index is the final guarantee.
    if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:id)"), {"id": _LOCK_ID}):
        return {"skipped": 1}

    candidates = {c.key: c for c in collect_candidates(db, now)}
    active = {
        a.dedup_key: a
        for a in db.scalars(select(Alert).where(Alert.status != AlertStatus.RESOLVED))
    }
    suppressed = set(
        db.scalars(
            select(Alert.dedup_key).where(
                Alert.status == AlertStatus.RESOLVED,
                Alert.auto_resolved.is_(False),
                Alert.resolved_at > now - SUPPRESS_AFTER_MANUAL_RESOLVE,
            )
        )
    )
    stats = {"created": 0, "updated": 0, "resolved": 0, "escalated": 0}

    for key, c in candidates.items():
        alert = active.get(key)
        if alert is not None:
            if (
                _RANK[c.severity] > _RANK[alert.severity]
                and alert.status == AlertStatus.ACKNOWLEDGED
            ):
                alert.status, alert.acknowledged_at, alert.acknowledged_by_id = (
                    AlertStatus.OPEN,
                    None,
                    None,
                )
                stats["escalated"] += 1
            alert.severity, alert.title, alert.message, alert.last_seen_at = (
                c.severity,
                c.title,
                c.message,
                now,
            )
            stats["updated"] += 1
        elif key not in suppressed:
            db.add(
                Alert(
                    dedup_key=key,
                    alert_type=c.alert_type,
                    severity=c.severity,
                    title=c.title,
                    message=c.message,
                    truck_id=c.truck_id,
                    schedule_id=c.schedule_id,
                    dispatch_id=c.dispatch_id,
                    document_id=c.document_id,
                    incident_id=c.incident_id,
                    first_seen_at=now,
                    last_seen_at=now,
                    status=AlertStatus.OPEN,
                )
            )
            stats["created"] += 1
    for key, alert in active.items():
        if key not in candidates:
            alert.status, alert.resolved_at, alert.auto_resolved = AlertStatus.RESOLVED, now, True
            alert.resolution_note = "Condition cleared automatically."
            stats["resolved"] += 1
    set_setting(db, REFRESHED_AT_KEY, now.isoformat())
    db.commit()
    return stats


def link_for(alert: Alert) -> str:
    t = alert.alert_type
    if t in (
        AlertType.DOCUMENT_MISSING,
        AlertType.DOCUMENT_EXPIRED,
        AlertType.DOCUMENT_EXPIRING,
        AlertType.INSPECTION_DUE,
    ):
        return f"/compliance?truck={alert.truck_id}"
    if t == AlertType.MAINTENANCE_REQUIRED:
        return f"/fleet?truck={alert.truck_id}"
    if t == AlertType.MISSED_DISPATCH:
        return f"/dispatch?schedule={alert.schedule_id}"
    if t == AlertType.LOADING_OVER_TARGET:
        return "/loading-bays"
    if t == AlertType.DELIVERY_OVERDUE:
        return "/dispatch"
    return "/delays"
