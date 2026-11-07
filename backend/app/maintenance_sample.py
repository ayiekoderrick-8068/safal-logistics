"""Clearly-labelled SAMPLE data for the Maintenance Operations workspace.

Loading sets the `maintenance_sample_data` app setting; the API reports it and the UI shows a
"Sample data" banner on every maintenance page, and every export says so, so demonstration
figures are never presented as live maintenance records.

The dataset is generated deterministically relative to today (120 days of history) and obeys
the same rules as real data: one open breakdown per asset and no overlapping breakdowns, one
open preventive task per plan, next due dates from the plan interval, equipment status that
follows open breakdowns and work, and a stock ledger whose balances never go negative.
Work is attributed to sample technician accounts that are deactivated (no one can sign in as
them) and named "(sample)". The generator refuses to run if maintenance records already exist.
"""

import random
import secrets
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AuditEvent, MaintenanceRole, Role, User, UserStatus
from .models_maintenance import (
    Breakdown,
    BreakdownSeverity,
    Equipment,
    EquipmentCategory,
    EquipmentEvent,
    EquipmentStatus,
    FaultCategory,
    IntervalUnit,
    MaintenancePlan,
    MaintenanceTask,
    MovementKind,
    SparePart,
    StockMovement,
    StockUnit,
    TaskStatus,
    WorkOrder,
    WorkOrderEvent,
    WorkOrderPriority,
    WorkOrderStatus,
    WorkOrderType,
)
from .security import hash_password
from .services.app_settings import (
    MAINTENANCE_SAMPLE_KEY,
    delete_setting,
    is_maintenance_sample,
    set_setting,
)
from .services.pm import add_interval, sync_equipment_dates

HISTORY_DAYS = 120
SAMPLE_USER_PREFIX = "sample."
WO_STATUS = WorkOrderStatus

PEOPLE = [
    ("grace", "Grace Wanjiru", MaintenanceRole.TECHNICIAN),
    ("brian", "Brian Ochieng", MaintenanceRole.TECHNICIAN),
    ("faith", "Faith Chebet", MaintenanceRole.TECHNICIAN),
    ("ruth", "Ruth Akinyi", MaintenanceRole.PLANNER),
]

C = EquipmentCategory
# code, name, category, manufacturer, model, facility, department, location,
# technician index, daily failure probability, registered days ago (None = start of history)
EQUIPMENT = [
    (
        "CNV-101",
        "Line 1 infeed conveyor",
        C.CONVEYOR,
        "Interroll",
        "RM 8.2",
        "Nairobi Plant",
        "Packaging",
        "Line 1",
        0,
        0.035,
        None,
    ),
    (
        "CNV-102",
        "Line 2 packing conveyor",
        C.CONVEYOR,
        "Interroll",
        "RM 8.2",
        "Nairobi Plant",
        "Packaging",
        "Line 2",
        0,
        0.05,
        None,
    ),
    (
        "MTR-201",
        "Mixer drive motor",
        C.MOTOR,
        "WEG",
        "W22 37 kW",
        "Nairobi Plant",
        "Production",
        "Mixing hall",
        1,
        0.012,
        None,
    ),
    (
        "CMP-301",
        "Main air compressor",
        C.COMPRESSOR,
        "Atlas Copco",
        "GA37 VSD",
        "Nairobi Plant",
        "Utilities",
        "Compressor room",
        1,
        0.03,
        None,
    ),
    (
        "CMP-302",
        "Standby air compressor",
        C.COMPRESSOR,
        "Atlas Copco",
        "GA30",
        "Nairobi Plant",
        "Utilities",
        "Compressor room",
        1,
        0.008,
        None,
    ),
    (
        "HYD-401",
        "Baling press hydraulic unit",
        C.HYDRAULIC_SYSTEM,
        "Bosch Rexroth",
        "ABPAC",
        "Nairobi Plant",
        "Production",
        "Baling area",
        2,
        0.015,
        None,
    ),
    (
        "PMP-501",
        "Cooling water pump",
        C.PUMP,
        "Grundfos",
        "NB 65-200",
        "Nairobi Plant",
        "Utilities",
        "Cooling tower",
        2,
        0.04,
        None,
    ),
    (
        "PMP-502",
        "Effluent transfer pump",
        C.PUMP,
        "KSB",
        "Etanorm 50",
        "Nairobi Plant",
        "Utilities",
        "Effluent plant",
        2,
        0.015,
        None,
    ),
    (
        "PRD-601",
        "Bottle filler",
        C.PRODUCTION_MACHINE,
        "Krones",
        "Modulfill",
        "Nairobi Plant",
        "Production",
        "Line 1",
        0,
        0.03,
        None,
    ),
    (
        "PRD-602",
        "Carton erector",
        C.PRODUCTION_MACHINE,
        "Smurfit Westrock",
        "CE-25",
        "Nairobi Plant",
        "Packaging",
        "Line 2",
        0,
        0.03,
        26,
    ),
    (
        "GEN-701",
        "Standby generator 500 kVA",
        C.GENERATOR,
        "Cummins",
        "C500 D5",
        "Nairobi Plant",
        "Utilities",
        "Generator house",
        1,
        0.006,
        None,
    ),
    (
        "ELC-801",
        "Main switchboard MSB-1",
        C.ELECTRICAL,
        "Schneider Electric",
        "Okken",
        "Nairobi Plant",
        "Utilities",
        "Substation",
        1,
        0.004,
        None,
    ),
    (
        "CNV-151",
        "Depot loading conveyor",
        C.CONVEYOR,
        "Bastian",
        "TL-600",
        "Mombasa Depot",
        "Warehouse",
        "Dock 2",
        2,
        0.02,
        None,
    ),
    (
        "GEN-702",
        "Depot generator 250 kVA",
        C.GENERATOR,
        "Perkins",
        "2506A",
        "Mombasa Depot",
        "Utilities",
        "Yard",
        2,
        0.006,
        None,
    ),
    (
        "OTH-901",
        "Forklift battery charger bank",
        C.OTHER,
        "Hoppecke",
        "trak charger",
        "Mombasa Depot",
        "Warehouse",
        "Charging bay",
        2,
        0.008,
        None,
    ),
]

