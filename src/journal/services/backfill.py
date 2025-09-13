from __future__ import annotations

from datetime import date

from .market import backfill_daily, get_prev_close


def backfill_for_trade(symbol: str, trade_date: date) -> dict:
    backfill_daily(symbol, trade_date, trade_date)
    prev = get_prev_close(symbol, trade_date)
    return {"prev_close": prev}
