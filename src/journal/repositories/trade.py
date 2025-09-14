"""
Trade repository implementation with caching
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

from sqlalchemy import Engine, and_, asc, desc, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..db.models import DailyPrice, Trade
from ..services.cache import TTLCache
from .base import BaseRepository


class TradeRepository(BaseRepository[Trade]):
    """Repository for Trade entities with business-specific queries"""

    def __init__(self, engine: Engine, cache: TTLCache | None = None) -> None:
        super().__init__(engine, Trade)
        self._cache = cache

    def insert_ignore_duplicates(self, trades: list[dict]) -> int:
        """Insert trades ignoring duplicates based on unique constraint"""
        if not trades:
            return 0

        stmt = sqlite_insert(Trade).values(trades)
        stmt = stmt.on_conflict_do_nothing(index_elements=["profile_id", "symbol", "trade_date"])

        with self._engine.begin() as conn:
            result = conn.execute(stmt)
            inserted = result.rowcount or 0

            # Invalidate caches if data was inserted
            if inserted and self._cache:
                self._cache.invalidate_prefix("trades:")
                self._cache.invalidate_prefix("analytics:")

            return inserted

    def get_paginated(
        self,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "trade_date",
        order_dir: str = "desc",
        filters: dict[str, Any] | None = None,
    ) -> tuple[list[Trade], int]:
        """Get paginated trades with optional filters"""
        # Build cache key
        cache_key = f"trades:paginated:{limit}:{offset}:{order_by}:{order_dir}:{hash(str(filters))}"

        # Try cache first
        if self._cache:
            cached_result = self._cache.get(cache_key)
            if cached_result is not None:
                return cached_result
        with self._session_scope() as session:
            # Base query
            query = select(Trade)

            # Apply filters
            conditions = []
            if filters:
                # CRITICAL: Always filter by profile_id to ensure profile isolation
                if profile_id := filters.get("profile_id"):
                    conditions.append(Trade.profile_id == profile_id)

                if symbol := filters.get("symbol"):
                    conditions.append(Trade.symbol.ilike(f"%{symbol}%"))

                if side := filters.get("side"):
                    conditions.append(Trade.side == side)

                if date_from := filters.get("date_from"):
                    conditions.append(Trade.trade_date >= date_from)

                if date_to := filters.get("date_to"):
                    conditions.append(Trade.trade_date <= date_to)

                if (pnl_min := filters.get("pnl_min")) is not None:
                    conditions.append(Trade.pnl >= pnl_min)

                if (pnl_max := filters.get("pnl_max")) is not None:
                    conditions.append(Trade.pnl <= pnl_max)

                if filters.get("has_ohlcv"):
                    # Join with daily prices to filter
                    query = query.join(
                        DailyPrice,
                        and_(
                            DailyPrice.symbol == Trade.symbol, DailyPrice.date == Trade.trade_date
                        ),
                    )

            if conditions:
                query = query.where(and_(*conditions))

            # Count total
            count_query = select(func.count()).select_from(Trade)
            if conditions:
                count_query = count_query.where(and_(*conditions))
            total = session.scalar(count_query) or 0

            # Apply ordering
            order_column = getattr(Trade, order_by, Trade.trade_date)
            if order_dir == "desc":
                query = query.order_by(desc(order_column))
            else:
                query = query.order_by(asc(order_column))

            # Apply pagination
            query = query.limit(limit).offset(offset)

            # Execute and extract data while in session context to avoid detached instance errors
            trades_result = list(session.scalars(query).all())

            # Convert to dictionaries to avoid detached instance errors
            trades_data = []
            for trade in trades_result:
                trade_dict = {
                    "id": trade.id,
                    "profile_id": trade.profile_id,
                    "trade_date": trade.trade_date,
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "size": trade.size,
                    "entry": trade.entry,
                    "exit": trade.exit,
                    "pnl": trade.pnl,
                    "return_pct": trade.return_pct,
                    "notes": trade.notes,
                    "prev_close": trade.prev_close,
                    "created_at": trade.created_at,
                }
                trades_data.append(trade_dict)

            result = (trades_data, total)

            # Cache the result
            if self._cache:
                self._cache.set(cache_key, result, ttl=60)

            return result

    def get_paginated_with_prices(
        self,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "trade_date",
        order_dir: str = "desc",
        filters: dict[str, Any] | None = None,
    ) -> tuple[list[tuple[Trade, DailyPrice | None]], int]:
        """Get paginated trades with their daily prices in a single query"""
        # Build cache key
        cache_key = (
            f"trades:paginated_prices:{limit}:{offset}:{order_by}:{order_dir}:{hash(str(filters))}"
        )

        # Try cache first
        if self._cache:
            cached_result = self._cache.get(cache_key)
            if cached_result is not None:
                return cached_result

        with self._session_scope() as session:
            # Query with LEFT JOIN to get both trade and price data
            query = (
                select(Trade, DailyPrice)
                .select_from(Trade)
                .outerjoin(
                    DailyPrice,
                    and_(DailyPrice.symbol == Trade.symbol, DailyPrice.date == Trade.trade_date),
                )
            )

            # Apply filters
            conditions = []
            if filters:
                # CRITICAL: Always filter by profile_id to ensure profile isolation
                if profile_id := filters.get("profile_id"):
                    conditions.append(Trade.profile_id == profile_id)

                if symbol := filters.get("symbol"):
                    conditions.append(Trade.symbol.ilike(f"%{symbol}%"))

                if side := filters.get("side"):
                    conditions.append(Trade.side == side)

                if date_from := filters.get("date_from"):
                    conditions.append(Trade.trade_date >= date_from)

                if date_to := filters.get("date_to"):
                    conditions.append(Trade.trade_date <= date_to)

                if (pnl_min := filters.get("pnl_min")) is not None:
                    conditions.append(Trade.pnl >= pnl_min)

                if (pnl_max := filters.get("pnl_max")) is not None:
                    conditions.append(Trade.pnl <= pnl_max)

                if filters.get("has_ohlcv"):
                    # Only include trades that have daily price data
                    conditions.append(DailyPrice.symbol.isnot(None))

            if conditions:
                query = query.where(and_(*conditions))

            # Count total (separate query for accuracy)
            count_query = select(func.count()).select_from(Trade)
            if conditions:
                # Apply same filters to count query
                if filters and filters.get("has_ohlcv"):
                    count_query = count_query.join(
                        DailyPrice,
                        and_(
                            DailyPrice.symbol == Trade.symbol, DailyPrice.date == Trade.trade_date
                        ),
                    )
                count_query = count_query.where(and_(*conditions))
            total = session.scalar(count_query) or 0

            # Apply ordering
            order_column = getattr(Trade, order_by, Trade.trade_date)
            if order_dir == "desc":
                query = query.order_by(desc(order_column))
            else:
                query = query.order_by(asc(order_column))

            # Apply pagination
            query = query.limit(limit).offset(offset)

            # Execute and extract data while in session context
            results = list(session.execute(query).all())

            # Extract data to dictionaries to avoid detached instance errors
            trades_with_prices = []
            for trade, price in results:
                trade_data = {
                    "id": trade.id,
                    "profile_id": trade.profile_id,
                    "trade_date": trade.trade_date,
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "size": trade.size,
                    "entry": trade.entry,
                    "exit": trade.exit,
                    "pnl": trade.pnl,
                    "return_pct": trade.return_pct,
                    "notes": trade.notes,
                    "prev_close": trade.prev_close,
                    "created_at": trade.created_at,
                }

                price_data = None
                if price:
                    price_data = {
                        "symbol": price.symbol,
                        "date": price.date,
                        "o": price.o,
                        "h": price.h,
                        "low": price.low,
                        "c": price.c,
                        "v": price.v,
                    }

                trades_with_prices.append((trade_data, price_data))

            result = (trades_with_prices, total)

            # Cache the result
            if self._cache:
                self._cache.set(cache_key, result, ttl=60)

            return result

    def get_by_profile(self, profile_id: int, limit: int | None = None) -> list[dict]:
        """Get trades for a specific profile"""
        with self._session_scope() as session:
            query = select(Trade).where(Trade.profile_id == profile_id)
            query = query.order_by(desc(Trade.trade_date))

            if limit:
                query = query.limit(limit)

            trades_result = list(session.scalars(query).all())

            # Convert to dictionaries to avoid detached instance errors
            trades_data = []
            for trade in trades_result:
                trade_dict = {
                    "id": trade.id,
                    "profile_id": trade.profile_id,
                    "trade_date": trade.trade_date,
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "size": trade.size,
                    "entry": trade.entry,
                    "exit": trade.exit,
                    "pnl": trade.pnl,
                    "return_pct": trade.return_pct,
                    "notes": trade.notes,
                    "prev_close": trade.prev_close,
                    "created_at": trade.created_at,
                }
                trades_data.append(trade_dict)

            return trades_data

    def get_by_symbol(self, symbol: str, limit: int | None = None) -> list[dict]:
        """Get trades for a specific symbol"""
        with self._session_scope() as session:
            query = select(Trade).where(Trade.symbol == symbol)
            query = query.order_by(desc(Trade.trade_date))

            if limit:
                query = query.limit(limit)

            trades_result = list(session.scalars(query).all())

            # Convert to dictionaries to avoid detached instance errors
            trades_data = []
            for trade in trades_result:
                trade_dict = {
                    "id": trade.id,
                    "profile_id": trade.profile_id,
                    "trade_date": trade.trade_date,
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "size": trade.size,
                    "entry": trade.entry,
                    "exit": trade.exit,
                    "pnl": trade.pnl,
                    "return_pct": trade.return_pct,
                    "notes": trade.notes,
                    "prev_close": trade.prev_close,
                    "created_at": trade.created_at,
                }
                trades_data.append(trade_dict)

            return trades_data

    def get_date_range(self, start_date: date, end_date: date) -> list[dict]:
        """Get trades within a date range"""
        with self._session_scope() as session:
            query = select(Trade).where(
                and_(Trade.trade_date >= start_date, Trade.trade_date <= end_date)
            )
            query = query.order_by(desc(Trade.trade_date))

            trades_result = list(session.scalars(query).all())

            # Convert to dictionaries to avoid detached instance errors
            trades_data = []
            for trade in trades_result:
                trade_dict = {
                    "id": trade.id,
                    "profile_id": trade.profile_id,
                    "trade_date": trade.trade_date,
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "size": trade.size,
                    "entry": trade.entry,
                    "exit": trade.exit,
                    "pnl": trade.pnl,
                    "return_pct": trade.return_pct,
                    "notes": trade.notes,
                    "prev_close": trade.prev_close,
                    "created_at": trade.created_at,
                }
                trades_data.append(trade_dict)

            return trades_data

    def iter_for_export(
        self,
        filters: dict[str, Any] | None = None,
        order_by: str = "trade_date",
        order_dir: str = "desc",
    ) -> Iterator[tuple[Any, ...]]:
        """Iterate trades for export with derived fields"""
        with self._session_scope() as session:
            # Query with joins for derived fields
            query = (
                select(
                    Trade.id,
                    Trade.trade_date,
                    Trade.symbol,
                    Trade.side,
                    Trade.size,
                    Trade.entry,
                    Trade.exit,
                    Trade.pnl,
                    Trade.return_pct,
                    Trade.prev_close,
                    DailyPrice.o,
                    DailyPrice.h,
                    DailyPrice.low,
                    DailyPrice.c,
                    DailyPrice.v,
                    # Derived fields
                    func.coalesce(
                        (DailyPrice.o - Trade.prev_close) / Trade.prev_close * 100, 0
                    ).label("gap_pct"),
                    func.coalesce((DailyPrice.h - DailyPrice.low) / DailyPrice.low * 100, 0).label(
                        "range_pct"
                    ),
                    func.coalesce(
                        (DailyPrice.c - Trade.prev_close) / Trade.prev_close * 100, 0
                    ).label("closechg_pct"),
                )
                .select_from(Trade)
                .outerjoin(
                    DailyPrice,
                    and_(DailyPrice.symbol == Trade.symbol, DailyPrice.date == Trade.trade_date),
                )
            )

            # Apply filters (similar to get_paginated)
            if filters:
                conditions = []
                # CRITICAL: Always filter by profile_id to ensure profile isolation
                if profile_id := filters.get("profile_id"):
                    conditions.append(Trade.profile_id == profile_id)

                if symbol := filters.get("symbol"):
                    conditions.append(Trade.symbol.ilike(f"%{symbol}%"))
                if side := filters.get("side"):
                    conditions.append(Trade.side == side)
                if date_from := filters.get("date_from"):
                    conditions.append(Trade.trade_date >= date_from)
                if date_to := filters.get("date_to"):
                    conditions.append(Trade.trade_date <= date_to)
                if (pnl_min := filters.get("pnl_min")) is not None:
                    conditions.append(Trade.pnl >= pnl_min)
                if (pnl_max := filters.get("pnl_max")) is not None:
                    conditions.append(Trade.pnl <= pnl_max)

                if conditions:
                    query = query.where(and_(*conditions))

            # Apply ordering
            order_column = getattr(Trade, order_by, Trade.trade_date)
            if order_dir == "desc":
                query = query.order_by(desc(order_column))
            else:
                query = query.order_by(asc(order_column))

            # Stream results
            yield from session.execute(query)
