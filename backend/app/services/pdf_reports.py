"""Server-side PDF reports (ReportLab), built from the same report functions as the API."""

import io
from collections.abc import Callable
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from ..config import get_settings
from ..services.compliance import DOC_LABELS
from .exports import _trucks, compliance_rows
from .reporting import (
    ReportFilters,
    bay_report,
    delay_report,
    describe_filters,
    dispatch_report,
    summary_report,
    turnaround_report,
)

TEAL = colors.HexColor("#0b3446")
PRIMARY = colors.HexColor("#0e6481")
ACCENT = colors.HexColor("#1bb3d1")
INK = colors.HexColor("#0f2b3d")
MUTED = colors.HexColor("#4a6272")
LINE = colors.HexColor("#d9e6ec")
ZEBRA = colors.HexColor("#f3f8fb")

REPORTS: dict[str, str] = {
    "executive": "Executive Operations Summary",
    "turnaround": "Truck Turnaround Performance",
    "bays": "Loading Bay Efficiency",
    "dispatch": "Dispatch & Delivery Performance",
    "delays": "Delay Incident Analysis",
    "compliance": "Compliance Summary",
}

_ss = getSampleStyleSheet()
H1 = ParagraphStyle(
    "h1",
    parent=_ss["Title"],
    fontName="Helvetica-Bold",
    fontSize=20,
    textColor=INK,
    alignment=TA_LEFT,
    spaceAfter=2,
)
H2 = ParagraphStyle(
    "h2",
    parent=_ss["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=12.5,
    textColor=INK,
    spaceBefore=10,
    spaceAfter=4,
)
BODY = ParagraphStyle(
    "body", parent=_ss["BodyText"], fontName="Helvetica", fontSize=9, textColor=INK, leading=12
)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8, textColor=MUTED, leading=10)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8, leading=10)


def clean(text: Any) -> str:
    """Escape user text for ReportLab markup and map glyphs absent from the base fonts."""
    s = "—" if text is None or text == "" else str(text)
    s = s.replace("→", "–").replace("≤", "<=").replace("≥", ">=").replace("−", "-")
    return escape(s)


def mins(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.0f} min" if v < 120 else f"{v / 60:.1f} h ({v:.0f} min)"


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}%"


def dt(v: datetime | None) -> str:
    return "—" if v is None else v.astimezone(get_settings().tz).strftime("%d %b %Y %H:%M")


