from __future__ import annotations

from typing import Any

from ..db.dao import SortDir
from ..db.dao import fetch_trades_paged_with_derived as fetch_paged

COLUMNS = [
    ("trade_date", "Date"),
    ("symbol", "Symbol"),
    ("side", "Side"),
    ("size", "Size"),
    ("entry", "Entry"),
    ("exit", "Exit"),
    ("pnl", "PnL"),
    ("return_pct", "%Ret"),
    ("prev_close", "PrevClose"),
    ("o", "Open"),
    ("h", "High"),
    ("l", "Low"),
    ("c", "Close"),
    ("v", "Vol"),
    ("gap_pct", "%Gap"),
    ("range_pct", "%Range"),
    ("closechg_pct", "%CloseChg"),
]

INDEX_TO_KEY = [c[0] for c in COLUMNS]
HEADERS = [c[1] for c in COLUMNS]


def page(
    filters: dict | None, order_by: str, order_dir: SortDir, limit: int, offset: int
) -> tuple[list[list[Any]], int]:
    data, total = fetch_paged(
        limit=limit, offset=offset, order_by=order_by, order_dir=order_dir, filters=filters
    )
    return data, total
