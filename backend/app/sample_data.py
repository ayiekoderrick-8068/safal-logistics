"""Clearly-labelled SAMPLE data for demonstrations.

Loading it sets the `sample_data` app setting, which the API exposes and the UI displays
as a "Sample data" banner, so demo figures are never presented as live operations.
Records are generated deterministically relative to today, then run through the same
tables and constraints as real data. The generator refuses to run on a database that
already holds non-sample operational records.
"""

import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    AuditEvent,
    ComplianceDocument,
    DelayCause,
    DelayIncident,
    Dispatch,
    DispatchStatus,
    DocumentType,
    Driver,
    IncidentStatus,
    LoadingBay,
    LoadingSchedule,
    Route,
    ScheduleStatus,
    Truck,
    TruckStatus,
)
from .services.app_settings import SAMPLE_DATA_KEY, delete_setting, is_sample_data, set_setting

DAYS = 14

DRIVERS = [
    "James Otieno",
    "Brian Ndiema",
    "Peter Mwangi",
    "Daniel Karanja",
    "Samuel Kimani",
    "Joseph Mutua",
    "Kevin Odhiambo",
    "Collins Wanjala",
    "Dennis Cheruiyot",
    "Moses Njoroge",
]
TRUCKS = [
    ("KDG 752R", "Isuzu", "FVZ", "16"),
    ("KCF 903P", "Mercedes-Benz", "Actros", "28"),
    ("KDB 118M", "Isuzu", "FSR", "10"),
    ("KCY 406B", "Scania", "P410", "26"),
    ("KDE 221Z", "Hino", "500", "15"),
    ("KDA 650T", "Isuzu", "FVZ", "16"),
    ("KCX 377K", "Mercedes-Benz", "Axor", "24"),
    ("KDC 914H", "Scania", "G460", "28"),
    ("KDF 033L", "Hino", "700", "30"),
    ("KCU 582D", "Isuzu", "NPR", "5"),
    ("KDH 207S", "FAW", "J6", "25"),
    ("KDD 469W", "Mitsubishi", "Fuso FJ", "18"),
]
ROUTES = [
    ("Nairobi", "Eldoret", "312", 330),
    ("Nairobi", "Mombasa", "485", 540),
    ("Nairobi", "Thika", "45", 75),
    ("Nairobi", "Naivasha", "92", 120),
    ("Nairobi", "Kisumu", "345", 400),
    ("Nairobi", "Nakuru", "160", 180),
]
BAYS = [
    ("BAY-01", "Bay 01", None),
    ("BAY-02", "Bay 02", None),
    ("BAY-03", "Bay 03", 150),
    ("BAY-04", "Bay 04", None),
]


def _has_operational_data(db: Session) -> bool:
    return bool(
        db.scalar(select(func.count(Truck.id))) or db.scalar(select(func.count(LoadingBay.id)))
    )


def clear_sample_data(db: Session) -> None:
    if not is_sample_data(db):
        raise RuntimeError("Refusing to clear: the database is not marked as sample data.")
    for model in (
        DelayIncident,
        Dispatch,
        LoadingSchedule,
        ComplianceDocument,
        Truck,
        Driver,
        Route,
        LoadingBay,
    ):
        db.execute(delete(model))
    db.execute(delete(AuditEvent).where(AuditEvent.action == "sample_data.loaded"))
    delete_setting(db, SAMPLE_DATA_KEY)
    db.commit()


