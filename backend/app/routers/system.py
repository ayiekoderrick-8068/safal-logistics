from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import HealthOut, MetaOut
from ..services.app_settings import is_sample_data, turnaround_target_minutes

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)) -> HealthOut | JSONResponse:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503, content={"status": "degraded", "database": "unavailable"}
        )
    return HealthOut(status="ok", database="ok")


@router.get("/meta", response_model=MetaOut)
def meta(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> MetaOut:
    return MetaOut(
        version=__version__,
        timezone=get_settings().timezone,
        turnaround_target_minutes=turnaround_target_minutes(db),
        delay_grace_minutes=get_settings().delay_grace_minutes,
        sample_data=is_sample_data(db),
    )
