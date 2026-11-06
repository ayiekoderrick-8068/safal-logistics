"""Reporting performance benchmark on a synthetic, clearly labelled dataset.

    LOGITRACK_DATABASE_NAME=logitrack_bench uv run python -m scripts.bench_reports \
        --scale 1 --out ../docs/benchmarks/reports-scale1.json

Safety: refuses to run unless the database name ends in ``_bench``. The database is rebuilt
from the Alembic migrations, filled with generated operations and flagged as SAMPLE data
(the UI banner and export preambles say so). It never touches development data.

Dataset per scale unit (400 days of history, so 366-day reports are fully populated):
  12 bays x 6 bookings/day, 80 trucks, 80 drivers rotated between trucks every 90 days,
  10 routes, one dispatch per departed load, ~18% of dispatches with a delay incident.
  Scale 1 ~ 28,800 bookings + 28,800 dispatches; scale 3 ~ 86,400 of each.

Measurements: each endpoint is called once to warm up, then ``--repeat`` times through
the real ASGI app (auth, validation, SQL, Python aggregation, serialisation). SQL-only
timings of the underlying row queries are recorded separately to locate bottlenecks.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import statistics
import sys
import time
from datetime import timedelta
from pathlib import Path

from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from alembic import command
from app.config import get_settings
from app.db import SessionLocal
from app.main import create_app
from app.models import DelayIncident, Dispatch, LoadingSchedule, Role, User, UserStatus
from app.security import hash_password
from app.services import reporting as rpt
from app.services.app_settings import SAMPLE_DATA_KEY, set_setting
from app.services.operations import local_today

BACKEND_DIR = Path(__file__).resolve().parents[1]
DAYS = 400
BENCH_USER = "bench-admin"


def _guard() -> str:
    name = make_url(get_settings().database_url).database or ""
    if not re.fullmatch(r"[a-z0-9_]+_bench", name):
        sys.exit(f"Refusing to run on '{name}': set LOGITRACK_DATABASE_NAME=<name>_bench.")
    return name


def rebuild(name: str) -> None:
    url = make_url(get_settings().database_url)
    server = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with server.connect() as conn:
        if not conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}):
            conn.execute(text(f'CREATE DATABASE "{name}"'))  # noqa: S608 - name validated
    server.dispose()
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = url.render_as_string(hide_password=False)
    cfg.attributes["configure_logging"] = False
    command.upgrade(cfg, "head")


SEED_SQL = """
SELECT setseed(0.2026);
INSERT INTO drivers (full_name, licence_number, licence_expiry, is_active)
SELECT 'Sample Driver ' || g, 'SMP-' || lpad(g::text, 6, '0'), CURRENT_DATE + 400, true
FROM generate_series(1, :trucks) g;
INSERT INTO trucks (registration, make, model, capacity_tonnes, status)
SELECT 'SMP ' || lpad(g::text, 3, '0') || 'X', 'Sample', 'Hauler', 10 + (g % 21), 'available'
FROM generate_series(1, :trucks) g;
INSERT INTO routes (origin, destination, distance_km, expected_duration_minutes, is_active)
SELECT 'Nairobi', 'Sample Town ' || g, 40 + g * 45, 60 + g * 45, true FROM generate_series(1, 10) g;
INSERT INTO loading_bays (code, name, target_turnaround_minutes, is_active)
SELECT 'SB-' || lpad(g::text, 2, '0'), 'Sample Bay ' || g, CASE WHEN g % 4 = 0 THEN 150 END, true
FROM generate_series(1, :bays) g;

-- Drivers rotate every 90 days: in period p, truck t is driven by driver ((t - 1 + p) % n) + 1.
INSERT INTO driver_assignments (driver_id, truck_id, assigned_at, released_at, source, note)
SELECT ((t - 1 + p) % :trucks) + 1, t,
       :start + make_interval(days => p * 90),
       CASE WHEN :start + make_interval(days => (p + 1) * 90) < now()
            THEN :start + make_interval(days => (p + 1) * 90) END,
       'sample', 'Benchmark rotation'
FROM generate_series(1, :trucks) t, generate_series(0, ceil(:days / 90.0)::int) p
WHERE :start + make_interval(days => p * 90) < now();
UPDATE trucks t SET driver_id = a.driver_id
FROM driver_assignments a WHERE a.truck_id = t.id AND a.released_at IS NULL;

-- 6 bookings per bay per day, 3 h apart; each truck loads at most once per day.
CREATE TEMP TABLE gen AS
SELECT d, b, s,
       ((s * :bays + b - 1 + d) % :trucks) + 1 AS truck_id,
       (((current_date - :days + d)::date + time '04:00' + make_interval(hours => s * 3))
           AT TIME ZONE 'Africa/Nairobi') AS start_at,
       (random() * 35 - 10)::int AS arr, (10 + random() * 25)::int AS wait,
       (55 + random() * 60)::int AS load, (8 + random() * 20)::int AS post,
       (1 + floor(random() * 10))::int AS route_id,
       (floor(random() * 11))::int AS late_bucket
