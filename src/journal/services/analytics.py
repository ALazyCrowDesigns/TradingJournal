"""
Analytics service for trade performance calculations
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import and_, case, func, select

from ..db.models import Trade
from ..repositories.price import PriceRepository
from ..repositories.trade import TradeRepository
from ..services.cache import TTLCache, cached


class AnalyticsService:
    """Service for calculating trading analytics and performance metrics"""

    def __init__(
        self,
        trade_repository: TradeRepository,
        price_repository: PriceRepository,
        cache: TTLCache | None = None,
    ) -> None:
        self._trade_repo = trade_repository
        self._price_repo = price_repository
        self._cache = cache

    @cached(ttl=60, key_prefix="analytics")
    def get_summary(self, filters: dict[str, Any] | None = None) -> dict:
        """Get comprehensive analytics summary"""
        with self._trade_repo._session_scope() as session:
            # Base query for trades
            query = select(Trade)

            # Apply filters
            conditions = []
            if filters:
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

            # Calculate aggregate metrics
            agg_query = select(
                func.count(Trade.id).label("total_trades"),
                func.sum(case((Trade.pnl > 0, 1), else_=0)).label("wins"),
                func.sum(case((Trade.pnl < 0, 1), else_=0)).label("losses"),
                func.sum(case((Trade.pnl == 0, 1), else_=0)).label("breakeven"),
                func.sum(Trade.pnl).label("net_pnl"),
                func.avg(Trade.pnl).label("avg_pnl"),
                func.avg(case((Trade.pnl > 0, Trade.pnl))).label("avg_gain"),
                func.avg(case((Trade.pnl < 0, Trade.pnl))).label("avg_loss"),
                func.max(Trade.pnl).label("max_gain"),
                func.min(Trade.pnl).label("min_loss"),
            ).select_from(Trade)

            if conditions:
                agg_query = agg_query.where(and_(*conditions))

            result = session.execute(agg_query).one()

            # Calculate derived metrics
            total_trades = result.total_trades or 0
            wins = result.wins or 0
            losses = result.losses or 0

            hit_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

            # Get per-symbol breakdown
            symbol_query = select(
                Trade.symbol,
                func.count(Trade.id).label("trades"),
                func.sum(Trade.pnl).label("net_pnl"),
                func.avg(Trade.pnl).label("avg_pnl"),
                func.sum(case((Trade.pnl > 0, 1), else_=0)).label("wins"),
            ).select_from(Trade)

            if conditions:
                symbol_query = symbol_query.where(and_(*conditions))

            symbol_query = (
                symbol_query.group_by(Trade.symbol).order_by(func.sum(Trade.pnl).desc()).limit(20)
            )  # Top 20 symbols

            symbol_results = session.execute(symbol_query).all()

            return {
                "trades": total_trades,
                "wins": wins,
                "losses": losses,
                "breakeven": result.breakeven or 0,
                "net_pnl": float(result.net_pnl or 0),
                "avg_pnl": float(result.avg_pnl or 0),
                "avg_gain": float(result.avg_gain or 0),
                "avg_loss": float(result.avg_loss or 0),
                "max_gain": float(result.max_gain or 0),
                "min_loss": float(result.min_loss or 0),
                "hit_rate": hit_rate,
                "by_symbol": [
                    {
                        "symbol": row.symbol,
                        "trades": row.trades,
                        "net_pnl": float(row.net_pnl or 0),
                        "avg_pnl": float(row.avg_pnl or 0),
                        "wins": row.wins,
                        "hit_rate": (row.wins / row.trades * 100) if row.trades > 0 else 0,
                    }
                    for row in symbol_results
                ],
            }

    def get_performance_by_date(
        self,
        start_date: date,
        end_date: date,
        group_by: str = "day",  # day, week, month
    ) -> list[dict]:
        """Get performance metrics grouped by time period"""
        with self._trade_repo._session_scope() as session:
            # Determine grouping function
            if group_by == "week":
                date_group = func.strftime("%Y-%W", Trade.trade_date)
            elif group_by == "month":
                date_group = func.strftime("%Y-%m", Trade.trade_date)
            else:  # day
                date_group = Trade.trade_date

            query = (
                select(
                    date_group.label("period"),
                    func.count(Trade.id).label("trades"),
                    func.sum(Trade.pnl).label("net_pnl"),
                    func.sum(case((Trade.pnl > 0, 1), else_=0)).label("wins"),
                    func.sum(case((Trade.pnl < 0, 1), else_=0)).label("losses"),
                )
                .select_from(Trade)
                .where(and_(Trade.trade_date >= start_date, Trade.trade_date <= end_date))
                .group_by(date_group)
                .order_by(date_group)
            )

            results = session.execute(query).all()

            return [
                {
                    "period": str(row.period),
                    "trades": row.trades,
                    "net_pnl": float(row.net_pnl or 0),
                    "wins": row.wins,
                    "losses": row.losses,
                    "hit_rate": (row.wins / row.trades * 100) if row.trades > 0 else 0,
                }
                for row in results
            ]

    def get_trade_statistics(self, symbol: str | None = None) -> dict:
        """Get detailed trade statistics"""
        filters = {"symbol": symbol} if symbol else None
        trades = self._trade_repo.get_many(filters)

        if not trades:
            return {
                "count": 0,
                "avg_hold_time": 0,
                "best_trade": None,
                "worst_trade": None,
                "consecutive_wins": 0,
                "consecutive_losses": 0,
            }

        # Sort by date for consecutive calculation
        trades.sort(key=lambda t: t.trade_date)

        # Calculate consecutive wins/losses
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_wins = 0
        current_losses = 0

        for trade in trades:
            if trade.pnl and trade.pnl > 0:
                current_wins += 1
                current_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, current_wins)
            elif trade.pnl and trade.pnl < 0:
                current_losses += 1
                current_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, current_losses)
            else:
                current_wins = 0
                current_losses = 0

        # Find best and worst trades
        trades_with_pnl = [t for t in trades if t.pnl is not None]
        best_trade = max(trades_with_pnl, key=lambda t: t.pnl) if trades_with_pnl else None
        worst_trade = min(trades_with_pnl, key=lambda t: t.pnl) if trades_with_pnl else None

        return {
            "count": len(trades),
            "best_trade": (
                {
                    "date": best_trade.trade_date,
                    "symbol": best_trade.symbol,
                    "pnl": float(best_trade.pnl),
                    "return_pct": float(best_trade.return_pct or 0),
                }
                if best_trade
                else None
            ),
            "worst_trade": (
                {
                    "date": worst_trade.trade_date,
                    "symbol": worst_trade.symbol,
                    "pnl": float(worst_trade.pnl),
                    "return_pct": float(worst_trade.return_pct or 0),
                }
                if worst_trade
                else None
            ),
            "consecutive_wins": max_consecutive_wins,
            "consecutive_losses": max_consecutive_losses,
        }
