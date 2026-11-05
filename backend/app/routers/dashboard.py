from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import DashboardOverview
from ..services.dashboard import MAX_RANGE_DAYS, build_overview

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=DashboardOverview)
def overview(
    start: date | None = Query(None, description="First day (inclusive), local time"),
    end: date | None = Query(None, description="Last day (inclusive), local time"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DashboardOverview:
    today = datetime.now(get_settings().tz).date()
    end = end or today
    start = start or end - timedelta(days=6)
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "start must be on or before end")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Date range cannot exceed {MAX_RANGE_DAYS} days"
        )
    return build_overview(db, start, end)
