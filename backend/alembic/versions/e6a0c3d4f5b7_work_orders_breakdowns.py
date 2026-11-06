"""maintenance: work orders, status history and breakdowns

Revision ID: e6a0c3d4f5b7
Revises: d5f9b2c3e4a6
Create Date: 2026-11-06 18:06:40.335471

New tables and two sequences for human-readable numbers (WO-2026-00001, BD-2026-00001).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6a0c3d4f5b7"
down_revision: str | Sequence[str] | None = "d5f9b2c3e4a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE work_order_number_seq")
    op.execute("CREATE SEQUENCE breakdown_number_seq")
    op.create_table(
        "breakdowns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=20), nullable=False),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "severity",
            sa.Enum(
                "minor",
                "major",
                "critical",
                name="breakdown_severity",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.Enum(
                "mechanical",
                "electrical",
                "hydraulic",
                "pneumatic",
                "instrumentation",
                "lubrication",
                "operational",
                "other",
                name="fault_category",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("possible_cause", sa.Text(), nullable=True),
        sa.Column("actions_taken", sa.Text(), nullable=True),
        sa.Column("equipment_down", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("reported_by_id", sa.Integer(), nullable=True),
        sa.Column("restored_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "restored_at IS NULL OR restored_at >= started_at",
            name=op.f("ck_breakdowns_restored_after_start"),
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipment.id"],
            name=op.f("fk_breakdowns_equipment_id_equipment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reported_by_id"],
            ["users.id"],
            name=op.f("fk_breakdowns_reported_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["restored_by_id"],
            ["users.id"],
            name=op.f("fk_breakdowns_restored_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_breakdowns")),
        sa.UniqueConstraint("number", name=op.f("uq_breakdowns_number")),
    )
    op.create_index(
        op.f("ix_breakdowns_equipment_id"), "breakdowns", ["equipment_id"], unique=False
    )
    op.create_index(
        "uq_breakdowns_one_open_per_equipment",
        "breakdowns",
        ["equipment_id"],
        unique=True,
        postgresql_where="restored_at IS NULL",
    )
    op.create_table(
        "work_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=20), nullable=False),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.Column("breakdown_id", sa.Integer(), nullable=True),
        sa.Column(
            "maintenance_type",
            sa.Enum(
                "corrective",
                "preventive",
                "inspection",
                "improvement",
                name="work_order_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum(
                "low",
                "medium",
                "high",
                "critical",
                name="work_order_priority",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "assigned",
                "in_progress",
                "awaiting_parts",
                "completed",
                "cancelled",
                name="work_order_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("fault_description", sa.Text(), nullable=False),
        sa.Column("assigned_technician_id", sa.Integer(), nullable=True),
        sa.Column("scheduled_on", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("work_performed", sa.Text(), nullable=True),
        sa.Column("completion_notes", sa.Text(), nullable=True),
        sa.Column("cancel_reason", sa.String(length=255), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("completed_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'cancelled') = (cancel_reason IS NOT NULL)",
            name=op.f("ck_work_orders_cancelled_has_reason"),
        ),
        sa.CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name=op.f("ck_work_orders_completed_has_time"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('assigned', 'in_progress', 'awaiting_parts', 'completed') "
            "OR assigned_technician_id IS NOT NULL",
            name=op.f("ck_work_orders_active_needs_technician"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR (started_at IS NOT NULL AND completed_at >= started_at)",
            name=op.f("ck_work_orders_completed_after_start"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_technician_id"],
            ["users.id"],
            name=op.f("fk_work_orders_assigned_technician_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["breakdown_id"],
            ["breakdowns.id"],
            name=op.f("fk_work_orders_breakdown_id_breakdowns"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["completed_by_id"],
            ["users.id"],
            name=op.f("fk_work_orders_completed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_work_orders_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipment.id"],
            name=op.f("fk_work_orders_equipment_id_equipment"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_orders")),
        sa.UniqueConstraint("number", name=op.f("uq_work_orders_number")),
    )
    op.create_index(
        op.f("ix_work_orders_assigned_technician_id"),
        "work_orders",
        ["assigned_technician_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_work_orders_breakdown_id"), "work_orders", ["breakdown_id"], unique=False
    )
    op.create_index(
        op.f("ix_work_orders_equipment_id"), "work_orders", ["equipment_id"], unique=False
    )
    op.create_index("ix_work_orders_status", "work_orders", ["status"], unique=False)
    op.create_table(
        "work_order_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=True),
        sa.Column("summary", sa.String(length=255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_work_order_events_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["work_order_id"],
            ["work_orders.id"],
            name=op.f("fk_work_order_events_work_order_id_work_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_order_events")),
    )
    op.create_index(
        op.f("ix_work_order_events_work_order_id"),
        "work_order_events",
        ["work_order_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_work_order_events_work_order_id"), table_name="work_order_events")
    op.drop_table("work_order_events")
    op.drop_index("ix_work_orders_status", table_name="work_orders")
    op.drop_index(op.f("ix_work_orders_equipment_id"), table_name="work_orders")
    op.drop_index(op.f("ix_work_orders_breakdown_id"), table_name="work_orders")
    op.drop_index(op.f("ix_work_orders_assigned_technician_id"), table_name="work_orders")
    op.drop_table("work_orders")
    op.drop_index(
        "uq_breakdowns_one_open_per_equipment",
        table_name="breakdowns",
        postgresql_where="restored_at IS NULL",
    )
    op.drop_index(op.f("ix_breakdowns_equipment_id"), table_name="breakdowns")
    op.drop_table("breakdowns")
    op.execute("DROP SEQUENCE breakdown_number_seq")
    op.execute("DROP SEQUENCE work_order_number_seq")
