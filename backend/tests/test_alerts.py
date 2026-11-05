"""Operational alerts: generation, deduplication, escalation, resolution and history."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    AlertSeverity,
    AlertStatus,
    AlertType,
    AuditEvent,
    ComplianceDocument,
    DelayCause,
    DelayIncident,
    Dispatch,
    DispatchStatus,
    DocumentType,
    LoadingBay,
    LoadingSchedule,
    Role,
    Route,
    ScheduleStatus,
    Truck,
    TruckStatus,
)
from app.services.alerts import refresh_alerts
from tests.conftest import TEST_PASSWORD

NOW = datetime.now(UTC).replace(microsecond=0)
TODAY = NOW.date()


def add_docs(
    db: Session, truck: Truck, days: dict[DocumentType, int]
) -> dict[DocumentType, ComplianceDocument]:
    docs = {
        t: ComplianceDocument(
            truck=truck,
            doc_type=t,
            reference_number=f"{t.value}-1",
            issued_on=TODAY - timedelta(days=400),
            expires_on=TODAY + timedelta(days=d),
        )
        for t, d in days.items()
    }
    db.add_all(docs.values())
    db.commit()
    return docs


@pytest.fixture
def truck(db: Session) -> Truck:
    t = Truck(registration="KDA 200B", capacity_tonnes=Decimal(16))
    db.add(t)
    db.commit()
    return t


def active(db: Session) -> list[Alert]:
    return list(
        db.scalars(
            select(Alert).where(Alert.status != AlertStatus.RESOLVED).order_by(Alert.dedup_key)
        )
    )


def test_missing_documents_raise_one_alert_each_and_never_duplicate(db, truck) -> None:
    refresh_alerts(db, NOW, force=True)
    refresh_alerts(db, NOW + timedelta(minutes=5), force=True)
    alerts = active(db)
    assert [a.dedup_key for a in alerts] == [
        f"document_missing:{truck.id}:inspection",
        f"document_missing:{truck.id}:insurance",
        f"document_missing:{truck.id}:licence",
    ]
    assert all(a.severity == AlertSeverity.CRITICAL for a in alerts)
    assert alerts[0].first_seen_at == NOW and alerts[0].last_seen_at == NOW + timedelta(minutes=5)

    # The database itself forbids a second unresolved alert with the same key.
    dup = Alert(
        dedup_key=alerts[0].dedup_key,
        alert_type=AlertType.DOCUMENT_MISSING,
        severity=AlertSeverity.CRITICAL,
        title="x",
        message="x",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.commit()


def test_alerts_auto_resolve_and_history_is_kept(db, truck) -> None:
    refresh_alerts(db, NOW, force=True)
    add_docs(
        db,
        truck,
        {DocumentType.INSURANCE: 200, DocumentType.LICENCE: 200, DocumentType.INSPECTION: 200},
    )
    stats = refresh_alerts(db, NOW + timedelta(minutes=1), force=True)
    assert stats["resolved"] == 3 and active(db) == []
    history = db.scalars(select(Alert).where(Alert.status == AlertStatus.RESOLVED)).all()
    assert len(history) == 3 and all(a.auto_resolved and a.resolved_at for a in history)


def test_expiry_severity_and_inspection_type(db, truck) -> None:
    add_docs(
        db,
        truck,
        {DocumentType.INSURANCE: 20, DocumentType.LICENCE: 5, DocumentType.INSPECTION: 12},
    )
    refresh_alerts(db, NOW, force=True)
    by_type = {a.alert_type: a for a in active(db)}
    assert set(by_type) == {AlertType.DOCUMENT_EXPIRING, AlertType.INSPECTION_DUE}
    expiring = {
        a.document_id: a.severity for a in active(db) if a.alert_type == AlertType.DOCUMENT_EXPIRING
    }
    assert sorted(expiring.values()) == [AlertSeverity.INFO, AlertSeverity.WARNING]
    assert by_type[AlertType.INSPECTION_DUE].severity == AlertSeverity.INFO


def test_expired_mandatory_document_is_critical(db, truck) -> None:
    docs = add_docs(
        db,
        truck,
        {
            DocumentType.INSURANCE: -3,
            DocumentType.LICENCE: 200,
            DocumentType.INSPECTION: 200,
            DocumentType.ROADWORTHY: -1,
        },
    )
    refresh_alerts(db, NOW, force=True)
    sev = {a.document_id: a.severity for a in active(db)}
    assert sev[docs[DocumentType.INSURANCE].id] == AlertSeverity.CRITICAL
    assert sev[docs[DocumentType.ROADWORTHY].id] == AlertSeverity.WARNING  # optional document
    assert (
        "dispatch is blocked"
        in next(a for a in active(db) if a.document_id == docs[DocumentType.INSURANCE].id).message
    )


def test_escalation_reopens_acknowledged_alert(auth_client, db, truck) -> None:
    docs = add_docs(
        db,
        truck,
        {DocumentType.INSURANCE: 20, DocumentType.LICENCE: 200, DocumentType.INSPECTION: 200},
    )
    alert = auth_client.get("/api/alerts").json()["items"][0]
    assert alert["severity"] == "info" and alert["link"] == f"/compliance?truck={truck.id}"
    acked = auth_client.post(f"/api/alerts/{alert['id']}/acknowledge").json()
    assert acked["status"] == "acknowledged" and acked["acknowledged_by"] == "Derrick"
    assert auth_client.post(f"/api/alerts/{alert['id']}/acknowledge").status_code == 409

    docs[DocumentType.INSURANCE].expires_on = TODAY + timedelta(days=3)
    db.commit()
    again = auth_client.get("/api/alerts").json()["items"][0]
    assert (
        again["id"] == alert["id"] and again["severity"] == "warning" and again["status"] == "open"
    )


def test_manual_resolution_requires_note_suppresses_and_is_audited(auth_client, db, truck) -> None:
    add_docs(
        db,
        truck,
        {DocumentType.INSURANCE: 200, DocumentType.LICENCE: 200, DocumentType.INSPECTION: 200},
    )
    truck.status = TruckStatus.MAINTENANCE
    db.commit()
    alert = auth_client.get("/api/alerts").json()["items"][0]
    assert (
        alert["alert_type"] == "maintenance_required"
        and alert["link"] == f"/fleet?truck={truck.id}"
    )
    assert (
        auth_client.post(f"/api/alerts/{alert['id']}/resolve", json={"note": ""}).status_code == 422
    )
    done = auth_client.post(f"/api/alerts/{alert['id']}/resolve", json={"note": "Workshop booked"})
    assert done.json()["status"] == "resolved" and done.json()["auto_resolved"] is False
    # Condition persists, but an operator closed it: not re-raised within the suppression window.
    assert auth_client.get("/api/alerts").json()["total"] == 0
    assert (
        auth_client.get("/api/alerts?status=resolved").json()["items"][0]["resolution_note"]
        == "Workshop booked"
    )
    actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.entity_type == "alert")))
    assert actions == {"alert.resolved"}


def _operations(db: Session, truck: Truck) -> dict[str, int]:
    add_docs(
        db,
        truck,
        {DocumentType.INSURANCE: 200, DocumentType.LICENCE: 200, DocumentType.INSPECTION: 200},
    )
    bay = LoadingBay(code="B1", name="Bay 01")
    other = Truck(registration="KDB 300C", capacity_tonnes=Decimal(10))
    add_docs(
        db,
        other,
        {DocumentType.INSURANCE: 200, DocumentType.LICENCE: 200, DocumentType.INSPECTION: 200},
    )
    route = Route(
        origin="Nairobi", destination="Thika", distance_km=Decimal(45), expected_duration_minutes=60
    )
    # On site 200 min (> 1.5 x 120 target) and booking ended 40 min ago.
    sched = LoadingSchedule(
        truck=truck,
        bay=bay,
        scheduled_start=NOW - timedelta(minutes=220),
        scheduled_end=NOW - timedelta(minutes=40),
        arrival_at=NOW - timedelta(minutes=200),
        loading_started_at=NOW - timedelta(minutes=180),
        status=ScheduleStatus.LOADING,
    )
    disp = Dispatch(
        load_ref="LD-X1",
        truck=other,
        route=route,
        dispatched_at=NOW - timedelta(minutes=100),
        expected_arrival_at=NOW - timedelta(minutes=40),
        status=DispatchStatus.IN_TRANSIT,
    )
    inc = DelayIncident(
        dispatch=disp,
        cause=DelayCause.TRAFFIC,
        delay_minutes=20,
        occurred_at=NOW - timedelta(hours=5),
    )
    db.add_all([sched, disp, inc])
    db.commit()
    return {"schedule": sched.id, "dispatch": disp.id, "incident": inc.id}


def test_operational_alerts(auth_client, db, truck) -> None:
    ids = _operations(db, truck)
    items = auth_client.get("/api/alerts?limit=50").json()["items"]
    by_type = {a["alert_type"]: a for a in items}
    assert by_type["loading_over_target"]["severity"] == "critical"
    assert by_type["missed_dispatch"]["link"] == f"/dispatch?schedule={ids['schedule']}"
    assert (
        by_type["delivery_overdue"]["severity"] == "warning"
        and "40 min past its ETA" in by_type["delivery_overdue"]["message"]
    )
    assert (
        by_type["incident_unresolved"]["severity"] == "warning"
        and "unassigned" in by_type["incident_unresolved"]["message"]
    )
    # Critical alerts are listed first.
    assert items[0]["severity"] == "critical"

    s = auth_client.get("/api/alerts/summary").json()
    assert s["critical"] == 1 and s["warning"] == 3 and s["total_active"] == 4
    only = auth_client.get("/api/alerts?types=delivery_overdue,incident_unresolved").json()
    assert only["total"] == 2
    assert auth_client.get(f"/api/alerts?truck_id={truck.id}").json()["total"] == 2
    assert auth_client.get("/api/alerts?types=bogus").status_code == 422

    # Resolving the incident clears its alert on the next refresh.
    db.get(DelayIncident, ids["incident"]).status = "resolved"
    db.get(DelayIncident, ids["incident"]).resolved_at = NOW
    db.commit()
    assert "incident_unresolved" not in {
        a["alert_type"] for a in auth_client.get("/api/alerts").json()["items"]
    }


def test_refresh_is_throttled(db, truck, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "alert_refresh_seconds", 300)
    refresh_alerts(db, NOW)
    assert refresh_alerts(db, NOW + timedelta(seconds=30)) == {"skipped": 1}
    assert refresh_alerts(db, NOW + timedelta(seconds=301))["updated"] == 3
    assert db.scalar(select(func.count(Alert.id))) == 3


@pytest.mark.parametrize(
    ("role", "ack"), [(Role.VIEWER, 403), (Role.COMPLIANCE, 200), (Role.OPERATIONS, 200)]
)
def test_alert_permissions(client, make_user, db, truck, role, ack) -> None:
    refresh_alerts(db, NOW, force=True)
    make_user("u", role=role)
    client.post("/api/auth/login", json={"username": "u", "password": TEST_PASSWORD})
    items = client.get("/api/alerts").json()["items"]
    assert len(items) == 3  # everyone can read
    assert client.post(f"/api/alerts/{items[0]['id']}/acknowledge").status_code == ack
    assert client.post("/api/alerts/refresh").status_code == (403 if role == Role.VIEWER else 200)
