from __future__ import annotations

from datetime import date, datetime
from typing import Any

import polars as pl

from ..db.dao import insert_trades, upsert_symbols

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"]


def _parse_date(x: Any) -> date | None:
    if x is None:
        return None
    s = str(x).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None


def _to_float(x: Any) -> float | None:
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None


def load_tradersync_csv(path: str, profile_id: int = 1) -> None:
    df = pl.read_csv(path, ignore_errors=True)
    trades = []
    symbols = set()
    for row in df.iter_rows(named=True):
        symbol = str(row.get("Symbol", "")).strip().upper()
        if not symbol:
            continue
        symbols.add(symbol)
        trade_date = _parse_date(row.get("Date"))
        trades.append(
            {
                "profile_id": profile_id,
                "trade_date": trade_date,
                "symbol": symbol,
                "side": str(row.get("Side", ""))[:5],
                "size": int(float(row.get("Quantity", 0) or 0)),
                "entry": _to_float(row.get("Entry")),
                "exit": _to_float(row.get("Exit")),
                "pnl": _to_float(row.get("PnL")),
                "return_pct": _to_float(row.get("ReturnPct")),
                "notes": (str(row.get("Notes")) if row.get("Notes") else "")[:500],
            }
        )
    upsert_symbols({"symbol": s} for s in symbols)
    if trades:
        insert_trades(trades)
