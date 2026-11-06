"""maintenance: spare parts and the stock movement ledger

Revision ID: f7b1d4e5a6c8
Revises: e6a0c3d4f5b7
Create Date: 2026-11-06 20:29:26.378919

New tables only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7b1d4e5a6c8"
down_revision: str | Sequence[str] | None = "e6a0c3d4f5b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('spare_parts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('part_number', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('category', sa.String(length=60), nullable=True),
    sa.Column('unit', sa.Enum('each', 'set', 'metre', 'litre', 'kg', name='stock_unit', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('on_hand', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('reorder_level', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('reorder_quantity', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('location', sa.String(length=80), nullable=True),
    sa.Column('supplier', sa.String(length=120), nullable=True),
    sa.Column('unit_cost', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('on_hand >= 0', name=op.f('ck_spare_parts_on_hand_non_negative')),
    sa.CheckConstraint('reorder_level >= 0', name=op.f('ck_spare_parts_reorder_level_non_negative')),
    sa.CheckConstraint('unit_cost IS NULL OR unit_cost >= 0', name=op.f('ck_spare_parts_unit_cost_non_negative')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_spare_parts')),
    sa.UniqueConstraint('part_number', name=op.f('uq_spare_parts_part_number'))
    )
    op.create_table('stock_movements',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('part_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Enum('receipt', 'issue', 'return', 'adjustment', name='stock_movement_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('balance_after', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('work_order_id', sa.Integer(), nullable=True),
    sa.Column('reference', sa.String(length=80), nullable=True),
    sa.Column('note', sa.String(length=255), nullable=True),
    sa.Column('unit_cost', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'issue' AND quantity < 0) OR (kind IN ('receipt', 'return') AND quantity > 0) OR kind = 'adjustment'", name=op.f('ck_stock_movements_sign_matches_kind')),
    sa.CheckConstraint("(kind IN ('issue', 'return')) = (work_order_id IS NOT NULL)", name=op.f('ck_stock_movements_work_order_for_issue_and_return')),
    sa.CheckConstraint('balance_after >= 0', name=op.f('ck_stock_movements_balance_non_negative')),
    sa.CheckConstraint('quantity <> 0', name=op.f('ck_stock_movements_quantity_non_zero')),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_stock_movements_actor_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['part_id'], ['spare_parts.id'], name=op.f('fk_stock_movements_part_id_spare_parts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], name=op.f('fk_stock_movements_work_order_id_work_orders'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stock_movements')),
    sa.UniqueConstraint('request_id', name=op.f('uq_stock_movements_request_id'))
    )
    op.create_index(op.f('ix_stock_movements_occurred_at'), 'stock_movements', ['occurred_at'], unique=False)
    op.create_index(op.f('ix_stock_movements_part_id'), 'stock_movements', ['part_id'], unique=False)
    op.create_index(op.f('ix_stock_movements_work_order_id'), 'stock_movements', ['work_order_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_stock_movements_work_order_id'), table_name='stock_movements')
    op.drop_index(op.f('ix_stock_movements_part_id'), table_name='stock_movements')
    op.drop_index(op.f('ix_stock_movements_occurred_at'), table_name='stock_movements')
    op.drop_table('stock_movements')
    op.drop_table('spare_parts')