class _NumberedCanvas(canvas.Canvas):
    """Two-pass canvas so every page can show 'Page X of Y'."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved: list[dict] = []

    def showPage(self) -> None:  # noqa: N802 - ReportLab API
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.setFont("Helvetica", 8)
            self.setFillColor(MUTED)
            self.drawRightString(
                self._pagesize[0] - 15 * mm, 10 * mm, f"Page {self._pageNumber} of {total}"
            )
            super().showPage()
        super().save()


def _frame(title: str, generated: str) -> Callable:
    def draw(c: canvas.Canvas, doc: SimpleDocTemplate) -> None:
        w, h = doc.pagesize
        c.saveState()
        c.setFillColor(TEAL)
        c.rect(0, h - 18 * mm, w, 18 * mm, stroke=0, fill=1)
        c.setFillColor(ACCENT)
        c.roundRect(15 * mm, h - 14 * mm, 10 * mm, 10 * mm, 2 * mm, stroke=0, fill=1)
        c.setFillColor(TEAL)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(20 * mm, h - 10.4 * mm, "LT")
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(28 * mm, h - 9 * mm, "LogiTrack")
        c.setFont("Helvetica", 8)
        c.drawString(28 * mm, h - 13 * mm, "Operations Portal")
        c.setFont("Helvetica", 9)
        c.drawRightString(w - 15 * mm, h - 10.5 * mm, title)
        c.setStrokeColor(LINE)
        c.line(15 * mm, 15 * mm, w - 15 * mm, 15 * mm)
        c.setFont("Helvetica", 8)
        c.setFillColor(MUTED)
        c.drawString(
            15 * mm, 10 * mm, f"Generated {generated} · Confidential — internal operational use"
        )
        c.restoreState()

    return draw


def table(header: list[str], body: list[list[Any]], widths: list[float] | None = None) -> Table:
    data = [[Paragraph(f"<b>{clean(h)}</b>", CELL) for h in header]]
    data += [[Paragraph(clean(c), CELL) for c in row] for row in body]
    if not body:
        data.append(
            [Paragraph("<i>No records for the selected filters.</i>", CELL)]
            + [""] * (len(header) - 1)
        )
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e4f1f7")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    style += [("BACKGROUND", (0, i), (-1, i), ZEBRA) for i in range(2, len(data), 2)]
    if not body:
        style.append(("SPAN", (0, 1), (-1, 1)))
    t.setStyle(TableStyle(style))
    return t


def kpi_grid(items: list[tuple[str, str]], cols: int = 4) -> Table:
    cells = [
        Paragraph(
            f"<font size=7 color='#4a6272'>{clean(k).upper()}</font><br/>"
            f"<font size=13><b>{clean(v)}</b></font>",
            BODY,
        )
        for k, v in items
    ]
    while len(cells) % cols:
        cells.append("")
    grid = [cells[i : i + cols] for i in range(0, len(cells), cols)]
    t = Table(grid, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return t


def bar_chart(
    title: str,
    labels: list[str],
    values: list[float | None],
    unit: str,
    width: float = 170 * mm,
    height: float = 60 * mm,
) -> Drawing:
    d = Drawing(width, height)
    d.add(
        String(
            0,
            height - 10,
            f"{title} ({unit})",
            fontName="Helvetica-Bold",
            fontSize=9,
            fillColor=INK,
        )
    )
    if not any(v for v in values):
        d.add(
            String(
                0,
                height / 2,
                "No data for the selected filters.",
                fontName="Helvetica",
                fontSize=8,
                fillColor=MUTED,
            )
        )
        return d
    ch = VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 30, 22, width - 40, height - 40
    ch.data = [[v or 0 for v in values]]
    ch.valueAxis.valueMin = 0  # honest zero baseline for counts and durations
    ch.valueAxis.labels.fontSize = 7
    ch.categoryAxis.categoryNames = labels
    ch.categoryAxis.labels.fontSize = 6.5
    ch.categoryAxis.labels.angle = 30 if len(labels) > 10 else 0
    ch.categoryAxis.labels.dy = -6 if len(labels) > 10 else -2
    ch.bars[0].fillColor = PRIMARY
    ch.barSpacing = 1
    d.add(ch)
    return d


def definitions(lines: list[str]) -> list:
    return [Paragraph("Definitions", H2)] + [Paragraph(f"• {clean(x)}", SMALL) for x in lines]


COMMON_DEFS = [
    "Yard turnaround = departure − arrival at the site; waiting = loading start − arrival; "
    "loading = loading finish − loading start. Only completed steps are averaged.",
    "Delivery duration = actual arrival − dispatch time (separate from yard turnaround).",
    "On time = delivered at or before the deadline (expected arrival + grace period). "
    "Deliveries still in transit are pending and excluded from on-time %.",
    "Loads are counted in the period in which the truck departed; dispatches in the period in which they "
    "were dispatched; delays in the period in which they started. Times are local "
    f"({get_settings().timezone}).",
]


# ---------------------------------------------------------------- report bodies
def _executive(db: Session, f: ReportFilters, hours: int) -> list:
    s = summary_report(db, f, hours)
    k = s["kpis"]
    dl = delay_report(db, f)
    bays = bay_report(db, f, hours)
    story = [
        kpi_grid(
            [
                ("Loads processed", str(k["loads_processed"])),
                ("Completed deliveries", str(k["completed_dispatches"])),
                ("On-time delivery", pct(k["on_time_pct"])),
                ("Avg yard turnaround", mins(k["avg_turnaround_minutes"])),
                ("Delayed loads", str(k["delayed_loads"])),
                ("Bay utilisation", pct(k["bay_utilization_pct"])),
                ("Compliance interruptions", str(k["compliance_interruptions"])),
                ("Delay incidents", str(k["delay_incidents"])),
            ]
        ),
        Spacer(1, 8),
    ]
    trend = s["trend"][-31:]
    story.append(
        bar_chart(
            "Loads processed per day",
            [t["day"][5:] for t in trend],
            [t["loads"] for t in trend],
            "loads",
        )
    )
    story.append(
        bar_chart(
            "Average yard turnaround per day",
            [t["day"][5:] for t in trend],
            [t["avg_turnaround_minutes"] for t in trend],
            "minutes",
        )
    )
    story += [
        Paragraph("Top delay categories", H2),
        table(
            ["Category", "Incidents", "Reported impact", "Avg resolution"],
            [
                [
                    c["cause"].replace("_", " "),
                    c["count"],
                    mins(c["impact_minutes"]),
                    mins(c["avg_resolution_minutes"]),
                ]
                for c in dl["by_cause"][:5]
            ],
        ),
        Paragraph("Loading bays", H2),
        table(
            ["Bay", "Loads", "Avg turnaround", "Target", "Utilisation"],
            [
                [
                    b["name"],
                    b["loads"],
                    mins(b["avg_turnaround_minutes"]),
                    mins(b["target_minutes"]),
                    pct(b["utilization_pct"]),
                ]
                for b in bays["bays"]
            ],
        ),
    ]
    return story + definitions(
        COMMON_DEFS
        + [
            "Delayed loads = completed loads over their bay's turnaround target, or whose delivery was late.",
            "Compliance interruptions = dispatch attempts blocked by missing/expired documents or vehicle status.",
            f"Bay utilisation = occupied bay time ÷ (active bays × days × {hours} operating hours) × 100.",
        ]
    )


def _turnaround(db: Session, f: ReportFilters, _: int) -> list:
    t = turnaround_report(db, f)
    c = t["components"]
    names = {
        "waiting": "Arrival to loading start (waiting)",
        "loading": "Loading duration",
        "post_load": "Loading finish to departure",
        "turnaround": "Yard turnaround (arrival to departure)",
        "delivery": "Dispatch to delivery",
    }
    story = [
        kpi_grid(
            [
                ("Completed loads", str(t["completed_loads"])),
                ("Ongoing loads", str(t["ongoing_loads"])),
                ("Within target", pct(t["within_target_pct"])),
                ("Global target", mins(t["target_minutes"])),
                ("Average turnaround", mins(c["turnaround"]["avg"])),
                ("Median turnaround", mins(c["turnaround"]["median"])),
            ]
        ),
        Paragraph("Duration statistics", H2),
        table(
            ["Measure", "Records", "Average", "Median", "Minimum", "Maximum"],
            [
                [
                    names[k],
                    v["count"],
                    mins(v["avg"]),
                    mins(v["median"]),
                    mins(v["min"]),
                    mins(v["max"]),
                ]
                for k, v in c.items()
            ],
        ),
        Spacer(1, 6),
        bar_chart(
            "Average yard turnaround per day",
            [d["period"][5:] for d in t["daily"][-31:]],
            [d["avg_minutes"] for d in t["daily"][-31:]],
            "minutes",
        ),
    ]
    for title, key in (
        ("By loading bay", "by_bay"),
        ("By route", "by_route"),
        ("By truck (slowest first)", "by_truck"),
    ):
        story += [
            Paragraph(title, H2),
            table(
                ["Name", "Loads", "Average", "Median", "Min", "Max", "Within target"],
                [
                    [
                        r["label"],
                        r["loads"],
                        mins(r["avg_minutes"]),
                        mins(r["median_minutes"]),
                        mins(r["min_minutes"]),
                        mins(r["max_minutes"]),
                        pct(r["within_target_pct"]),
                    ]
                    for r in t[key][:15]
                ],
            ),
        ]
    return story + definitions(COMMON_DEFS)


def _bays(db: Session, f: ReportFilters, hours: int) -> list:
    b = bay_report(db, f, hours)
    story = [
        Paragraph(f"Reporting window: {b['days']} day(s) × {hours} operating hours per day.", BODY),
        Paragraph("Bay performance", H2),
        table(
            [
                "Bay",
                "Loads",
                "Within target",
                "Delayed",
                "Avg waiting",
                "Avg loading",
                "Avg turnaround",
                "Loads/day",
                "Occupied",
                "Utilisation",
                "Peak hour",
            ],
            [
                [
                    x["name"],
                    x["loads"],
                    x["completed_within_target"],
                    x["delayed"],
                    mins(x["avg_waiting_minutes"]),
                    mins(x["avg_loading_minutes"]),
                    mins(x["avg_turnaround_minutes"]),
                    x["throughput_per_day"],
                    f"{x['occupied_hours']} h",
                    pct(x["utilization_pct"]),
                    x["peak_hour"] or "—",
                ]
                for x in b["bays"]
            ],
        ),
        Spacer(1, 8),
        bar_chart(
            "Truck arrivals by hour of day",
            [f"{p['hour']:02d}" for p in b["peak_hours"]],
            [p["arrivals"] for p in b["peak_hours"]],
            "arrivals",
        ),
    ]
    return story + definitions(
        COMMON_DEFS
        + [
            "Utilisation = recorded occupied time (arrival to departure, clipped to the period) ÷ available time "
            f"(days × {hours} h) × 100. Bays without recorded occupancy show no figure rather than 0%.",
            "Delayed = completed load whose yard turnaround exceeded the bay's target.",
        ]
    )


def _dispatch(db: Session, f: ReportFilters, _: int) -> list:
    d = dispatch_report(db, f)
    story = [
        kpi_grid(
            [
                ("Scheduled loads", str(d["scheduled_loads"])),
                ("Dispatches", str(d["dispatched"])),
                ("Trucks dispatched", str(d["dispatched_trucks"])),
                ("Completed deliveries", str(d["completed"])),
                ("On time", str(d["on_time"])),
                ("Late", str(d["late"])),
                ("Pending", str(d["pending"])),
                ("On-time rate", pct(d["on_time_pct"])),
                ("Avg delivery duration", mins(d["avg_delivery_minutes"])),
                ("Avg planned duration", mins(d["avg_planned_minutes"])),
            ]
        ),
        Spacer(1, 6),
        bar_chart(
            "Delivery lateness distribution (completed deliveries)",
            [x["bucket"].replace("–", "-") for x in d["delay_distribution"]],
            [x["count"] for x in d["delay_distribution"]],
            "deliveries",
        ),
        Paragraph("Performance by route", H2),
        table(
            [
                "Route",
                "Dispatches",
                "Completed",
                "Pending",
                "On time",
                "Planned",
                "Actual",
                "Avg lateness",
            ],
            [
                [
                    r["label"],
                    r["dispatches"],
                    r["completed"],
                    r["pending"],
                    pct(r["on_time_pct"]),
                    mins(r["avg_planned_minutes"]),
                    mins(r["avg_actual_minutes"]),
                    mins(r["avg_lateness_minutes"])
                    if (r["avg_lateness_minutes"] or 0) >= 0
                    else f"{-r['avg_lateness_minutes']:.0f} min early",
                ]
                for r in d["by_route"]
            ],
        ),
    ]
    return story + definitions(
        COMMON_DEFS
        + [
            f"Grace period: {d['grace_minutes']} minutes.",
            "Scheduled loads = loading bookings whose start falls in the period.",
        ]
    )


def _delays(db: Session, f: ReportFilters, _: int) -> list:
    d = delay_report(db, f)
    story = [
        kpi_grid(
            [
                ("Incidents", str(d["total"])),
                ("Open", str(d["open"])),
                ("Resolved", str(d["resolved"])),
                ("Reported impact", mins(d["impact_minutes"])),
                ("Avg impact", mins(d["avg_impact_minutes"])),
                ("Avg resolution time", mins(d["avg_resolution_minutes"])),
            ]
        ),
        Spacer(1, 6),
        bar_chart(
            "Incidents by category",
            [c["cause"].replace("_", " ") for c in d["by_cause"]],
            [c["count"] for c in d["by_cause"]],
            "incidents",
        ),
        Paragraph("Categories", H2),
        table(
            ["Category", "Incidents", "Reported impact", "Avg impact", "Avg resolution"],
            [
                [
                    c["cause"].replace("_", " "),
                    c["count"],
                    mins(c["impact_minutes"]),
                    mins(c["avg_impact_minutes"]),
                    mins(c["avg_resolution_minutes"]),
                ]
                for c in d["by_cause"]
            ],
        ),
    ]
    for title, key in (
        ("Most affected loading bays", "by_bay"),
        ("By route", "by_route"),
        ("By vehicle", "by_truck"),
    ):
        story += [
            Paragraph(title, H2),
            table(
                ["Name", "Incidents", "Open", "Reported impact"],
                [
                    [r["label"], r["count"], r["open"], mins(r["impact_minutes"])]
                    for r in d[key][:10]
                ],
            ),
        ]
    story += [
        Paragraph("Repeat patterns (same truck and category, 2+ incidents)", H2),
        table(
            ["Truck", "Category", "Incidents"],
            [[r["truck"], r["cause"].replace("_", " "), r["count"]] for r in d["repeat_patterns"]],
        ),
        Paragraph("Recent incidents", H2),
        table(
            ["Started", "Truck", "Category", "Status", "Duration", "Description"],
            [
                [
                    dt(i["started_at"]),
                    i["truck"],
                    i["cause"].replace("_", " "),
                    i["status"].replace("_", " "),
                    mins(i["duration_minutes"]) + (" (ongoing)" if i["ongoing"] else ""),
                    i["description"],
                ]
                for i in d["recent"]
            ],
            [28 * mm, 20 * mm, 30 * mm, 20 * mm, 30 * mm, 52 * mm],
        ),
    ]
    return story + definitions(
        COMMON_DEFS
        + [
            "Each incident is counted once, even when linked to both a loading booking and a dispatch.",
            "Reported impact = minutes of delay recorded on the incident; resolution time = resolved − started.",
        ]
    )


def _compliance(db: Session, f: ReportFilters, _: int) -> list:
    rows = compliance_rows(db, _trucks(db, f))
    trucks = {r["truck"]: r for r in rows}
    statuses = [r["vehicle_status"] for r in trucks.values()]
    issues = [r for r in rows if r["state"] in ("expired", "missing", "expiring")]
    story = [
        kpi_grid(
            [
                ("Vehicles", str(len(trucks))),
                ("Compliant", str(statuses.count("compliant"))),
                ("Expiring soon", str(statuses.count("expiring"))),
                ("Non-compliant", str(statuses.count("non_compliant"))),
                (
                    "Blocked from dispatch",
                    str(sum(1 for r in trucks.values() if not r["eligible"])),
                ),
            ]
        ),
        Paragraph("Documents needing attention", H2),
        table(
            ["Truck", "Document", "Mandatory", "State", "Reference", "Expires", "Days"],
            [
                [
                    r["truck"],
                    r["document"],
                    "yes" if r["mandatory"] else "no",
                    r["state"],
                    r["reference"],
                    r["expires_on"],
                    r["days_remaining"],
                ]
                for r in sorted(
                    issues,
                    key=lambda r: r["days_remaining"] if r["days_remaining"] is not None else -9999,
                )
            ],
        ),
        Paragraph("Vehicle status", H2),
        table(
            ["Truck", "Status", "Eligible for dispatch"],
            [
                [t, r["vehicle_status"].replace("_", " "), "yes" if r["eligible"] else "no"]
                for t, r in sorted(trucks.items())
            ],
        ),
    ]
    return story + definitions(
        [
            "Expired = past the expiry date; expiring = within the document type's reminder window; "
            "missing = mandatory document type with no current record.",
            "Mandatory document types: "
            + ", ".join(sorted({r["document"] for r in rows if r["mandatory"]}) or ["none"]),
            "This is a current snapshot; it is not limited to the reporting period.",
            "Known document types: " + ", ".join(DOC_LABELS.values()) + ".",
        ]
    )


BUILDERS: dict[str, Callable[[Session, ReportFilters, int], list]] = {
    "executive": _executive,
    "turnaround": _turnaround,
    "bays": _bays,
    "dispatch": _dispatch,
    "delays": _delays,
    "compliance": _compliance,
}


def build_pdf(db: Session, f: ReportFilters, report: str, hours_per_day: int) -> bytes:
    title = REPORTS[report]
    generated = datetime.now(get_settings().tz).strftime("%d %b %Y %H:%M %Z")
    buf = io.BytesIO()
    wide = report in ("bays",)
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4) if wide else A4,
        title=f"LogiTrack — {title}",
        author="LogiTrack",
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=26 * mm,
        bottomMargin=20 * mm,
    )
    applied = describe_filters(db, f)
    if report == "compliance":
        applied = [x for x in applied if x[0] in ("Truck", "Driver")] or [("Scope", "All vehicles")]
    story: list = [
        Paragraph(clean(title), H1),
        Paragraph(f"Generated {clean(generated)}", SMALL),
        Spacer(1, 6),
        KeepTogether(
            [
                Paragraph("Applied filters", H2),
                table(["Filter", "Value"], [[k, v] for k, v in applied], [40 * mm, 120 * mm]),
            ]
        ),
        Paragraph("Summary", H2),
    ]
    story += BUILDERS[report](db, f, hours_per_day)
    frame = _frame(title, generated)
    doc.build(story, onFirstPage=frame, onLaterPages=frame, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
