"""Rebuild the disposable end-to-end test database.

Only runs against a database whose name ends in `_e2e` (set LOGITRACK_DATABASE_NAME), so
it can never wipe development or production data. Creates the database if needed, applies
the Alembic migrations, creates the admin account from E2E_USERNAME / E2E_PASSWORD and
loads the labelled sample dataset.
"""

import os
import re
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command

from .config import get_settings
from .db import SessionLocal
from .models import Role, User, UserStatus
from .sample_data import load_sample_data
from .security import hash_password

BACKEND_DIR = Path(__file__).resolve().parents[1]


def reset_e2e_database() -> str:
    url = make_url(get_settings().database_url)
    name = url.database or ""
    if not re.fullmatch(r"[a-z0-9_]+_e2e", name):
        raise RuntimeError(f"Refusing to reset '{name}': the database name must end with _e2e.")
    username, password = os.environ.get("E2E_USERNAME"), os.environ.get("E2E_PASSWORD")
    if not username or not password:
        raise RuntimeError("Set E2E_USERNAME and E2E_PASSWORD.")

    server = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with server.connect() as conn:
        if not conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}):
            conn.execute(text(f'CREATE DATABASE "{name}"'))  # noqa: S608 - name validated above
    server.dispose()

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = url.render_as_string(hide_password=False)
    cfg.attributes["configure_logging"] = False
    command.upgrade(cfg, "head")

    with SessionLocal() as db:
        db.add(
            User(
                username=username,
                email="e2e-admin@example.com",
                full_name="E2E Admin",
                password_hash=hash_password(password),
                role=Role.ADMIN,
                status=UserStatus.ACTIVE,
            )
        )
        db.commit()
        load_sample_data(db)
    return name
