"""Maintenance dashboard, KPIs and reports (definitions: services/maintenance_analytics.py).

Reading needs any maintenance role; downloading CSV / Excel / PDF needs `reports.export`.
Exports reuse the logistics export machinery (formula-safe CSV, typed XLSX, branded PDF).
"""

import io
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy.orm import Session

from ..audit import record_event
from ..config import get_settings
from ..db import get_db
from ..deps import require_maintenance
from ..maintenance_permissions import MaintenancePermission as P
from ..maintenance_permissions import allows
from ..models import User
from ..services import maintenance_analytics as ma
from ..services.app_settings import is_maintenance_sample
from ..services.exports import XLSX_MAX_ROWS, write_csv, write_xlsx
from ..services.pdf_reports import (
    H1,
    H2,
    SMALL,
    _frame,
    _NumberedCanvas,
    clean,
    definitions,
    dt,
    kpi_grid,
    table,
)

router = APIRouter(prefix="/api/maintenance", tags=["maintenance: analytics"])
DB = Annotated[Session, Depends(get_db)]
Reader = Annotated[User, Depends(require_maintenance(P.VIEW))]

PREVIEW_ROWS = 500
PDF_ROWS = 300
WIDE = {"equipment-downtime", "maintenance-history", "overdue-work-orders"}
SAMPLE_NOTE = "SAMPLE demonstration data - not live maintenance records"


def _window(start: date | None, end: date | None) -> ma.Window:
    try:
        return ma.make_window(start, end)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.get("/dashboard")
def dashboard(db: DB, _: Reader, days: int = Query(30, ge=7, le=365)) -> dict[str, Any]:
    return {**ma.dashboard(db, days), "sample_data": is_maintenance_sample(db)}


@router.get("/analytics")
def analytics(
    db: DB,
    _: Reader,
    start: date | None = None,
    end: date | None = None,
    facility: str | None = Query(None, max_length=80),
) -> dict[str, Any]:
    w = _window(start, end)
    return {"kpis": ma.kpis(db, w, facility), "equipment": ma.per_equipment(db, w, facility)}


@router.get("/reports")
def list_reports(_: Reader) -> list[dict[str, str]]:
    return [
        {"key": k, "title": r.title, "description": r.description} for k, r in ma.REPORTS.items()
    ]


def _kpi_items(k: dict[str, Any]) -> list[tuple[str, str]]:
    def val(v: Any, unit: str) -> str:
        return "Insufficient data" if v is None else f"{v:,}{unit}"

    pm = k["pm_compliance"]
    return [
        ("Availability", val(k["availability"]["pct"], " %")),
        ("Downtime", f"{k['availability']['downtime_minutes']:,} min"),
        ("MTBF", val(k["mtbf"]["hours"], " h") + f" ({k['mtbf']['failures']} failures)"),
        ("MTTR", val(k["mttr"]["minutes"], " min") + f" ({k['mttr']['repairs']} repairs)"),
        ("PM compliance", val(pm["pct"], " %") + f" ({pm['on_time']}/{pm['due']})"),
        (
            "WO completion",
            val(k["work_order_completion"]["pct"], " %")
            + " ({completed}/{raised})".format(**k["work_order_completion"]),
        ),
        ("Time to restore", val(k["time_to_restore"]["minutes"], " min")),
        ("Assets in scope", str(k["equipment"])),
    ]