W, M_ = IntervalUnit.WEEKS, IntervalUnit.MONTHS
PLANS = {
    C.CONVEYOR: [
        ("Belt tracking and roller inspection", 1, W),
        ("Drive and gearbox lubrication", 1, M_),
    ],
    C.MOTOR: [("Bearing and insulation check", 1, M_)],
    C.COMPRESSOR: [
        ("Filter and condensate drain check", 2, W),
        ("Oil and separator service", 3, M_),
    ],
    C.HYDRAULIC_SYSTEM: [("Oil level, hose and seal inspection", 2, W)],
    C.PUMP: [("Seal, vibration and alignment check", 2, W)],
    C.PRODUCTION_MACHINE: [("Change parts and guarding inspection", 1, W)],
    C.GENERATOR: [("Weekly load test", 1, W), ("Oil, filters and coolant service", 3, M_)],
    C.ELECTRICAL: [("Thermographic survey", 3, M_)],
    C.OTHER: [("Charger and cable inspection", 1, M_)],
}

F = FaultCategory
FAULTS = {
    C.CONVEYOR: [
        (
            F.MECHANICAL,
            "Belt drifted off the tail pulley",
            "Worn tracking idler",
            "Re-tracked belt and replaced tracking idler",
        ),
        (
            F.MECHANICAL,
            "Drive chain snapped",
            "Chain stretched past wear limit",
            "Fitted new drive chain and tensioned",
        ),
        (
            F.ELECTRICAL,
            "Drive motor tripped on overload",
            "Seized return roller",
            "Freed roller, reset overload and tested under load",
        ),
        (
            F.INSTRUMENTATION,
            "Photo-eye not detecting cartons",
            "Misaligned sensor bracket",
            "Realigned and replaced the photo-eye",
        ),
    ],
    C.MOTOR: [
        (
            F.ELECTRICAL,
            "Motor tripped on earth fault",
            "Moisture in terminal box",
            "Dried windings, resealed gland, megger tested",
        ),
        (F.MECHANICAL, "High vibration on drive end", "Bearing wear", "Replaced drive-end bearing"),
    ],
    C.COMPRESSOR: [
        (
            F.PNEUMATIC,
            "Low line pressure, compressor not loading",
            "Faulty inlet valve",
            "Replaced inlet valve kit",
        ),
        (
            F.LUBRICATION,
            "High element temperature shutdown",
            "Blocked oil cooler",
            "Cleaned oil cooler and topped up oil",
        ),
        (F.ELECTRICAL, "Compressor would not start", "Failed contactor", "Replaced main contactor"),
    ],
    C.HYDRAULIC_SYSTEM: [
        (
            F.HYDRAULIC,
            "Press losing pressure during cycle",
            "Worn cylinder seals",
            "Replaced ram seal kit and bled the system",
        ),
        (
            F.HYDRAULIC,
            "Hose burst on return line",
            "Hose chafing on frame",
            "Replaced hose and fitted protective sleeve",
        ),
    ],
    C.PUMP: [
        (F.MECHANICAL, "Mechanical seal leaking", "Seal faces worn", "Replaced mechanical seal"),
        (
            F.ELECTRICAL,
            "Pump tripped on overload",
            "Impeller fouled with debris",
            "Cleaned impeller and strainer, reset overload",
        ),
        (
            F.OPERATIONAL,
            "Pump ran dry",
            "Suction valve left closed after cleaning",
            "Opened valve, checked seal, briefed operators",
        ),
    ],
    C.PRODUCTION_MACHINE: [
        (
            F.MECHANICAL,
            "Star wheel jammed",
            "Sheared drive key",
            "Replaced key and star wheel guide",
        ),
        (F.PNEUMATIC, "Grippers not closing", "Leaking air cylinder", "Replaced cylinder seals"),
        (
            F.OPERATIONAL,
            "Wrong format parts fitted at changeover",
            "Changeover checklist skipped",
            "Fitted correct parts, updated changeover sheet",
        ),
        (
            F.INSTRUMENTATION,
            "Fill level sensor out of tolerance",
            "Sensor drift",
            "Recalibrated level sensor",
        ),
    ],
    C.GENERATOR: [
        (
            F.ELECTRICAL,
            "Failed to start on mains failure",
            "Flat starter battery",
            "Replaced battery and tested auto-start",
        ),
        (
            F.LUBRICATION,
            "Low oil pressure alarm",
            "Oil below minimum",
            "Topped up oil and checked for leaks",
        ),
    ],
    C.ELECTRICAL: [
        (
            F.ELECTRICAL,
            "Feeder breaker tripped",
            "Loose busbar connection",
            "Retorqued connections after thermographic check",
        ),
    ],
    C.OTHER: [
        (
            F.ELECTRICAL,
            "Charger showing fault code",
            "Failed charging module",
            "Replaced charging module",
        ),
    ],
}

