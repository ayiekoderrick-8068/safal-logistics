from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..audit import record_event
from ..db import get_db
from ..deps import get_current_user, require_roles
from ..models import (
    ComplianceDocument,
    ComplianceRequirement,
    DocumentType,
    Driver,
    Role,
    Truck,
    User,
)
from ..schemas_compliance import (
    ComplianceOverview,
    DocumentIn,
    DocumentOut,
    Eligibility,
    FileInfo,
    ItemOut,
    RenewIn,
    RequirementOut,
    RequirementUpdate,
    TypeBreakdown,
    UpcomingRenewal,
    VehicleCompliance,
)
from ..schemas_ops import Page, Ref
from ..services import storage
from ..services.app_settings import is_sample_data
from ..services.compliance import (
    DEFAULT_REMINDER_DAYS,
    DOC_LABELS,
    TRACKED_TYPES,
    TruckCompliance,
    document_state,
    evaluate_trucks,
    load_requirements,
)
from ..services.operations import commit, conflict, invalid, local_today, not_found, utcnow

router = APIRouter(prefix="/api", tags=["compliance"])
DB = Annotated[Session, Depends(get_db)]
Reader = Annotated[User, Depends(get_current_user)]
# Compliance officers and fleet managers maintain documents; administrators always can.
DocWriter = Annotated[User, Depends(require_roles(Role.COMPLIANCE, Role.FLEET_MANAGER))]
RuleWriter = Annotated[User, Depends(require_roles(Role.COMPLIANCE))]


def _reminder(db: Session, doc_type: DocumentType) -> int:
    req = db.get(ComplianceRequirement, doc_type)
    return req.reminder_days if req else DEFAULT_REMINDER_DAYS


def _doc_out(doc: ComplianceDocument, reminder_days: int) -> DocumentOut:
    today = local_today()
    return DocumentOut(
        id=doc.id,
        truck=Ref(id=doc.truck.id, label=doc.truck.registration),
        doc_type=doc.doc_type,
        reference_number=doc.reference_number,
        issuing_authority=doc.issuing_authority,
        issued_on=doc.issued_on,
        expires_on=doc.expires_on,
        days_remaining=(doc.expires_on - today).days,
        state=document_state(doc.expires_on, today, reminder_days),  # type: ignore[arg-type]
        is_current=doc.superseded_at is None,
        superseded_at=doc.superseded_at,
        renewed_from_id=doc.renewed_from_id,
        file=FileInfo(
            name=doc.file_name,
            content_type=doc.file_content_type,
            size=doc.file_size,
            uploaded_at=doc.file_uploaded_at,
        )
        if doc.storage_key
        else None,  # type: ignore[arg-type]
        notes=doc.notes,
        created_at=doc.created_at,
    )


def _get_doc(db: Session, doc_id: int) -> ComplianceDocument:
    doc = db.get(ComplianceDocument, doc_id, options=[joinedload(ComplianceDocument.truck)])
    if doc is None:
        raise not_found("Document")
    return doc


def _vehicle_out(tc: TruckCompliance) -> VehicleCompliance:
    t = tc.truck
    return VehicleCompliance(
        truck=Ref(id=t.id, label=t.registration),
        driver_name=t.driver.full_name if t.driver else None,
        truck_status=t.status.value,
        status=tc.status,  # type: ignore[arg-type]
        eligible=tc.eligible,
        blockers=tc.blockers,
        items=[
            ItemOut(
                doc_type=i.doc_type,
                mandatory=i.mandatory,
                state=i.state,  # type: ignore[arg-type]
                document_id=i.document.id if i.document else None,
                expires_on=i.document.expires_on if i.document else None,
                days_remaining=i.days_remaining,
            )
            for i in tc.items
        ],
    )


