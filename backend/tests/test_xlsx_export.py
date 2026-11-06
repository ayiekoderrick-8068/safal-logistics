"""Excel exports: workbook validity, typed cells, formatting, sanitising and parity with CSV."""

import csv
import io
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.models import ReportRun
from app.services.exports import XLSX_MEDIA_TYPE, write_xlsx, xlsx_text
from tests.test_reports import Q, ids  # noqa: F401  (shared scenario fixture)


def _book(content: bytes):
    return load_workbook(io.BytesIO(content))  # raises on an invalid workbook


def _csv_rows(text: str) -> list[list[str]]:
    """Header + data rows of a CSV export (the preamble ends at the first blank row)."""
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    return rows[rows.index([]) + 1 :]


def test_xlsx_is_a_valid_formatted_workbook(auth_client, ids) -> None:  # noqa: F811
    r = auth_client.get(f"/api/reports/export/turnaround.xlsx?{Q}&truck_id={ids['t1']}")
    assert r.status_code == 200
    assert r.headers["content-type"] == XLSX_MEDIA_TYPE
    assert (
        'filename="logitrack-turnaround-20261102-20261102.xlsx"' in r.headers["content-disposition"]
    )
    assert r.headers["cache-control"] == "no-store"
    assert zipfile.ZipFile(io.BytesIO(r.content)).testzip() is None

    wb = _book(r.content)
    assert wb.sheetnames == ["Loading turnaround records", "Report info"]
    ws = wb["Loading turnaround records"]
    header = [c.value for c in ws[1]]
    assert header[:3] == ["Booking ID", "Truck", "Driver (at the time)"]
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == f"A1:{ws.cell(1, len(header)).column_letter}3"
    assert ws["A1"].font.bold and ws["A1"].fill.start_color.rgb.endswith("0E5A6B")

    rows = [dict(zip(header, (c.value for c in row), strict=True)) for row in ws.iter_rows(2)]
    assert [x["Load ref"] for x in rows] == ["LD-1", "LD-3"]
    first = rows[0]
    # Real typed cells: local time (Africa/Nairobi) datetimes and numeric minutes.
    assert first["Arrival"] == datetime(2026, 11, 2, 6, 0)
    assert first["Yard turnaround (min)"] == 100.0
    assert isinstance(first["Booking ID"], int)
    assert first["Driver (at the time)"] == "Jane One"
    assert first["Within target"] == "yes"
    arrival_col = header.index("Arrival") + 1
    assert ws.cell(2, arrival_col).number_format == "yyyy-mm-dd hh:mm"

    info = {row[0].value: row[1].value for row in wb["Report info"].iter_rows()}
    assert info["LogiTrack report"] == "Loading turnaround records"
    assert info["Truck"] == "KAA 001A" and info["Rows"] == "2"
    assert "Africa/Nairobi" in info["Times"]


def test_xlsx_neutralises_formulas(auth_client, ids) -> None:  # noqa: F811
    r = auth_client.get(f"/api/reports/export/delays.xlsx?{Q}")
    ws = _book(r.content)["Delay incidents"]
    header = [c.value for c in ws[1]]
    col = header.index("Description") + 1
    cells = [ws.cell(i, col) for i in range(2, ws.max_row + 1)]
    evil = next(c for c in cells if c.value and "HYPERLINK" in c.value)
    assert evil.value.startswith("'=HYPERLINK") and evil.data_type == "s"
    # No formula elements anywhere in the workbook XML.
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in z.namelist():
            if name.startswith("xl/worksheets/"):
                assert b"<f>" not in z.read(name) and b"<f " not in z.read(name)


def test_xlsx_rows_match_csv_for_every_dataset(auth_client, ids) -> None:  # noqa: F811
    for dataset in (
        "operations",
        "turnaround",
        "schedules",
        "dispatches",
        "delays",
        "fleet",
        "compliance",
    ):
        x = auth_client.get(f"/api/reports/export/{dataset}.xlsx?{Q}")
        c = auth_client.get(f"/api/reports/export/{dataset}.csv?{Q}")
        assert x.status_code == c.status_code == 200, dataset
        ws = _book(x.content).worksheets[0]
        csv_rows = _csv_rows(c.text)
        assert [cell.value for cell in ws[1]] == csv_rows[0], dataset
        assert ws.max_row - 1 == len(csv_rows) - 1, dataset


def test_xlsx_filters_and_history(auth_client, ids, db) -> None:  # noqa: F811
    r = auth_client.get(f"/api/reports/export/dispatches.xlsx?{Q}&driver_id={ids['d2']}")
    ws = _book(r.content).worksheets[0]
    assert [row[0].value for row in ws.iter_rows(2)] == ["LD-2"]
    run = db.scalars(select(ReportRun).order_by(ReportRun.id.desc())).first()
    assert run.format == "xlsx" and run.row_count == 1 and run.status == "success"
    h = auth_client.get("/api/reports/history").json()
    assert (h[0]["title"], h[0]["format"]) == ("Dispatch records", "xlsx")
    assert auth_client.get("/api/reports/export/nope.xlsx").status_code == 404


def test_catalogue_offers_excel_alongside_csv(auth_client) -> None:
    items = {c["key"]: c["formats"] for c in auth_client.get("/api/reports/catalogue").json()}
    assert items["turnaround"] == ["pdf", "csv", "xlsx"]
    assert items["fleet"] == ["csv", "xlsx"]
    assert items["executive"] == ["pdf"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("=1+1", "'=1+1"),
        ("+cmd", "'+cmd"),
        ("-2", "'-2"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("ok\x00\x07text", "oktext"),
        ("x" * 40_000, "x" * 32_767),
    ],
)
def test_xlsx_text_sanitising(raw, expected) -> None:
    assert xlsx_text(raw) == expected


def test_write_xlsx_handles_types_and_empty_sets() -> None:
    cols = [("Text", lambda r: r["t"]), ("When", lambda r: r["w"]), ("Qty", lambda r: r["q"])]
    recs = [
        {"t": "=evil()", "w": datetime(2026, 11, 2, 3, 0, tzinfo=UTC), "q": Decimal("2.5")},
        {"t": None, "w": date(2026, 11, 3), "q": 3},
    ]
    wb = _book(write_xlsx(cols, recs, [("LogiTrack report", "Test")], "Test: a/b?"))
    ws = wb.worksheets[0]
    assert ws.title == "Test  a b "
    assert ws["A2"].value == "'=evil()" and ws["A2"].data_type == "s"
    assert ws["B2"].value == datetime(2026, 11, 2, 6, 0)  # UTC -> Africa/Nairobi local
    assert ws["C2"].value == 2.5 and ws["C3"].value == 3
    assert ws["A3"].value is None

    empty = _book(write_xlsx(cols, [], [], "Empty")).worksheets[0]
    assert [c.value for c in empty[1]] == ["Text", "When", "Qty"] and empty.max_row == 1
