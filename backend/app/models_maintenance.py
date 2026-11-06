"""Maintenance Operations (CMMS) schema. Kept apart from the logistics tables; shares `users`
for technicians and audit actors. Imported by `models` so Alembic sees the tables."""

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import TimestampMixin, User, _enum


class EquipmentCategory(enum.StrEnum):
    CONVEYOR = "conveyor"
    MOTOR = "motor"
    COMPRESSOR = "compressor"
    HYDRAULIC_SYSTEM = "hydraulic_system"
    PUMP = "pump"
    PRODUCTION_MACHINE = "production_machine"
    GENERATOR = "generator"
    ELECTRICAL = "electrical"
    OTHER = "other"


class EquipmentStatus(enum.StrEnum):
    OPERATIONAL = "operational"
    UNDER_MAINTENANCE = "under_maintenance"
    OUT_OF_SERVICE = "out_of_service"


class Equipment(TimestampMixin, Base):
    """A maintained asset. Archived equipment keeps its history but leaves the active register."""

    __tablename__ = "equipment"
    # No "next >= last" constraint: with several plans an asset can have one task overdue while
    # another was serviced today. Hand-entered dates are still checked by the API.
    __table_args__ = (
        CheckConstraint(
            "last_service_on IS NULL OR installed_on IS NULL OR last_service_on >= installed_on",
            name="service_after_install",
        ),
        Index("ix_equipment_active_status", "status", postgresql_where="archived_at IS NULL"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # the Equipment ID, e.g. CNV-001
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[EquipmentCategory] = mapped_column(
        _enum(EquipmentCategory, "equipment_category")
    )
    manufacturer: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    serial_number: Mapped[str | None] = mapped_column(String(80), unique=True)
    facility: Mapped[str] = mapped_column(String(80))
    department: Mapped[str | None] = mapped_column(String(80))
    location: Mapped[str | None] = mapped_column(String(120))
    installed_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[EquipmentStatus] = mapped_column(
        _enum(EquipmentStatus, "equipment_status"), default=EquipmentStatus.OPERATIONAL
    )
    assigned_technician_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    last_service_on: Mapped[date | None] = mapped_column(Date)
    next_service_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    assigned_technician: Mapped[User | None] = relationship(foreign_keys=[assigned_technician_id])
    events: Mapped[list[EquipmentEvent]] = relationship(
        back_populates="equipment", order_by="EquipmentEvent.occurred_at.desc()"
    )


class EquipmentEvent(Base):
    """Append-only maintenance history of one asset (register changes now; servicing,
    work orders and breakdowns are added to the same timeline by later modules)."""

    __tablename__ = "equipment_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    kind: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(String(255))
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    equipment: Mapped[Equipment] = relationship(back_populates="events")
    actor: Mapped[User | None] = relationship()


# ---------- Preventive maintenance (Milestone 3) ----------
class IntervalUnit(enum.StrEnum):
    DAYS = "days"
    WEEKS = "weeks"
    MONTHS = "months"


class ScheduleBasis(enum.StrEnum):
    """How the next due date is derived when a task is closed."""

    DUE_DATE = "due_date"  # fixed calendar: previous due date + interval
    COMPLETION_DATE = "completion_date"  # floating: completion date + interval


class TaskStatus(enum.StrEnum):
    """Stored state. "Overdue" is derived (scheduled and past its due date), never stored."""

    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MaintenancePlan(TimestampMixin, Base):
    """A recurring, date-based service plan for one asset."""

    __tablename__ = "maintenance_plans"
    __table_args__ = (CheckConstraint("interval_value BETWEEN 1 AND 3650", name="interval_range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(120))
    instructions: Mapped[str | None] = mapped_column(Text)
    interval_value: Mapped[int]
    interval_unit: Mapped[IntervalUnit] = mapped_column(_enum(IntervalUnit, "interval_unit"))
    schedule_basis: Mapped[ScheduleBasis] = mapped_column(
        _enum(ScheduleBasis, "schedule_basis"), default=ScheduleBasis.DUE_DATE
    )
    start_on: Mapped[date] = mapped_column(Date)
    assigned_technician_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    equipment: Mapped[Equipment] = relationship()
    assigned_technician: Mapped[User | None] = relationship(foreign_keys=[assigned_technician_id])


class MaintenanceTask(TimestampMixin, Base):
    """One scheduled piece of preventive work: generated by a plan, or scheduled once-off."""

    __tablename__ = "maintenance_tasks"
    __table_args__ = (
        # A plan has at most one open task, so a late plan never piles up duplicates.
        Index(
            "uq_maintenance_tasks_one_open_per_plan",
            "plan_id",
            unique=True,
            postgresql_where="status = 'scheduled' AND plan_id IS NOT NULL",
        ),
        Index("ix_maintenance_tasks_open_due", "due_on", postgresql_where="status = 'scheduled'"),
        CheckConstraint(
            "(status = 'completed') = (completed_on IS NOT NULL)", name="completed_has_date"
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancel_reason IS NOT NULL)", name="cancelled_has_reason"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("maintenance_plans.id", ondelete="SET NULL"), index=True
    )
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(120))
    due_on: Mapped[date] = mapped_column(Date)
    status: Mapped[TaskStatus] = mapped_column(
        _enum(TaskStatus, "maintenance_task_status"), default=TaskStatus.SCHEDULED
    )
    assigned_technician_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    completed_on: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    work_notes: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    plan: Mapped[MaintenancePlan | None] = relationship()
    equipment: Mapped[Equipment] = relationship()
    assigned_technician: Mapped[User | None] = relationship(foreign_keys=[assigned_technician_id])
    completed_by: Mapped[User | None] = relationship(foreign_keys=[completed_by_id])


# ---------- Breakdowns and work orders (Milestone 4) ----------
class BreakdownSeverity(enum.StrEnum):
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class FaultCategory(enum.StrEnum):
    MECHANICAL = "mechanical"
    ELECTRICAL = "electrical"
    HYDRAULIC = "hydraulic"
    PNEUMATIC = "pneumatic"
    INSTRUMENTATION = "instrumentation"
    LUBRICATION = "lubrication"
    OPERATIONAL = "operational"  # misuse, wrong settings, operator error
    OTHER = "other"


class Breakdown(TimestampMixin, Base):
    """One equipment failure, from failure start to restoration. Breakdowns of the same asset
    never overlap (one open at a time; a new one cannot start before the last restoration),
    so summed downtime never counts the same period twice."""

    __tablename__ = "breakdowns"
    __table_args__ = (
        Index(
            "uq_breakdowns_one_open_per_equipment",
            "equipment_id",
            unique=True,
            postgresql_where="restored_at IS NULL",
        ),
        CheckConstraint(
            "restored_at IS NULL OR restored_at >= started_at", name="restored_after_start"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)  # BD-2026-00001
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    severity: Mapped[BreakdownSeverity] = mapped_column(
        _enum(BreakdownSeverity, "breakdown_severity")
    )
    category: Mapped[FaultCategory] = mapped_column(_enum(FaultCategory, "fault_category"))
    description: Mapped[str] = mapped_column(Text)
    possible_cause: Mapped[str | None] = mapped_column(Text)
    actions_taken: Mapped[str | None] = mapped_column(Text)
    # Whether the failure stopped the asset (counts as downtime / out of service).
    equipment_down: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    reported_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    restored_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    equipment: Mapped[Equipment] = relationship()
    reported_by: Mapped[User | None] = relationship(foreign_keys=[reported_by_id])
    restored_by: Mapped[User | None] = relationship(foreign_keys=[restored_by_id])


class WorkOrderType(enum.StrEnum):
    CORRECTIVE = "corrective"  # repair after a fault or breakdown
    PREVENTIVE = "preventive"
    INSPECTION = "inspection"
    IMPROVEMENT = "improvement"


class WorkOrderPriority(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkOrderStatus(enum.StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    AWAITING_PARTS = "awaiting_parts"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkOrder(TimestampMixin, Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)", name="completed_has_time"
        ),
        CheckConstraint(
            "completed_at IS NULL OR (started_at IS NOT NULL AND completed_at >= started_at)",
            name="completed_after_start",
        ),
        CheckConstraint(
            "status NOT IN ('assigned', 'in_progress', 'awaiting_parts', 'completed') "
            "OR assigned_technician_id IS NOT NULL",
            name="active_needs_technician",
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancel_reason IS NOT NULL)", name="cancelled_has_reason"
        ),
        Index("ix_work_orders_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)  # WO-2026-00001
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), index=True
    )
    breakdown_id: Mapped[int | None] = mapped_column(
        ForeignKey("breakdowns.id", ondelete="SET NULL"), index=True
    )
    maintenance_type: Mapped[WorkOrderType] = mapped_column(_enum(WorkOrderType, "work_order_type"))
    priority: Mapped[WorkOrderPriority] = mapped_column(
        _enum(WorkOrderPriority, "work_order_priority")
    )
    status: Mapped[WorkOrderStatus] = mapped_column(
        _enum(WorkOrderStatus, "work_order_status"), default=WorkOrderStatus.OPEN
    )
    fault_description: Mapped[str] = mapped_column(Text)
    assigned_technician_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    scheduled_on: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    work_performed: Mapped[str | None] = mapped_column(Text)
    completion_notes: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    equipment: Mapped[Equipment] = relationship()
    breakdown: Mapped[Breakdown | None] = relationship()
    assigned_technician: Mapped[User | None] = relationship(foreign_keys=[assigned_technician_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    completed_by: Mapped[User | None] = relationship(foreign_keys=[completed_by_id])


class WorkOrderEvent(Base):
    """Status history and audit trail of a work order (append-only)."""

    __tablename__ = "work_order_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(
        ForeignKey("work_orders.id", ondelete="CASCADE"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    actor: Mapped[User | None] = relationship()