U = StockUnit
# part number, name, category, unit, opening stock, reorder level, reorder qty, cost (KES),
# location, supplier, used by categories, auto-reorder
PARTS = [
    (
        "BRG-6205-2RS",
        "Deep groove bearing 6205-2RS",
        "Bearings",
        U.EACH,
        24,
        8,
        20,
        "450.00",
        "Store A / B3",
        "Kenya Bearings Ltd",
        (C.CONVEYOR, C.MOTOR, C.PUMP),
        True,
    ),
    (
        "BRG-6310-ZZ",
        "Deep groove bearing 6310-ZZ",
        "Bearings",
        U.EACH,
        6,
        2,
        6,
        "2850.00",
        "Store A / B4",
        "Kenya Bearings Ltd",
        (C.MOTOR,),
        True,
    ),
    (
        "CHN-08B-1",
        "Roller chain 08B-1 (5 m)",
        "Power transmission",
        U.EACH,
        6,
        2,
        6,
        "3200.00",
        "Store A / C1",
        "Industrial Drives EA",
        (C.CONVEYOR,),
        True,
    ),
    (
        "IDL-TRK-600",
        "Tracking idler 600 mm",
        "Conveyor",
        U.EACH,
        4,
        2,
        4,
        "7800.00",
        "Store B / R2",
        "Belt Solutions Kenya",
        (C.CONVEYOR,),
        False,
    ),
    (
        "SEN-PE-M18",
        "Photo-eye sensor M18",
        "Instrumentation",
        U.EACH,
        5,
        2,
        5,
        "6400.00",
        "Store A / E2",
        "Automation Centre Nairobi",
        (C.CONVEYOR, C.PRODUCTION_MACHINE),
        True,
    ),
    (
        "FLT-AIR-GA37",
        "Compressor air filter element",
        "Filters",
        U.EACH,
        6,
        2,
        6,
        "5200.00",
        "Store A / F1",
        "Atlas Copco Kenya",
        (C.COMPRESSOR,),
        True,
    ),
    (
        "KIT-INV-GA",
        "Compressor inlet valve kit",
        "Compressor",
        U.SET,
        2,
        1,
        2,
        "38500.00",
        "Store A / F2",
        "Atlas Copco Kenya",
        (C.COMPRESSOR,),
        True,
    ),
    (
        "OIL-ROTO-20",
        "Compressor oil Roto-Inject (20 L)",
        "Lubricants",
        U.LITRE,
        60,
        20,
        40,
        "1150.00",
        "Oil store",
        "Atlas Copco Kenya",
        (C.COMPRESSOR,),
        True,
    ),
    (
        "KIT-SEAL-ABP",
        "Hydraulic ram seal kit",
        "Hydraulics",
        U.SET,
        2,
        2,
        2,
        "24500.00",
        "Store B / H1",
        "Hydraulic Services EA",
        (C.HYDRAULIC_SYSTEM,),
        False,
    ),
    (
        "OIL-HYD-46",
        "Hydraulic oil ISO VG 46",
        "Lubricants",
        U.LITRE,
        120,
        40,
        100,
        "420.00",
        "Oil store",
        "Vivo Energy",
        (C.HYDRAULIC_SYSTEM,),
        True,
    ),
    (
        "SEAL-MEC-35",
        "Mechanical seal 35 mm",
        "Pumps",
        U.EACH,
        4,
        2,
        4,
        "9800.00",
        "Store B / P1",
        "Davis & Shirtliff",
        (C.PUMP,),
        False,
    ),
    (
        "CTR-3P-40A",
        "Contactor 3-pole 40 A",
        "Electrical",
        U.EACH,
        5,
        2,
        5,
        "4600.00",
        "Store A / E1",
        "Schneider Electric Kenya",
        (C.COMPRESSOR, C.ELECTRICAL, C.MOTOR),
        True,
    ),
    (
        "BAT-12V-200",
        "Starter battery 12 V 200 Ah",
        "Electrical",
        U.EACH,
        2,
        1,
        2,
        "28500.00",
        "Store A / E4",
        "Chloride Exide",
        (C.GENERATOR,),
        True,
    ),
    (
        "GRS-EP2",
        "Lithium EP2 grease",
        "Lubricants",
        U.KILOGRAM,
        Decimal("18.5"),
        5,
        15,
        "780.00",
        "Oil store",
        "Vivo Energy",
        (C.CONVEYOR, C.MOTOR, C.PUMP),
        True,
    ),
    (
        "KEY-STW-8",
        "Star wheel drive key 8 mm",
        "Production",
        U.EACH,
        10,
        4,
        10,
        "350.00",
        "Store A / D2",
        "Krones East Africa",
        (C.PRODUCTION_MACHINE,),
        True,
    ),
]


