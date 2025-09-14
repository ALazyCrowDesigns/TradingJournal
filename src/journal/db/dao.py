from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from typing import Any, Literal

import sqlalchemy.event
import sqlalchemy.pool
from sqlalchemy import Engine, and_, asc, case, create_engine, desc, func, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased

from ..config import settings
from ..dto import DailyPriceIn, SymbolIn, TradeIn
from ..services.cache import cached, invalidate_cache
from .models import Base, DailyPrice, Symbol, Trade


def _mk_engine() -> Engine:
    url = f"sqlite:///{settings.db_path}"
    # Optimized connection pooling for SQLite
    engine = create_engine(
        url,
        future=True,
        # Disable pre-ping for SQLite (not needed for file-based DB)
        pool_pre_ping=False,
        # SQLite optimization: use StaticPool for better performance
        poolclass=sqlalchemy.pool.StaticPool,
        connect_args={
            "check_same_thread": False,
            "timeout": 10,  # Reduced timeout for faster failures
        },
        # Disable SQL logging for better startup performance
        echo=False,
    )

    # Apply performance pragmas
    @sqlalchemy.event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        # Performance optimizations
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA mmap_size=30000000000")  # 30GB mmap
        cursor.execute("PRAGMA page_size=32768")  # 32KB pages
        cursor.execute("PRAGMA cache_size=10000")  # ~320MB cache
        cursor.close()

    return engine


engine = _mk_engine()
Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(engine, autoflush=False) as s:
        try:
            yield s
            s.commit()
        except:
            s.rollback()
            raise


def upsert_symbols(rows: Iterable[dict]) -> None:
    with session_scope() as s:
        for r in rows:
            key = (r.get("symbol") or "").upper()
            if not key:
                continue
            obj = s.get(Symbol, key)
            if obj:
                for k, v in r.items():
                    setattr(obj, k, v)
            else:
                s.add(Symbol(**r))


def insert_trades(trades: Sequence[dict]) -> None:
    """Insert trades (legacy function - prefer insert_trades_ignore_duplicates_dicts)"""
    with session_scope() as s:
        s.bulk_insert_mappings(Trade, list(trades))


def insert_trades_ignore_duplicates_dicts(rows: list[dict]) -> int:
    if not rows:
        return 0
    stmt = sqlite_insert(Trade).values(rows)
    # Unique constraint exists on (profile_id, symbol, trade_date)
    stmt = stmt.on_conflict_do_nothing(index_elements=["profile_id", "symbol", "trade_date"])
    with engine.begin() as conn:
        result = conn.execute(stmt)
        # Invalidate analytics cache when new trades are inserted
        if result.rowcount:
            invalidate_cache("analytics")
        # SQLite returns rowcount for inserted rows only
        return result.rowcount or 0


def upsert_daily_prices(rows: Sequence[dict]) -> None:
    with session_scope() as s:
        keys = {(r["symbol"], r["date"]) for r in rows if r.get("symbol") and r.get("date")}
        if keys:
            syms = list({k[0] for k in keys})
            dts = list({k[1] for k in keys})
            s.query(DailyPrice).filter(DailyPrice.symbol.in_(syms)).filter(
                DailyPrice.date.in_(dts)
            ).delete(synchronize_session=False)
        s.bulk_insert_mappings(DailyPrice, list(rows))


def get_missing_price_dates(symbol: str, dates: list[date]) -> list[date]:
    with session_scope() as s:
        present = {
            d
            for (d,) in s.query(DailyPrice.date)
            .filter(DailyPrice.symbol == symbol, DailyPrice.date.in_(dates))
            .all()
        }
    return [d for d in dates if d not in present]


def upsert_symbols_dto(rows: Iterable[SymbolIn]) -> None:
    with session_scope() as s:
        for dto in rows:
            data = dto.model_dump()
            key = data["symbol"]
            obj = s.get(Symbol, key)
            if obj:
                for k, v in data.items():
                    setattr(obj, k, v)
            else:
                s.add(Symbol(**data))


def insert_trades_dto(rows: Sequence[TradeIn]) -> None:
    # Convert to dict once to use bulk_insert_mappings
    payload = [r.model_dump() for r in rows]
    with session_scope() as s:
        s.bulk_insert_mappings(Trade, payload)


def upsert_daily_prices_dto(rows: Sequence[DailyPriceIn]) -> None:
    payload = [r.model_dump() for r in rows]
    with session_scope() as s:
        keys = {(r["symbol"], r["date"]) for r in payload}
        if keys:
            syms = list({k[0] for k in keys})
            dts = list({k[1] for k in keys})
            s.query(DailyPrice).filter(DailyPrice.symbol.in_(syms)).filter(
                DailyPrice.date.in_(dts)
            ).delete(synchronize_session=False)
        s.bulk_insert_mappings(DailyPrice, payload)


