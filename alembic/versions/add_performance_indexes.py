"""add performance indexes

Revision ID: add_perf_indexes
Revises: 44baa90b4d93
Create Date: 2025-09-13

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_perf_indexes"
down_revision: str | None = "44baa90b4d93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Performance indexes for common query patterns

    # For filtering trades by profile and date
    op.create_index("ix_trades_profile_date", "trades", ["profile_id", "trade_date"])

    # For filtering trades by symbol and date
    op.create_index("ix_trades_symbol_date", "trades", ["symbol", "trade_date"])

    # For PnL analysis queries
    op.create_index("ix_trades_pnl", "trades", ["pnl"])

    # Composite index for analytics queries
    op.create_index(
        "ix_trades_profile_symbol_date_pnl", "trades", ["profile_id", "symbol", "trade_date", "pnl"]
    )

    # For daily prices lookups
    op.create_index("ix_daily_prices_date", "daily_prices", ["date"])

    # For symbol lookups by sector/industry
    op.create_index("ix_symbols_sector_industry", "symbols", ["sector", "industry"])


def downgrade() -> None:
    op.drop_index("ix_symbols_sector_industry", "symbols")
    op.drop_index("ix_daily_prices_date", "daily_prices")
    op.drop_index("ix_trades_profile_symbol_date_pnl", "trades")
    op.drop_index("ix_trades_pnl", "trades")
    op.drop_index("ix_trades_symbol_date", "trades")
    op.drop_index("ix_trades_profile_date", "trades")
