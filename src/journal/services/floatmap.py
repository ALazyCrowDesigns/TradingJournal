from __future__ import annotations

import csv
from datetime import date

from ..db.dao import upsert_symbols


def load_float_csv(path: str, asof: date | None = None) -> None:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for rec in csv.reader(f):
            if not rec:
                continue
            sym = (rec[0] or "").strip().upper()
            if not sym:
                continue
            try:
                val = float(rec[1])
            except Exception:
                continue
            rows.append({"symbol": sym, "float": val, "float_asof": asof})
    if rows:
        upsert_symbols(rows)
