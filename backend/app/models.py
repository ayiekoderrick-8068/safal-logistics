"""Relational schema for LogiTrack.

Timestamps are stored as timezone-aware UTC (`timestamptz`). Business rules that can be
expressed declaratively (ordering of loading timestamps, positive quantities, one active
truck per driver, no overlapping bay bookings) are enforced in the database as well as in
the API layer.
"""

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Store enums as VARCHAR + CHECK (portable, migration-friendly) using their values."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


class Role(enum.StrEnum):
    ADMIN = "admin"
    OPERATIONS = "operations"
    FLEET_MANAGER = "fleet_manager"
    COMPLIANCE = "compliance"
    VIEWER = "viewer"


class UserStatus(enum.StrEnum):
    ACTIVE = "active"
    PENDING = "pending"
    DEACTIVATED = "deactivated"


class TruckStatus(enum.StrEnum):
    AVAILABLE = "available"
    LOADING = "loading"
    IN_TRANSIT = "in_transit"
    MAINTENANCE = "maintenance"
    OUT_OF_SERVICE = "out_of_service"


class ScheduleStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    ARRIVED = "arrived"
    LOADING = "loading"
    LOADED = "loaded"
    DEPARTED = "departed"
    CANCELLED = "cancelled"


class DispatchStatus(enum.StrEnum):
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class DelayCause(enum.StrEnum):
    LOADING_CONGESTION = "loading_congestion"
    DOCUMENTATION = "documentation"
    TRUCK_UNAVAILABILITY = "truck_unavailability"
    EQUIPMENT_BREAKDOWN = "equipment_breakdown"
    TRAFFIC = "traffic"
    OTHER = "other"