def fetch_trades(
    limit: int = 100, offset: int = 0, order_by: str = "trade_date", order_dir: str = "desc"
) -> list[Trade]:
    col = getattr(Trade, order_by, Trade.trade_date)
    order = desc(col) if order_dir.lower().startswith("d") else asc(col)
    with session_scope() as s:
        rows = s.execute(select(Trade).order_by(order).limit(limit).offset(offset)).scalars().all()
        return rows


def optimize_db() -> None:
    with engine.connect() as con:
        con.execute(text("PRAGMA optimize;"))
        con.execute(text("ANALYZE;"))


def get_distinct_symbols() -> list[str]:
    with session_scope() as s:
        return [r[0] for r in s.execute(select(Symbol.symbol)).all()]


def get_trade_dates_by_symbol(symbol: str) -> list[date]:
    with session_scope() as s:
        rows = s.execute(select(Trade.trade_date).where(Trade.symbol == symbol)).all()
        return [r[0] for r in rows]


def set_prev_close(symbol: str, d: date, prev_close: float) -> int:
    with session_scope() as s:
        res = s.execute(
            update(Trade)
            .where(Trade.symbol == symbol, Trade.trade_date == d)
            .values(prev_close=prev_close)
        )
        return res.rowcount or 0


def set_prev_close_bulk(updates: list[tuple[str, date, float]]) -> int:
    """Bulk update previous close values for multiple symbol-date pairs"""
    if not updates:
        return 0

    total_updated = 0
    with session_scope() as s:
        # Group updates by symbol for better performance
        symbol_updates = {}
        for symbol, trade_date, prev_close in updates:
            if symbol not in symbol_updates:
                symbol_updates[symbol] = []
            symbol_updates[symbol].append((trade_date, prev_close))

        # Update each symbol's trades in batch
        for symbol, date_price_pairs in symbol_updates.items():
            # Build CASE statement for bulk update
            case_conditions = []
            for trade_date, prev_close in date_price_pairs:
                case_conditions.append((Trade.trade_date == trade_date, prev_close))

            if case_conditions:
                res = s.execute(
                    update(Trade)
                    .where(
                        and_(
                            Trade.symbol == symbol,
                            Trade.trade_date.in_([dp[0] for dp in date_price_pairs]),
                        )
                    )
                    .values(
                        prev_close=case(
                            *case_conditions,
                            else_=Trade.prev_close,  # Keep existing value if no match
                        )
                    )
                )
                total_updated += res.rowcount or 0

    return total_updated


def get_close_from_db(symbol: str, d: date) -> float | None:
    with session_scope() as s:
        row = s.execute(
            select(DailyPrice.c).where(DailyPrice.symbol == symbol, DailyPrice.date == d)
        ).first()
        return float(row[0]) if row else None


def get_closes_from_db_bulk(symbol_dates: list[tuple[str, date]]) -> dict[tuple[str, date], float]:
    """Get closing prices for multiple symbol-date pairs in a single query"""
    if not symbol_dates:
        return {}

    result = {}
    with session_scope() as s:
        # Group by symbol for more efficient queries
        symbol_to_dates = {}
        for symbol, date in symbol_dates:
            if symbol not in symbol_to_dates:
                symbol_to_dates[symbol] = []
            symbol_to_dates[symbol].append(date)

        # Query each symbol's dates efficiently
        for symbol, dates in symbol_to_dates.items():
            rows = s.execute(
                select(DailyPrice.date, DailyPrice.c).where(
                    and_(DailyPrice.symbol == symbol, DailyPrice.date.in_(dates))
                )
            ).all()

            for date_val, close_price in rows:
                result[(symbol, date_val)] = float(close_price)

    return result


def upsert_symbols_float_newer(rows: list[dict]) -> int:
    """
    rows: [{"symbol": "AAPL", "float": 15_000_000, "float_asof": date(2024,1,15)}, ...]
    Newer wins: update only if incoming float_asof is newer than existing (or existing is NULL).
    """
    if not rows:
        return 0
    stmt = sqlite_insert(Symbol).values(rows)
    # On insert: write all fields. On conflict: update only when newer.
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol"],
        set_={
            "float": stmt.excluded.float,
            "float_asof": stmt.excluded.float_asof,
        },
        where=(
            (stmt.excluded.float_asof.isnot(None))
            & ((Symbol.float_asof.is_(None)) | (stmt.excluded.float_asof > Symbol.float_asof))
        ),
    )
    with engine.begin() as conn:
        res = conn.execute(stmt)
        return res.rowcount or 0


