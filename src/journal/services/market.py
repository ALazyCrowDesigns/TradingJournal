from __future__ import annotations

import random
import time
from datetime import UTC, date, datetime

import httpx

from ..config import settings
from ..db.dao import upsert_daily_prices

BASE = "https://api.polygon.io/v2"


def _auth() -> dict:
    if not settings.polygon_api_key:
        raise RuntimeError("POLYGON_API_KEY missing")
    return {"apiKey": settings.polygon_api_key}


def _req_with_retries(url: str, params: dict, max_tries: int = 5) -> httpx.Response:
    delay = 0.5
    for attempt in range(1, max_tries + 1):
        try:
            r = httpx.get(url, params=params, timeout=30)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
            r.raise_for_status()
            return r
        except (httpx.TimeoutException, httpx.HTTPStatusError):
            if attempt == max_tries:
                raise
            time.sleep(delay + random.uniform(0, delay / 2))
            delay = min(delay * 2, 8.0)


def _parse_results(symbol: str, results: list[dict]) -> list[dict]:
    rows = []
    for it in results or []:
        # Polygon returns ms epoch in "t"; normalize to UTC date
        d = datetime.fromtimestamp(it["t"] / 1000, UTC).date()
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


def get_daily_range(symbol: str, start: date, end: date) -> list[dict]:
    url = f"{BASE}/aggs/ticker/{symbol}/range/1/day/{start.isoformat()}/{end.isoformat()}"
    r = _req_with_retries(url, _auth())
    return _parse_results(symbol, (r.json() or {}).get("results", []) or [])


def backfill_daily(symbol: str, start: date, end: date) -> int:
    rows = get_daily_range(symbol, start, end)
    if rows:
        upsert_daily_prices(rows)
    return len(rows)
