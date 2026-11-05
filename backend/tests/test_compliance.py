"""Compliance records, renewal history, file storage and dispatch enforcement."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, ComplianceDocument, Role
from app.services.compliance import document_state
from tests.conftest import TEST_PASSWORD
from tests.test_workflow import add_valid_documents, event, iso

TODAY = datetime.now(UTC).date()
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture
def truck(auth_client: TestClient) -> int:
    r = auth_client.post("/api/trucks", json={"registration": "KDA 100A", "capacity_tonnes": 12})
    return r.json()["id"]


def doc(c: TestClient, truck_id: int, doc_type: str, expires_in: int, **kw):
    return c.post(
        "/api/compliance/documents",
        json={
            "truck_id": truck_id,
            "doc_type": doc_type,
            "reference_number": kw.get("ref", f"{doc_type}-1"),
            "issuing_authority": kw.get("authority", "NTSA"),
            "issued_on": str(TODAY - timedelta(days=200)),
            "expires_on": str(TODAY + timedelta(days=expires_in)),
        },
    )


# ---------- pure rules ----------
@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (-1, "expired"),
        (0, "expiring"),
        (30, "expiring"),
        (31, "valid"),
    ],
)
def test_document_state_boundaries(offset: int, expected: str) -> None:
    today = date(2026, 11, 5)
    assert document_state(today + timedelta(days=offset), today, 30) == expected


# ---------- records ----------
def test_create_document_and_vehicle_view(auth_client, truck) -> None:
    r = doc(auth_client, truck, "insurance", 100, ref=" INS-  77 ")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["reference_number"] == "INS- 77" and body["state"] == "valid" and body["is_current"]
    assert body["days_remaining"] == 100 and body["issuing_authority"] == "NTSA"

    v = auth_client.get(f"/api/trucks/{truck}/compliance").json()
    states = {i["doc_type"]: i["state"] for i in v["items"]}
    assert states["insurance"] == "valid"
    assert states["licence"] == "missing" and states["inspection"] == "missing"
    assert states["roadworthy"] == "not_required"  # optional by default
    assert v["status"] == "non_compliant" and v["eligible"] is False
    assert "Vehicle licence is missing." in v["blockers"]


def test_duplicate_current_document_rejected(auth_client, truck) -> None:
    assert doc(auth_client, truck, "insurance", 100).status_code == 201
    dup = doc(auth_client, truck, "insurance", 200)
    assert dup.status_code == 409 and "renew it instead" in dup.json()["detail"]
    # 'other' documents may repeat
    assert doc(auth_client, truck, "other", 50, ref="A").status_code == 201
    assert doc(auth_client, truck, "other", 60, ref="B").status_code == 201


def test_invalid_dates_rejected(auth_client, truck) -> None:
    r = auth_client.post(
        "/api/compliance/documents",
        json={
            "truck_id": truck,
            "doc_type": "insurance",
            "reference_number": "X",
            "issued_on": str(TODAY),
            "expires_on": str(TODAY),
        },
    )
    assert r.status_code == 422


def test_renewal_preserves_history(auth_client, truck, db: Session) -> None:
    first = doc(auth_client, truck, "inspection", -3).json()
    assert first["state"] == "expired"
    renewal = {
        "reference_number": "INSP-2",
        "issuing_authority": "NTSA",
        "issued_on": str(TODAY),
        "expires_on": str(TODAY + timedelta(days=365)),
    }
    too_short = auth_client.post(
        f"/api/compliance/documents/{first['id']}/renew",
        json={
            **renewal,
            "expires_on": str(TODAY - timedelta(days=5)),
            "issued_on": str(TODAY - timedelta(days=60)),
        },
    )
    assert too_short.status_code == 422

    r = auth_client.post(f"/api/compliance/documents/{first['id']}/renew", json=renewal)
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["renewed_from_id"] == first["id"] and new["is_current"] and new["state"] == "valid"

    again = auth_client.post(f"/api/compliance/documents/{first['id']}/renew", json=renewal)
    assert again.status_code == 409  # superseded documents cannot be renewed twice

    history = auth_client.get(f"/api/trucks/{truck}/documents").json()
    assert [(d["reference_number"], d["is_current"]) for d in history] == [
        ("INSP-2", True),
        ("inspection-1", False),
    ]
    current = auth_client.get(f"/api/trucks/{truck}/documents?include_history=false").json()
    assert [d["id"] for d in current] == [new["id"]]
    assert db.scalar(
        select(AuditEvent.action).where(AuditEvent.action == "compliance.document_renewed")
    )


# ---------- files ----------
def test_upload_and_download_supporting_file(auth_client, truck, db: Session) -> None:
    d = doc(auth_client, truck, "insurance", 100).json()
    up = auth_client.put(
        f"/api/compliance/documents/{d['id']}/file",
        files={"file": ("../../etc/policy.pdf", PDF, "text/plain")},
    )
    assert up.status_code == 200, up.text
    info = up.json()["file"]
    assert info["name"] == "policy.pdf"  # path stripped
    assert info["content_type"] == "application/pdf"  # sniffed, client type ignored
    assert info["size"] == len(PDF)

    dl = auth_client.get(f"/api/compliance/documents/{d['id']}/file")
    assert dl.status_code == 200 and dl.content == PDF
    assert dl.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in dl.headers["content-disposition"]
    stored = db.scalar(select(ComplianceDocument).where(ComplianceDocument.id == d["id"]))
    assert stored.file_sha256 and len(stored.storage_key) == 32


def test_rejects_disguised_and_oversized_files(auth_client, truck, monkeypatch) -> None:
    d = doc(auth_client, truck, "insurance", 100).json()
    url = f"/api/compliance/documents/{d['id']}/file"
    fake = auth_client.put(
        url, files={"file": ("scan.pdf", b"<script>alert(1)</script>", "application/pdf")}
    )
    assert fake.status_code == 415

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_bytes", 100)
    big = auth_client.put(url, files={"file": ("big.pdf", PDF + b"0" * 200, "application/pdf")})
    assert big.status_code == 413
    assert auth_client.get(url).status_code == 404  # nothing stored


# ---------- requirements & enforcement ----------
def _loaded_schedule(c: TestClient, truck_id: int) -> tuple[int, int]:
    now = datetime.now(UTC).replace(microsecond=0)
    bay = c.post("/api/bays", json={"code": "BAY-C", "name": "Bay C"}).json()["id"]
    route = c.post(
        "/api/routes",
        json={
            "origin": "Nairobi",
            "destination": "Thika",
            "distance_km": 45,
            "expected_duration_minutes": 75,
        },
    ).json()["id"]
    sid = c.post(
        "/api/schedules",
        json={
            "truck_id": truck_id,
            "bay_id": bay,
            "scheduled_start": iso(now - timedelta(minutes=30)),
            "scheduled_end": iso(now + timedelta(minutes=60)),
        },
    ).json()["id"]
    for name, mins in (("arrived", 25), ("loading_started", 20), ("loading_finished", 5)):
        assert event(c, sid, name, now - timedelta(minutes=mins)).status_code == 200
    return sid, route


def test_dispatch_blocked_when_mandatory_documents_missing_or_expired(
    auth_client, truck, db
) -> None:
    c = auth_client
    add_valid_documents(c, truck, types=("insurance", "licence"))
    expired = doc(c, truck, "inspection", -2).json()
    sid, route = _loaded_schedule(c, truck)

    blocked = c.post("/api/dispatches", json={"schedule_id": sid, "route_id": route})
    assert blocked.status_code == 409
    assert "Dispatch blocked for KDA 100A" in blocked.json()["detail"]
    assert "Inspection certificate expired on" in blocked.json()["detail"]
    assert c.get(f"/api/trucks/{truck}/eligibility").json()["eligible"] is False
    assert db.scalar(select(AuditEvent.action).where(AuditEvent.action == "dispatch.blocked"))

    # An authorised renewal restores eligibility.
    renewed = c.post(
        f"/api/compliance/documents/{expired['id']}/renew",
        json={
            "reference_number": "INSP-NEW",
            "issued_on": str(TODAY),
            "expires_on": str(TODAY + timedelta(days=365)),
        },
    )
    assert renewed.status_code == 201
    assert c.get(f"/api/trucks/{truck}/eligibility").json() == {
        "truck": {"id": truck, "label": "KDA 100A"},
        "eligible": True,
        "reasons": [],
    }
    ok = c.post("/api/dispatches", json={"schedule_id": sid, "route_id": route})
    assert ok.status_code == 201, ok.text


def test_requirements_are_configurable(auth_client, truck) -> None:
    c = auth_client
    add_valid_documents(c, truck)
    assert c.get(f"/api/trucks/{truck}/eligibility").json()["eligible"] is True

    # Speed governor mandatory only for trucks of 15 t or more: this 12 t truck is unaffected.
    r = c.put(
        "/api/compliance/requirements/speed_governor",
        json={"is_mandatory": True, "min_capacity_tonnes": 15, "reminder_days": 14},
    )
    assert r.status_code == 200
    assert c.get(f"/api/trucks/{truck}/eligibility").json()["eligible"] is True
    c.put(
        "/api/compliance/requirements/speed_governor",
        json={"is_mandatory": True, "reminder_days": 14},
    )
    reasons = c.get(f"/api/trucks/{truck}/eligibility").json()["reasons"]
    assert reasons == ["Speed governor certificate is missing."]

    # Making inspection optional means an expired inspection no longer blocks dispatch.
    assert (
        c.put("/api/compliance/requirements/other", json={"is_mandatory": True}).status_code == 422
    )


def test_maintenance_blocks_dispatch_at_the_moment_of_dispatch(
    auth_client, truck, db: Session
) -> None:
    from app.models import Truck, TruckStatus

    c = auth_client
    add_valid_documents(c, truck)
    sid, route = _loaded_schedule(c, truck)
    # Simulate the truck being withdrawn after loading (e.g. by a workshop system).
    t = db.get(Truck, truck)
    t.status = TruckStatus.MAINTENANCE
    db.commit()
    r = c.post("/api/dispatches", json={"schedule_id": sid, "route_id": route})
    assert r.status_code == 409 and "under maintenance" in r.json()["detail"]


def test_compliance_overview_counts(auth_client, truck) -> None:
    c = auth_client
    doc(c, truck, "insurance", 10)  # expiring
    doc(c, truck, "licence", -1)  # expired
    o = c.get("/api/compliance/overview").json()
    assert o["total_vehicles"] == 1 and o["non_compliant_vehicles"] == 1
    assert o["expiring_documents"] == 1 and o["expired_documents"] == 1
    assert o["missing_documents"] == 1  # inspection
    ins = next(t for t in o["by_type"] if t["doc_type"] == "insurance")
    assert ins["expiring"] == 1
    assert [u["doc_type"] for u in o["upcoming"]] == ["licence", "insurance"]
    page = c.get("/api/compliance/vehicles?status=non_compliant&doc_type=inspection").json()
    assert page["total"] == 1 and page["items"][0]["truck"]["label"] == "KDA 100A"


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.COMPLIANCE, 201),
        (Role.FLEET_MANAGER, 201),
        (Role.OPERATIONS, 403),
        (Role.VIEWER, 403),
    ],
)
def test_document_write_permissions(client, make_user, db, role, expected) -> None:
    from decimal import Decimal

    from app.models import Truck

    t = Truck(registration="KZZ 1Z", capacity_tonnes=Decimal(5))
    db.add(t)
    db.commit()
    make_user("u", role=role)
    client.post("/api/auth/login", json={"username": "u", "password": TEST_PASSWORD})
    r = client.post(
        "/api/compliance/documents",
        json={
            "truck_id": t.id,
            "doc_type": "insurance",
            "reference_number": "R",
            "issued_on": str(TODAY),
            "expires_on": str(TODAY + timedelta(days=10)),
        },
    )
    assert r.status_code == expected
    rule = client.put("/api/compliance/requirements/roadworthy", json={"is_mandatory": True})
    assert rule.status_code == (200 if role == Role.COMPLIANCE else 403)
    assert client.get("/api/compliance/overview").status_code == 200  # everyone can read