def get_symbols_missing_fundamentals(limit: int | None = None) -> list[str]:
    """
    Return symbols where any of name/sector/industry is NULL.
    """
    q = select(Symbol.symbol).where(
        (Symbol.name.is_(None)) | (Symbol.sector.is_(None)) | (Symbol.industry.is_(None))
    )
    if limit:
        q = q.limit(limit)
    with session_scope() as s:
        return [r[0] for r in s.execute(q).all()]


def update_symbols_fundamentals(rows: list[dict]) -> int:
    """
    rows: [{"symbol":"AAPL","name":"Apple Inc.","sector":"Tech","industry":"Electronics"}, ...]
    Overwrites provided fields.
    """
    if not rows:
        return 0

    # Use upsert for better performance
    upsert_rows = []
    for r in rows:
        sym = r.get("symbol")
        if not sym:
            continue

        # Prepare row for upsert
        upsert_row = {"symbol": sym}
        for k in ("name", "sector", "industry"):
            if k in r:
                upsert_row[k] = r[k]
        upsert_rows.append(upsert_row)

    if not upsert_rows:
        return 0

    # Bulk upsert using SQLite's ON CONFLICT
    stmt = sqlite_insert(Symbol).values(upsert_rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol"],
        set_={
            "name": stmt.excluded.name,
            "sector": stmt.excluded.sector,
            "industry": stmt.excluded.industry,
        },
    )

    with engine.begin() as conn:
        result = conn.execute(stmt)
        return result.rowcount or 0


SortDir = Literal["asc", "desc"]


def _apply_trade_filters(q: Any, filters: dict | None) -> Any:
    conds = []
    df = filters or {}
    if v := df.get("date_from"):
        conds.append(Trade.trade_date >= v)
    if v := df.get("date_to"):
        conds.append(Trade.trade_date <= v)
    if v := df.get("symbol"):
        like = f"%{v.strip().upper()}%"
        conds.append(Trade.symbol.like(like))
    if (v := df.get("side")) and v.upper() in ("LONG", "SHORT", "BUY", "SELL"):
        conds.append(Trade.side == v.upper())
    # PnL filters
    if (v := df.get("pnl_min")) is not None:
        conds.append(Trade.pnl >= float(v))
    if (v := df.get("pnl_max")) is not None:
        conds.append(Trade.pnl <= float(v))
    # has-OHLCV = existence of DailyPrice on trade_date for symbol
    if df.get("has_ohlcv"):
        dp = aliased(DailyPrice)
        q = q.join(dp, and_(dp.symbol == Trade.symbol, dp.date == Trade.trade_date), isouter=False)
    if conds:
        q = q.where(and_(*conds))
    return q


def fetch_trades_paged(
    limit: int = 500,
    offset: int = 0,
    order_by: str = "trade_date",
    order_dir: SortDir = "desc",
    filters: dict | None = None,
) -> tuple[list[list], int]:
    # Left-join DailyPrice to enrich OHLCV in the grid
    dp = aliased(DailyPrice)
    q = select(
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
        dp.o,
        dp.h,
        dp.low,
        dp.c,
        dp.v,
    ).join(dp, and_(dp.symbol == Trade.symbol, dp.date == Trade.trade_date), isouter=True)

    q = _apply_trade_filters(q, filters)
    # Sort
    valid = {
        "trade_date": Trade.trade_date,
        "symbol": Trade.symbol,
        "side": Trade.side,
        "size": Trade.size,
        "entry": Trade.entry,
        "exit": Trade.exit,
        "pnl": Trade.pnl,
        "return_pct": Trade.return_pct,
        "prev_close": Trade.prev_close,
        "o": dp.o,
        "h": dp.h,
        "l": dp.low,
        "c": dp.c,
        "v": dp.v,
    }
    col = valid.get(order_by, Trade.trade_date)
    q = q.order_by(col.desc() if order_dir == "desc" else col.asc())
    # Page
    q = q.limit(limit).offset(offset)

    with session_scope() as s:
        rows = s.execute(q).all()
    # Total count for current filters
    cq = select(func.count()).select_from(Trade)
    cq = _apply_trade_filters(cq, filters)
    with session_scope() as s:
        total = s.execute(cq).scalar_one()
    # Normalize rows to lists
    data = [list(r) for r in rows]
    return data, int(total)


def _derived_columns_expr(dp: Any) -> tuple[Any, Any, Any]:
    # Protect against divide-by-zero/NULL
    prev = Trade.prev_close
    o, h, low, c = dp.o, dp.h, dp.low, dp.c
    gap_pct = (o - prev) / prev * 100.0
    range_pct = (h - low) / prev * 100.0
    closechg_pct = (c - prev) / prev * 100.0
    # SQLite returns NULL if any operand NULL; that's fine.
    return (
        gap_pct.label("gap_pct"),
        range_pct.label("range_pct"),
        closechg_pct.label("closechg_pct"),
    )


