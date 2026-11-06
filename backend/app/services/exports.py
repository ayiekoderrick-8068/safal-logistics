"""CSV and Excel exports built from the same report queries as the dashboard.

- Dates/times: CSV uses ISO 8601 in the operations timezone (2026-11-05T08:30:00+03:00);
  Excel uses real date cells in local operations time (Excel has no time zones), and the
  "Report info" sheet states the zone.
- Units are in the column headings, e.g. "Turnaround (min)".
- Formula injection: text cells beginning with = + - @ TAB CR are prefixed with an apostrophe
  so spreadsheet applications treat them as text. Numbers are written as numbers. In Excel
  files every text value is additionally stored as a string cell (never a formula), and
  XML-illegal control characters are removed.
- Sensitive fields (phone numbers, licence numbers, password data, file storage keys) are
  never exported.
"""

import csv
import io
import re
from collections.abc import Callable, Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import xlsxwriter
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..models import ComplianceDocument, Truck
from .app_settings import is_sample_data
from .compliance import DOC_LABELS, evaluate_trucks
from .operations import local_today, trucks_out
from .reporting import (
    Context,
    ReportFilters,
    describe_filters,
    dispatch_query,
    dispatch_record,
    incident_query,
    incident_record,
    load_query,
    load_record,
    rows,
)

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: Any) -> Any:
    """Render one value for CSV, neutralising spreadsheet formulas in text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        return value.astimezone(get_settings().tz).isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float, Decimal)):
        return value
    text = str(value)
    if text.startswith(_DANGEROUS):
        return "'" + text
    return text


Column = tuple[str, Callable[[dict[str, Any]], Any]]


def _col(heading: str, key: str) -> Column:
    return heading, lambda r: r.get(key)


def write_csv(
    columns: list[Column],
    records: Iterable[dict[str, Any]],
    preamble: list[tuple[str, str]] | None = None,
) -> tuple[str, int]:
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel opens UTF-8 (→, é) correctly
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    for label, value in preamble or []:
        w.writerow([safe_cell(f"# {label}"), safe_cell(value)])
    if preamble:
        w.writerow([])
    w.writerow([h for h, _ in columns])
    n = 0
    for rec in records:
        w.writerow([safe_cell(fn(rec)) for _, fn in columns])
        n += 1
    return buf.getvalue(), n


LOAD_COLUMNS: list[Column] = [
    _col("Booking ID", "schedule_id"),
    _col("Truck", "truck"),
    _col("Driver (at the time)", "driver"),
    _col("Loading bay", "bay"),
    _col("Route", "route"),
    _col("Load ref", "load_ref"),
    _col("Scheduled start", "scheduled_start"),
    _col("Arrival", "arrival_at"),
    _col("Loading start", "loading_started_at"),
    _col("Loading finish", "loading_finished_at"),
    _col("Departure", "departed_at"),
    _col("Booking status", "status"),
    _col("Waiting (min)", "waiting_minutes"),
    _col("Loading (min)", "loading_minutes"),
    _col("Finish to departure (min)", "post_load_minutes"),
    _col("Yard turnaround (min)", "turnaround_minutes"),
    _col("Turnaround target (min)", "target_minutes"),
    _col("Within target", "within_target"),
    _col("Dispatched", "dispatched_at"),
    _col("Expected arrival", "expected_arrival_at"),
    _col("Actual arrival", "actual_arrival_at"),
    _col("Delivery duration (min)", "delivery_minutes"),
    _col("Delivery outcome", "delivery_outcome"),
]
DISPATCH_COLUMNS: list[Column] = [
    _col("Load ref", "load_ref"),
    _col("Truck", "truck"),
    _col("Driver (at the time)", "driver"),
    _col("Route", "route"),
    _col("Loading bay", "bay"),
    _col("Dispatched", "dispatched_at"),
    _col("Expected arrival", "expected_arrival_at"),
    _col("On-time deadline", "deadline_at"),
    _col("Actual arrival", "actual_arrival_at"),
    _col("Status", "status"),
    _col("Flagged delayed", "flagged_delayed"),
    _col("Planned duration (min)", "planned_minutes"),
    _col("Actual duration (min)", "delivery_minutes"),
    _col("Lateness vs expected (min)", "lateness_minutes"),
    _col("Outcome", "outcome"),
]
DELAY_COLUMNS: list[Column] = [
    _col("Incident ID", "id"),
    _col("Started", "started_at"),
    _col("Resolved", "resolved_at"),
    _col("Status", "status"),
    _col("Category", "cause"),
    _col("Truck", "truck"),
    _col("Loading bay", "bay"),
    _col("Route", "route"),
    _col("Load ref", "load_ref"),
    _col("Reported impact (min)", "impact_minutes"),
    _col("Duration (min)", "duration_minutes"),
    _col("Ongoing", "ongoing"),
    _col("Assigned to", "assigned_to"),
    _col("Description", "description"),
]
FLEET_COLUMNS: list[Column] = [
    _col("Registration", "registration"),
    _col("Make", "make"),
    _col("Model", "model"),
    _col("Capacity (t)", "capacity_tonnes"),
    _col("Status", "status"),
    _col("Driver", "driver"),
    _col("Last route", "last_route"),
    _col("Last dispatched", "last_dispatched_at"),
    _col("Compliance", "compliance"),
    _col("Next expiry", "next_expiry"),
    _col("Next expiry document", "next_expiry_type"),
    _col("Eligible for dispatch", "eligible"),
]
COMPLIANCE_COLUMNS: list[Column] = [
    _col("Truck", "truck"),
    _col("Vehicle status", "vehicle_status"),
    _col("Document", "document"),
    _col("Mandatory", "mandatory"),
    _col("State", "state"),
    _col("Reference", "reference"),
    _col("Issuing authority", "authority"),
    _col("Issued", "issued_on"),
    _col("Expires", "expires_on"),
    _col("Days remaining", "days_remaining"),
    _col("Eligible for dispatch", "eligible"),
]

DATASETS = {
    "operations": "Filtered operational report",
    "turnaround": "Loading turnaround records",
    "schedules": "Loading schedules",
    "dispatches": "Dispatch records",
    "delays": "Delay incidents",
    "fleet": "Fleet inventory",
    "compliance": "Compliance summary",
}


def dataset_rows(
    db: Session, f: ReportFilters, dataset: str
) -> tuple[list[Column], list[dict[str, Any]]]:
    ctx = Context(db, f)
    if dataset in ("operations", "turnaround"):
        q = load_query(f, "departed")
        return LOAD_COLUMNS, [
            load_record(r, ctx.target) for r in rows(db, q.order_by(q.selected_columns.departed_at))
        ]
    if dataset == "schedules":
        q = load_query(f, "scheduled")
        return LOAD_COLUMNS, [
            load_record(r, ctx.target)
            for r in rows(db, q.order_by(q.selected_columns.scheduled_start))
        ]
    if dataset == "dispatches":
        q = dispatch_query(f)
        return DISPATCH_COLUMNS, [
            dispatch_record(r) for r in rows(db, q.order_by(q.selected_columns.dispatched_at))
        ]
    if dataset == "delays":
        q = incident_query(f)
        return DELAY_COLUMNS, [
            incident_record(r, ctx.now)
            for r in rows(db, q.order_by(q.selected_columns.occurred_at))
        ]
    trucks = _trucks(db, f)
    if dataset == "fleet":
        recs = []
        for t in trucks_out(db, trucks):
            recs.append(
                {
                    "registration": t.registration,
                    "make": t.make,
                    "model": t.model,
                    "capacity_tonnes": t.capacity_tonnes,
                    "status": t.status.value,
                    "driver": t.driver.label if t.driver else None,
                    "last_route": t.last_route,
                    "last_dispatched_at": t.last_dispatched_at,
                    "compliance": t.compliance.status,
                    "next_expiry": t.compliance.next_expiry,
                    "next_expiry_type": DOC_LABELS[t.compliance.next_expiry_type]
                    if t.compliance.next_expiry_type
                    else None,
                    "eligible": t.compliance.eligible,
                }
            )
        return FLEET_COLUMNS, recs
    if dataset == "compliance":
        return COMPLIANCE_COLUMNS, compliance_rows(db, trucks)
    raise ValueError(f"Unknown dataset {dataset}")


def _trucks(db: Session, f: ReportFilters) -> list[Truck]:
    q = select(Truck).options(joinedload(Truck.driver)).order_by(Truck.registration)
    if f.truck_id:
        q = q.where(Truck.id == f.truck_id)
    if f.driver_id:
        q = q.where(Truck.driver_id == f.driver_id)
    return list(db.scalars(q).unique())


def compliance_rows(db: Session, trucks: list[Truck]) -> list[dict[str, Any]]:
    out = []
    for tc in evaluate_trucks(db, trucks, local_today()).values():
        for item in tc.items:
            if item.state == "not_required":
                continue
            doc: ComplianceDocument | None = item.document
            out.append(
                {
                    "truck": tc.truck.registration,
                    "vehicle_status": tc.status,
                    "document": DOC_LABELS[item.doc_type],
                    "mandatory": item.mandatory,
                    "state": item.state,
                    "reference": doc.reference_number if doc else None,
                    "authority": doc.issuing_authority if doc else None,
                    "issued_on": doc.issued_on if doc else None,
                    "expires_on": doc.expires_on if doc else None,
                    "days_remaining": item.days_remaining,
                    "eligible": tc.eligible,
                }
            )
    return out


def export_preamble(db: Session, f: ReportFilters, dataset: str) -> list[tuple[str, str]]:
    """Title, generation time, data source and applied filters - shared by CSV and Excel."""
    preamble = [
        ("LogiTrack report", DATASETS[dataset]),
        ("Generated", datetime.now(get_settings().tz).isoformat(timespec="seconds")),
    ]
    if is_sample_data(db):
        preamble.append(("Data source", "SAMPLE demonstration data - not live operations"))
    if dataset in ("fleet", "compliance"):
        preamble += [(k, v) for k, v in describe_filters(db, f) if k in ("Truck", "Driver")]
        preamble.append(("Note", "Current snapshot (not limited to the reporting period)"))
    else:
        preamble += describe_filters(db, f)
    return preamble


def export_csv(db: Session, f: ReportFilters, dataset: str) -> tuple[str, int]:
    columns, recs = dataset_rows(db, f, dataset)
    return write_csv(columns, recs, export_preamble(db, f, dataset))


# ---------------------------------------------------------------- Excel (.xlsx)
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Excel generation is CPU-bound (~1-2 s per 10,000 rows on modest hardware). Above this
# limit the export is refused with a clear message; CSV has no such limit.
XLSX_MAX_ROWS = 50_000
_TEAL = "#0E5A6B"  # LogiTrack brand teal
_MAX_CELL = 32_767  # Excel's limit for one cell
# XML 1.0 cannot carry these control characters; Excel rejects files containing them.
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class ExportTooLarge(ValueError):
    """The requested Excel export exceeds XLSX_MAX_ROWS."""


def xlsx_text(value: Any) -> str:
    """Text for an Excel cell: formula-safe, free of XML-illegal control characters."""
    text = safe_cell(value)
    text = text if isinstance(text, str) else str(text)
    return _ILLEGAL_XML.sub("", text)[:_MAX_CELL]


def _width(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, datetime):
        return 16
    if isinstance(value, date):
        return 10
    return min(len(str(value)), 60)


def write_xlsx(
    columns: list[Column],
    records: list[dict[str, Any]],
    preamble: list[tuple[str, str]],
    sheet_title: str,
) -> bytes:
    """Build the workbook with explicitly typed writes.

    Every text value goes through ``write_string`` (never interpreted as a formula, URL or
    number), numbers through ``write_number`` and dates through ``write_datetime`` in
    operations local time - Excel has no time zones, so the info sheet states the zone.
    """
    tz = get_settings().tz
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(
        buf,
        {
            "constant_memory": True,  # stream rows; memory stays flat for large exports
            "strings_to_formulas": False,
            "strings_to_urls": False,
            "strings_to_numbers": False,
        },
    )
    wb.set_properties({"title": sheet_title, "author": "LogiTrack", "company": "LogiTrack"})
    header_fmt = wb.add_format(
        {
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": _TEAL,
            "text_wrap": True,
            "valign": "vcenter",
            "border": 1,
            "border_color": _TEAL,
        }
    )
    label_fmt = wb.add_format({"bold": True, "font_color": _TEAL})
    dt_fmt = wb.add_format({"num_format": "yyyy-mm-dd hh:mm"})
    d_fmt = wb.add_format({"num_format": "yyyy-mm-dd"})
    int_fmt = wb.add_format({"num_format": "0"})
    num_fmt = wb.add_format({"num_format": "0.0"})

    ws = wb.add_worksheet(re.sub(r"[\[\]:*?/\\]", " ", sheet_title)[:31])
    values = [[fn(r) for _, fn in columns] for r in records]
    for i, (heading, _) in enumerate(columns):
        widest = max([len(heading)] + [_width(row[i]) for row in values[:2000]])
        ws.set_column(i, i, widest + 2)
    ws.freeze_panes(1, 0)
    if columns:
        ws.autofilter(0, 0, max(len(values), 1), len(columns) - 1)
    for c, (heading, _) in enumerate(columns):
        ws.write_string(0, c, xlsx_text(heading), header_fmt)

    write_string, write_number, write_datetime = ws.write_string, ws.write_number, ws.write_datetime
    for r, row in enumerate(values, start=1):
        for c, v in enumerate(row):
            if v is None:
                continue
            if isinstance(v, bool):
                write_string(r, c, "yes" if v else "no")
            elif isinstance(v, datetime):
                write_datetime(r, c, v.astimezone(tz).replace(tzinfo=None), dt_fmt)
            elif isinstance(v, date):
                write_datetime(r, c, datetime(v.year, v.month, v.day), d_fmt)
            elif isinstance(v, int):
                write_number(r, c, v, int_fmt)
            elif isinstance(v, (float, Decimal)):
                write_number(r, c, float(v), num_fmt)
            else:
                write_string(r, c, xlsx_text(v))

    info = wb.add_worksheet("Report info")
    info.set_column(0, 0, 22)
    info.set_column(1, 1, 70)
    rows_info = [
        *preamble,
        ("Rows", str(len(values))),
        ("Times", f"Local time ({get_settings().timezone}); durations in minutes"),
    ]
    for r, (label, value) in enumerate(rows_info):
        info.write_string(r, 0, xlsx_text(label), label_fmt)
        info.write_string(r, 1, xlsx_text(value))

    wb.close()
    return buf.getvalue()


def export_xlsx(db: Session, f: ReportFilters, dataset: str) -> tuple[bytes, int]:
    columns, recs = dataset_rows(db, f, dataset)
    if len(recs) > XLSX_MAX_ROWS:
        raise ExportTooLarge(
            f"This export has {len(recs):,} rows; Excel exports are limited to "
            f"{XLSX_MAX_ROWS:,}. Narrow the date range or filters, or use CSV."
        )
    content = write_xlsx(columns, recs, export_preamble(db, f, dataset), DATASETS[dataset])
    return content, len(recs)
