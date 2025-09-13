"""remove_ohlcv_from_trades

Revision ID: 44baa90b4d93
Revises: 4003c62dbf9c
Create Date: 2025-09-13 12:55:28.571401

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "44baa90b4d93"
down_revision: str | Sequence[str] | None = "4003c62dbf9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove OHLCV columns from trades table - they belong only in daily_prices."""
    # Drop OHLCV columns from trades table
    with op.batch_alter_table("trades") as batch_op:
        batch_op.drop_column("o")
        batch_op.drop_column("h")
        batch_op.drop_column("low")
        batch_op.drop_column("c")
        batch_op.drop_column("v")


def downgrade() -> None:
    """Re-add OHLCV columns to trades table."""
    with op.batch_alter_table("trades") as batch_op:
        batch_op.add_column(sa.Column("o", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("h", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("low", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("c", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("v", sa.Integer(), nullable=True))
