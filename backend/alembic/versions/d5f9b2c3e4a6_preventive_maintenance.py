"""maintenance: preventive maintenance plans and tasks

Revision ID: d5f9b2c3e4a6
Revises: c4e8a1d2f3b5
Create Date: 2026-11-06 16:18:30.122913

New tables, plus one relaxation on `equipment`: the "next service >= last service" CHECK is
dropped because an asset with several plans can legitimately have one task overdue while
another was serviced today (hand-entered dates are still validated by the API).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d5f9b2c3e4a6"
down_revision: str | Sequence[str] | None = "c4e8a1d2f3b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEXT_AFTER_LAST = "ck_equipment_next_service_after_last"


def _enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def upgrade() -> None:
    op.drop_constraint(op.f(NEXT_AFTER_LAST), "equipment", type_="check")

    op.create_table(
        "maintenance_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("interval_value", sa.Integer(), nullable=False),
        sa.Column(
            "interval_unit", _enum("days", "weeks", "months", name="interval_unit"), nullable=False
        ),
        sa.Column(
            "schedule_basis",
            _enum("due_date", "completion_date", name="schedule_basis"),
            nullable=False,
        ),
        sa.Column("start_on", sa.Date(), nullable=False),
        sa.Column("assigned_technician_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
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
            "interval_value BETWEEN 1 AND 3650", name=op.f("ck_maintenance_plans_interval_range")
        ),
        sa.ForeignKeyConstraint(
            ["assigned_technician_id"],
            ["users.id"],
            ondelete="SET NULL",
            name=op.f("fk_maintenance_plans_assigned_technician_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
            name=op.f("fk_maintenance_plans_created_by_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipment.id"],
            ondelete="CASCADE",
            name=op.f("fk_maintenance_plans_equipment_id_equipment"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_plans")),
    )
    op.create_index(
        op.f("ix_maintenance_plans_equipment_id"), "maintenance_plans", ["equipment_id"]
    )

    op.create_table(
        "maintenance_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column(
            "status",
            _enum("scheduled", "completed", "cancelled", name="maintenance_task_status"),
            nullable=False,
        ),
        sa.Column("assigned_technician_id", sa.Integer(), nullable=True),
        sa.Column("completed_on", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_id", sa.Integer(), nullable=True),
        sa.Column("work_notes", sa.Text(), nullable=True),
        sa.Column("cancel_reason", sa.String(length=255), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_id", sa.Integer(), nullable=True),
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
            name=op.f("ck_maintenance_tasks_cancelled_has_reason"),
        ),
        sa.CheckConstraint(
            "(status = 'completed') = (completed_on IS NOT NULL)",
            name=op.f("ck_maintenance_tasks_completed_has_date"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_technician_id"],
            ["users.id"],
            ondelete="SET NULL",
            name=op.f("fk_maintenance_tasks_assigned_technician_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by_id"],
            ["users.id"],
            ondelete="SET NULL",
            name=op.f("fk_maintenance_tasks_cancelled_by_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["completed_by_id"],
            ["users.id"],
            ondelete="SET NULL",
            name=op.f("fk_maintenance_tasks_completed_by_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipment.id"],
            ondelete="CASCADE",
            name=op.f("fk_maintenance_tasks_equipment_id_equipment"),
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["maintenance_plans.id"],
            ondelete="SET NULL",
            name=op.f("fk_maintenance_tasks_plan_id_maintenance_plans"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_tasks")),
    )
    op.create_index(
        op.f("ix_maintenance_tasks_equipment_id"), "maintenance_tasks", ["equipment_id"]
    )
    op.create_index(op.f("ix_maintenance_tasks_plan_id"), "maintenance_tasks", ["plan_id"])
    op.create_index(
        "ix_maintenance_tasks_open_due",
        "maintenance_tasks",
        ["due_on"],
        postgresql_where=sa.text("status = 'scheduled'"),
    )
    op.create_index(
        "uq_maintenance_tasks_one_open_per_plan",
        "maintenance_tasks",
        ["plan_id"],
        unique=True,
        postgresql_where=sa.text("status = 'scheduled' AND plan_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_maintenance_tasks_one_open_per_plan", table_name="maintenance_tasks")
    op.drop_index("ix_maintenance_tasks_open_due", table_name="maintenance_tasks")
    op.drop_index(op.f("ix_maintenance_tasks_plan_id"), table_name="maintenance_tasks")
    op.drop_index(op.f("ix_maintenance_tasks_equipment_id"), table_name="maintenance_tasks")
    op.drop_table("maintenance_tasks")
    op.drop_index(op.f("ix_maintenance_plans_equipment_id"), table_name="maintenance_plans")
    op.drop_table("maintenance_plans")
    # The old rule cannot hold for rows written under the new one: clear offending next dates.
    op.execute(
        "UPDATE equipment SET next_service_on = NULL WHERE next_service_on < last_service_on"
    )
    op.create_check_constraint(
        op.f(NEXT_AFTER_LAST),
        "equipment",
        "next_service_on IS NULL OR last_service_on IS NULL OR next_service_on >= last_service_on",
    )
