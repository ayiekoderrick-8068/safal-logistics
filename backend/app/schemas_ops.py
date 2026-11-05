"""Request/response schemas for fleet, loading-bay and dispatch operations."""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import (
    DelayCause,
    DispatchStatus,
    DocumentType,
    ScheduleStatus,
    TruckStatus,
)

MAX_BOOKING = timedelta(hours=12)
_REGISTRATION = re.compile(r"^[A-Z0-9][A-Z0-9 -]{1,18}[A-Z0-9]$")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class Ref(BaseModel):
    id: int
    label: str


# ---------- Drivers ----------
class DriverIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    licence_number: str = Field(min_length=3, max_length=50)
    licence_expiry: date | None = None

    @field_validator("full_name", "licence_number", "phone", mode="before")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        return _clean(v) if isinstance(v, str) else v

    @field_validator("licence_number")
    @classmethod
    def upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("phone")
    @classmethod
    def phone_format(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"\+?[0-9 ]{7,20}", v):
            raise ValueError("Phone must contain 7-20 digits, optionally starting with +")
        return v


class DriverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    phone: str | None
    licence_number: str
    licence_expiry: date | None
    is_active: bool
    truck_id: int | None = None
    truck_registration: str | None = None


# ---------- Trucks ----------
class TruckIn(BaseModel):
    registration: str = Field(min_length=3, max_length=20)
    make: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=60)
    capacity_tonnes: Decimal = Field(gt=0, le=100, decimal_places=2)
    driver_id: int | None = None

    @field_validator("registration", mode="before")
    @classmethod
    def normalise_registration(cls, v: str) -> str:
        v = " ".join(str(v).upper().split())
        if not _REGISTRATION.fullmatch(v):
            raise ValueError("Use letters, digits and spaces only, e.g. KDA 123A")
        return v

    @field_validator("make", "model", mode="before")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        return _clean(v) if isinstance(v, str) else v


class TruckUpdate(BaseModel):
    """Partial update. Send `driver_id: null` explicitly to unassign the driver."""

    make: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=60)
    capacity_tonnes: Decimal | None = Field(default=None, gt=0, le=100, decimal_places=2)
    driver_id: int | None = None
    status: Literal["available", "maintenance", "out_of_service"] | None = None


class ComplianceSummary(BaseModel):
    status: Literal["valid", "expiring", "overdue", "missing"]
    next_expiry: date | None = None
    next_expiry_type: DocumentType | None = None


class TruckOut(BaseModel):
    id: int
    registration: str
    make: str | None
    model: str | None
    capacity_tonnes: float
    status: TruckStatus
    driver: Ref | None
    last_route: str | None
    last_dispatched_at: datetime | None
    compliance: ComplianceSummary


class TruckDocument(BaseModel):
    doc_type: DocumentType
    reference_number: str
    expires_on: date
    days_remaining: int


class TruckDetail(TruckOut):
    documents: list[TruckDocument]
    loads_completed_30d: int
    avg_turnaround_30d: float | None


class FleetSummary(BaseModel):
    total: int
    available: int
    loading: int
    in_transit: int
    maintenance: int
    out_of_service: int
    compliance_due: int
    availability_pct: float | None


# ---------- Routes & bays ----------
class RouteIn(BaseModel):
    origin: str = Field(min_length=2, max_length=80)
    destination: str = Field(min_length=2, max_length=80)
    distance_km: Decimal = Field(gt=0, le=5000, decimal_places=1)
    expected_duration_minutes: int = Field(gt=0, le=72 * 60)

    @field_validator("origin", "destination", mode="before")
    @classmethod
    def title(cls, v: str) -> str:
        return (_clean(v) or "").title()

    @model_validator(mode="after")
    def distinct(self) -> RouteIn:
        if self.origin.lower() == self.destination.lower():
            raise ValueError("Origin and destination must differ")
        return self


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    origin: str
    destination: str
    label: str
    distance_km: float
    expected_duration_minutes: int
    is_active: bool


