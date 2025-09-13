from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PREFS_PATH = Path("./userprefs.json")

_DEFAULTS = {
    "columns_visible": [
        "trade_date",
        "symbol",
        "side",
        "size",
        "entry",
        "exit",
        "pnl",
        "return_pct",
        "prev_close",
        "o",
        "h",
        "l",
        "c",
        "v",
        "gap_pct",
        "range_pct",
        "closechg_pct",
    ],
    "filters": {
        "symbol": "",
        "side": "",
        "date_from": None,
        "date_to": None,
        "pnl_min": None,
        "pnl_max": None,
        "has_ohlcv": False,
    },
    "page_size": 500,
    "order_by": "trade_date",
    "order_dir": "desc",
}


def load_prefs() -> dict[str, Any]:
    if not PREFS_PATH.exists():
        return _DEFAULTS.copy()
    try:
        return {**_DEFAULTS, **json.loads(PREFS_PATH.read_text(encoding="utf-8"))}
    except Exception:
        return _DEFAULTS.copy()


def save_prefs(p: dict[str, Any]) -> None:
    from contextlib import suppress

    with suppress(Exception):
        PREFS_PATH.write_text(json.dumps(p, indent=2), encoding="utf-8")