@dataclass
class _Ledger:
    """Stock positions while generating, so every balance_after is the true running balance."""

    parts: dict[str, SparePart]
    on_hand: dict[str, Decimal] = field(default_factory=dict)
    # Reorder deliveries due (local date, part). Delivered at 06:00, before any work that day,
    # so the ledger stays in time order.
    pending: list[tuple[date, str]] = field(default_factory=list)


def _sample_users(db: Session) -> list[User]:
    unusable = hash_password(secrets.token_urlsafe(32))  # never stored or shown anywhere
    users = [
        User(
            username=f"{SAMPLE_USER_PREFIX}{key}",
            email=f"{key}@sample.invalid",
            full_name=f"{name} (sample)",
            password_hash=unusable,
            role=Role.VIEWER,
            status=UserStatus.DEACTIVATED,
            maintenance_role=mrole,
        )
        for key, name, mrole in PEOPLE
    ]
    db.add_all(users)
    db.flush()
    return users


def _has_maintenance_data(db: Session) -> bool:
    return bool(
        db.scalar(select(func.count(Equipment.id))) or db.scalar(select(func.count(SparePart.id)))
    )


def clear_maintenance_sample(db: Session) -> None:
    """Delete every maintenance record and the sample accounts. Only on a sample dataset."""
    if not is_maintenance_sample(db):
        raise RuntimeError("Refusing to clear: maintenance data is not marked as sample data.")
    for model in (
        StockMovement,
        WorkOrderEvent,
        WorkOrder,
        Breakdown,
        MaintenanceTask,
        MaintenancePlan,
        EquipmentEvent,
        Equipment,
        SparePart,
    ):
        db.execute(delete(model))
    db.execute(delete(AuditEvent).where(AuditEvent.action == "maintenance_sample.loaded"))
    db.execute(delete(User).where(User.username.startswith(SAMPLE_USER_PREFIX, autoescape=True)))
    delete_setting(db, MAINTENANCE_SAMPLE_KEY)
    db.commit()


def load_maintenance_sample(
    db: Session, now: datetime | None = None, seed: int = 2026
) -> dict[str, int]:
    if _has_maintenance_data(db):
        raise RuntimeError(
            "Refusing to load maintenance sample data: equipment or spare parts already exist. "
            "Run `clear-maintenance-sample` first (only works on the sample dataset)."
        )
    if db.scalar(select(func.count(User.id)).where(User.username.startswith(SAMPLE_USER_PREFIX))):
        raise RuntimeError("Sample accounts already exist; run `clear-maintenance-sample` first.")
    g = _Generator(db, random.Random(seed), now or datetime.now(UTC))
    counts = g.run()
    set_setting(
        db,
        MAINTENANCE_SAMPLE_KEY,
        {"loaded": True, "loaded_at": g.now.isoformat(), "seed": seed},
    )
    db.add(
        AuditEvent(
            action="maintenance_sample.loaded",
            entity_type="system",
            summary="Maintenance sample demonstration dataset loaded",
            changes=counts,
        )
    )
    db.commit()
    return counts


