from datetime import date, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import MaintenanceRole
from .models_maintenance import (
    BreakdownSeverity,
    EquipmentCategory,
    EquipmentStatus,
    FaultCategory,
    IntervalUnit,
    ScheduleBasis,
    TaskStatus,
    WorkOrderPriority,
    WorkOrderStatus,
    WorkOrderType,
)

CODE_PATTERN = r"^[A-Z0-9][A-Z0-9-]{1,29}$"
TEXT_FIELDS = (
    "name",
    "manufacturer",
    "model",
    "serial_number",
    "facility",
    "department",
    "location",
)


def _clean(v: object) -> object:
    """Trim and collapse whitespace; empty strings become None."""
    if isinstance(v, str):
        v = " ".join(v.split())
        return v or None
    return v


class Person(BaseModel):
    id: int
    full_name: str


class Technician(Person):
    maintenance_role: MaintenanceRole


# ---------- Equipment ----------
class _EquipmentFields(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: EquipmentCategory
    manufacturer: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    serial_number: str | None = Field(default=None, max_length=80)
    facility: str = Field(min_length=2, max_length=80)
    department: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=120)
    installed_on: date | None = None
    status: EquipmentStatus = EquipmentStatus.OPERATIONAL
    assigned_technician_id: int | None = None
    last_service_on: date | None = None
    next_service_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator(*TEXT_FIELDS, mode="before")
    @classmethod
    def _text(cls, v: object) -> object:
        return _clean(v)

    @field_validator("notes", mode="before")
    @classmethod
    def _notes(cls, v: object) -> object:
        return (v.strip() or None) if isinstance(v, str) else v


class EquipmentIn(_EquipmentFields):
    code: str = Field(pattern=CODE_PATTERN, description="Equipment ID, e.g. CNV-001")

    @field_validator("code", mode="before")
    @classmethod
    def _upper(cls, v: object) -> object:
        return str(v).strip().upper() if v is not None else v

    @model_validator(mode="after")
    def _dates(self) -> Self:
        check_service_dates(self.installed_on, self.last_service_on, self.next_service_on)
        return self


class EquipmentUpdate(BaseModel):
    """Partial update: only fields that are sent change (send null to clear an optional one)."""

    name: str | None = Field(default=None, min_length=2, max_length=120)
    category: EquipmentCategory | None = None
    manufacturer: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    serial_number: str | None = Field(default=None, max_length=80)
    facility: str | None = Field(default=None, min_length=2, max_length=80)
    department: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=120)
    installed_on: date | None = None
    status: EquipmentStatus | None = None
    assigned_technician_id: int | None = None
    last_service_on: date | None = None
    next_service_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator(*TEXT_FIELDS, mode="before")
    @classmethod
    def _text(cls, v: object) -> object:
        return _clean(v)

    @field_validator("notes", mode="before")
    @classmethod
    def _notes(cls, v: object) -> object:
        return (v.strip() or None) if isinstance(v, str) else v


def check_service_dates(installed: date | None, last: date | None, nxt: date | None) -> None:
    if last and installed and last < installed:
        raise ValueError("The last service date cannot be before the installation date.")
    if nxt and last and nxt < last:
        raise ValueError("The next service date cannot be before the last service date.")


class EquipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    category: EquipmentCategory
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    facility: str
    department: str | None
    location: str | None
    installed_on: date | None
    status: EquipmentStatus
    assigned_technician: Person | None
    last_service_on: date | None
    next_service_on: date | None
    notes: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Derived from next_service_on and today's date in the configured timezone.
    service_state: str  # "overdue" | "due_soon" | "scheduled" | "not_scheduled"
    days_until_service: int | None


class EquipmentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    kind: str
    summary: str
    changes: dict[str, Any] | None
    actor: Person | None


class EquipmentDetail(EquipmentOut):
    history: list[EquipmentEventOut]
    # True once preventive maintenance sets the service dates (they are then read-only here).
    schedule_managed: bool = False


class EquipmentSummary(BaseModel):
    """Counts over the active (non-archived) register."""

    total: int
    operational: int
    under_maintenance: int
    out_of_service: int
    service_overdue: int
    service_due_soon: int
    archived: int
    due_soon_days: int


class EquipmentOptions(BaseModel):
    """Values already in use, offered as suggestions, plus assignable technicians."""

    facilities: list[str]
    departments: list[str]
    locations: list[str]
    technicians: list[Technician]


# ---------- Preventive maintenance ----------
def _text(v: object) -> object:
    return (" ".join(v.split()) or None) if isinstance(v, str) else v