def fetch_trades_paged_with_derived(
    limit: int = 500,
    offset: int = 0,
    order_by: str = "trade_date",
    order_dir: SortDir = "desc",
    filters: dict | None = None,
) -> tuple[list[list], int]:
    dp = aliased(DailyPrice)
    gap_pct, range_pct, closechg_pct = _derived_columns_expr(dp)

    q = select(
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
        dp.o,
        dp.h,
        dp.low,
        dp.c,
        dp.v,
        gap_pct,
        range_pct,
        closechg_pct,
    ).join(dp, and_(dp.symbol == Trade.symbol, dp.date == Trade.trade_date), isouter=True)

    q = _apply_trade_filters(q, filters)

    valid = {
        "trade_date": Trade.trade_date,
        "symbol": Trade.symbol,
        "side": Trade.side,
        "size": Trade.size,
        "entry": Trade.entry,
        "exit": Trade.exit,
        "pnl": Trade.pnl,
        "return_pct": Trade.return_pct,
        "prev_close": Trade.prev_close,
        "o": dp.o,
        "h": dp.h,
        "l": dp.low,
        "c": dp.c,
        "v": dp.v,
        "gap_pct": gap_pct,
        "range_pct": range_pct,
        "closechg_pct": closechg_pct,
    }
    col = valid.get(order_by, Trade.trade_date)
    q = q.order_by(col.desc() if order_dir == "desc" else col.asc())
    q = q.limit(limit).offset(offset)

    with session_scope() as s:
        rows = s.execute(q).all()

    cq = select(func.count()).select_from(Trade)
    cq = _apply_trade_filters(cq, filters)
    with session_scope() as s:
        total = s.execute(cq).scalar_one()

    data = [list(r) for r in rows]
    return data, int(total)


@cached(ttl=60, key_prefix="analytics")  # Cache for 1 minute
def analytics_summary(filters: dict | None = None) -> dict:
    """
    Returns: {
      'trades': N, 'wins': W, 'losses': L, 'hit_rate': float,
      'avg_gain': float, 'avg_loss': float, 'net_pnl': float,
      'by_symbol': [{'symbol': 'AAPL', 'trades': 10, 'net_pnl': 123.4}...]
    }
    """
    # Base query with filters
    base = select(Trade.pnl).select_from(Trade)
    base = _apply_trade_filters(base, filters)

    win_case = case((Trade.pnl > 0, 1), else_=0)
    loss_case = case((Trade.pnl < 0, 1), else_=0)
    gain_case = case((Trade.pnl > 0, Trade.pnl), else_=None)
    loss_case_val = case((Trade.pnl < 0, Trade.pnl), else_=None)

    q = select(
        func.count(Trade.id),
        func.sum(win_case),
        func.sum(loss_case),
        func.avg(gain_case),
        func.avg(loss_case_val),
        func.sum(Trade.pnl),
    ).select_from(Trade)
    q = _apply_trade_filters(q, filters)

    with session_scope() as s:
        total, wins, losses, avg_gain, avg_loss, net = s.execute(q).one()

    # By symbol
    q2 = select(Trade.symbol, func.count(Trade.id), func.sum(Trade.pnl)).select_from(Trade)
    q2 = _apply_trade_filters(q2, filters)
    q2 = q2.group_by(Trade.symbol).order_by(func.sum(Trade.pnl).desc()).limit(20)

    with session_scope() as s:
        rows = s.execute(q2).all()

    hit_rate = (wins / total * 100.0) if total else 0.0

    return {
        "trades": int(total or 0),
        "wins": int(wins or 0),
        "losses": int(losses or 0),
        "hit_rate": float(hit_rate),
        "avg_gain": float(avg_gain or 0.0),
        "avg_loss": float(avg_loss or 0.0),
        "net_pnl": float(net or 0.0),
        "by_symbol": [
            {"symbol": r[0], "trades": int(r[1]), "net_pnl": float(r[2] or 0.0)} for r in rows
        ],
    }


def iter_trades_for_export(
    filters: dict | None, order_by: str, order_dir: SortDir, chunk: int = 2000
) -> Iterator[list]:
    """
    Yield rows (as lists) for the full filtered view, with derived columns at the end.
    """
    offset = 0
    while True:
        page, total = fetch_trades_paged_with_derived(
            limit=chunk, offset=offset, order_by=order_by, order_dir=order_dir, filters=filters
        )
        if not page:
            break
        yield from page
        offset += chunk