# ---------- requirements ----------
@router.get("/compliance/requirements", response_model=list[RequirementOut])
def list_requirements(db: DB, _: Reader) -> list[RequirementOut]:
    reqs = load_requirements(db)
    out = []
    for doc_type in DocumentType:
        r = reqs.get(doc_type)
        out.append(
            RequirementOut(
                doc_type=doc_type,
                label=DOC_LABELS[doc_type],
                is_mandatory=bool(r and r.is_mandatory),
                min_capacity_tonnes=float(r.min_capacity_tonnes)
                if r and r.min_capacity_tonnes
                else None,
                reminder_days=r.reminder_days if r else DEFAULT_REMINDER_DAYS,
            )
        )
    return out


@router.put("/compliance/requirements/{doc_type}", response_model=list[RequirementOut])
def update_requirement(
    doc_type: DocumentType, body: RequirementUpdate, request: Request, db: DB, user: RuleWriter
) -> list[RequirementOut]:
    if doc_type == DocumentType.OTHER and body.is_mandatory:
        raise invalid("'Other' documents cannot be mandatory.")
    req = db.get(ComplianceRequirement, doc_type) or ComplianceRequirement(doc_type=doc_type)
    before = {
        "is_mandatory": req.is_mandatory,
        "min_capacity_tonnes": str(req.min_capacity_tonnes),
        "reminder_days": req.reminder_days,
    }
    req.is_mandatory, req.min_capacity_tonnes = body.is_mandatory, body.min_capacity_tonnes
    req.reminder_days = body.reminder_days
    db.add(req)
    record_event(
        db,
        action="compliance.requirement_updated",
        entity_type="compliance_requirement",
        entity_id=doc_type.value,
        actor=user,
        request=request,
        summary=f"Requirement for {DOC_LABELS[doc_type]} updated",
        changes={"before": before, "after": body.model_dump(mode="json")},
    )
    commit(db)
    return list_requirements(db, user)


# ---------- overview & vehicles ----------
def _all_trucks(db: Session) -> list[Truck]:
    return list(
        db.scalars(select(Truck).options(joinedload(Truck.driver)).order_by(Truck.registration))
    )


@router.get("/compliance/overview", response_model=ComplianceOverview)
def overview(db: DB, _: Reader) -> ComplianceOverview:
    today = local_today()
    trucks = _all_trucks(db)
    evaluated = evaluate_trucks(db, trucks, today)
    states = [tc.status for tc in evaluated.values()]
    items = [i for tc in evaluated.values() for i in tc.items]
    by_type = [
        TypeBreakdown(
            doc_type=t,
            **{
                s: sum(1 for i in items if i.doc_type == t and i.state == s)
                for s in ("valid", "expiring", "expired", "missing")
            },
        )
        for t in TRACKED_TYPES
    ]
    reqs = load_requirements(db)
    window = {
        t: (reqs[t].reminder_days if t in reqs else DEFAULT_REMINDER_DAYS) for t in DocumentType
    }
    upcoming_rows = db.scalars(
        select(ComplianceDocument)
        .options(joinedload(ComplianceDocument.truck))
        .where(
            ComplianceDocument.superseded_at.is_(None),
            ComplianceDocument.expires_on <= today + timedelta(days=60),
        )
        .order_by(ComplianceDocument.expires_on)
        .limit(8)
    ).all()
    total = len(trucks)
    compliant = states.count("compliant")
    return ComplianceOverview(
        total_vehicles=total,
        compliant_vehicles=compliant,
        expiring_vehicles=states.count("expiring"),
        non_compliant_vehicles=states.count("non_compliant"),
        compliant_pct=round(compliant / total * 100, 1) if total else None,
        expiring_documents=sum(1 for i in items if i.state == "expiring"),
        expired_documents=sum(1 for i in items if i.state == "expired"),
        missing_documents=sum(1 for i in items if i.state == "missing"),
        documents_on_record=db.scalar(
            select(func.count(ComplianceDocument.id)).where(
                ComplianceDocument.superseded_at.is_(None)
            )
        )
        or 0,
        documents_added_30d=db.scalar(
            select(func.count(ComplianceDocument.id)).where(
                ComplianceDocument.created_at >= utcnow() - timedelta(days=30)
            )
        )
        or 0,
        inspections_due_30d=sum(
            1
            for i in items
            if i.doc_type == DocumentType.INSPECTION
            and i.document
            and 0 <= (i.days_remaining or 0) <= 30
        ),
        by_type=by_type,
        upcoming=[
            UpcomingRenewal(
                document_id=d.id,
                truck=Ref(id=d.truck.id, label=d.truck.registration),
                doc_type=d.doc_type,
                expires_on=d.expires_on,
                days_remaining=(d.expires_on - today).days,
                state=document_state(d.expires_on, today, window[d.doc_type]),
            )  # type: ignore[arg-type]
            for d in upcoming_rows
        ],
        sample_data=is_sample_data(db),
    )


