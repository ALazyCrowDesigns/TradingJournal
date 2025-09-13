"""rename shares_float to float

Revision ID: 4003c62dbf9c
Revises: f67064f3f30c
Create Date: 2025-09-13 12:20:56.054738

"""

from collections.abc import Sequence

import alembic.op as op

# revision identifiers, used by Alembic.
revision: str = "4003c62dbf9c"
down_revision: str | Sequence[str] | None = "f67064f3f30c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Rename shares_float column to float in symbols table
    op.alter_column("symbols", "shares_float", new_column_name="float")


def downgrade() -> None:
    """Downgrade schema."""
    # Rename float column back to shares_float in symbols table
    op.alter_column("symbols", "float", new_column_name="shares_float")
