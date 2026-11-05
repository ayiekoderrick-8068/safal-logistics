"""Turnaround-time analytics: KPIs, daily trend, per-bay performance and delay causes."""

from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import DelayIncident, LoadingBay, LoadingSchedule, ScheduleStatus, User
from ..schemas import DashboardKpis, TrendPoint
from ..schemas_incidents import CauseCount, IncidentOut
from ..schemas_ops import BayOut
from ..services.dashboard import MAX_RANGE_DAYS, build_overview, local_bounds
from ..services.operations import bay_out, default_target, utcnow
from .incidents import _OPTIONS as INCIDENT_OPTIONS
from .incidents import incident_out

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
DB = Annotated[Session, Depends(get_db)]
Reader = Annotated[User, Depends(get_current_user)]


class BayTurnaround(BaseModel):
    bay: BayOut
    loads: int
    avg_turnaround_minutes: float | None
    avg_loading_minutes: float | None
    within_target_pct: float | None
    utilization_pct: float | None
    status: Literal["within", "above", "no_data"]


class TurnaroundAnalytics(BaseModel):
    period_start: date
    period_end: date
    previous_period_start: date
    previous_period_end: date
    target_minutes: int
    kpis: DashboardKpis
    trend: list[TrendPoint]
    bays: list[BayTurnaround]
    causes: list[CauseCount]
    recent_incidents: list[IncidentOut]
    sample_data: bool


def _r(v: object) -> float | None:
    return None if v is None else round(float(v), 1)  # type: ignore[arg-type]


@router.get("/turnaround", response_model=TurnaroundAnalytics)
def turnaround(
    db: DB,
    _: Reader,
    start: date | None = Query(None),
    end: date | None = Query(None),
) -> TurnaroundAnalytics:
    settings = get_settings()
    today = datetime.now(settings.tz).date()
    end = end or today
    start = start or end - timedelta(days=6)
    if start > end or (end - start).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Choose a range of 1 to {MAX_RANGE_DAYS} days with start on or before end",
        )
    overview = build_overview(db, start, end)
    s, e = local_bounds(start, end, settings.tz)
    target = default_target(db)
    days = (end - start).days + 1

    ta = func.extract("epoch", LoadingSchedule.departed_at - LoadingSchedule.arrival_at) / 60
    load = (
        func.extract(
            "epoch", LoadingSchedule.loading_finished_at - LoadingSchedule.loading_started_at
        )
        / 60
    )
    occupied = func.extract(
        "epoch",
        func.least(LoadingSchedule.departed_at, e) - func.greatest(LoadingSchedule.arrival_at, s),
    )
    rows = {
        r.bay_id: r
        for r in db.execute(
            select(
                LoadingSchedule.bay_id,
                func.count(LoadingSchedule.id).label("n"),
                func.avg(ta).label("ta"),
                func.avg(load).label("load"),
                func.count(LoadingSchedule.id)
                .filter(ta <= func.coalesce(LoadingBay.target_turnaround_minutes, target))
                .label("within"),
                func.coalesce(func.sum(occupied), 0).label("occupied"),
            )
            .join(LoadingBay, LoadingBay.id == LoadingSchedule.bay_id)
            .where(
                LoadingSchedule.departed_at >= s,
                LoadingSchedule.departed_at < e,
                LoadingSchedule.arrival_at.is_not(None),
                LoadingSchedule.status != ScheduleStatus.CANCELLED,
            )
            .group_by(LoadingSchedule.bay_id)
        )
    }
    capacity = days * settings.bay_operating_hours_per_day * 3600
    bays: list[BayTurnaround] = []
    for bay in db.scalars(select(LoadingBay).order_by(LoadingBay.code)):
        out = bay_out(bay, target)
        r = rows.get(bay.id)
        avg = _r(r.ta) if r else None
        bays.append(
            BayTurnaround(
                bay=out,
                loads=r.n if r else 0,
                avg_turnaround_minutes=avg,
                avg_loading_minutes=_r(r.load) if r else None,
                within_target_pct=round(r.within / r.n * 100, 1) if r and r.n else None,
                utilization_pct=min(100.0, round(float(r.occupied) / capacity * 100, 1))
                if r
                else (0.0 if bay.is_active else None),
                status="no_data"
                if avg is None
                else "within"
                if avg <= out.effective_target_minutes
                else "above",
            )
        )

    causes = db.execute(
        select(
            DelayIncident.cause,
            func.count(DelayIncident.id),
            func.coalesce(func.sum(DelayIncident.delay_minutes), 0),
        )
        .where(DelayIncident.occurred_at >= s, DelayIncident.occurred_at < e)
        .group_by(DelayIncident.cause)
        .order_by(func.count(DelayIncident.id).desc())
    ).all()
    now = utcnow()
    recent = db.scalars(
        select(DelayIncident)
        .options(*INCIDENT_OPTIONS)
        .where(DelayIncident.occurred_at >= s, DelayIncident.occurred_at < e)
        .order_by(DelayIncident.occurred_at.desc())
        .limit(6)
    ).unique()

    return TurnaroundAnalytics(
        period_start=start,
        period_end=end,
        previous_period_start=overview.previous_period_start,
        previous_period_end=overview.previous_period_end,
        target_minutes=target,
        kpis=overview.kpis,
        trend=overview.trend,
        bays=bays,
        causes=[CauseCount(cause=c, count=n, impact_minutes=int(m)) for c, n, m in causes],
        recent_incidents=[incident_out(i, now) for i in recent],
        sample_data=overview.sample_data,
    )
