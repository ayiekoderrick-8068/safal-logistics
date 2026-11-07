"""Maintenance workspace API. Every route requires a maintenance-bound session
(router-level guard in `main.py`); individual actions additionally check the role matrix."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import maintenance_user
from ..maintenance_permissions import permissions_for
from ..models import MaintenanceRole, User
from ..services.app_settings import is_maintenance_sample

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])
MaintUser = Annotated[User, Depends(maintenance_user)]


class AccessOut(BaseModel):
    maintenance_role: MaintenanceRole
    permissions: list[str]
    # True while the labelled demonstration dataset is loaded (the UI shows a banner).
    sample_data: bool


@router.get("/access", response_model=AccessOut)
def access(user: MaintUser, db: Annotated[Session, Depends(get_db)]) -> AccessOut:
    """The caller's effective maintenance role and what it allows (drives the UI)."""
    # The workspace guard guarantees a role; fall back to the least privilege regardless.
    role = user.effective_maintenance_role or MaintenanceRole.VIEWER
    return AccessOut(
        maintenance_role=role,
        permissions=permissions_for(role),
        sample_data=is_maintenance_sample(db),
    )
