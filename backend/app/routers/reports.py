"""Reporting API: analytics, paginated records, CSV / PDF exports and report history.

Access (enforced here, server-side):
  operational analytics (summary, turnaround, delays, bays, dispatch, records)
      view:   Administrator, Operations, Fleet Manager, Viewer
      export: Administrator, Operations, Fleet Manager
  fleet inventory export:      Administrator, Operations, Fleet Manager
  compliance report / export:  Administrator, Compliance, Fleet Manager
"""

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..audit import record_event
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import DelayCause, ReportRun, Role, User
from ..services import reporting as rpt
from ..services.exports import DATASETS, export_csv
from ..services.operations import local_today
from ..services.pdf_reports import REPORTS, build_pdf

router = APIRouter(prefix="/api/reports", tags=["reports"])
DB = Annotated[Session, Depends(get_db)]

OPS_VIEW = {Role.OPERATIONS, Role.FLEET_MANAGER, Role.VIEWER}
OPS_EXPORT = {Role.OPERATIONS, Role.FLEET_MANAGER}
FLEET_EXPORT = {Role.OPERATIONS, Role.FLEET_MANAGER}
COMPLIANCE = {Role.COMPLIANCE, Role.FLEET_MANAGER}

CSV_ACCESS = {
    **{k: OPS_EXPORT for k in ("operations", "turnaround", "schedules", "dispatches", "delays")},
    "fleet": FLEET_EXPORT,
    "compliance": COMPLIANCE,
}
PDF_ACCESS = {
    **{k: OPS_EXPORT for k in ("executive", "turnaround", "bays", "dispatch", "delays")},
    "compliance": COMPLIANCE,
}


def _allow(user: User, roles: set[Role]) -> None:
    if user.role != Role.ADMIN and user.role not in roles:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Your role does not have access to this report"
        )


def ops_viewer(user: User = Depends(get_current_user)) -> User:
    _allow(user, OPS_VIEW)
    return user


Viewer = Annotated[User, Depends(ops_viewer)]


def report_filters(
    period: str = Query(
        "last_7_days", pattern="^(today|yesterday|last_7_days|last_30_days|custom)$"
    ),
    start: date | None = None,
    end: date | None = None,
    truck_id: int | None = Query(None, ge=1),
    driver_id: int | None = Query(None, ge=1),
    bay_id: int | None = Query(None, ge=1),
    route_id: int | None = Query(None, ge=1),
    dispatch_status: str | None = Query(
        None, pattern="^(pending|in_transit|delivered|cancelled|delayed)$"
    ),
    delay_cause: DelayCause | None = None,
) -> rpt.ReportFilters:
    try:
        s, e = rpt.resolve_period(period, start, end, local_today())
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return rpt.ReportFilters(
        start=s,
        end=e,
        preset=period,
        truck_id=truck_id,
        driver_id=driver_id,
        bay_id=bay_id,
        route_id=route_id,
        dispatch_status=dispatch_status,
        delay_cause=delay_cause,
    )


Filters = Annotated[rpt.ReportFilters, Depends(report_filters)]


def hours_param(
    hours_per_day: int | None = Query(None, ge=1, le=24, description="Bay operating hours per day"),
) -> int:
    return hours_per_day or get_settings().bay_operating_hours_per_day


Hours = Annotated[int, Depends(hours_param)]


def _envelope(f: rpt.ReportFilters, db: Session, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "filters": f.as_dict(),
        "applied": [{"label": k, "value": v} for k, v in rpt.describe_filters(db, f)],
        "timezone": get_settings().timezone,
        **body,
    }


# ---------------------------------------------------------------- analytics
@router.get("/summary")
def summary(f: Filters, db: DB, _: Viewer, hours: Hours) -> dict[str, Any]:
    return _envelope(f, db, rpt.summary_report(db, f, hours))


@router.get("/turnaround")
def turnaround(f: Filters, db: DB, _: Viewer) -> dict[str, Any]:
    return _envelope(f, db, rpt.turnaround_report(db, f))


@router.get("/delays")
def delays(f: Filters, db: DB, _: Viewer) -> dict[str, Any]:
    return _envelope(f, db, rpt.delay_report(db, f))


@router.get("/bays")
def bays(f: Filters, db: DB, _: Viewer, hours: Hours) -> dict[str, Any]:
    return _envelope(f, db, rpt.bay_report(db, f, hours))


@router.get("/dispatch")
def dispatch(f: Filters, db: DB, _: Viewer) -> dict[str, Any]:
    return _envelope(f, db, rpt.dispatch_report(db, f))


