from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from .models import DelayCause, IncidentStatus, Role
from .schemas_ops import Ref


class IncidentIn(BaseModel):
    schedule_id: int | None = None
    dispatch_id: int | None = None
    cause: DelayCause
    started_at: AwareDatetime | None = Field(
        default=None, description="When the delay began; defaults to now"
    )
    impact_minutes: int = Field(default=0, ge=0, le=48 * 60)
    description: str = Field(min_length=3, max_length=1000)
    assigned_to_id: int | None = None

    @model_validator(mode="after")
    def one_operation(self) -> IncidentIn:
        if (self.schedule_id is None) == (self.dispatch_id is None):
            raise ValueError("Link the delay to exactly one loading schedule or dispatch")
        return self


class IncidentUpdate(BaseModel):
    """Partial update. Send `assigned_to_id: null` explicitly to unassign."""

    status: IncidentStatus | None = None
    cause: DelayCause | None = None
    assigned_to_id: int | None = None
    impact_minutes: int | None = Field(default=None, ge=0, le=48 * 60)
    resolution_notes: str | None = Field(default=None, max_length=1000)
    resolved_at: AwareDatetime | None = None


class IncidentOut(BaseModel):
    id: int
    source: Literal["loading", "dispatch"]
    truck: Ref | None
    operation: str
    load_ref: str | None
    schedule_id: int | None
    dispatch_id: int | None
    cause: DelayCause
    status: IncidentStatus
    started_at: datetime
    resolved_at: datetime | None
    duration_minutes: int
    is_ongoing: bool
    impact_minutes: int
    description: str | None
    resolution_notes: str | None
    assigned_to: Ref | None
    reported_by: str | None
    created_at: datetime


class CauseCount(BaseModel):
    cause: DelayCause
    count: int
    impact_minutes: int


class IncidentSummary(BaseModel):
    unresolved: int
    unassigned: int
    resolved_7d: int
    avg_resolution_minutes_30d: float | None
    impact_minutes_7d: int
    oldest_unresolved_minutes: int | None
    by_cause_30d: list[CauseCount]
    sample_data: bool


class AssignableUser(BaseModel):
    id: int
    label: str
    role: Role