class BayIn(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str = Field(min_length=2, max_length=80)
    target_turnaround_minutes: int | None = Field(default=None, gt=0, le=24 * 60)

    @field_validator("code", mode="before")
    @classmethod
    def upper(cls, v: str) -> str:
        return "-".join(str(v).upper().split())


class BayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    target_turnaround_minutes: int | None
    effective_target_minutes: int
    is_active: bool


# ---------- Loading schedules ----------
class ScheduleIn(BaseModel):
    truck_id: int
    bay_id: int
    scheduled_start: AwareDatetime
    scheduled_end: AwareDatetime
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def window(self) -> ScheduleIn:
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("Scheduled end must be after the start")
        if self.scheduled_end - self.scheduled_start > MAX_BOOKING:
            raise ValueError("A bay booking cannot exceed 12 hours")
        return self


ScheduleEventType = Literal["arrived", "loading_started", "loading_finished"]


class ScheduleEventIn(BaseModel):
    event: ScheduleEventType
    at: AwareDatetime | None = Field(default=None, description="Defaults to now")


class ScheduleOut(BaseModel):
    id: int
    truck: Ref
    driver_name: str | None
    bay: Ref
    scheduled_start: datetime
    scheduled_end: datetime
    arrival_at: datetime | None
    loading_started_at: datetime | None
    loading_finished_at: datetime | None
    departed_at: datetime | None
    status: ScheduleStatus
    notes: str | None
    loading_minutes: float | None
    turnaround_minutes: float | None
    target_minutes: int
    within_target: bool | None
    is_late: bool
    late_minutes: int
    dispatch_id: int | None
    load_ref: str | None


class HourBucket(BaseModel):
    hour: int
    scheduled: int
    completed: int


class BayBoardItem(BaseModel):
    bay: BayOut
    state: Literal["in_use", "reserved", "available", "inactive"]
    schedule: ScheduleOut | None
    progress_pct: int | None


class LoadingOverview(BaseModel):
    date: date
    active_bays: int
    total_bays: int
    scheduled_count: int
    completed_count: int
    avg_loading_minutes: float | None
    avg_loading_minutes_previous_day: float | None
    avg_turnaround_minutes: float | None
    late_count: int
    hourly: list[HourBucket]
    bay_board: list[BayBoardItem]
    upcoming: list[ScheduleOut]
    late: list[ScheduleOut]
    sample_data: bool


# ---------- Dispatch ----------
class DispatchIn(BaseModel):
    schedule_id: int
    route_id: int
    dispatched_at: AwareDatetime | None = Field(default=None, description="Defaults to now")
    notes: str | None = Field(default=None, max_length=500)


class DeliverIn(BaseModel):
    actual_arrival_at: AwareDatetime | None = Field(default=None, description="Defaults to now")
    delay_cause: DelayCause | None = None
    delay_notes: str | None = Field(default=None, max_length=500)


class FlagDelayIn(BaseModel):
    cause: DelayCause
    estimated_delay_minutes: int = Field(gt=0, le=48 * 60)
    description: str | None = Field(default=None, max_length=500)


class DispatchOut(BaseModel):
    id: int
    load_ref: str
    schedule_id: int | None
    truck: Ref
    driver_name: str | None
    route: Ref
    dispatched_at: datetime
    expected_arrival_at: datetime
    actual_arrival_at: datetime | None
    status: DispatchStatus
    is_delayed: bool
    is_overdue: bool
    delay_minutes: int
    delivery_minutes: float | None
    turnaround_minutes: float | None
    delay_cause: DelayCause | None


class DispatchHourBucket(BaseModel):
    hour: int
    delivered: int
    in_transit: int
    delayed: int


class DispatchOverview(BaseModel):
    date: date
    active: int
    in_transit: int
    delayed_active: int
    delivered_today: int
    delivered_previous_day: int
    on_time_rate_7d: float | None
    on_time_rate_prev_7d: float | None
    delayed_rate_7d: float | None
    avg_delivery_minutes_7d: float | None
    status_breakdown: list[dict[str, int | str]]
    hourly: list[DispatchHourBucket]
    alerts: list[DispatchOut]
    sample_data: bool
