from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment variables / .env (prefix LOGITRACK_)."""

    model_config = SettingsConfigDict(
        env_prefix="LOGITRACK_",
        env_file=(".env", "../.env"),
        extra="ignore",
    )

    database_url: str
    test_database_url: str | None = None
    # Optional override of just the database name in database_url (used for the e2e DB).
    database_name: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")

    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=480, ge=5, le=24 * 60)
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5190"]

    timezone: str = "Africa/Nairobi"
    default_turnaround_target_minutes: int = Field(default=120, gt=0)
    bay_operating_hours_per_day: int = Field(default=12, gt=0, le=24)
    # Minutes of lateness tolerated before a load/delivery counts as delayed.
    delay_grace_minutes: int = Field(default=15, ge=0, le=240)

    # Compliance document storage (outside any web root; files are served only via the API).
    upload_dir: Path = Path(__file__).resolve().parents[1] / "var" / "uploads"
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)

    # Sign-in throttling (per account and per client IP).
    login_max_failures: int = Field(default=5, ge=1, le=100)
    login_ip_max_failures: int = Field(default=30, ge=1, le=10_000)
    login_window_minutes: int = Field(default=15, ge=1, le=1440)
    login_lockout_minutes: int = Field(default=15, ge=1, le=1440)

    # Alerts are re-evaluated on read at most this often (seconds). With the background
    # worker running, read-time refresh can be switched off (it is only a fallback).
    alert_refresh_seconds: int = Field(default=60, ge=0)
    alert_refresh_on_read: bool = True
    # Background worker cadence (python -m app.worker).
    worker_interval_seconds: int = Field(default=60, ge=5, le=3600)
    worker_max_backoff_seconds: int = Field(default=600, ge=5, le=86_400)

    @model_validator(mode="after")
    def _apply_database_name(self) -> Settings:
        if self.database_name:
            url = make_url(self.database_url).set(database=self.database_name)
            self.database_url = url.render_as_string(hide_password=False)
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
