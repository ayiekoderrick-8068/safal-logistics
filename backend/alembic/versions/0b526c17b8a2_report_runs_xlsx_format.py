"""report runs: allow the xlsx format

Revision ID: 0b526c17b8a2
Revises: 5edef33dc935
Create Date: 2026-11-05 22:24:11.089405

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0b526c17b8a2"
down_revision: str | Sequence[str] | None = "5edef33dc935"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_report_runs_format_valid"


def upgrade() -> None:
    op.drop_constraint(op.f(NAME), "report_runs", type_="check")
    op.create_check_constraint(op.f(NAME), "report_runs", "format IN ('csv', 'pdf', 'xlsx')")


def downgrade() -> None:
    # Excel runs cannot be represented in the old schema; drop them from the history first.
    op.execute("DELETE FROM report_runs WHERE format = 'xlsx'")
    op.drop_constraint(op.f(NAME), "report_runs", type_="check")
    op.create_check_constraint(op.f(NAME), "report_runs", "format IN ('csv', 'pdf')")