class EquipmentRef(BaseModel):
    id: int
    code: str
    name: str


class PlanIn(BaseModel):
    equipment_id: int
    title: str = Field(min_length=3, max_length=120)
    instructions: str | None = Field(default=None, max_length=4000)
    interval_value: int = Field(ge=1, le=3650)
    interval_unit: IntervalUnit
    schedule_basis: ScheduleBasis = ScheduleBasis.DUE_DATE
    start_on: date = Field(description="Due date of the first task")
    assigned_technician_id: int | None = None

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, v: object) -> object:
        return _text(v)


class PlanUpdate(BaseModel):
    """Changes apply to tasks generated from now on; the open task keeps its due date
    unless it is rescheduled separately."""

    title: str | None = Field(default=None, min_length=3, max_length=120)
    instructions: str | None = Field(default=None, max_length=4000)
    interval_value: int | None = Field(default=None, ge=1, le=3650)
    interval_unit: IntervalUnit | None = None
    schedule_basis: ScheduleBasis | None = None
    assigned_technician_id: int | None = None

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, v: object) -> object:
        return _text(v)


class PlanActivate(BaseModel):
    next_due_on: date


class TaskBrief(BaseModel):
    id: int
    due_on: date
    state: str
    days_until_due: int


class PlanOut(BaseModel):
    id: int
    equipment: EquipmentRef
    title: str
    instructions: str | None
    interval_value: int
    interval_unit: IntervalUnit
    schedule_basis: ScheduleBasis
    start_on: date
    assigned_technician: Person | None
    is_active: bool
    next_task: TaskBrief | None
    last_completed_on: date | None
    created_at: datetime


class TaskIn(BaseModel):
    """A once-off scheduled service (not part of a recurring plan)."""

    equipment_id: int
    title: str = Field(min_length=3, max_length=120)
    due_on: date
    assigned_technician_id: int | None = None

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, v: object) -> object:
        return _text(v)


class TaskUpdate(BaseModel):
    due_on: date | None = None
    assigned_technician_id: int | None = None


