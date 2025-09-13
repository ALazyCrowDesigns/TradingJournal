"""add_performance_indexes

Revision ID: 7b0e01eb48a1
Revises: 44baa90b4d93
Create Date: 2025-09-13 13:10:04.029588

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "7b0e01eb48a1"
down_revision: str | Sequence[str] | None = "44baa90b4d93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
