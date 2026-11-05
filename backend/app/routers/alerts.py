from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from ..audit import record_event
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user, require_roles
from ..models import Alert, AlertSeverity, AlertStatus, AlertType, Role, User
from ..schemas_ops import Page, Ref
from ..services.alerts import link_for, refresh_alerts
from ..services.operations import commit, conflict, invalid, not_found, utcnow

router = APIRouter(prefix="/api/alerts", tags=["alerts"])
DB = Annotated[Session, Depends(get_db)]
Reader = Annotated[User, Depends(get_current_user)]
Staff = Annotated[
    User, Depends(require_roles(Role.OPERATIONS, Role.FLEET_MANAGER, Role.COMPLIANCE))
]


def _refresh_on_read(db: Session) -> None:
    """Fallback refresh when no worker runs.

    Throttled; disable with LOGITRACK_ALERT_REFRESH_ON_READ=false once the worker is running.
    """
    if get_settings().alert_refresh_on_read:
        refresh_alerts(db)


class WorkerStatus(BaseModel):
    configured_interval_seconds: int
    refresh_on_read: bool
    last_run_at: datetime | None
    last_success_at: datetime | None
    status: str  # ok | failed | stale | never_run
    consecutive_failures: int
    last_error: str | None
    last_stats: dict[str, int] | None


_SEVERITY_ORDER = case(
    {AlertSeverity.CRITICAL.value: 0, AlertSeverity.WARNING.value: 1}, value=Alert.severity, else_=2
)


class AlertOut(BaseModel):
    id: int
    alert_type: AlertType
    severity: AlertSeverity
    status: AlertStatus
    title: str
    message: str
    link: str
    truck: Ref | None
    first_seen_at: datetime
    last_seen_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_note: str | None
    auto_resolved: bool


class AlertSummary(BaseModel):
    critical: int
    warning: int
    info: int
    acknowledged: int
    total_active: int
    latest: list[AlertOut]


class ResolveIn(BaseModel):
    note: str = Field(min_length=3, max_length=500)


def _out(a: Alert) -> AlertOut:
    return AlertOut(
        id=a.id,
        alert_type=a.alert_type,
        severity=a.severity,
        status=a.status,
        title=a.title,
        message=a.message,
        link=link_for(a),
        truck=Ref(id=a.truck.id, label=a.truck.registration) if a.truck else None,
        first_seen_at=a.first_seen_at,
        last_seen_at=a.last_seen_at,
        acknowledged_at=a.acknowledged_at,
        acknowledged_by=a.acknowledged_by.full_name if a.acknowledged_by else None,
        resolved_at=a.resolved_at,
        resolved_by=a.resolved_by.full_name if a.resolved_by else None,
        resolution_note=a.resolution_note,
        auto_resolved=a.auto_resolved,
    )


_OPTIONS = (
    joinedload(Alert.truck),
    joinedload(Alert.acknowledged_by),
    joinedload(Alert.resolved_by),
)


def _get(db: Session, alert_id: int) -> Alert:
    a = db.get(Alert, alert_id, options=list(_OPTIONS))
    if a is None:
        raise not_found("Alert")
    return a