FROM generate_series(0, :days - 1) d, generate_series(1, :bays) b, generate_series(0, 5) s;
-- Keep every generated event (up to ~13 h after the booking starts) in the past.
DELETE FROM gen WHERE start_at > now() - interval '16 hours';

INSERT INTO loading_schedules (truck_id, bay_id, scheduled_start, scheduled_end, arrival_at,
    loading_started_at, loading_finished_at, departed_at, status, notes)
SELECT truck_id, b, start_at, start_at + interval '150 minutes',
       start_at + make_interval(mins => arr),
       start_at + make_interval(mins => arr + wait),
       start_at + make_interval(mins => arr + wait + load),
       start_at + make_interval(mins => arr + wait + load + post),
       'departed', 'Benchmark sample'
FROM gen ORDER BY start_at, b;

INSERT INTO dispatches (load_ref, schedule_id, truck_id, route_id, dispatched_at,
    expected_arrival_at, actual_arrival_at, status, is_delayed)
SELECT 'BN-' || s.id, s.id, s.truck_id, r.id, s.departed_at,
       s.departed_at + make_interval(mins => r.expected_duration_minutes),
       s.departed_at + make_interval(mins => r.expected_duration_minutes
           + (ARRAY[-30,-20,-15,-10,-5,0,0,5,15,40,75])[g.late_bucket + 1]),
       'delivered', (ARRAY[-30,-20,-15,-10,-5,0,0,5,15,40,75])[g.late_bucket + 1] > 15
FROM loading_schedules s
JOIN gen g ON g.truck_id = s.truck_id AND g.b = s.bay_id AND g.start_at = s.scheduled_start
JOIN routes r ON r.id = g.route_id;

INSERT INTO delay_incidents (dispatch_id, cause, delay_minutes, description, status,
    occurred_at, resolved_at)
SELECT d.id,
       (ARRAY['traffic','documentation','loading_congestion','vehicle_breakdown','other'])
           [1 + (d.id % 5)],
       GREATEST(EXTRACT(EPOCH FROM d.actual_arrival_at - d.expected_arrival_at) / 60, 0)::int,
       'Benchmark sample incident', 'resolved', d.expected_arrival_at,
       d.expected_arrival_at + interval '90 minutes'
FROM dispatches d WHERE d.is_delayed;

INSERT INTO compliance_documents (truck_id, doc_type, reference_number, issuing_authority,
    issued_on, expires_on, notes)
SELECT t.id, dt, upper(left(dt, 3)) || '-' || t.id, 'Sample authority',
       CURRENT_DATE - 200, CURRENT_DATE + ((t.id * 37) % 330) - 20, 'Benchmark sample'
FROM trucks t, unnest(ARRAY['insurance','licence','inspection','roadworthy']) dt;

