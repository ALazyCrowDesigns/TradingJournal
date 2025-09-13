from __future__ import annotations

import csv
from datetime import date, datetime

from ..db.dao import upsert_symbols_float_newer


def _parse_asof(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def load_float_csv(path: str, asof: date | None = None) -> int:
    """
    CSV must be: symbol,float  (header optional). Additional columns ignored.
    Returns number of attempted upserts (rows passed to DAO).
    """
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        first = next(reader, None)

        def is_header(rec: list[str] | None) -> bool:
            return bool(rec and str(rec[0]).strip().lower() in ("symbol", "ticker"))

        if first is None:
            return 0
        recs = [first] + list(reader) if not is_header(first) else list(reader)
        for rec in recs:
            if not rec:
                continue
            sym = (rec[0] or "").strip().upper()
            if not sym:
                continue
            try:
                val = float(str(rec[1]).replace(",", ""))
            except Exception:
                continue
            rows.append({"symbol": sym, "float": val, "float_asof": asof})
    return upsert_symbols_float_newer(rows)


# CLI
def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Load float CSV into symbols (newer-wins)")
    p.add_argument("csv_path", help="CSV with symbol,float")
    p.add_argument(
        "--asof",
        help="As-of date (YYYY-MM-DD). If omitted, floats stored with NULL asof.",
    )
    args = p.parse_args()

    asof = _parse_asof(args.asof) if args.asof else None
    n = load_float_csv(args.csv_path, asof=asof)
    print(f"float_upserts_attempted={n}")


if __name__ == "__main__":
    main()