def _pdf(
    report: ma.Report,
    key: str,
    w: ma.Window,
    facility: str | None,
    rows: list[dict],
    k: dict,
    sample: bool = False,
) -> bytes:
    generated = datetime.now(get_settings().tz).strftime("%d %b %Y %H:%M %Z")
    buf = io.BytesIO()
    page = landscape(A4) if key in WIDE else A4
    doc = SimpleDocTemplate(
        buf,
        pagesize=page,
        title=f"LogiTrack — {report.title}",
        author="LogiTrack",
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=26 * mm,
        bottomMargin=20 * mm,
    )

    def cell(v: Any) -> str:
        if v is None:
            return "—"
        if isinstance(v, datetime):
            return dt(v)
        if isinstance(v, date):
            return v.strftime("%d %b %Y")
        return str(v)

    story: list = [
        Paragraph(clean(report.title), H1),
        Paragraph(f"Generated {clean(generated)} · {clean(report.description)}", SMALL),
        Spacer(1, 6),
        table(
            ["Filter", "Value"],
            [
                ["Period", f"{w.start:%d %b %Y} – {w.end:%d %b %Y}"],
                ["Facility", facility or "All facilities"],
                *([["Data source", SAMPLE_NOTE]] if sample else []),
            ],
            [40 * mm, 120 * mm],
        ),
        Paragraph("Key figures", H2),
        kpi_grid(_kpi_items(k)),
        Paragraph(f"Records ({len(rows):,})", H2),
        table(
            [h for h, _ in report.columns],
            [[cell(r.get(c)) for _, c in report.columns] for r in rows[:PDF_ROWS]],
        ),
    ]
    if len(rows) > PDF_ROWS:
        story.append(
            Paragraph(
                f"Showing the first {PDF_ROWS} of {len(rows):,} rows. "
                "Use CSV or Excel for all rows.",
                SMALL,
            )
        )
    story += definitions(ma.DEFINITIONS)
    frame = _frame(report.title, generated)
    doc.build(story, onFirstPage=frame, onLaterPages=frame, canvasmaker=_NumberedCanvas)
    return buf.getvalue()


@router.get("/reports/{key}")
def report(
    key: str,
    request: Request,
    db: DB,
    user: Reader,
    start: date | None = None,
    end: date | None = None,
    facility: str | None = Query(None, max_length=80),
    format_: str = Query("json", alias="format", pattern="^(json|csv|xlsx|pdf)$"),
) -> Any:
    rep = ma.REPORTS.get(key)
    if rep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    w = _window(start, end)
    rows = rep.rows(db, w, facility)
    sample = is_maintenance_sample(db)
    if format_ == "json":
        return {
            "key": key,
            "title": rep.title,
            "description": rep.description,
            "window": {"start": w.start, "end": w.end},
            "facility": facility,
            "columns": [{"label": h, "key": c} for h, c in rep.columns],
            "rows": rows[:PREVIEW_ROWS],
            "total": len(rows),
            "kpis": ma.kpis(db, w, facility),
            "sample_data": sample,
        }
    if not allows(user.effective_maintenance_role, P.EXPORT_REPORTS):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You do not have permission to export reports."
        )
    period = f"{w.start.isoformat()} to {w.end.isoformat()}"
    preamble = [
        ("Report", rep.title),
        ("Period", period),
        ("Facility", facility or "All facilities"),
        ("Generated", datetime.now(get_settings().tz).isoformat(timespec="minutes")),
    ]
    if sample:
        preamble.append(("Data source", SAMPLE_NOTE))
    columns = [(h, (lambda r, c=c: r.get(c))) for h, c in rep.columns]
    base = f"logitrack-{key}-{w.start.isoformat()}-{w.end.isoformat()}"
    if format_ == "csv":
        content, _n = write_csv(columns, rows, preamble)
        body, media, ext = content.encode("utf-8"), "text/csv; charset=utf-8", "csv"
    elif format_ == "xlsx":
        if len(rows) > XLSX_MAX_ROWS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"This export has {len(rows):,} rows; "
                f"Excel exports are limited to {XLSX_MAX_ROWS:,}.",
            )
        body = write_xlsx(columns, rows, preamble, rep.title[:31])
        media, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    else:
        body, media, ext = (
            _pdf(rep, key, w, facility, rows, ma.kpis(db, w, facility), sample),
            "application/pdf",
            "pdf",
        )
    record_event(
        db,
        action="maintenance_report.exported",
        entity_type="report",
        entity_id=key,
        actor=user,
        request=request,
        summary=f"{rep.title} exported as {ext.upper()} ({len(rows)} rows)",
        changes={"period": period, "facility": facility, "format": ext},
    )
    db.commit()
    return Response(
        body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{base}.{ext}"'},
    )