class IncidentStatus(enum.StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class DocumentType(enum.StrEnum):
    INSURANCE = "insurance"
    LICENCE = "licence"
    INSPECTION = "inspection"
    ROADWORTHY = "roadworthy"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"), default=Role.VIEWER)
    status: Mapped[UserStatus] = mapped_column(
        _enum(UserStatus, "user_status"), default=UserStatus.PENDING, index=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Driver(TimestampMixin, Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(30))
    licence_number: Mapped[str] = mapped_column(String(50), unique=True)
    licence_expiry: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    truck: Mapped[Truck | None] = relationship(back_populates="driver")


class Truck(TimestampMixin, Base):
    __tablename__ = "trucks"
    __table_args__ = (
        CheckConstraint("capacity_tonnes > 0", name="capacity_positive"),
        # A driver can be assigned to at most one truck at a time.
        Index(
            "uq_trucks_driver_id",
            "driver_id",
            unique=True,
            postgresql_where=text("driver_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    registration: Mapped[str] = mapped_column(String(20), unique=True)
    make: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(60))
    capacity_tonnes: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    status: Mapped[TruckStatus] = mapped_column(
        _enum(TruckStatus, "truck_status"), default=TruckStatus.AVAILABLE, index=True
    )
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id", ondelete="SET NULL"))

    driver: Mapped[Driver | None] = relationship(back_populates="truck")


class Route(TimestampMixin, Base):
    __tablename__ = "routes"
    __table_args__ = (
        UniqueConstraint("origin", "destination", name="uq_routes_origin_destination"),
        CheckConstraint("origin <> destination", name="distinct_endpoints"),
        CheckConstraint("distance_km > 0", name="distance_positive"),
        CheckConstraint("expected_duration_minutes > 0", name="duration_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str] = mapped_column(String(80))
    destination: Mapped[str] = mapped_column(String(80))
    distance_km: Mapped[Decimal] = mapped_column(Numeric(8, 1))
    expected_duration_minutes: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    @property
    def label(self) -> str:
        return f"{self.origin} → {self.destination}"


class LoadingBay(TimestampMixin, Base):
    __tablename__ = "loading_bays"
    __table_args__ = (
        CheckConstraint(
            "target_turnaround_minutes IS NULL OR target_turnaround_minutes > 0",
            name="target_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    # Per-bay override; falls back to the global target when NULL.
    target_turnaround_minutes: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class LoadingSchedule(TimestampMixin, Base):
    """A booking of a loading bay for a truck, plus the actual recorded timestamps.

    Turnaround time = departed_at - arrival_at (truck arrival to departure).
    Overlapping bookings on the same bay are rejected by a PostgreSQL exclusion
    constraint (`ex_loading_schedules_bay_overlap`, created in the migration).
    """

    __tablename__ = "loading_schedules"
    __table_args__ = (
        CheckConstraint("scheduled_end > scheduled_start", name="scheduled_window_valid"),
        CheckConstraint(
            "loading_started_at IS NULL OR "
            "(arrival_at IS NOT NULL AND loading_started_at >= arrival_at)",
            name="loading_start_after_arrival",
        ),
        CheckConstraint(
            "loading_finished_at IS NULL OR (loading_started_at IS NOT NULL "
            "AND loading_finished_at >= loading_started_at)",
            name="loading_finish_after_start",
        ),
        CheckConstraint(
            "departed_at IS NULL OR (arrival_at IS NOT NULL AND departed_at >= arrival_at "
            "AND (loading_finished_at IS NULL OR departed_at >= loading_finished_at))",
            name="departure_after_loading",
        ),
        Index("ix_loading_schedules_bay_start", "bay_id", "scheduled_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    truck_id: Mapped[int] = mapped_column(ForeignKey("trucks.id", ondelete="RESTRICT"), index=True)
    bay_id: Mapped[int] = mapped_column(ForeignKey("loading_bays.id", ondelete="RESTRICT"))
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    loading_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    loading_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    departed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[ScheduleStatus] = mapped_column(
        _enum(ScheduleStatus, "schedule_status"), default=ScheduleStatus.SCHEDULED, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    truck: Mapped[Truck] = relationship()
    bay: Mapped[LoadingBay] = relationship()
    dispatch: Mapped[Dispatch | None] = relationship(back_populates="schedule")


class Dispatch(TimestampMixin, Base):
    __tablename__ = "dispatches"
    __table_args__ = (
        CheckConstraint("expected_arrival_at > dispatched_at", name="expected_after_dispatch"),
        CheckConstraint(
            "actual_arrival_at IS NULL OR actual_arrival_at >= dispatched_at",
            name="actual_after_dispatch",
        ),
        CheckConstraint(
            "status <> 'delivered' OR actual_arrival_at IS NOT NULL",
            name="delivered_has_arrival",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    load_ref: Mapped[str] = mapped_column(String(20), unique=True)
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("loading_schedules.id", ondelete="SET NULL"), unique=True
    )
    truck_id: Mapped[int] = mapped_column(ForeignKey("trucks.id", ondelete="RESTRICT"), index=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="RESTRICT"), index=True)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expected_arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[DispatchStatus] = mapped_column(
        _enum(DispatchStatus, "dispatch_status"), default=DispatchStatus.PENDING, index=True
    )
    is_delayed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    truck: Mapped[Truck] = relationship()
    route: Mapped[Route] = relationship()
    schedule: Mapped[LoadingSchedule | None] = relationship(back_populates="dispatch")


class DelayIncident(TimestampMixin, Base):
    __tablename__ = "delay_incidents"
    __table_args__ = (
        CheckConstraint("delay_minutes >= 0", name="delay_non_negative"),
        CheckConstraint(
            "dispatch_id IS NOT NULL OR schedule_id IS NOT NULL", name="linked_to_operation"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dispatch_id: Mapped[int | None] = mapped_column(
        ForeignKey("dispatches.id", ondelete="CASCADE"), index=True
    )
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("loading_schedules.id", ondelete="CASCADE"), index=True
    )
    cause: Mapped[DelayCause] = mapped_column(_enum(DelayCause, "delay_cause"), index=True)
    delay_minutes: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[IncidentStatus] = mapped_column(
        _enum(IncidentStatus, "incident_status"), default=IncidentStatus.OPEN, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    dispatch: Mapped[Dispatch | None] = relationship()


class ComplianceDocument(TimestampMixin, Base):
    __tablename__ = "compliance_documents"
    __table_args__ = (
        CheckConstraint("expires_on > issued_on", name="expiry_after_issue"),
        Index("ix_compliance_documents_truck_type", "truck_id", "doc_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    truck_id: Mapped[int] = mapped_column(ForeignKey("trucks.id", ondelete="CASCADE"))
    doc_type: Mapped[DocumentType] = mapped_column(_enum(DocumentType, "document_type"))
    reference_number: Mapped[str] = mapped_column(String(80))
    issued_on: Mapped[date] = mapped_column(Date)
    expires_on: Mapped[date] = mapped_column(Date, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    truck: Mapped[Truck] = relationship()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(50))
    summary: Mapped[str] = mapped_column(String(255))
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
