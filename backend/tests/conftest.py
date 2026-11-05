"""Test configuration.

Tests run against a dedicated PostgreSQL database (default: <dev db name>_test) that is
rebuilt with the real Alembic migrations once per session and truncated between tests.
"""

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import Settings, get_settings

_base = Settings()  # type: ignore[call-arg]
TEST_DB_URL = _base.test_database_url or make_url(_base.database_url).set(
    database=f"{make_url(_base.database_url).database}_test"
).render_as_string(hide_password=False)
os.environ["LOGITRACK_DATABASE_URL"] = TEST_DB_URL
get_settings.cache_clear()

from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from app.db import SessionLocal, get_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Role, User, UserStatus  # noqa: E402
from app.security import hash_password  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_PASSWORD = "Test-pass-123!"


@pytest.fixture(scope="session", autouse=True)
def _migrated_database() -> Iterator[None]:
    assert make_url(TEST_DB_URL).database.endswith("_test"), "refusing to run on non-test DB"
    engine = create_engine(TEST_DB_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = TEST_DB_URL
    cfg.attributes["configure_logging"] = False
    command.upgrade(cfg, "head")
    yield
    get_engine().dispose()


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    yield
    with get_engine().begin() as conn:
        tables = (
            conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename <> 'alembic_version'"
                )
            )
            .scalars()
            .all()
        )
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    def _make(
        username: str = "derrick",
        role: Role = Role.ADMIN,
        status: UserStatus = UserStatus.ACTIVE,
        password: str = TEST_PASSWORD,
    ) -> User:
        user = User(
            username=username,
            email=f"{username}@example.com",
            full_name=username.title(),
            password_hash=hash_password(password),
            role=role,
            status=status,
        )
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture
def auth_client(client: TestClient, make_user: Callable[..., User]) -> TestClient:
    make_user()
    resp = client.post("/api/auth/login", json={"username": "derrick", "password": TEST_PASSWORD})
    assert resp.status_code == 200, resp.text
    return client
