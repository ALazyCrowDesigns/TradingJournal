"""
Backfill service using the new architecture
"""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import structlog

from ..repositories.price import PriceRepository
from ..repositories.trade import TradeRepository
from .market import MarketService


@dataclass
class BackfillPlan:
    """Plan for backfilling a symbol"""

    symbol: str
    missing_dates: list[date]
    date_spans: list[tuple[date, date]]


class BackfillService:
    """Service for backfilling missing market data"""

    def __init__(
        self,
        trade_repository: TradeRepository,
        price_repository: PriceRepository,
        market_service: MarketService,
        logger: structlog.BoundLogger | None = None,
    ) -> None:
        self._trade_repo = trade_repository
        self._price_repo = price_repository
        self._market_service = market_service
        self._logger = logger or structlog.get_logger()

    def backfill_all_missing(self, max_workers: int = 4) -> dict[str, int]:
        """Backfill all missing OHLCV data across all symbols"""
        # Get all unique symbols from trades
        symbols = self._get_all_trade_symbols()

        self._logger.info(
            "backfill_all_started", total_symbols=len(symbols), max_workers=max_workers
        )

        totals = {"symbols": 0, "rows_fetched": 0, "prev_close_set": 0, "spans": 0, "errors": 0}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.backfill_symbol, symbol): symbol for symbol in symbols}

            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    result = future.result()
                    totals["symbols"] += result["symbol"]
                    totals["rows_fetched"] += result["rows_fetched"]
                    totals["prev_close_set"] += result["prev_close_set"]
                    totals["spans"] += result["spans"]

                except Exception as e:
                    totals["errors"] += 1
                    self._logger.error("symbol_backfill_failed", symbol=symbol, error=str(e))

        self._logger.info("backfill_all_complete", **totals)

        return totals

    def backfill_symbol(self, symbol: str, max_failures: int = 3) -> dict[str, int]:
        """Backfill data for a single symbol"""
        plan = self._make_symbol_plan(symbol)

        if not plan.missing_dates:
            # Still try to set prev_close from DB for any trades lacking it
            trade_dates = self._get_trade_dates_for_symbol(symbol)
            updated = self._fill_prev_close_from_db(symbol, trade_dates)

            return {"symbol": 1, "rows_fetched": 0, "prev_close_set": updated, "spans": 0}

        fetched = 0
        failures = 0

        # Fetch OHLCV data for each contiguous date span
        for start, end in plan.date_spans:
            try:
                count = self._market_service.backfill_daily(symbol, start, end)
                fetched += count

                self._logger.debug(
                    "span_backfilled", symbol=symbol, start=start, end=end, fetched=count
                )

            except Exception as e:
                failures += 1
                self._logger.warning(
                    "span_backfill_failed", symbol=symbol, start=start, end=end, error=str(e)
                )

                if failures >= max_failures:
                    self._logger.error("circuit_breaker_open", symbol=symbol, failures=failures)
                    break

        # After fetching OHLCV, update prev_close values
        updated = self._fill_prev_close_from_db(symbol, plan.missing_dates)

        return {
            "symbol": 1,
            "rows_fetched": fetched,
            "prev_close_set": updated,
            "spans": len(plan.date_spans),
        }

    def _make_symbol_plan(self, symbol: str) -> BackfillPlan:
        """Create a backfill plan for a symbol"""
        trade_dates = self._get_trade_dates_for_symbol(symbol)
        missing_dates = self._price_repo.get_missing_dates(symbol, trade_dates)
        date_spans = self._group_contiguous_dates(missing_dates)

        return BackfillPlan(symbol=symbol, missing_dates=missing_dates, date_spans=date_spans)

    def _group_contiguous_dates(self, dates: list[date]) -> list[tuple[date, date]]:
        """Group dates into contiguous spans"""
        if not dates:
            return []

        sorted_dates = sorted(set(dates))
        spans: list[tuple[date, date]] = []
        start = prev = sorted_dates[0]

        for current_date in sorted_dates[1:]:
            if (current_date - prev).days == 1:
                prev = current_date
                continue

            spans.append((start, prev))
            start = prev = current_date

        spans.append((start, prev))
        return spans

    def _fill_prev_close_from_db(self, symbol: str, dates: Iterable[date]) -> int:
        """Fill previous close values from existing price data"""
        updated = 0

        with self._trade_repo._session_scope() as session:
            from sqlalchemy import update

            from ..db.models import Trade

            for trade_date in dates:
                # Get previous close
                _ = trade_date - timedelta(days=1)  # prev_date was unused
                prev_close = self._price_repo.get_previous_close(symbol, trade_date)

                if prev_close is not None:
                    # Update trades for this symbol/date
                    stmt = (
                        update(Trade)
                        .where(
                            (Trade.symbol == symbol)
                            & (Trade.trade_date == trade_date)
                            & (Trade.prev_close.is_(None))
                        )
                        .values(prev_close=prev_close)
                    )

                    result = session.execute(stmt)
                    updated += result.rowcount or 0

            session.commit()

        return updated

    def _get_all_trade_symbols(self) -> list[str]:
        """Get all unique symbols from trades"""
        with self._trade_repo._session_scope() as session:
            from sqlalchemy import distinct, select

            from ..db.models import Trade

            query = select(distinct(Trade.symbol)).order_by(Trade.symbol)
            return list(session.scalars(query).all())

    def _get_trade_dates_for_symbol(self, symbol: str) -> list[date]:
        """Get all trade dates for a symbol"""
        with self._trade_repo._session_scope() as session:
            from sqlalchemy import distinct, select

            from ..db.models import Trade

            query = (
                select(distinct(Trade.trade_date))
                .where(Trade.symbol == symbol)
                .order_by(Trade.trade_date)
            )

            return list(session.scalars(query).all())

    def get_backfill_status(self) -> dict[str, Any]:
        """Get current backfill status across all symbols"""
        with self._trade_repo._session_scope() as session:
            from sqlalchemy import and_, func, select

            from ..db.models import DailyPrice, Trade

            # Count trades with and without prices
            total_trades = session.scalar(select(func.count(Trade.id))) or 0

            # Count trades with prices
            trades_with_prices = (
                session.scalar(
                    select(func.count(func.distinct(Trade.id)))
                    .select_from(Trade)
                    .join(
                        DailyPrice,
                        and_(
                            DailyPrice.symbol == Trade.symbol, DailyPrice.date == Trade.trade_date
                        ),
                    )
                )
                or 0
            )

            # Count trades with prev_close
            trades_with_prev_close = (
                session.scalar(select(func.count(Trade.id)).where(Trade.prev_close.isnot(None)))
                or 0
            )

            return {
                "total_trades": total_trades,
                "trades_with_prices": trades_with_prices,
                "trades_without_prices": total_trades - trades_with_prices,
                "trades_with_prev_close": trades_with_prev_close,
                "trades_without_prev_close": total_trades - trades_with_prev_close,
                "completion_pct": (
                    (trades_with_prices / total_trades * 100) if total_trades > 0 else 0
                ),
            }
