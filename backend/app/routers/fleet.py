from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, joinedload

from ..audit import record_event
from ..db import get_db
from ..deps import get_current_user, require_roles
from ..models import (
    ComplianceDocument,
    Driver,
    DriverAssignment,
    LoadingSchedule,
    Role,
    ScheduleStatus,
    Truck,
    TruckStatus,
    User,
)
from ..schemas_ops import (
    AssignmentOut,
    DriverIn,
    DriverOut,
    FleetSummary,
    Page,
    Ref,
    TruckDetail,
    TruckDocument,
    TruckIn,
    TruckOut,
    TruckUpdate,
)
from ..services.assignments import set_driver
from ..services.operations import (
    commit,
    compliance_by_truck,
    conflict,
    invalid,
    local_today,
    not_found,
    trucks_out,
    utcnow,
)
from ..services.turnaround import turnaround_minutes

router = APIRouter(prefix="/api", tags=["fleet"])
# Assignment history: operational staff (viewers do not see personnel history).
HistoryReader = Annotated[
    User, Depends(require_roles(Role.OPERATIONS, Role.FLEET_MANAGER, Role.COMPLIANCE))
]
FleetWriter = Annotated[User, Depends(require_roles(Role.FLEET_MANAGER))]
Reader = Annotated[User, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


# ---------- drivers ----------
@router.get("/drivers", response_model=list[DriverOut])
def list_drivers(db: DB, _: Reader, unassigned: bool = False) -> list[DriverOut]:
    query = select(Driver).options(joinedload(Driver.truck)).order_by(Driver.full_name)
    if unassigned:
        query = query.where(~Driver.truck.has(), Driver.is_active)
    return [
        DriverOut.model_validate(d).model_copy(
            update={
                "truck_id": d.truck.id if d.truck else None,
                "truck_registration": d.truck.registration if d.truck else None,
            }
        )
        for d in db.scalars(query).unique()
    ]


@router.post("/drivers", response_model=DriverOut, status_code=status.HTTP_201_CREATED)
def create_driver(body: DriverIn, request: Request, db: DB, user: FleetWriter) -> DriverOut:
    driver = Driver(**body.model_dump())
    db.add(driver)
    db.flush()
    record_event(
        db,
        action="driver.created",
        entity_type="driver",
        entity_id=driver.id,
        actor=user,
        request=request,
        summary=f"Driver {driver.full_name} registered",
    )
    commit(db)
    return DriverOut.model_validate(driver)


# ---------- trucks ----------
def _get_truck(db: Session, truck_id: int) -> Truck:
    truck = db.get(Truck, truck_id, options=[joinedload(Truck.driver)])
    if truck is None:
        raise not_found("Truck")
    return truck


def _assignable_driver(db: Session, driver_id: int, truck: Truck | None = None) -> Driver:
    driver = db.get(Driver, driver_id, options=[joinedload(Driver.truck)])
    if driver is None or not driver.is_active:
        raise invalid("Driver not found or inactive")
    if driver.truck is not None and driver.truck is not truck:
        raise conflict(f"{driver.full_name} is already assigned to {driver.truck.registration}.")
    return driver


@router.get("/trucks/summary", response_model=FleetSummary)
def fleet_summary(db: DB, _: Reader) -> FleetSummary:
    counts = dict(
        db.execute(select(Truck.status, func.count(Truck.id)).group_by(Truck.status)).all()
    )
    total = sum(counts.values())
    ids = list(db.scalars(select(Truck.id)))
    due = sum(
        1 for c in compliance_by_truck(db, ids).values() if c.status in ("expiring", "overdue")
    )
    available = counts.get(TruckStatus.AVAILABLE, 0)
    return FleetSummary(
        total=total,
        available=available,
        loading=counts.get(TruckStatus.LOADING, 0),
        in_transit=counts.get(TruckStatus.IN_TRANSIT, 0),
        maintenance=counts.get(TruckStatus.MAINTENANCE, 0),
        out_of_service=counts.get(TruckStatus.OUT_OF_SERVICE, 0),
        compliance_due=due,
        availability_pct=round(available / total * 100, 1) if total else None,
    )


@router.get("/trucks", response_model=Page[TruckOut])
def list_trucks(
    db: DB,
    _: Reader,
    q: str | None = Query(None, max_length=80, description="Registration, make or driver"),
    status_: TruckStatus | None = Query(None, alias="status"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[TruckOut]:
    query = select(Truck).outerjoin(Truck.driver)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                Truck.registration.ilike(like),
                Truck.make.ilike(like),
                Truck.model.ilike(like),
                Driver.full_name.ilike(like),
            )
        )
    if status_:
        query = query.where(Truck.status == status_)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    trucks = list(
        db.scalars(
            query.options(joinedload(Truck.driver))
            .order_by(Truck.registration)
            .limit(limit)
            .offset(offset)
        ).unique()
    )
    return Page(items=trucks_out(db, trucks), total=total, limit=limit, offset=offset)


@router.get("/trucks/{truck_id}", response_model=TruckDetail)
def get_truck(truck_id: int, db: DB, _: Reader) -> TruckDetail:
    truck = _get_truck(db, truck_id)
    base = trucks_out(db, [truck])[0]
    today = local_today()
    docs = db.scalars(
        select(ComplianceDocument)
        .where(ComplianceDocument.truck_id == truck.id)
        .ext(distinct_on(ComplianceDocument.doc_type))
        .order_by(ComplianceDocument.doc_type, ComplianceDocument.expires_on.desc())
    ).all()
    since = utcnow() - timedelta(days=30)
    completed = db.scalars(
        select(LoadingSchedule).where(
            LoadingSchedule.truck_id == truck.id,
            LoadingSchedule.status == ScheduleStatus.DEPARTED,
            LoadingSchedule.departed_at >= since,
        )
    ).all()
    tas = [
        t for s in completed if (t := turnaround_minutes(s.arrival_at, s.departed_at)) is not None
    ]
    return TruckDetail(
        **base.model_dump(),
        documents=[
            TruckDocument(
                doc_type=d.doc_type,
                reference_number=d.reference_number,
                expires_on=d.expires_on,
                days_remaining=(d.expires_on - today).days,
            )
            for d in sorted(docs, key=lambda d: d.expires_on)
        ],
        loads_completed_30d=len(completed),
        avg_turnaround_30d=round(sum(tas) / len(tas), 1) if tas else None,
    )


@router.post("/trucks", response_model=TruckOut, status_code=status.HTTP_201_CREATED)
def create_truck(body: TruckIn, request: Request, db: DB, user: FleetWriter) -> TruckOut:
    if db.scalar(select(Truck.id).where(Truck.registration == body.registration)):
        raise conflict("A truck with that registration already exists.")
    truck = Truck(
        registration=body.registration,
        make=body.make,
        model=body.model,
        capacity_tonnes=body.capacity_tonnes,
        status=TruckStatus.AVAILABLE,
    )
    db.add(truck)
    if body.driver_id is not None:
        set_driver(db, truck, _assignable_driver(db, body.driver_id), user)
    db.flush()
    record_event(
        db,
        action="truck.created",
        entity_type="truck",
        entity_id=truck.id,
        actor=user,
        request=request,
        summary=f"Truck {truck.registration} registered",
        changes=body.model_dump(mode="json"),
    )
    commit(db)
    return trucks_out(db, [truck])[0]


@router.patch("/trucks/{truck_id}", response_model=TruckOut)
def update_truck(
    truck_id: int, body: TruckUpdate, request: Request, db: DB, user: FleetWriter
) -> TruckOut:
    truck = _get_truck(db, truck_id)
    changes: dict[str, object] = {}
    fields = body.model_fields_set

    for attr in ("make", "model", "capacity_tonnes"):
        if attr in fields and getattr(body, attr) is not None:
            setattr(truck, attr, getattr(body, attr))
            changes[attr] = str(getattr(body, attr))

    if "driver_id" in fields:
        new_driver = _assignable_driver(db, body.driver_id, truck) if body.driver_id else None
        if set_driver(db, truck, new_driver, user, note=body.assignment_note):
            changes["driver"] = new_driver.full_name if new_driver else None

    if body.status is not None and body.status != truck.status:
        if truck.status in (TruckStatus.LOADING, TruckStatus.IN_TRANSIT):
            raise conflict(
                f"{truck.registration} is {truck.status.value.replace('_', ' ')}; "
                "finish the current load before changing its status."
            )
        changes["status"] = body.status
        truck.status = TruckStatus(body.status)

    if changes:
        record_event(
            db,
            action="truck.updated",
            entity_type="truck",
            entity_id=truck.id,
            actor=user,
            request=request,
            summary=f"Truck {truck.registration} updated",
            changes=changes,
        )
        commit(db, "That driver already has an assignment in that period.")
    return trucks_out(db, [truck])[0]


# ---------- driver assignment history ----------
_ASSIGNMENT_OPTIONS = (
    joinedload(DriverAssignment.driver),
    joinedload(DriverAssignment.truck),
    joinedload(DriverAssignment.assigned_by),
    joinedload(DriverAssignment.released_by),
)


def _assignment_out(a: DriverAssignment) -> AssignmentOut:
    return AssignmentOut(
        id=a.id,
        driver=Ref(id=a.driver.id, label=a.driver.full_name),
        truck=Ref(id=a.truck.id, label=a.truck.registration),
        assigned_at=a.assigned_at,
        released_at=a.released_at,
        is_current=a.released_at is None,
        assigned_by=a.assigned_by.full_name if a.assigned_by else None,
        released_by=a.released_by.full_name if a.released_by else None,
        note=a.note,
        source=a.source,
    )


def _history(db: Session, column, ident: int) -> list[AssignmentOut]:
    rows = db.scalars(
        select(DriverAssignment)
        .options(*_ASSIGNMENT_OPTIONS)
        .where(column == ident)
        .order_by(DriverAssignment.assigned_at.desc())
    ).unique()
    return [_assignment_out(a) for a in rows]


@router.get("/trucks/{truck_id}/assignments", response_model=list[AssignmentOut])
def truck_assignments(truck_id: int, db: DB, _: HistoryReader) -> list[AssignmentOut]:
    if db.get(Truck, truck_id) is None:
        raise not_found("Truck")
    return _history(db, DriverAssignment.truck_id, truck_id)


@router.get("/drivers/{driver_id}/assignments", response_model=list[AssignmentOut])
def driver_assignments(driver_id: int, db: DB, _: HistoryReader) -> list[AssignmentOut]:
    if db.get(Driver, driver_id) is None:
        raise not_found("Driver")
    return _history(db, DriverAssignment.driver_id, driver_id)
