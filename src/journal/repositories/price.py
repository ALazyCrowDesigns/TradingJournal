"""
Daily price repository implementation
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Engine, and_, delete, select

from ..db.models import DailyPrice
from ..services.cache import TTLCache
from .base import BaseRepository


class PriceRepository(BaseRepository[DailyPrice]):
    """Repository for DailyPrice entities"""

    def __init__(self, engine: Engine, cache: TTLCache | None = None) -> None:
        super().__init__(engine, DailyPrice)
        self._cache = cache

    def upsert_batch(self, prices: list[dict]) -> int:
        """Upsert a batch of daily prices"""
        if not prices:
            return 0

        with self._session_scope() as session:
            # Collect unique (symbol, date) pairs
            key_pairs = {
                (p["symbol"], p["date"]) for p in prices if p.get("symbol") and p.get("date")
            }

            if key_pairs:
                # Delete existing records
                symbols = list({k[0] for k in key_pairs})
                dates = list({k[1] for k in key_pairs})

                stmt = delete(DailyPrice).where(
                    and_(DailyPrice.symbol.in_(symbols), DailyPrice.date.in_(dates))
                )
                session.execute(stmt)

            # Insert new records
            session.bulk_insert_mappings(DailyPrice, prices)

            # Invalidate caches
            if self._cache:
                for symbol, _ in key_pairs:
                    self._cache.invalidate_prefix(f"price:{symbol}")

            return len(prices)

    def get_missing_dates(self, symbol: str, dates: list[date]) -> list[date]:
        """Get dates missing price data for a symbol"""
        if not dates:
            return []

        with self._session_scope() as session:
            query = select(DailyPrice.date).where(
                and_(DailyPrice.symbol == symbol, DailyPrice.date.in_(dates))
            )

            present_dates = set(session.scalars(query).all())
            return [d for d in dates if d not in present_dates]

    def get_price_range(self, symbol: str, start_date: date, end_date: date) -> list[DailyPrice]:
        """Get prices for a symbol within a date range"""
        with self._session_scope() as session:
            query = (
                select(DailyPrice)
                .where(
                    and_(
                        DailyPrice.symbol == symbol,
                        DailyPrice.date >= start_date,
                        DailyPrice.date <= end_date,
                    )
                )
                .order_by(DailyPrice.date)
            )

            return list(session.scalars(query).all())

    def get_latest_price(self, symbol: str) -> DailyPrice | None:
        """Get the most recent price for a symbol"""
        with self._session_scope() as session:
            query = (
                select(DailyPrice)
                .where(DailyPrice.symbol == symbol)
                .order_by(DailyPrice.date.desc())
                .limit(1)
            )

            return session.scalar(query)

    def get_prices_for_date(self, target_date: date) -> list[DailyPrice]:
        """Get all prices for a specific date"""
        with self._session_scope() as session:
            query = (
                select(DailyPrice).where(DailyPrice.date == target_date).order_by(DailyPrice.symbol)
            )

            return list(session.scalars(query).all())

    def get_previous_close(self, symbol: str, target_date: date) -> float | None:
        """Get the previous trading day's close price"""
        with self._session_scope() as session:
            query = (
                select(DailyPrice.c)
                .where(and_(DailyPrice.symbol == symbol, DailyPrice.date < target_date))
                .order_by(DailyPrice.date.desc())
                .limit(1)
            )

            return session.scalar(query)

    def bulk_get_previous_closes(
        self, symbol_dates: list[tuple[str, date]]
    ) -> dict[tuple[str, date], float | None]:
        """Get previous closes for multiple symbol-date pairs efficiently"""
        result = {}

        with self._session_scope() as session:
            # Group by symbol for efficiency
            symbol_to_dates: dict[str, list[date]] = {}
            for symbol, date in symbol_dates:
                if symbol not in symbol_to_dates:
                    symbol_to_dates[symbol] = []
                symbol_to_dates[symbol].append(date)

            # Query for each symbol
            for symbol, dates in symbol_to_dates.items():
                _ = min(dates)  # min_date was unused
                max_date = max(dates)

                # Get all prices in the range we might need (more efficient)
                query = (
                    select(DailyPrice.date, DailyPrice.c)
                    .where(
                        and_(
                            DailyPrice.symbol == symbol,
                            DailyPrice.date < max_date,  # Get all prices before max date
                        )
                    )
                    .order_by(DailyPrice.date.desc())
                )

                prices = list(session.execute(query))

                # For each requested date, find the previous close
                for target_date in dates:
                    prev_close = None
                    for price_date, close in prices:
                        if price_date < target_date:
                            prev_close = close
                            break
                    result[(symbol, target_date)] = prev_close

        return result
