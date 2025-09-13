from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date

from sqlalchemy import Engine, asc, create_engine, desc, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..config import settings
from ..dto import DailyPriceIn, SymbolIn, TradeIn
from .models import Base, DailyPrice, Symbol, Trade


def _mk_engine() -> Engine:
    url = f"sqlite:///{settings.db_path}"
    engine = create_engine(url, future=True, pool_pre_ping=True)
    with engine.connect() as con:
        con.execute(text("PRAGMA journal_mode=WAL;"))
        con.execute(text("PRAGMA synchronous=NORMAL;"))
        con.execute(text("PRAGMA foreign_keys=ON;"))
        con.execute(text("PRAGMA temp_store=MEMORY;"))
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
