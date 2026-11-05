from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import DocumentType
from .schemas_ops import Ref

MAX_VALIDITY = timedelta(days=10 * 365)
DocState = Literal["valid", "expiring", "expired", "missing", "not_required"]


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = " ".join(v.split())
    return v or None


class _DocFields(BaseModel):
    reference_number: str = Field(min_length=1, max_length=80)
    issuing_authority: str | None = Field(default=None, max_length=120)
    issued_on: date
    expires_on: date
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("reference_number", "issuing_authority", mode="before")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        return _clean(v) if isinstance(v, str) else v

    @model_validator(mode="after")
    def dates(self) -> _DocFields:
        if self.expires_on <= self.issued_on:
            raise ValueError("Expiry date must be after the issue date")
        if self.expires_on - self.issued_on > MAX_VALIDITY:
            raise ValueError("Validity cannot exceed 10 years")
        return self


class DocumentIn(_DocFields):
    truck_id: int
    doc_type: DocumentType


class RenewIn(_DocFields):
    pass


class FileInfo(BaseModel):
    name: str
    content_type: str
    size: int
    uploaded_at: datetime


class DocumentOut(BaseModel):
    id: int
    truck: Ref
    doc_type: DocumentType
    reference_number: str
    issuing_authority: str | None
    issued_on: date
    expires_on: date
    days_remaining: int
    state: Literal["valid", "expiring", "expired"]
    is_current: bool
    superseded_at: datetime | None
    renewed_from_id: int | None
    file: FileInfo | None
    notes: str | None
    created_at: datetime


class RequirementOut(BaseModel):
    doc_type: DocumentType
    label: str
    is_mandatory: bool
    min_capacity_tonnes: float | None
    reminder_days: int


class RequirementUpdate(BaseModel):
    is_mandatory: bool
    min_capacity_tonnes: Decimal | None = Field(default=None, gt=0, le=100)
    reminder_days: int = Field(default=30, ge=1, le=365)


class ItemOut(BaseModel):
    doc_type: DocumentType
    mandatory: bool
    state: DocState
    document_id: int | None
    expires_on: date | None
    days_remaining: int | None


class VehicleCompliance(BaseModel):
    truck: Ref
    driver_name: str | None
    truck_status: str
    status: Literal["compliant", "expiring", "non_compliant"]
    eligible: bool
    blockers: list[str]
    items: list[ItemOut]


class Eligibility(BaseModel):
    truck: Ref
    eligible: bool
    reasons: list[str]


class TypeBreakdown(BaseModel):
    doc_type: DocumentType
    valid: int
    expiring: int
    expired: int
    missing: int


class UpcomingRenewal(BaseModel):
    document_id: int
    truck: Ref
    doc_type: DocumentType
    expires_on: date
    days_remaining: int
    state: Literal["valid", "expiring", "expired"]


class ComplianceOverview(BaseModel):
    total_vehicles: int
    compliant_vehicles: int
    expiring_vehicles: int
    non_compliant_vehicles: int
    compliant_pct: float | None
    expiring_documents: int
    expired_documents: int
    missing_documents: int
    documents_on_record: int
    documents_added_30d: int
    inspections_due_30d: int
    by_type: list[TypeBreakdown]
    upcoming: list[UpcomingRenewal]
    sample_data: bool
