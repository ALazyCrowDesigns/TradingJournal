"""add_profiles_table

Revision ID: 4636d7465c00
Revises: 7b0e01eb48a1
Create Date: 2025-09-13 20:07:09.711470

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4636d7465c00"
down_revision: str | Sequence[str] | None = "7b0e01eb48a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create profiles table
    op.create_table(
        "profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("default_csv_format", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profiles")),
        sa.UniqueConstraint("name", name=op.f("uq_profiles_name")),
    )
    op.create_index("ix_profile_active", "profiles", ["is_active"], unique=False)
    op.create_index("ix_profile_name", "profiles", ["name"], unique=False)

    # Insert default profile to ensure existing trades have a valid profile_id
    op.execute(
        """
        INSERT INTO profiles (id, name, description, is_active, created_at, updated_at, default_csv_format)
        VALUES (1, 'Default Trader', 'Default trading profile', 1, datetime('now'), datetime('now'), 'tradersync')
    """
    )

    # Add foreign key constraint to trades table using batch mode
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.create_foreign_key(
            op.f("fk_trades_profile_id_profiles"), "profiles", ["profile_id"], ["id"]
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove foreign key constraint from trades table using batch mode
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("fk_trades_profile_id_profiles"), type_="foreignkey")

    # Drop profiles table and its indexes
    op.drop_index("ix_profile_name", table_name="profiles")
    op.drop_index("ix_profile_active", table_name="profiles")
    op.drop_table("profiles")
