from __future__ import annotations

from datetime import date, datetime, timedelta

import httpx

from ..config import settings
from ..db.dao import upsert_daily_prices

BASE = "https://api.polygon.io/v2"


def _auth_params() -> dict:
    if not settings.polygon_api_key:
        raise RuntimeError("POLYGON_API_KEY is missing in .env")
    return {"apiKey": settings.polygon_api_key}


def get_daily_range(symbol: str, start: date, end: date) -> list[dict]:
    start_s = start.isoformat()
    end_s = end.isoformat()
    url = f"{BASE}/aggs/ticker/{symbol}/range/1/day/{start_s}/{end_s}"
    r = httpx.get(url, params=_auth_params(), timeout=30)
    r.raise_for_status()
    data = (r.json() or {}).get("results", []) or []
    rows = []
    for it in data:
        d = datetime.utcfromtimestamp(it["t"] / 1000).date()
        rows.append(
            {
                "symbol": symbol,
                "date": d,
                "o": float(it["o"]),
                "h": float(it["h"]),
                "low": float(it["l"]),
                "c": float(it["c"]),
                "v": int(it["v"]),
            }
        )
    return rows


def get_prev_close(symbol: str, on_date: date) -> float | None:
    prev = on_date - timedelta(days=1)
    rows = get_daily_range(symbol, prev, prev)
    return rows[0]["c"] if rows else None


def backfill_daily(symbol: str, start: date, end: date) -> None:
    rows = get_daily_range(symbol, start, end)
    if rows:
        upsert_daily_prices(rows)
