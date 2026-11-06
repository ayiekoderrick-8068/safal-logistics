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
    EQUIPMENT_BREAKDOWN = "equipment_breakdown"  # site/loading equipment failure
    VEHICLE_BREAKDOWN = "vehicle_breakdown"
    TRAFFIC = "traffic"
    OTHER = "other"


class IncidentStatus(enum.StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class DocumentType(enum.StrEnum):
    INSURANCE = "insurance"
    LICENCE = "licence"  # vehicle licence
    INSPECTION = "inspection"  # inspection certificate
    ROADWORTHY = "roadworthy"
    SPEED_GOVERNOR = "speed_governor"
    OTHER = "other"


class AlertSeverity(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(enum.StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class AlertType(enum.StrEnum):
    DOCUMENT_EXPIRING = "document_expiring"
    DOCUMENT_EXPIRED = "document_expired"
    DOCUMENT_MISSING = "document_missing"
    INSPECTION_DUE = "inspection_due"
    MAINTENANCE_REQUIRED = "maintenance_required"
    LOADING_OVER_TARGET = "loading_over_target"
    MISSED_DISPATCH = "missed_dispatch"
    DELIVERY_OVERDUE = "delivery_overdue"
    INCIDENT_UNRESOLVED = "incident_unresolved"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("token_version >= 0", name="token_version_non_negative"),)

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
    # Incremented to revoke every session of this user (logout, password change or reset,
    # deactivation, role change). Tokens carry the version they were issued with.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # Set when an administrator issues a temporary password; cleared when the user changes it.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class DriverAssignment(Base):
    """History of which driver was assigned to which truck, and when.

    Exclusion constraints (created in the migration) forbid overlapping periods for the same
    truck or the same driver, so at most one assignment is active per truck and per driver,
    and "who drove truck X at time T" always has a single answer. trucks.driver_id remains
    the denormalised *current* assignment and is kept in sync by services.assignments.
    """

    __tablename__ = "driver_assignments"
    __table_args__ = (
        CheckConstraint(
            "released_at IS NULL OR released_at >= assigned_at", name="released_after_assigned"
        ),
        CheckConstraint("source IN ('manual', 'backfill', 'sample')", name="source_valid"),
        Index("ix_driver_assignments_truck_period", "truck_id", "assigned_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id", ondelete="CASCADE"), index=True)
    truck_id: Mapped[int] = mapped_column(ForeignKey("trucks.id", ondelete="CASCADE"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    released_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(10), default="manual", server_default="manual")

    driver: Mapped[Driver] = relationship()
    truck: Mapped[Truck] = relationship()
    assigned_by: Mapped[User | None] = relationship(foreign_keys=[assigned_by_id])
    released_by: Mapped[User | None] = relationship(foreign_keys=[released_by_id])


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
    """A loading or dispatch delay.

    occurred_at = when the delay started; resolved_at = when it was resolved.
    Duration is always derived from those two stored timestamps. delay_minutes is the
    reported impact on the operation (e.g. lateness against ETA).
    """

    __tablename__ = "delay_incidents"
    __table_args__ = (
        CheckConstraint("delay_minutes >= 0", name="delay_non_negative"),
        CheckConstraint(
            "dispatch_id IS NOT NULL OR schedule_id IS NOT NULL", name="linked_to_operation"
        ),
        CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL)", name="resolved_has_time"
        ),
        CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= occurred_at", name="resolved_after_start"
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
    delay_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    description: Mapped[str | None] = mapped_column(Text)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[IncidentStatus] = mapped_column(
        _enum(IncidentStatus, "incident_status"), default=IncidentStatus.OPEN, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assigned_to_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    dispatch: Mapped[Dispatch | None] = relationship()
    schedule: Mapped[LoadingSchedule | None] = relationship()
    assigned_to: Mapped[User | None] = relationship(foreign_keys=[assigned_to_id])
    reported_by: Mapped[User | None] = relationship(foreign_keys=[reported_by_id])


class ComplianceRequirement(Base):
    """Configurable rule: which document types a truck must hold to be dispatched."""

    __tablename__ = "compliance_requirements"
    __table_args__ = (
        CheckConstraint("reminder_days BETWEEN 1 AND 365", name="reminder_range"),
        CheckConstraint(
            "min_capacity_tonnes IS NULL OR min_capacity_tonnes > 0", name="capacity_positive"
        ),
        CheckConstraint("doc_type <> 'other' OR NOT is_mandatory", name="other_not_mandatory"),
    )

    doc_type: Mapped[DocumentType] = mapped_column(
        _enum(DocumentType, "requirement_document_type"), primary_key=True
    )
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    # Applies only to trucks with at least this capacity (NULL = all trucks).
    min_capacity_tonnes: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    reminder_days: Mapped[int] = mapped_column(Integer, default=30, server_default=text("30"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ComplianceDocument(TimestampMixin, Base):
    """A vehicle document. Renewals create a new row; the old one is kept as history
    (superseded_at set) so the compliance record is never overwritten."""

    __tablename__ = "compliance_documents"
    __table_args__ = (
        CheckConstraint("expires_on > issued_on", name="expiry_after_issue"),
        CheckConstraint("file_size IS NULL OR file_size > 0", name="file_size_positive"),
        Index("ix_compliance_documents_truck_type", "truck_id", "doc_type"),
        # Only one *current* document per truck and type ('other' may repeat).
        Index(
            "uq_compliance_documents_current",
            "truck_id",
            "doc_type",
            unique=True,
            postgresql_where=text("superseded_at IS NULL AND doc_type <> 'other'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    truck_id: Mapped[int] = mapped_column(ForeignKey("trucks.id", ondelete="CASCADE"))
    doc_type: Mapped[DocumentType] = mapped_column(_enum(DocumentType, "document_type"))
    reference_number: Mapped[str] = mapped_column(String(80))
    issuing_authority: Mapped[str | None] = mapped_column(String(120))
    issued_on: Mapped[date] = mapped_column(Date)
    expires_on: Mapped[date] = mapped_column(Date, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    renewed_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("compliance_documents.id", ondelete="SET NULL"), unique=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Supporting file (stored on disk under an opaque key, never a user-supplied path).
    storage_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_content_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(Integer)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    file_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    truck: Mapped[Truck] = relationship()


class Alert(TimestampMixin, Base):
    """Operational alert. Deduplicated by dedup_key: at most one unresolved alert per key."""

    __tablename__ = "alerts"
    __table_args__ = (
        Index(
            "uq_alerts_active_dedup_key",
            "dedup_key",
            unique=True,
            postgresql_where=text("status <> 'resolved'"),
        ),
        Index("ix_alerts_status_severity", "status", "severity"),
        CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL)", name="resolved_has_time"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_type: Mapped[AlertType] = mapped_column(_enum(AlertType, "alert_type"), index=True)
    severity: Mapped[AlertSeverity] = mapped_column(_enum(AlertSeverity, "alert_severity"))
    status: Mapped[AlertStatus] = mapped_column(
        _enum(AlertStatus, "alert_status"), default=AlertStatus.OPEN
    )
    dedup_key: Mapped[str] = mapped_column(String(160), index=True)
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(String(500))
    truck_id: Mapped[int | None] = mapped_column(
        ForeignKey("trucks.id", ondelete="CASCADE"), index=True
    )
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("loading_schedules.id", ondelete="CASCADE")
    )
    dispatch_id: Mapped[int | None] = mapped_column(ForeignKey("dispatches.id", ondelete="CASCADE"))
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("compliance_documents.id", ondelete="CASCADE")
    )
    incident_id: Mapped[int | None] = mapped_column(
        ForeignKey("delay_incidents.id", ondelete="CASCADE")
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolution_note: Mapped[str | None] = mapped_column(String(500))
    auto_resolved: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )

    truck: Mapped[Truck | None] = relationship()
    acknowledged_by: Mapped[User | None] = relationship(foreign_keys=[acknowledged_by_id])
    resolved_by: Mapped[User | None] = relationship(foreign_keys=[resolved_by_id])


class AuthThrottle(Base):
    """Failed sign-in counters for brute-force / credential-stuffing protection.

    key = "acct:<sha256 of normalised identifier>" or "ip:<address>". Identifiers are hashed
    so mistyped passwords pasted into the username field are never stored in clear text.
    """

    __tablename__ = "auth_throttles"
    __table_args__ = (CheckConstraint("failures >= 0", name="failures_non_negative"),)

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReportRun(Base):
    """History of generated reports/exports. The documents themselves are not stored."""

    __tablename__ = "report_runs"
    __table_args__ = (
        CheckConstraint("format IN ('csv', 'pdf', 'xlsx')", name="format_valid"),
        CheckConstraint("status IN ('success', 'failed')", name="status_valid"),
        CheckConstraint("row_count IS NULL OR row_count >= 0", name="row_count_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    report_type: Mapped[str] = mapped_column(String(40), index=True)
    format: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10))
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    row_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(255))
    requested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    requested_by: Mapped[User | None] = relationship()


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
