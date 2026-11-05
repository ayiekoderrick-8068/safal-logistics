from typing import Any

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AppSetting

SAMPLE_DATA_KEY = "sample_data"
TURNAROUND_TARGET_KEY = "turnaround_target_minutes"


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(AppSetting, key)
    return row.value if row is not None else default


def set_setting(db: Session, key: str, value: Any) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def delete_setting(db: Session, key: str) -> None:
    row = db.get(AppSetting, key)
    if row is not None:
        db.delete(row)


def is_sample_data(db: Session) -> bool:
    value = get_setting(db, SAMPLE_DATA_KEY)
    return bool(isinstance(value, dict) and value.get("loaded"))


def turnaround_target_minutes(db: Session) -> int:
    value = get_setting(db, TURNAROUND_TARGET_KEY)
    if isinstance(value, int) and value > 0:
        return value
    return get_settings().default_turnaround_target_minutes