INSERT INTO audit_events (action, entity_type, entity_id, summary, created_at)
SELECT 'dispatch.blocked', 'loading_schedule', s.id::text, 'Benchmark sample', s.scheduled_start
FROM loading_schedules s WHERE s.id % 97 = 0;
ANALYZE;
"""


def seed(scale: int) -> dict[str, int]:
    bays, trucks = 12 * scale, 80 * scale
    with SessionLocal() as db:
        start = db.scalar(text("SELECT (current_date - :d)::timestamptz"), {"d": DAYS + 1})
        conn = db.connection()
        params = {"trucks": trucks, "bays": bays, "days": DAYS, "start": start}
        for stmt in (s.strip() for s in SEED_SQL.split(";\n")):
            if stmt:
                conn.execute(text(stmt), {k: v for k, v in params.items() if f":{k}" in stmt})
        db.add(
            User(
                username=BENCH_USER,
                email="bench-admin@example.com",
                full_name="Benchmark Admin",
                password_hash=hash_password(BENCH_PASSWORD),
                role=Role.ADMIN,
                status=UserStatus.ACTIVE,
            )
        )
        set_setting(db, SAMPLE_DATA_KEY, {"loaded": True, "benchmark": True, "scale": scale})
        db.commit()
        return {
            "bookings": db.scalar(select(func.count(LoadingSchedule.id))) or 0,
            "dispatches": db.scalar(select(func.count(Dispatch.id))) or 0,
            "incidents": db.scalar(select(func.count(DelayIncident.id))) or 0,
            "assignments": db.scalar(text("SELECT count(*) FROM driver_assignments")) or 0,
            "trucks": trucks,
            "bays": bays,
        }


BENCH_PASSWORD = os.environ.get("BENCH_PASSWORD") or "Bench-" + os.urandom(9).hex() + "-1!"


def periods() -> dict[str, str]:
    today = local_today()

    def custom(days: int) -> str:
        return f"period=custom&start={today - timedelta(days=days - 1)}&end={today}"

    return {
        "7d": "period=last_7_days",
        "30d": "period=last_30_days",
        "90d": custom(90),
        "366d": custom(366),
    }


ENDPOINTS = [
    ("summary", "/api/reports/summary"),
    ("turnaround", "/api/reports/turnaround"),
    ("delays", "/api/reports/delays"),
    ("bays", "/api/reports/bays"),
    ("dispatch", "/api/reports/dispatch"),
    ("records (page 1, 100 rows)", "/api/reports/records?type=dispatches&limit=100"),
    ("CSV turnaround", "/api/reports/export/turnaround.csv"),
    ("CSV dispatches", "/api/reports/export/dispatches.csv"),
    ("XLSX turnaround", "/api/reports/export/turnaround.xlsx"),
    ("XLSX dispatches", "/api/reports/export/dispatches.xlsx"),
    ("PDF executive", "/api/reports/export/executive.pdf"),
    ("PDF turnaround", "/api/reports/export/turnaround.pdf"),
]


def _time(fn, repeat: int) -> dict[str, float]:
    fn()  # warm-up (connection pool, caches)
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return {
        "median_ms": round(statistics.median(samples), 1),
        "max_ms": round(samples[-1], 1),
        "min_ms": round(samples[0], 1),
    }


def bench_http(repeat: int, only: set[str] | None) -> list[dict]:
    out = []
    with TestClient(create_app()) as client:
        creds = {"username": BENCH_USER, "password": BENCH_PASSWORD}
        client.post("/api/auth/login", json=creds).raise_for_status()
        for pkey, pq in periods().items():
            if only and pkey not in only:
                continue
            for label, path in ENDPOINTS:
                url = f"{path}{'&' if '?' in path else '?'}{pq}"
                size = {}

                def call(url=url, size=size):
                    resp = client.get(url)
                    if resp.status_code == 422 and "limited to" in resp.text:
                        size["bytes"], size["refused"] = 0, True  # documented Excel limit
                        return
                    resp.raise_for_status()
                    size["bytes"], size["refused"] = len(resp.content), False

                t = _time(call, repeat)
                out.append(
                    {
                        "period": pkey,
                        "endpoint": label,
                        **t,
                        "bytes": size["bytes"],
                        "refused_over_limit": size["refused"],
                    }
                )
                note = "  (refused: over Excel row limit)" if size["refused"] else ""
                print(
                    f"{pkey:>5} {label:<28} median {t['median_ms']:>8.1f} ms  "
                    f"max {t['max_ms']:>8.1f} ms  {size['bytes']:>10,} B{note}",
                    flush=True,
                )
        # Driver filter exercises the point-in-time assignment lookup.
        with SessionLocal() as db:
            driver_id = db.scalar(text("SELECT min(id) FROM drivers"))
        pq = periods()["366d"] + f"&driver_id={driver_id}"
        for label, path in (
            ("summary + driver", "/api/reports/summary"),
            ("CSV dispatches + driver", "/api/reports/export/dispatches.csv"),
        ):

            def call(url=f"{path}?{pq}"):
                client.get(url).raise_for_status()

            t = _time(call, repeat)
            out.append({"period": "366d", "endpoint": label, **t, "bytes": None})
            print(f" 366d {label:<28} median {t['median_ms']:>8.1f} ms", flush=True)
    return out


def bench_sql(repeat: int) -> list[dict]:
    """Time the raw row queries alone (no Python aggregation) for the 366-day range."""
    today = local_today()
    f = rpt.ReportFilters(start=today - timedelta(days=365), end=today, preset="custom")
    queries = {
        "load_query (departed)": lambda: rpt.load_query(f, "departed"),
        "dispatch_query": lambda: rpt.dispatch_query(f),
        "incident_query": lambda: rpt.incident_query(f),
    }
    out = []
    with SessionLocal() as db:
        for label, build in queries.items():
            n = {}

            def run(build=build, n=n):
                n["rows"] = len(db.execute(build()).all())

            t = _time(run, repeat)
            out.append({"query": label, "rows": n["rows"], **t})
            print(f"  SQL {label:<24} {n['rows']:>7,} rows  median {t['median_ms']:>8.1f} ms")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--scale", type=int, default=1)
    p.add_argument("--repeat", type=int, default=5)
    p.add_argument("--periods", help="Comma-separated subset of 7d,30d,90d,366d")
    p.add_argument("--skip-seed", action="store_true", help="Reuse the existing bench data")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)

    name = _guard()
    volume = None
    if not args.skip_seed:
        t0 = time.perf_counter()
        rebuild(name)
        volume = seed(args.scale)
        print(f"Seeded {name} in {time.perf_counter() - t0:.0f}s: {volume}", flush=True)
    else:
        with SessionLocal() as db:
            db.execute(
                text("UPDATE users SET password_hash = :h WHERE username = :u"),
                {"h": hash_password(BENCH_PASSWORD), "u": BENCH_USER},
            )
            db.commit()
    only = set(args.periods.split(",")) if args.periods else None
    result = {
        "scale": args.scale,
        "volume": volume,
        "repeat": args.repeat,
        "machine": {
            "python": platform.python_version(),
            "cpus": os.cpu_count(),
            "platform": platform.platform(),
        },
        "http": bench_http(args.repeat, only),
        "sql_366d": bench_sql(args.repeat),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, default=str))
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
