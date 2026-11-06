"""users: session revocation version and password-change tracking

Revision ID: a3f1c9e27b45
Revises: 0b526c17b8a2
Create Date: 2026-11-06 10:00:00.000000

Additive only: existing users keep their passwords and sessions (token_version 0 matches
tokens issued before this migration).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3f1c9e27b45"
down_revision: str | Sequence[str] | None = "0b526c17b8a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("token_version", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_users_token_version_non_negative"), "users", "token_version >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_token_version_non_negative"), "users", type_="check")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "token_version")
