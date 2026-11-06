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
    __table_args__ = (
        CheckConstraint(
            "next_service_on IS NULL OR last_service_on IS NULL "
            "OR next_service_on >= last_service_on",
            name="next_service_after_last",
        ),
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