def load_sample_data(db: Session, today: date | None = None, seed: int = 2026) -> dict[str, int]:
    if _has_operational_data(db):
        raise RuntimeError(
            "Refusing to load sample data: operational records already exist. "
            "Run `clear-sample` first (only works on sample datasets)."
        )
    rng = random.Random(seed)
    tz = get_settings().tz
    today = today or datetime.now(tz).date()
    now = datetime.now(UTC)

    drivers = [
        Driver(
            full_name=name,
            phone=f"+2547{rng.randint(10_000_000, 99_999_999)}",
            licence_number=f"DL-{rng.randint(100000, 999999)}",
            licence_expiry=today + timedelta(days=rng.randint(60, 900)),
        )
        for name in DRIVERS
    ]
    db.add_all(drivers)
    trucks = [
        Truck(
            registration=reg,
            make=make,
            model=model,
            capacity_tonnes=Decimal(cap),
            driver=drivers[i] if i < len(drivers) else None,
        )
        for i, (reg, make, model, cap) in enumerate(TRUCKS)
    ]
    db.add_all(trucks)
    routes = [
        Route(origin=o, destination=d, distance_km=Decimal(km), expected_duration_minutes=m)
        for o, d, km, m in ROUTES
    ]
    db.add_all(routes)
    bays = [LoadingBay(code=c, name=n, target_turnaround_minutes=t) for c, n, t in BAYS]
    db.add_all(bays)
    db.flush()

    counts = {"schedules": 0, "dispatches": 0, "delays": 0}
    load_no = 1045
    busy_until: dict[int, datetime] = {}  # truck id -> back at depot

    for offset in range(DAYS - 1, -1, -1):
        day = today - timedelta(days=offset)
        # Gradual improvement over the fortnight, with day-to-day noise.
        congestion = 1.0 + 0.35 * (offset / DAYS)
        for bay_idx, bay in enumerate(bays):
            slot = datetime.combine(day, time(6, 30), tzinfo=tz) + timedelta(minutes=10 * bay_idx)
            for _ in range(rng.randint(1, 3)):
                start, end = slot, slot + timedelta(hours=2, minutes=30)
                slot = end + timedelta(minutes=15)
                free = [t for t in trucks if busy_until.get(t.id, start - timedelta(1)) <= start]
                if not free:
                    break
                truck = rng.choice(free)
                busy_until[truck.id] = end
                arrival = start + timedelta(minutes=rng.randint(-10, 25))
                load_start = arrival + timedelta(minutes=int(rng.randint(8, 30) * congestion))
                load_finish = load_start + timedelta(minutes=int(rng.randint(55, 105) * congestion))
                if bay.code == "BAY-03":
                    load_finish += timedelta(minutes=rng.randint(15, 40))
                depart = load_finish + timedelta(minutes=rng.randint(8, 25))

                sched = LoadingSchedule(
                    truck=truck,
                    bay=bay,
                    scheduled_start=start,
                    scheduled_end=end,
                    status=ScheduleStatus.SCHEDULED,
                )
                db.add(sched)
                counts["schedules"] += 1

                if arrival > now:
                    continue  # future booking
                sched.arrival_at, sched.status = arrival, ScheduleStatus.ARRIVED
                if load_start > now:
                    continue
                sched.loading_started_at, sched.status = load_start, ScheduleStatus.LOADING
                if load_finish > now:
                    truck.status = TruckStatus.LOADING
                    continue
                sched.loading_finished_at, sched.status = load_finish, ScheduleStatus.LOADED
                if depart > now:
                    continue
                sched.departed_at, sched.status = depart, ScheduleStatus.DEPARTED

                route = rng.choice(routes)
                expected = depart + timedelta(minutes=route.expected_duration_minutes)
                lateness = rng.choice([-30, -20, -15, -10, -5, 0, 0, 5, 15, 40, 75])
                actual = expected + timedelta(minutes=lateness)
                dispatch = Dispatch(
                    load_ref=f"LD-{load_no}",
                    schedule=sched,
                    truck=truck,
                    route=route,
                    dispatched_at=depart,
                    expected_arrival_at=expected,
                    status=DispatchStatus.IN_TRANSIT,
                )
                load_no += 1
                if actual <= now:
                    dispatch.actual_arrival_at, dispatch.status = actual, DispatchStatus.DELIVERED
                    dispatch.is_delayed = lateness > 30
                else:
                    truck.status = TruckStatus.IN_TRANSIT
                    dispatch.is_delayed = now > expected + timedelta(minutes=30)
                busy_until[truck.id] = expected + timedelta(minutes=route.expected_duration_minutes)
                db.add(dispatch)
                counts["dispatches"] += 1

                turnaround = (depart - arrival).total_seconds() / 60
                if dispatch.is_delayed or turnaround > 170:
                    if turnaround > 170:
                        cause = rng.choice(
                            [
                                DelayCause.LOADING_CONGESTION,
                                DelayCause.LOADING_CONGESTION,
                                DelayCause.EQUIPMENT_BREAKDOWN,
                                DelayCause.DOCUMENTATION,
                            ]
                        )
                        minutes = int(turnaround - 120)
                    else:
                        cause = rng.choice(
                            [
                                DelayCause.TRAFFIC,
                                DelayCause.DOCUMENTATION,
                                DelayCause.TRUCK_UNAVAILABILITY,
                                DelayCause.OTHER,
                            ]
                        )
                        minutes = max(lateness, 31)
                    age_days = (today - day).days
                    db.add(
                        DelayIncident(
                            dispatch=dispatch,
                            schedule_id=None,
                            cause=cause,
                            delay_minutes=minutes,
                            description="Sample incident",
                            occurred_at=depart,
                            status=IncidentStatus.RESOLVED
                            if age_days > 2
                            else rng.choice(
                                [IncidentStatus.INVESTIGATING, IncidentStatus.IN_PROGRESS]
                            ),
                            resolved_at=depart + timedelta(days=1) if age_days > 2 else None,
                        )
                    )
                    counts["delays"] += 1

    trucks[-1].status = TruckStatus.MAINTENANCE

    for truck in trucks:
        for doc_type in DocumentType:
            expires = today + timedelta(
                days=rng.choice(
                    [rng.randint(-20, -1)] * 1
                    + [rng.randint(5, 30)] * 3
                    + [rng.randint(31, 330)] * 16
                )
            )
            db.add(
                ComplianceDocument(
                    truck=truck,
                    doc_type=doc_type,
                    reference_number=f"{doc_type.value[:3].upper()}-{rng.randint(10000, 99999)}",
                    issued_on=expires - timedelta(days=365),
                    expires_on=expires,
                    notes="Sample document",
                )
            )

    set_setting(db, SAMPLE_DATA_KEY, {"loaded": True, "loaded_at": now.isoformat(), "seed": seed})
    db.add(
        AuditEvent(
            action="sample_data.loaded",
            entity_type="system",
            summary="Sample demonstration dataset loaded",
            changes=counts,
        )
    )
    db.commit()
    return counts