@router.get("", response_model=Page[AlertOut])
def list_alerts(
    db: DB,
    _: Reader,
    status_: str = Query(
        "active", alias="status", pattern="^(active|open|acknowledged|resolved|all)$"
    ),
    severity: AlertSeverity | None = None,
    types: str | None = Query(None, description="Comma-separated alert types"),
    truck_id: int | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[AlertOut]:
    _refresh_on_read(db)
    query = select(Alert)
    if status_ == "active":
        query = query.where(Alert.status != AlertStatus.RESOLVED)
    elif status_ != "all":
        query = query.where(Alert.status == AlertStatus(status_))
    if severity:
        query = query.where(Alert.severity == severity)
    if types:
        try:
            wanted = [AlertType(t.strip()) for t in types.split(",") if t.strip()]
        except ValueError:
            raise invalid("Unknown alert type") from None
        query = query.where(Alert.alert_type.in_(wanted))
    if truck_id:
        query = query.where(Alert.truck_id == truck_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    order = (
        (Alert.resolved_at.desc(),)
        if status_ == "resolved"
        else (_SEVERITY_ORDER, Alert.last_seen_at.desc(), Alert.id.desc())
    )
    rows = db.scalars(
        query.options(*_OPTIONS).order_by(*order).limit(limit).offset(offset)
    ).unique()
    return Page(items=[_out(a) for a in rows], total=total, limit=limit, offset=offset)


@router.get("/summary", response_model=AlertSummary)
def summary(db: DB, _: Reader) -> AlertSummary:
    _refresh_on_read(db)
    rows = dict(
        db.execute(
            select(Alert.severity, func.count(Alert.id))
            .where(Alert.status == AlertStatus.OPEN)
            .group_by(Alert.severity)
        ).all()
    )
    acknowledged = (
        db.scalar(select(func.count(Alert.id)).where(Alert.status == AlertStatus.ACKNOWLEDGED)) or 0
    )
    latest = db.scalars(
        select(Alert)
        .options(*_OPTIONS)
        .where(Alert.status == AlertStatus.OPEN)
        .order_by(_SEVERITY_ORDER, Alert.last_seen_at.desc())
        .limit(5)
    ).unique()
    return AlertSummary(
        critical=rows.get(AlertSeverity.CRITICAL, 0),
        warning=rows.get(AlertSeverity.WARNING, 0),
        info=rows.get(AlertSeverity.INFO, 0),
        acknowledged=acknowledged,
        total_active=sum(rows.values()) + acknowledged,
        latest=[_out(a) for a in latest],
    )


@router.post("/refresh")
def force_refresh(db: DB, _: Staff) -> dict[str, int]:
    return refresh_alerts(db, force=True)


@router.get("/worker-status", response_model=WorkerStatus)
def worker_status(db: DB, _: Reader) -> WorkerStatus:
    from ..services.app_settings import get_setting
    from ..worker import HEARTBEAT_KEY

    s = get_settings()
    hb = get_setting(db, HEARTBEAT_KEY) or {}
    last_run = datetime.fromisoformat(hb["last_run_at"]) if hb.get("last_run_at") else None
    status = hb.get("status", "never_run")
    # More than three missed intervals without a run means the worker is not running.
    if last_run and (utcnow() - last_run).total_seconds() > 3 * s.worker_interval_seconds:
        status = "stale"
    return WorkerStatus(
        configured_interval_seconds=s.worker_interval_seconds,
        refresh_on_read=s.alert_refresh_on_read,
        last_run_at=last_run,
        last_success_at=datetime.fromisoformat(hb["last_success_at"])
        if hb.get("last_success_at")
        else None,
        status=status,
        consecutive_failures=hb.get("consecutive_failures", 0),
        last_error=hb.get("last_error"),
        last_stats=hb.get("last_stats"),
    )


@router.post("/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge(alert_id: int, request: Request, db: DB, user: Staff) -> AlertOut:
    a = _get(db, alert_id)
    if a.status != AlertStatus.OPEN:
        raise conflict(f"Alert is already {a.status.value}.")
    a.status, a.acknowledged_at, a.acknowledged_by = AlertStatus.ACKNOWLEDGED, utcnow(), user
    record_event(
        db,
        action="alert.acknowledged",
        entity_type="alert",
        entity_id=a.id,
        actor=user,
        request=request,
        summary=f"Alert acknowledged: {a.title}"[:255],
    )
    commit(db)
    return _out(_get(db, a.id))


@router.post("/{alert_id}/resolve", response_model=AlertOut)
def resolve(alert_id: int, body: ResolveIn, request: Request, db: DB, user: Staff) -> AlertOut:
    a = _get(db, alert_id)
    if a.status == AlertStatus.RESOLVED:
        raise conflict("Alert is already resolved.")
    a.status, a.resolved_at, a.resolved_by = AlertStatus.RESOLVED, utcnow(), user
    a.resolution_note, a.auto_resolved = body.note.strip(), False
    record_event(
        db,
        action="alert.resolved",
        entity_type="alert",
        entity_id=a.id,
        actor=user,
        request=request,
        summary=f"Alert resolved: {a.title}"[:255],
        changes={"note": body.note},
    )
    commit(db)
    return _out(_get(db, a.id))
