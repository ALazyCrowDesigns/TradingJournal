from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from ..config import settings
from .models import Base, DailyPrice, Symbol, Trade


def _mk_engine() -> Engine:
    url = f"sqlite:///{settings.db_path}"
    engine = create_engine(url, future=True, pool_pre_ping=True)
    with engine.connect() as con:
        con.execute(text("PRAGMA journal_mode=WAL;"))
        con.execute(text("PRAGMA synchronous=NORMAL;"))
        con.execute(text("PRAGMA foreign_keys=ON;"))
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
