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