class TaskComplete(BaseModel):
    completed_on: date
    work_notes: str = Field(min_length=3, max_length=4000, description="Work performed")

    @field_validator("work_notes", mode="before")
    @classmethod
    def _notes(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


class TaskCancel(BaseModel):
    reason: str = Field(min_length=3, max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def _reason(cls, v: object) -> object:
        return _text(v) or ""


class TaskOut(BaseModel):
    id: int
    plan_id: int | None
    equipment: EquipmentRef
    title: str
    instructions: str | None
    due_on: date
    status: TaskStatus
    state: str  # overdue | due_today | upcoming | completed | cancelled
    days_until_due: int
    assigned_technician: Person | None
    completed_on: date | None
    completed_by: Person | None
    completed_on_time: bool | None
    work_notes: str | None
    cancel_reason: str | None


class PmCompliance(BaseModel):
    """Tasks due in the window (cancelled excluded): how many were completed by their due date."""

    window_days: int
    due: int
    completed_on_time: int
    completed_late: int
    not_completed: int
    pct: float | None  # None = no task fell due in the window (insufficient data)


class PmSummary(BaseModel):
    overdue: int
    due_today: int
    due_next_7_days: int
    open: int
    active_plans: int
    completed_last_30_days: int
    compliance: PmCompliance


# ---------- Breakdowns ----------
def _long_text(v: object) -> object:
    return (v.strip() or None) if isinstance(v, str) else v


class BreakdownIn(BaseModel):
    equipment_id: int
    started_at: datetime = Field(description="When the failure began")
    severity: BreakdownSeverity
    category: FaultCategory
    description: str = Field(min_length=5, max_length=4000)
    possible_cause: str | None = Field(default=None, max_length=4000)
    equipment_down: bool = True
    create_work_order: bool = Field(
        default=True, description="Also raise a corrective work order for the repair"
    )

    @field_validator("description", "possible_cause", mode="before")
    @classmethod
    def _t(cls, v: object) -> object:
        return _long_text(v)


class BreakdownUpdate(BaseModel):
    severity: BreakdownSeverity | None = None
    category: FaultCategory | None = None
    description: str | None = Field(default=None, min_length=5, max_length=4000)
    possible_cause: str | None = Field(default=None, max_length=4000)
    actions_taken: str | None = Field(default=None, max_length=4000)

    @field_validator("description", "possible_cause", "actions_taken", mode="before")
    @classmethod
    def _t(cls, v: object) -> object:
        return _long_text(v)


class BreakdownRestore(BaseModel):
    restored_at: datetime
    actions_taken: str = Field(min_length=5, max_length=4000, description="Repairs and actions")

    @field_validator("actions_taken", mode="before")
    @classmethod
    def _t(cls, v: object) -> object:
        return _long_text(v) or ""


class WorkOrderBrief(BaseModel):
    id: int
    number: str
    status: WorkOrderStatus


class BreakdownOut(BaseModel):
    id: int
    number: str
    equipment: EquipmentRef
    started_at: datetime
    restored_at: datetime | None
    is_open: bool
    downtime_minutes: int  # to restoration, or to now while still open
    severity: BreakdownSeverity
    category: FaultCategory
    description: str
    possible_cause: str | None
    actions_taken: str | None
    equipment_down: bool
    reported_by: Person | None
    restored_by: Person | None
    work_orders: list[WorkOrderBrief]


class RankedEquipment(BaseModel):
    equipment: EquipmentRef
    breakdowns: int
    downtime_minutes: int


class CategoryCount(BaseModel):
    category: FaultCategory
    breakdowns: int
    downtime_minutes: int


class BreakdownSummary(BaseModel):
    """Breakdowns overlapping the last `window_days`; downtime is clipped to the window and
    counts only failures that stopped the asset."""

    window_days: int
    open: int
    breakdowns: int
    downtime_minutes: int
    repeat_equipment: int  # assets with 2+ breakdowns in the window
    top_equipment: list[RankedEquipment]
    categories: list[CategoryCount]


# ---------- Work orders ----------
class WorkOrderIn(BaseModel):
    equipment_id: int
    maintenance_type: WorkOrderType
    priority: WorkOrderPriority
    fault_description: str = Field(min_length=5, max_length=4000)
    scheduled_on: date | None = None
    assigned_technician_id: int | None = None
    breakdown_id: int | None = None

    @field_validator("fault_description", mode="before")
    @classmethod
    def _t(cls, v: object) -> object:
        return _long_text(v)


class WorkOrderUpdate(BaseModel):
    priority: WorkOrderPriority | None = None
    fault_description: str | None = Field(default=None, min_length=5, max_length=4000)
    scheduled_on: date | None = None
    assigned_technician_id: int | None = None

    @field_validator("fault_description", mode="before")
    @classmethod
    def _t(cls, v: object) -> object:
        return _long_text(v)


class WorkOrderTransition(BaseModel):
    to: WorkOrderStatus
    note: str | None = Field(default=None, max_length=1000, description="Required to cancel")

    @field_validator("note", mode="before")
    @classmethod
    def _t(cls, v: object) -> object:
        return _text(v)


class WorkOrderComplete(BaseModel):
    work_performed: str = Field(min_length=10, max_length=4000)
    completion_notes: str | None = Field(default=None, max_length=4000)
    completed_at: datetime | None = Field(default=None, description="Defaults to now")
    restore_breakdown: bool = Field(
        default=False, description="Also record the linked breakdown as restored at completion"
    )

    @field_validator("work_performed", "completion_notes", mode="before")
    @classmethod
    def _t(cls, v: object) -> object:
        return _long_text(v)


class WorkOrderEventOut(BaseModel):
    id: int
    occurred_at: datetime
    from_status: WorkOrderStatus | None
    to_status: WorkOrderStatus | None
    summary: str
    note: str | None
    actor: Person | None


class BreakdownBrief(BaseModel):
    id: int
    number: str
    is_open: bool
    started_at: datetime
    restored_at: datetime | None


class WorkOrderOut(BaseModel):
    id: int
    number: str
    equipment: EquipmentRef
    maintenance_type: WorkOrderType
    priority: WorkOrderPriority
    status: WorkOrderStatus
    fault_description: str
    assigned_technician: Person | None
    scheduled_on: date | None
    overdue: bool  # scheduled date passed and not completed or cancelled
    created_at: datetime
    created_by: Person | None
    started_at: datetime | None
    completed_at: datetime | None
    repair_minutes: int | None  # start to completion
    work_performed: str | None
    completion_notes: str | None
    cancel_reason: str | None
    breakdown: BreakdownBrief | None
    allowed_transitions: list[WorkOrderStatus]


class WorkOrderDetail(WorkOrderOut):
    history: list[WorkOrderEventOut]


class WorkOrderSummary(BaseModel):
    open: int
    assigned: int
    in_progress: int
    awaiting_parts: int
    completed_last_30_days: int
    overdue: int
    critical_open: int
