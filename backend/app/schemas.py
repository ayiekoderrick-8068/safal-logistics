from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import DispatchStatus, DocumentType, Role, UserStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth ----------
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255, description="Username or email")
    password: str = Field(min_length=1, max_length=128)


class UserOut(ORMModel):
    id: int
    email: str
    username: str
    full_name: str
    role: Role
    status: UserStatus
    last_login_at: datetime | None
    must_change_password: bool = False


class LoginResponse(BaseModel):
    user: UserOut
    expires_in_seconds: int


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


# ---------- User management (administrators) ----------
_USERNAME = r"^[a-z0-9][a-z0-9._-]{2,49}$"


class AdminUserOut(UserOut):
    created_at: datetime
    password_changed_at: datetime | None


class UserCreate(BaseModel):
    username: str = Field(pattern=_USERNAME, description="3-50 chars: a-z 0-9 . _ -")
    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=2, max_length=120)
    role: Role
    temporary_password: str = Field(min_length=1, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def _lower(cls, v: str) -> str:
        return str(v).strip().lower()

    @field_validator("full_name", mode="before")
    @classmethod
    def _clean(cls, v: str) -> str:
        return " ".join(str(v).split())


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    role: Role | None = None
    status: Literal["active", "deactivated"] | None = None


class PasswordReset(BaseModel):
    temporary_password: str = Field(min_length=1, max_length=128)


# ---------- Meta / health ----------
class HealthOut(BaseModel):
    status: str
    database: str


class MetaOut(BaseModel):
    app: str = "LogiTrack"
    version: str
    timezone: str
    turnaround_target_minutes: int
    delay_grace_minutes: int
    sample_data: bool


# ---------- Dashboard ----------
class KpiValue(BaseModel):
    current: float | None
    previous: float | None


class DashboardKpis(BaseModel):
    loads_processed: KpiValue
    avg_turnaround_minutes: KpiValue
    within_target_pct: KpiValue
    on_time_delivery_pct: KpiValue
    delay_incidents: KpiValue
    bay_utilization_pct: KpiValue


class TrendPoint(BaseModel):
    day: date
    loads_processed: int
    avg_turnaround_minutes: float | None
    on_time_delivery_pct: float | None


class StatusCount(BaseModel):
    status: str
    count: int


class RecentDispatch(BaseModel):
    id: int
    load_ref: str
    truck_registration: str
    route: str
    dispatched_at: datetime
    expected_arrival_at: datetime
    actual_arrival_at: datetime | None
    status: DispatchStatus
    is_delayed: bool


class ExpiryAlert(BaseModel):
    truck_registration: str
    doc_type: DocumentType
    expires_on: date
    days_remaining: int


class DashboardOverview(BaseModel):
    period_start: date
    period_end: date
    previous_period_start: date
    previous_period_end: date
    sample_data: bool
    turnaround_target_minutes: int
    kpis: DashboardKpis
    trend: list[TrendPoint]
    dispatch_status: list[StatusCount]
    delayed_dispatches: int
    fleet_status: list[StatusCount]
    fleet_total: int
    open_delay_incidents: int
    recent_dispatches: list[RecentDispatch]
    expiry_alerts: list[ExpiryAlert]
