"""Vehicle compliance rules.

A document is *valid through* its expiry date:
    expired   expires_on < today
    expiring  today <= expires_on <= today + reminder_days (per document type)
    valid     otherwise
    missing   a mandatory, applicable document type has no current document

Requirements are configurable (compliance_requirements): whether a type is mandatory and,
optionally, the minimum truck capacity it applies to. A truck is eligible for dispatch only
if every applicable mandatory document is present and not expired, and the truck is not
under maintenance / out of service.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ComplianceDocument,
    ComplianceRequirement,
    DocumentType,
    Truck,
    TruckStatus,
)

DOC_LABELS = {
    DocumentType.INSURANCE: "Insurance",
    DocumentType.LICENCE: "Vehicle licence",
    DocumentType.INSPECTION: "Inspection certificate",
    DocumentType.ROADWORTHY: "Roadworthiness certificate",
    DocumentType.SPEED_GOVERNOR: "Speed governor certificate",
    DocumentType.OTHER: "Other document",
}
TRACKED_TYPES = [t for t in DocumentType if t != DocumentType.OTHER]
DEFAULT_REMINDER_DAYS = 30
# Seeded by migration 4cdcd62eb0a9; administrators / compliance officers can change them.
DEFAULT_MANDATORY = {DocumentType.INSURANCE, DocumentType.LICENCE, DocumentType.INSPECTION}


def default_requirement_rows() -> list[dict]:
    return [
        {
            "doc_type": t.value,
            "is_mandatory": t in DEFAULT_MANDATORY,
            "reminder_days": DEFAULT_REMINDER_DAYS,
        }
        for t in DocumentType
    ]


@dataclass
class ItemState:
    doc_type: DocumentType
    mandatory: bool
    state: str  # valid | expiring | expired | missing | not_required
    document: ComplianceDocument | None = None
    days_remaining: int | None = None


@dataclass
class TruckCompliance:
    truck: Truck
    items: list[ItemState]
    status: str  # compliant | expiring | non_compliant
    blockers: list[str] = field(default_factory=list)

    @property
    def eligible(self) -> bool:
        return not self.blockers


def document_state(expires_on: date, today: date, reminder_days: int) -> str:
    if expires_on < today:
        return "expired"
    if expires_on <= today + timedelta(days=reminder_days):
        return "expiring"
    return "valid"


def load_requirements(db: Session) -> dict[DocumentType, ComplianceRequirement]:
    return {r.doc_type: r for r in db.scalars(select(ComplianceRequirement))}


def is_applicable(req: ComplianceRequirement | None, truck: Truck) -> bool:
    if req is None or not req.is_mandatory:
        return False
    return (
        req.min_capacity_tonnes is None or Decimal(truck.capacity_tonnes) >= req.min_capacity_tonnes
    )


def current_documents(
    db: Session, truck_ids: list[int]
) -> dict[int, dict[DocumentType, ComplianceDocument]]:
    result: dict[int, dict[DocumentType, ComplianceDocument]] = {t: {} for t in truck_ids}
    if not truck_ids:
        return result
    for doc in db.scalars(
        select(ComplianceDocument).where(
            ComplianceDocument.truck_id.in_(truck_ids),
            ComplianceDocument.superseded_at.is_(None),
            ComplianceDocument.doc_type != DocumentType.OTHER,
        )
    ):
        result[doc.truck_id][doc.doc_type] = doc
    return result


def _fmt(d: date) -> str:
    return d.strftime("%d %b %Y").lstrip("0")


def evaluate(
    truck: Truck,
    docs: dict[DocumentType, ComplianceDocument],
    reqs: dict[DocumentType, ComplianceRequirement],
    today: date,
) -> TruckCompliance:
    items: list[ItemState] = []
    blockers: list[str] = []
    if truck.status == TruckStatus.MAINTENANCE:
        blockers.append(f"{truck.registration} is under maintenance.")
    elif truck.status == TruckStatus.OUT_OF_SERVICE:
        blockers.append(f"{truck.registration} is out of service.")

    any_expiring = any_missing_or_expired = False
    for doc_type in TRACKED_TYPES:
        req = reqs.get(doc_type)
        mandatory = is_applicable(req, truck)
        reminder = req.reminder_days if req else DEFAULT_REMINDER_DAYS
        doc = docs.get(doc_type)
        label = DOC_LABELS[doc_type]
        if doc is None:
            state = "missing" if mandatory else "not_required"
            if mandatory:
                any_missing_or_expired = True
                blockers.append(f"{label} is missing.")
            items.append(ItemState(doc_type, mandatory, state))
            continue
        state = document_state(doc.expires_on, today, reminder)
        if state == "expired" and mandatory:
            any_missing_or_expired = True
            blockers.append(f"{label} expired on {_fmt(doc.expires_on)}.")
        elif state in ("expiring", "expired"):
            any_expiring = True
        items.append(ItemState(doc_type, mandatory, state, doc, (doc.expires_on - today).days))

    status = (
        "non_compliant" if any_missing_or_expired else "expiring" if any_expiring else "compliant"
    )
    return TruckCompliance(truck=truck, items=items, status=status, blockers=blockers)


def evaluate_trucks(db: Session, trucks: list[Truck], today: date) -> dict[int, TruckCompliance]:
    reqs = load_requirements(db)
    docs = current_documents(db, [t.id for t in trucks])
    return {t.id: evaluate(t, docs[t.id], reqs, today) for t in trucks}


def dispatch_blockers(db: Session, truck: Truck, today: date) -> list[str]:
    """Server-side gate used at the moment of dispatch."""
    return evaluate_trucks(db, [truck], today)[truck.id].blockers
