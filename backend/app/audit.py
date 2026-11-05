from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditEvent, User


def record_event(
    db: Session,
    *,
    action: str,
    entity_type: str,
    summary: str,
    actor: User | None = None,
    entity_id: str | int | None = None,
    changes: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditEvent:
    """Add an audit event to the current transaction (the caller commits)."""
    event = AuditEvent(
        actor_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=summary[:255],
        changes=changes,
        ip_address=request.client.host if request and request.client else None,
    )
    db.add(event)
    return event