class _Generator:
    def __init__(self, db: Session, rng: random.Random, now: datetime) -> None:
        self.db, self.rng, self.now = db, rng, now
        self.tz = get_settings().tz
        self.today = now.astimezone(self.tz).date()
        self.start = self.today - timedelta(days=HISTORY_DAYS)
        self.counts = dict.fromkeys(
            ("equipment", "plans", "tasks", "breakdowns", "work_orders", "parts", "movements"), 0
        )

    # ---------- helpers ----------
    def at(self, day: date, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(day, time(hour, minute), self.tz).astimezone(UTC)

    def number(self, prefix: str, sequence: str, when: datetime) -> str:
        n = self.db.scalar(text(f"SELECT nextval('{sequence}')"))
        return f"{prefix}-{when.year}-{n:05d}"

    def event(
        self,
        eq: Equipment,
        when: datetime,
        kind: str,
        summary: str,
        actor: User,
        changes: dict | None = None,
    ) -> None:
        self.db.add(
            EquipmentEvent(
                equipment_id=eq.id,
                occurred_at=when,
                kind=kind,
                summary=summary[:255],
                changes=changes,
                actor_id=actor.id,
            )
        )

    def wo_event(
        self,
        wo: WorkOrder,
        when: datetime,
        summary: str,
        actor: User,
        frm: WorkOrderStatus | None = None,
        to: WorkOrderStatus | None = None,
    ) -> None:
        self.db.add(
            WorkOrderEvent(
                work_order_id=wo.id,
                occurred_at=when,
                summary=summary,
                from_status=frm.value if frm else None,
                to_status=to.value if to else None,
                actor_id=actor.id,
            )
        )

    def status(
        self, eq: Equipment, when: datetime, new: EquipmentStatus, why: str, actor: User
    ) -> None:
        if eq.status is new:
            return
        old, eq.status = eq.status, new
        self.event(
            eq,
            when,
            "status_changed",
            f"Status changed to {new.value.replace('_', ' ')} ({why})",
            actor,
            {"status": {"from": old.value, "to": new.value}},
        )

    def move(
        self,
        code: str,
        kind: MovementKind,
        qty: Decimal,
        when: datetime,
        actor: User,
        wo: WorkOrder | None = None,
        reference: str | None = None,
        note: str | None = None,
    ) -> bool:
        led, part = self.ledger, self.ledger.parts[code]
        balance = led.on_hand[code] + qty
        if balance < 0:
            return False
        led.on_hand[code] = balance
        self.db.add(
            StockMovement(
                part_id=part.id,
                kind=kind,
                quantity=qty,
                balance_after=balance,
                work_order_id=wo.id if wo else None,
                reference=reference,
                note=note,
                unit_cost=part.unit_cost,
                actor_id=actor.id,
                occurred_at=when,
            )
        )
        self.counts["movements"] += 1
        auto = next(p[11] for p in PARTS if p[0] == code)
        on_order = any(c == code for _, c in led.pending)
        if kind is MovementKind.ISSUE and auto and balance <= part.reorder_level and not on_order:
            day = when.astimezone(self.tz).date() + timedelta(days=self.rng.randint(2, 5))
            led.pending.append((day, code))
        return True

    def receive_due(self, until: date) -> None:
        led = self.ledger
        for day, code in sorted(p for p in led.pending if p[0] <= until):
            led.pending.remove((day, code))
            part = led.parts[code]
            grn = f"GRN-{day:%y%m%d}-{self.rng.randint(10, 99)}"
            self.move(
                code,
                MovementKind.RECEIPT,
                part.reorder_quantity or Decimal(1),
                self.at(day, 6),
                self.planner,
                reference=grn,
                note="Reorder delivery",
            )

    # ---------- build ----------
    def run(self) -> dict[str, int]:
        db = self.db
        *self.techs, self.planner = _sample_users(db)
        self.equipment = self._equipment()
        self._parts()
        self._plans()
        self._history()
        self._current_state()
        self.receive_due(self.today)  # later deliveries are still on order
        self._stock_count()
        for eq in self.equipment.values():
            sync_equipment_dates(db, eq)
        db.flush()
        return self.counts

    def _equipment(self) -> dict[str, Equipment]:
        out = {}
        for code, name, cat, make, model, fac, dept, loc, tech, _p, reg_days in EQUIPMENT:
            reg_day = self.today - timedelta(days=reg_days) if reg_days else self.start
            registered = self.at(reg_day, 8, self.rng.randint(0, 50))
            installed = (
                reg_day if reg_days else reg_day - timedelta(days=365 * self.rng.randint(1, 6))
            )
            eq = Equipment(
                code=code,
                name=name,
                category=cat,
                manufacturer=make,
                model=model,
                serial_number=f"{make[:3].upper()}-{self.rng.randint(100000, 999999)}",
                facility=fac,
                department=dept,
                location=loc,
                installed_on=installed,
                status=EquipmentStatus.OPERATIONAL,
                assigned_technician_id=self.techs[tech].id,
                created_at=registered,
                updated_at=registered,
            )
            self.db.add(eq)
            self.db.flush()
            self.event(eq, registered, "created", f"{code} registered (operational)", self.planner)
            out[code] = eq
            self.counts["equipment"] += 1
        return out

    def _parts(self) -> None:
        parts = {}
        opening = self.at(self.start, 7)
        for pn, name, cat, unit, _qty, rl, rq, cost, loc, sup, _used, _auto in PARTS:
            p = SparePart(
                part_number=pn,
                name=name,
                category=cat,
                unit=unit,
                on_hand=Decimal(0),
                reorder_level=Decimal(rl),
                reorder_quantity=Decimal(rq),
                location=loc,
                supplier=sup,
                unit_cost=Decimal(cost),
                created_at=opening,
                updated_at=opening,
            )
            self.db.add(p)
            parts[pn] = p
            self.counts["parts"] += 1
        self.db.flush()
        self.ledger = _Ledger(parts, dict.fromkeys(parts, Decimal(0)))
        for pn, _n, _c, _u, qty, *_rest in PARTS:
            self.move(
                pn,
                MovementKind.RECEIPT,
                Decimal(qty),
                opening,
                self.planner,
                reference="GRN-OPENING",
                note="Opening stock",
            )

    def _plans(self) -> None:
        """Plans with their completed history and one open task each. A few plans are left
        overdue so the schedule shows real work outstanding."""
        overdue = {"CNV-151", "PMP-502", "MTR-201"}
        for eq in self.equipment.values():
            reg_day = eq.created_at.astimezone(self.tz).date()
            for i, (title, value, unit) in enumerate(PLANS[eq.category]):
                first = reg_day + timedelta(days=2 + 3 * i + self.rng.randint(0, 4))
                tech = next(t for t in self.techs if t.id == eq.assigned_technician_id)
                plan = MaintenancePlan(
                    equipment_id=eq.id,
                    title=title,
                    interval_value=value,
                    interval_unit=unit,
                    start_on=first,
                    assigned_technician_id=tech.id,
                    created_by_id=self.planner.id,
                    created_at=eq.created_at,
                    updated_at=eq.created_at,
                    instructions="Follow the manufacturer checklist; record readings in notes.",
                )
                self.db.add(plan)
                self.db.flush()
                self.counts["plans"] += 1
                every = f"every {value} {unit.value.rstrip('s')}{'s' if value > 1 else ''}"
                self.event(
                    eq,
                    eq.created_at + timedelta(minutes=5),
                    "pm_plan_created",
                    f"Preventive plan added: {title}, {every} (first due {first:%d %b %Y})",
                    self.planner,
                )
                due = first
                while True:
                    task = MaintenanceTask(
                        plan_id=plan.id,
                        equipment_id=eq.id,
                        title=title,
                        due_on=due,
                        assigned_technician_id=tech.id,
                        created_at=eq.created_at,
                        updated_at=eq.created_at,
                    )
                    self.db.add(task)
                    self.counts["tasks"] += 1
                    # Overdue plans leave their most recent past-due task undone.
                    keep_open = due >= self.today or (
                        eq.code in overdue
                        and i == 0
                        and add_interval(due, value, unit) >= self.today
                    )
                    if keep_open:
                        break
                    roll = self.rng.random()
                    if roll < 0.04:
                        task.status, task.cancel_reason = TaskStatus.CANCELLED, "Line shutdown"
                        task.cancelled_at = self.at(due, 9)
                        task.cancelled_by_id = self.planner.id
                    else:
                        late = roll > 0.84
                        done = due + timedelta(days=self.rng.randint(1, 4)) if late else due
                        done = min(done, self.today)
                        task.status, task.completed_on = TaskStatus.COMPLETED, done
                        task.completed_at = min(
                            self.now,
                            self.at(done, self.rng.randint(9, 15), self.rng.choice((0, 15, 30))),
                        )
                        task.completed_by_id = tech.id
                        task.work_notes = (
                            "Checklist completed; no defects found."
                            if roll < 0.6
                            else "Checklist completed; minor adjustment made."
                        )
                        self.event(
                            eq,
                            task.completed_at,
                            "pm_task_completed",
                            f"Preventive maintenance done: {title}"
                            + (" (late)" if done > due else ""),
                            tech,
                            {"due_on": due.isoformat(), "completed_on": done.isoformat()},
                        )
                    due = add_interval(due, value, unit)

    def _history(self) -> None:
        """Breakdowns with their corrective work orders, day by day so stock runs in order."""
        free_from = {code: eq.created_at for code, eq in self.equipment.items()}
        # Assets that are down right now must have no history overlapping the open breakdown.
        stop = {
            "PRD-601": self.now - timedelta(hours=5),
            "HYD-401": self.now - timedelta(days=3),
            "CMP-302": self.now - timedelta(days=1),  # overhaul in progress since yesterday
        }
        probability = {e[0]: e[9] for e in EQUIPMENT}
        day = self.start
        while day < self.today:
            self.receive_due(day)
            for code, eq in self.equipment.items():
                if self.rng.random() >= probability[code]:
                    continue
                start = self.at(day, self.rng.randint(6, 20), self.rng.randint(0, 59))
                if start <= free_from[code]:
                    continue
                severity = self.rng.choices(
                    (BreakdownSeverity.MINOR, BreakdownSeverity.MAJOR, BreakdownSeverity.CRITICAL),
                    (5, 4, 1),
                )[0]
                lo, hi = {"minor": (25, 90), "major": (90, 360), "critical": (240, 720)}[
                    severity.value
                ]
                restored = start + timedelta(minutes=self.rng.randint(lo, hi))
                if restored >= min(stop.get(code, self.now), self.now - timedelta(hours=1)):
                    continue
                self._breakdown(eq, start, restored, severity)
                free_from[code] = restored
            day += timedelta(days=1)

    def _breakdown(
        self,
        eq: Equipment,
        start: datetime,
        restored: datetime | None,
        severity: BreakdownSeverity,
        fault: tuple | None = None,
        wo_status: WorkOrderStatus = WO_STATUS.COMPLETED,
    ) -> WorkOrder:
        cat, desc, cause, action = fault or self.rng.choice(FAULTS[eq.category])
        tech = next(t for t in self.techs if t.id == eq.assigned_technician_id)
        down = not (severity is BreakdownSeverity.MINOR and self.rng.random() < 0.3)
        bd = Breakdown(
            number=self.number("BD", "breakdown_number_seq", start),
            equipment_id=eq.id,
            started_at=start,
            restored_at=restored,
            severity=severity,
            category=cat,
            description=desc,
            possible_cause=cause,
            actions_taken=action if restored else None,
            equipment_down=down or restored is None,
            reported_by_id=tech.id,
            restored_by_id=tech.id if restored else None,
            created_at=start + timedelta(minutes=3),
            updated_at=restored or start,
        )
        self.db.add(bd)
        self.db.flush()
        self.counts["breakdowns"] += 1
        self.event(
            eq,
            bd.created_at,
            "breakdown_logged",
            f"Breakdown {bd.number} ({severity.value}, {cat.value}): {desc}",
            tech,
        )
        if bd.equipment_down:
            self.status(
                eq, bd.created_at, EquipmentStatus.OUT_OF_SERVICE, f"breakdown {bd.number}", tech
            )

        raised = start + timedelta(minutes=self.rng.randint(5, 15))
        begun = raised + timedelta(minutes=self.rng.randint(5, 25))
        if restored is not None and begun >= restored:
            begun = raised = start + (restored - start) / 3
        priority = {
            "minor": WorkOrderPriority.MEDIUM,
            "major": WorkOrderPriority.HIGH,
            "critical": WorkOrderPriority.CRITICAL,
        }[severity.value]
        wo = WorkOrder(
            number=self.number("WO", "work_order_number_seq", raised),
            equipment_id=eq.id,
            breakdown_id=bd.id,
            maintenance_type=WorkOrderType.CORRECTIVE,
            priority=priority,
            status=wo_status,
            fault_description=desc,
            assigned_technician_id=tech.id,
            scheduled_on=start.astimezone(self.tz).date(),
            started_at=begun,
            created_by_id=tech.id,
            created_at=raised,
            updated_at=restored or begun,
        )
        if wo_status is WO_STATUS.COMPLETED:
            wo.completed_at = max(begun, restored - timedelta(minutes=self.rng.randint(0, 10)))
            wo.work_performed, wo.completed_by_id = action, tech.id
        self.db.add(wo)
        self.db.flush()
        self.counts["work_orders"] += 1
        self.wo_event(wo, raised, "Work order raised", tech, to=WO_STATUS.ASSIGNED)
        self.wo_event(wo, raised, f"Assigned to {tech.full_name}", tech)
        self.event(eq, raised, "work_order_created", f"Work order {wo.number} raised: {desc}", tech)
        self.wo_event(wo, begun, "Work started", tech, WO_STATUS.ASSIGNED, WO_STATUS.IN_PROGRESS)
        if wo_status is WO_STATUS.COMPLETED:
            self._consume(eq, wo, begun, tech)
            self.wo_event(
                wo, wo.completed_at, "Completed", tech, WO_STATUS.IN_PROGRESS, WO_STATUS.COMPLETED
            )
            self.event(
                eq,
                wo.completed_at,
                "work_order_completed",
                f"Work order {wo.number} completed: {action}",
                tech,
            )
            mins = round((restored - start).total_seconds() / 60)
            self.event(
                eq,
                restored,
                "breakdown_restored",
                f"Breakdown {bd.number} restored ({mins} min downtime)",
                tech,
            )
            self.status(eq, restored, EquipmentStatus.OPERATIONAL, "repair completed", tech)
        return wo

    def _consume(self, eq: Equipment, wo: WorkOrder, when: datetime, tech: User) -> None:
        usable = [p for p in PARTS if eq.category in p[10]]
        if not usable or self.rng.random() < 0.35:
            return
        for p in self.rng.sample(usable, k=min(len(usable), self.rng.choice((1, 1, 2)))):
            code, unit = p[0], p[3]
            if unit in (U.LITRE, U.KILOGRAM):
                qty = Decimal(self.rng.choice(("0.5", "1", "2.5", "4", "5")))
            else:
                qty = Decimal(self.rng.choice((1, 1, 1, 2)))
            at = min(when + timedelta(minutes=10), wo.completed_at)
            issued = self.move(
                code, MovementKind.ISSUE, -qty, at, tech, wo=wo, note=f"For {wo.number}"
            )
            if (
                issued
                and qty >= 2
                and unit not in (U.LITRE, U.KILOGRAM)
                and self.rng.random() < 0.3
            ):
                self.move(
                    code,
                    MovementKind.RETURN,
                    Decimal(1),
                    wo.completed_at,
                    tech,
                    wo=wo,
                    note="Unused, returned to store",
                )

    def _current_state(self) -> None:
        """Work in progress right now, so the live views have something to show."""
        n, eqs = self.now, self.equipment
        # The filler stopped this morning and is being repaired.
        filler = FAULTS[C.PRODUCTION_MACHINE][0]
        self._breakdown(
            eqs["PRD-601"],
            n - timedelta(hours=3, minutes=10),
            None,
            BreakdownSeverity.CRITICAL,
            filler,
            WO_STATUS.IN_PROGRESS,
        )
        # The baling press waits for a seal kit that is out of stock.
        press = eqs["HYD-401"]
        wo = self._breakdown(
            press,
            n - timedelta(days=2, hours=4),
            None,
            BreakdownSeverity.MAJOR,
            FAULTS[C.HYDRAULIC_SYSTEM][0],
            WO_STATUS.AWAITING_PARTS,
        )
        tech = next(t for t in self.techs if t.id == press.assigned_technician_id)
        self.wo_event(
            wo,
            n - timedelta(days=2, hours=1),
            "Waiting for parts",
            tech,
            WO_STATUS.IN_PROGRESS,
            WO_STATUS.AWAITING_PARTS,
        )
        self.ledger.pending = [p for p in self.ledger.pending if p[1] != "KIT-SEAL-ABP"]

        def planned(
            code: str,
            kind: WorkOrderType,
            desc: str,
            status: WorkOrderStatus,
            scheduled: int,
            priority: WorkOrderPriority,
        ) -> None:
            eq = eqs[code]
            tech = next(t for t in self.techs if t.id == eq.assigned_technician_id)
            raised = self.at(self.today - timedelta(days=max(2, -scheduled + 2)), 9)
            wo = WorkOrder(
                number=self.number("WO", "work_order_number_seq", raised),
                equipment_id=eq.id,
                maintenance_type=kind,
                priority=priority,
                status=status,
                fault_description=desc,
                assigned_technician_id=None if status is WO_STATUS.OPEN else tech.id,
                scheduled_on=self.today + timedelta(days=scheduled),
                started_at=n - timedelta(hours=20) if status is WO_STATUS.IN_PROGRESS else None,
                created_by_id=self.planner.id,
                created_at=raised,
                updated_at=raised,
            )
            self.db.add(wo)
            self.db.flush()
            self.counts["work_orders"] += 1
            self.wo_event(
                wo,
                raised,
                "Work order raised",
                self.planner,
                to=status if status in (WO_STATUS.OPEN, WO_STATUS.ASSIGNED) else WO_STATUS.ASSIGNED,
            )
            self.event(
                eq,
                raised,
                "work_order_created",
                f"Work order {wo.number} raised: {desc}",
                self.planner,
            )
            if status is WO_STATUS.IN_PROGRESS:
                self.wo_event(
                    wo,
                    wo.started_at,
                    "Work started",
                    tech,
                    WO_STATUS.ASSIGNED,
                    WO_STATUS.IN_PROGRESS,
                )
                self.status(
                    eq,
                    wo.started_at,
                    EquipmentStatus.UNDER_MAINTENANCE,
                    f"work order {wo.number}",
                    tech,
                )

        P_ = WorkOrderPriority
        planned(
            "CMP-302",
            WorkOrderType.PREVENTIVE,
            "Annual overhaul: replace oil separator, inlet valve and drive belts",
            WO_STATUS.IN_PROGRESS,
            -1,
            P_.MEDIUM,
        )
        planned(
            "CNV-151",
            WorkOrderType.INSPECTION,
            "Inspect belt splice and dock-side guarding",
            WO_STATUS.ASSIGNED,
            -4,
            P_.MEDIUM,
        )
        planned(
            "ELC-801",
            WorkOrderType.INSPECTION,
            "Annual insurance inspection of MSB-1",
            WO_STATUS.ASSIGNED,
            1,
            P_.HIGH,
        )
        planned(
            "GEN-702",
            WorkOrderType.IMPROVEMENT,
            "Install remote fuel-level monitoring",
            WO_STATUS.OPEN,
            6,
            P_.LOW,
        )
        planned(
            "CNV-102",
            WorkOrderType.IMPROVEMENT,
            "Fit spillage guard under the transfer point",
            WO_STATUS.OPEN,
            10,
            P_.LOW,
        )

    def _stock_count(self) -> None:
        """A stock count found damaged seal kits, which is why the press is waiting for parts."""
        left = self.ledger.on_hand["KIT-SEAL-ABP"]
        if left > 0:
            self.move(
                "KIT-SEAL-ABP",
                MovementKind.ADJUSTMENT,
                -left,
                self.now - timedelta(days=2, hours=2),
                self.planner,
                note="Stock count: seal kits damaged in storage, discarded",
            )
        for code, part in self.ledger.parts.items():
            part.on_hand = self.ledger.on_hand[code]
