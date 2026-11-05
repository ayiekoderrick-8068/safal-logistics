from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment variables / .env (prefix LOGITRACK_)."""

    model_config = SettingsConfigDict(
        env_prefix="LOGITRACK_",
        env_file=(".env", "../.env"),
        extra="ignore",
    )

    database_url: str
    test_database_url: str | None = None

    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=480, ge=5, le=24 * 60)
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5190"]

    timezone: str = "Africa/Nairobi"
    default_turnaround_target_minutes: int = Field(default=120, gt=0)
    bay_operating_hours_per_day: int = Field(default=12, gt=0, le=24)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
