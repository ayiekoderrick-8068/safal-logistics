"""users: maintenance workspace role

Revision ID: b7d2e4f1a9c0
Revises: a3f1c9e27b45
Create Date: 2026-11-06 16:00:00.000000

Additive only: a nullable column, so every existing user keeps exactly the access they had
(logistics only) until an administrator grants a maintenance role.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7d2e4f1a9c0"
down_revision: str | Sequence[str] | None = "a3f1c9e27b45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ("manager", "planner", "technician", "storekeeper", "viewer")


def upgrade() -> None:
    op.add_column("users", sa.Column("maintenance_role", sa.String(32), nullable=True))
    op.create_check_constraint(
        op.f("ck_users_maintenance_role"),
        "users",
        "maintenance_role IN (" + ", ".join(f"'{r}'" for r in ROLES) + ")",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_maintenance_role"), "users", type_="check")
    op.drop_column("users", "maintenance_role")