@router.get("/records")
def records(
    f: Filters,
    db: DB,
    _: Viewer,
    kind: str = Query(
        "turnaround", alias="type", pattern="^(turnaround|schedules|dispatches|delays)$"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    total, items = rpt.records(db, f, kind, limit, offset)
    return {"type": kind, "total": total, "limit": limit, "offset": offset, "items": items}


# ---------------------------------------------------------------- catalogue & history
class CatalogueItem(BaseModel):
    key: str
    title: str
    formats: list[str]


@router.get("/catalogue", response_model=list[CatalogueItem])
def catalogue(user: Annotated[User, Depends(get_current_user)]) -> list[CatalogueItem]:
    """Reports and exports this user may generate (used to show/hide UI actions)."""

    def ok(roles: set[Role]) -> bool:
        return user.role == Role.ADMIN or user.role in roles

    items = [
        CatalogueItem(key=k, title=t, formats=["pdf"] + (["csv"] if k in CSV_ACCESS else []))
        for k, t in REPORTS.items()
        if ok(PDF_ACCESS[k])
    ]
    items += [
        CatalogueItem(key=k, title=t, formats=["csv"])
        for k, t in DATASETS.items()
        if k not in REPORTS and ok(CSV_ACCESS[k])
    ]
    return items


class ReportRunOut(BaseModel):
    id: int
    report_type: str
    title: str
    format: str
    status: str
    filters: dict[str, Any]
    row_count: int | None
    requested_by: str | None
    created_at: datetime


@router.get("/history", response_model=list[ReportRunOut])
def history(
    db: DB, user: Annotated[User, Depends(get_current_user)], limit: int = Query(10, ge=1, le=50)
) -> list[ReportRunOut]:
    q = (
        select(ReportRun)
        .options(joinedload(ReportRun.requested_by))
        .order_by(ReportRun.created_at.desc())
    )
    if user.role != Role.ADMIN:
        q = q.where(ReportRun.requested_by_id == user.id)  # users see their own report activity
    return [
        ReportRunOut(
            id=r.id,
            report_type=r.report_type,
            title=REPORTS.get(r.report_type) or DATASETS.get(r.report_type, r.report_type),
            format=r.format,
            status=r.status,
            filters=r.filters,
            row_count=r.row_count,
            requested_by=r.requested_by.full_name if r.requested_by else None,
            created_at=r.created_at,
        )
        for r in db.scalars(q.limit(limit)).unique()
    ]


# ---------------------------------------------------------------- exports
def _record_run(
    db: Session,
    request: Request,
    user: User,
    kind: str,
    fmt: str,
    f: rpt.ReportFilters,
    ok: bool,
    rows: int | None = None,
    error: str | None = None,
) -> None:
    db.add(
        ReportRun(
            report_type=kind,
            format=fmt,
            status="success" if ok else "failed",
            filters=f.as_dict(),
            row_count=rows,
            error=error,
            requested_by_id=user.id,
        )
    )
    record_event(
        db,
        action=f"report.{fmt}",
        entity_type="report",
        entity_id=kind,
        actor=user,
        request=request,
        summary=f"{fmt.upper()} report '{kind}' generated" + ("" if ok else " (failed)"),
        changes={"filters": f.as_dict(), "rows": rows},
    )
    db.commit()


def _filename(kind: str, f: rpt.ReportFilters, ext: str) -> str:
    return f"logitrack-{kind}-{f.start:%Y%m%d}-{f.end:%Y%m%d}.{ext}"


@router.get("/export/{dataset}.csv")
def export_csv_endpoint(
    dataset: str,
    f: Filters,
    request: Request,
    db: DB,
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    if dataset not in DATASETS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown export")
    _allow(user, CSV_ACCESS[dataset])
    try:
        content, n = export_csv(db, f, dataset)
    except Exception as exc:
        db.rollback()
        _record_run(db, request, user, dataset, "csv", f, ok=False, error=type(exc).__name__)
        raise
    _record_run(db, request, user, dataset, "csv", f, ok=True, rows=n)
    return Response(
        content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{_filename(dataset, f, "csv")}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/export/{report}.pdf")
def export_pdf_endpoint(
    report: str,
    f: Filters,
    request: Request,
    db: DB,
    hours: Hours,
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    if report not in REPORTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown report")
    _allow(user, PDF_ACCESS[report])
    try:
        pdf = build_pdf(db, f, report, hours)
    except Exception as exc:
        db.rollback()
        _record_run(db, request, user, report, "pdf", f, ok=False, error=type(exc).__name__)
        raise
    _record_run(db, request, user, report, "pdf", f, ok=True)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{_filename(report, f, "pdf")}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