@router.get("/compliance/vehicles", response_model=Page[VehicleCompliance])
def vehicles(
    db: DB,
    _: Reader,
    q: str | None = Query(None, max_length=80),
    status_: str | None = Query(
        None, alias="status", pattern="^(compliant|expiring|non_compliant)$"
    ),
    doc_type: DocumentType | None = Query(
        None, description="Only trucks with an issue in this type"
    ),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[VehicleCompliance]:
    query = (
        select(Truck)
        .outerjoin(Truck.driver)
        .options(joinedload(Truck.driver))
        .order_by(Truck.registration)
    )
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Truck.registration.ilike(like), Driver.full_name.ilike(like)))
    trucks = list(db.scalars(query).unique())
    rows = list(evaluate_trucks(db, trucks, local_today()).values())
    if status_:
        rows = [r for r in rows if r.status == status_]
    if doc_type:
        rows = [
            r
            for r in rows
            if any(
                i.doc_type == doc_type and i.state in ("expiring", "expired", "missing")
                for i in r.items
            )
        ]
    rows.sort(
        key=lambda r: (
            {"non_compliant": 0, "expiring": 1, "compliant": 2}[r.status],
            r.truck.registration,
        )
    )
    return Page(
        items=[_vehicle_out(r) for r in rows[offset : offset + limit]],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


@router.get("/trucks/{truck_id}/eligibility", response_model=Eligibility)
def eligibility(truck_id: int, db: DB, _: Reader) -> Eligibility:
    truck = db.get(Truck, truck_id)
    if truck is None:
        raise not_found("Truck")
    tc = evaluate_trucks(db, [truck], local_today())[truck.id]
    return Eligibility(
        truck=Ref(id=truck.id, label=truck.registration), eligible=tc.eligible, reasons=tc.blockers
    )


@router.get("/trucks/{truck_id}/compliance", response_model=VehicleCompliance)
def truck_compliance(truck_id: int, db: DB, _: Reader) -> VehicleCompliance:
    truck = db.get(Truck, truck_id, options=[joinedload(Truck.driver)])
    if truck is None:
        raise not_found("Truck")
    return _vehicle_out(evaluate_trucks(db, [truck], local_today())[truck.id])


@router.get("/trucks/{truck_id}/documents", response_model=list[DocumentOut])
def truck_documents(
    truck_id: int, db: DB, _: Reader, include_history: bool = True
) -> list[DocumentOut]:
    if db.get(Truck, truck_id) is None:
        raise not_found("Truck")
    query = (
        select(ComplianceDocument)
        .options(joinedload(ComplianceDocument.truck))
        .where(ComplianceDocument.truck_id == truck_id)
    )
    if not include_history:
        query = query.where(ComplianceDocument.superseded_at.is_(None))
    reqs = load_requirements(db)
    docs = db.scalars(
        query.order_by(ComplianceDocument.doc_type, ComplianceDocument.expires_on.desc())
    ).all()
    return [
        _doc_out(d, reqs[d.doc_type].reminder_days if d.doc_type in reqs else DEFAULT_REMINDER_DAYS)
        for d in docs
    ]


# ---------- documents ----------
@router.post(
    "/compliance/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED
)
def create_document(body: DocumentIn, request: Request, db: DB, user: DocWriter) -> DocumentOut:
    truck = db.get(Truck, body.truck_id)
    if truck is None:
        raise invalid("Truck not found")
    if body.doc_type != DocumentType.OTHER and db.scalar(
        select(ComplianceDocument.id).where(
            ComplianceDocument.truck_id == truck.id,
            ComplianceDocument.doc_type == body.doc_type,
            ComplianceDocument.superseded_at.is_(None),
        )
    ):
        raise conflict(
            f"{truck.registration} already has a current {DOC_LABELS[body.doc_type].lower()}; "
            "renew it instead."
        )
    doc = ComplianceDocument(**body.model_dump(), created_by_id=user.id)
    db.add(doc)
    db.flush()
    record_event(
        db,
        action="compliance.document_created",
        entity_type="compliance_document",
        entity_id=doc.id,
        actor=user,
        request=request,
        summary=f"{DOC_LABELS[doc.doc_type]} {doc.reference_number} added for {truck.registration}",
        changes=body.model_dump(mode="json"),
    )
    commit(db, "That document conflicts with an existing current document.")
    return _doc_out(_get_doc(db, doc.id), _reminder(db, doc.doc_type))


@router.post(
    "/compliance/documents/{doc_id}/renew",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def renew_document(
    doc_id: int, body: RenewIn, request: Request, db: DB, user: DocWriter
) -> DocumentOut:
    # Lock the current document so two simultaneous renewals cannot both succeed.
    old = db.scalar(
        select(ComplianceDocument).where(ComplianceDocument.id == doc_id).with_for_update()
    )
    if old is None:
        raise not_found("Document")
    if old.superseded_at is not None:
        raise conflict("This document has already been renewed; renew the current version.")
    if body.expires_on <= old.expires_on:
        raise invalid("The renewed document must expire after the current one.")
    now = utcnow()
    old.superseded_at = now
    db.flush()  # free the "one current document" slot before inserting the renewal
    new = ComplianceDocument(
        truck_id=old.truck_id,
        doc_type=old.doc_type,
        renewed_from_id=old.id,
        created_by_id=user.id,
        **body.model_dump(),
    )
    db.add(new)
    db.flush()
    record_event(
        db,
        action="compliance.document_renewed",
        entity_type="compliance_document",
        entity_id=new.id,
        actor=user,
        request=request,
        summary=f"{DOC_LABELS[old.doc_type]} renewed until {body.expires_on.isoformat()}",
        changes={
            "previous_document_id": old.id,
            "previous_expiry": old.expires_on.isoformat(),
            **body.model_dump(mode="json"),
        },
    )
    commit(db)
    return _doc_out(_get_doc(db, new.id), _reminder(db, new.doc_type))


@router.put("/compliance/documents/{doc_id}/file", response_model=DocumentOut)
async def upload_file(
    doc_id: int, request: Request, db: DB, user: DocWriter, file: UploadFile = File(...)
) -> DocumentOut:
    doc = _get_doc(db, doc_id)
    if doc.superseded_at is not None:
        raise conflict("Historical documents cannot be changed.")
    stored = await storage.save_upload(file)
    previous_key = doc.storage_key
    doc.storage_key, doc.file_name, doc.file_content_type = (
        stored.key,
        stored.name,
        stored.content_type,
    )
    doc.file_size, doc.file_sha256, doc.file_uploaded_at = stored.size, stored.sha256, utcnow()
    record_event(
        db,
        action="compliance.file_uploaded",
        entity_type="compliance_document",
        entity_id=doc.id,
        actor=user,
        request=request,
        summary=f"File {stored.name} attached to {DOC_LABELS[doc.doc_type].lower()}",
        changes={"sha256": stored.sha256, "size": stored.size, "replaced": bool(previous_key)},
    )
    try:
        commit(db)
    except Exception:
        storage.delete(stored.key)
        raise
    storage.delete(previous_key)
    return _doc_out(doc, _reminder(db, doc.doc_type))


@router.get("/compliance/documents/{doc_id}/file")
def download_file(doc_id: int, db: DB, _: Reader) -> FileResponse:
    doc = _get_doc(db, doc_id)
    if not doc.storage_key:
        raise not_found("File")
    path = storage.path_for(doc.storage_key)
    if not path.exists():
        raise not_found("File")
    return FileResponse(
        path,
        media_type=doc.file_content_type,
        filename=doc.file_name,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )
