from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from ..db.dao import insert_trades_ignore_duplicates_dicts, upsert_symbols_dto
from ..dto import SymbolIn, TradeIn

LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)
logger = logging.getLogger("ingest.tradersync")
if not logger.handlers:
    fh = logging.FileHandler(LOGS_DIR / "ingest.log", mode="a", encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
logger.setLevel(logging.INFO)


@dataclass(frozen=True)
class Mapping:
    columns: dict[str, str]
    date_formats: list[str]
    trim_symbols: bool = True
    uppercase_symbols: bool = True


def load_mapping(path: str | Path) -> Mapping:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Mapping(
        columns=data["columns"],
        date_formats=data.get("date_formats", ["%Y-%m-%d"]),
        trim_symbols=bool(data.get("trim_symbols", True)),
        uppercase_symbols=bool(data.get("uppercase_symbols", True)),
    )


def parse_date(value: Any, fmts: list[str]) -> date | None:
    if value is None:
        return None
    s = str(value).strip()
    for f in fmts:
        try:
            return datetime.strptime(s, f).date()
        except Exception:
            continue
    return None


def to_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None


def normalize_symbol(sym: str, trim: bool, upper: bool) -> str:
    s = sym or ""
    if trim:
        s = s.strip()
    if upper:
        s = s.upper()
    return s


def load_tradersync_csv(
    csv_path: str | Path, profile_id: int, mapping_path: str | Path, dry_run: bool = False
) -> dict:
    """Return a summary dict: {inserted, duplicates_skipped, errors}"""
    mapping = load_mapping(mapping_path)
    m = mapping.columns

    df = pl.read_csv(str(csv_path), ignore_errors=True)

    required = ["date", "symbol", "side", "quantity"]
    missing = [k for k in required if m.get(k) not in df.columns]
    if missing:
        msg = f"Missing required columns in CSV per mapping: {missing}"
        logger.error(msg)
        raise ValueError(msg)

    # Deduplicate within-file by identity key (profile_id, symbol, trade_date[, time])
    seen_keys: set[tuple[int, str, date, str | None]] = set()

    rows_to_insert: list[dict] = []
    symbols: set[str] = set()
    errors = 0
    for row in df.iter_rows(named=True):
        try:
            raw_symbol = row.get(m["symbol"])
            symbol = normalize_symbol(raw_symbol, mapping.trim_symbols, mapping.uppercase_symbols)
            if not symbol:
                raise ValueError("empty symbol")

            d = parse_date(row.get(m["date"]), mapping.date_formats)
            if not d:
                raise ValueError(f"bad date: {row.get(m['date'])}")

            time_val = None
            if "time" in m and m["time"] in df.columns:
                time_val = str(row.get(m["time"])) if row.get(m["time"]) is not None else None

            identity = (profile_id, symbol, d, time_val)
            if identity in seen_keys:
                continue
            seen_keys.add(identity)

            side = str(row.get(m.get("side", ""), "") or "")[:5]
            qty = row.get(m.get("quantity", ""), 0) or 0
            entry = to_float(row.get(m.get("entry", ""), None))
            exit_ = to_float(row.get(m.get("exit", ""), None))
            pnl = to_float(row.get(m.get("pnl", ""), None))
            rpct = to_float(row.get(m.get("return_pct", ""), None))
            notes = row.get(m.get("notes", ""), None) or ""
            notes = str(notes)[:500]

            # DTO-level guarantees
            symbols.add(symbol)
            trade_dict = TradeIn(
                profile_id=profile_id,
                trade_date=d,
                symbol=symbol,
                side=side,
                size=int(float(qty) if qty not in (None, "") else 0),
                entry=entry,
                exit=exit_,
                pnl=pnl,
                return_pct=rpct,
                notes=notes,
            ).model_dump()

            rows_to_insert.append(trade_dict)
        except Exception as e:
            errors += 1
            logger.warning(f"row_error | {e} | row={row}")

    # Ensure symbols exist
    symbol_dtos = [SymbolIn(symbol=s) for s in symbols]

    summary = {"inserted": 0, "duplicates_skipped": 0, "errors": errors}

    if dry_run:
        logger.info(
            f"dry_run | profile={profile_id} | rows={len(rows_to_insert)} | "
            f"symbols={len(symbols)} | errors={errors}"
        )
        return summary

    # Persist
    upsert_symbols_dto(symbol_dtos)
    inserted = insert_trades_ignore_duplicates_dicts(rows_to_insert)
    summary["inserted"] = inserted
    summary["duplicates_skipped"] = len(rows_to_insert) - inserted
    logger.info(
        f"ingest_done | profile={profile_id} | inserted={inserted} | "
        f"duplicates={summary['duplicates_skipped']} | errors={errors}"
    )
    return summary


# CLI
def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Import TraderSync-like CSV into TradingJournal")
    p.add_argument("csv_path", help="Path to CSV")
    p.add_argument("--profile", type=int, default=1, help="Profile ID (default: 1)")
    p.add_argument(
        "--mapping",
        default="src/journal/ingest/mapping.tradersync.json",
        help="Path to mapping JSON",
    )
    p.add_argument("--dry-run", action="store_true", help="Validate and parse without inserting")
    args = p.parse_args()

    s = load_tradersync_csv(args.csv_path, args.profile, args.mapping, dry_run=args.dry_run)
    print(
        f"Imported: {s['inserted']} | Duplicates skipped: {s['duplicates_skipped']} | "
        f"Errors: {s['errors']}"
    )


if __name__ == "__main__":
    main()
