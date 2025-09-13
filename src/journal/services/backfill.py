from __future__ import annotations

import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta

from ..db.dao import (
    get_close_from_db,
    get_distinct_symbols,
    get_missing_price_dates,
    get_trade_dates_by_symbol,
    set_prev_close,
)
from .market import backfill_daily

logger = logging.getLogger("backfill")
logger.setLevel(logging.INFO)


def _group_contiguous(dates: list[date]) -> list[tuple[date, date]]:
    if not dates:
        return []
    ds = sorted(set(dates))
    spans: list[tuple[date, date]] = []
    start = prev = ds[0]
    for d in ds[1:]:
        if (d - prev).days == 1:
            prev = d
            continue
        spans.append((start, prev))
        start = prev = d
    spans.append((start, prev))
    return spans


def _prev_day(d: date) -> date:
    return d - timedelta(days=1)


@dataclass
class SymbolPlan:
    symbol: str
    missing_dates: list[date]  # trade dates needing OHLCV and/or prev_close


def _make_symbol_plan(symbol: str) -> SymbolPlan:
    trade_dates = get_trade_dates_by_symbol(symbol)
    missing = get_missing_price_dates(symbol, trade_dates)  # DB-first caching
    return SymbolPlan(symbol=symbol, missing_dates=missing)


def _fill_prev_close_from_db(symbol: str, dates: Iterable[date]) -> int:
    updated = 0
    for d in dates:
        pc = get_close_from_db(symbol, _prev_day(d))
        if pc is not None:
            updated += set_prev_close(symbol, d, pc)
    return updated


def backfill_symbol(symbol: str, max_failures: int = 3) -> dict[str, int]:
    plan = _make_symbol_plan(symbol)
    if not plan.missing_dates:
        # Still try to set prev_close from DB for any trades lacking it
        updated = _fill_prev_close_from_db(symbol, get_trade_dates_by_symbol(symbol))
        return {"symbol": 1, "rows_fetched": 0, "prev_close_set": updated, "spans": 0}

    spans = _group_contiguous(plan.missing_dates)
    fetched = 0
    failures = 0
    for start, end in spans:
        try:
            fetched += backfill_daily(symbol, start, end)
        except Exception as e:
            failures += 1
            logger.warning(f"backfill_failed | {symbol} {start}..{end} | {e}")
            if failures >= max_failures:
                logger.error(f"circuit_open | {symbol} | failures={failures}")
                break

    # After fetching OHLCV, try to set prev_close from DB
    updated = _fill_prev_close_from_db(symbol, plan.missing_dates)
    return {"symbol": 1, "rows_fetched": fetched, "prev_close_set": updated, "spans": len(spans)}


def backfill_all_missing(max_workers: int = 4) -> dict[str, int]:
    syms = get_distinct_symbols()
    totals = {"symbols": 0, "rows_fetched": 0, "prev_close_set": 0, "spans": 0}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(backfill_symbol, s): s for s in syms}
        for fut in as_completed(futs):
            res = fut.result()
            totals["symbols"] += res["symbol"]
            totals["rows_fetched"] += res["rows_fetched"]
            totals["prev_close_set"] += res["prev_close_set"]
            totals["spans"] += res["spans"]
    return totals


# CLI
def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Backfill OHLCV + prev_close")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--all-missing", action="store_true", help="Scan trades and backfill all missing"
    )
    g.add_argument("--symbol", help="Backfill a single symbol")
    p.add_argument("--max-workers", type=int, default=4)
    args = p.parse_args()

    if args.symbol:
        out = backfill_symbol(args.symbol)
        print(out)
        return
    out = backfill_all_missing(max_workers=args.max_workers)
    print(out)


if __name__ == "__main__":
    main()
