from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

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


class LoginResponse(BaseModel):
    user: UserOut
    expires_in_seconds: int


# ---------- Meta / health ----------
class HealthOut(BaseModel):
    status: str
    database: str


class MetaOut(BaseModel):
    app: str = "LogiTrack"
    version: str
    timezone: str
    turnaround_target_minutes: int
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
