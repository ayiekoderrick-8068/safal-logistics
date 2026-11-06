"""maintenance: equipment register and equipment history

Revision ID: c4e8a1d2f3b5
Revises: b7d2e4f1a9c0
Create Date: 2026-11-06 18:00:00.000000

New tables only; no existing table is altered.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c4e8a1d2f3b5"
down_revision: str | Sequence[str] | None = "b7d2e4f1a9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORIES = (
    "conveyor",
    "motor",
    "compressor",
    "hydraulic_system",
    "pump",
    "production_machine",
    "generator",
    "electrical",
    "other",
)
STATUSES = ("operational", "under_maintenance", "out_of_service")


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.create_table(
        "equipment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("manufacturer", sa.String(80), nullable=True),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("serial_number", sa.String(80), nullable=True),
        sa.Column("facility", sa.String(80), nullable=False),
        sa.Column("department", sa.String(80), nullable=True),
        sa.Column("location", sa.String(120), nullable=True),
        sa.Column("installed_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("assigned_technician_id", sa.Integer(), nullable=True),
        sa.Column("last_service_on", sa.Date(), nullable=True),
        sa.Column("next_service_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"category IN {_in(CATEGORIES)}", name=op.f("ck_equipment_equipment_category")
        ),
        sa.CheckConstraint(
            f"status IN {_in(STATUSES)}", name=op.f("ck_equipment_equipment_status")
        ),
        sa.CheckConstraint(
            "next_service_on IS NULL OR last_service_on IS NULL "
            "OR next_service_on >= last_service_on",
            name=op.f("ck_equipment_next_service_after_last"),
        ),
        sa.CheckConstraint(
            "last_service_on IS NULL OR installed_on IS NULL OR last_service_on >= installed_on",
            name=op.f("ck_equipment_service_after_install"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_technician_id"],
            ["users.id"],
            ondelete="SET NULL",
            name=op.f("fk_equipment_assigned_technician_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["archived_by_id"],
            ["users.id"],
            ondelete="SET NULL",
            name=op.f("fk_equipment_archived_by_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equipment")),
        sa.UniqueConstraint("code", name=op.f("uq_equipment_code")),
        sa.UniqueConstraint("serial_number", name=op.f("uq_equipment_serial_number")),
    )
    op.create_index(
        op.f("ix_equipment_assigned_technician_id"), "equipment", ["assigned_technician_id"]
    )
    op.create_index(
        "ix_equipment_active_status",
        "equipment",
        ["status"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    op.create_table(
        "equipment_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("summary", sa.String(255), nullable=False),
        sa.Column("changes", postgresql.JSONB(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipment.id"],
            ondelete="CASCADE",
            name=op.f("fk_equipment_events_equipment_id_equipment"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            ondelete="SET NULL",
            name=op.f("fk_equipment_events_actor_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equipment_events")),
    )
    op.create_index(op.f("ix_equipment_events_equipment_id"), "equipment_events", ["equipment_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_equipment_events_equipment_id"), table_name="equipment_events")
    op.drop_table("equipment_events")
    op.drop_index("ix_equipment_active_status", table_name="equipment")
    op.drop_index(op.f("ix_equipment_assigned_technician_id"), table_name="equipment")
    op.drop_table("equipment")
