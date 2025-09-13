from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
import numpy as np

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


def process_csv_chunk(
    chunk_df: pl.DataFrame,
    mapping: Mapping,
    profile_id: int,
    seen_keys: set[tuple[int, str, date, str | None]],
) -> tuple[list[dict], set[str], int, set[tuple[int, str, date, str | None]]]:
    """Process a chunk of CSV data in parallel"""
    m = mapping.columns
    rows_to_insert: list[dict] = []
    symbols: set[str] = set()
    errors = 0
    local_seen_keys = seen_keys.copy()
    
    for row in chunk_df.iter_rows(named=True):
        try:
            raw_symbol = row.get(m["symbol"])
            if raw_symbol is None:
                raise ValueError("empty symbol")
            symbol = normalize_symbol(raw_symbol, mapping.trim_symbols, mapping.uppercase_symbols)
            if not symbol:
                raise ValueError("empty symbol")

            d = parse_date(row.get(m["date"]), mapping.date_formats)
            if not d:
                raise ValueError(f"bad date: {row.get(m['date'])}")

            time_val = None
            if "time" in m and m["time"] in chunk_df.columns:
                time_val = str(row.get(m["time"])) if row.get(m["time"]) is not None else None

            identity = (profile_id, symbol, d, time_val)
            if identity in local_seen_keys:
                continue
            local_seen_keys.add(identity)

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
    
    return rows_to_insert, symbols, errors, local_seen_keys


def load_tradersync_csv(
    csv_path: str | Path, profile_id: int, mapping_path: str | Path, dry_run: bool = False,
    chunk_size: int = 5000, max_workers: int = 4
) -> dict:
    """Return a summary dict: {inserted, duplicates_skipped, errors}"""
    mapping = load_mapping(mapping_path)
    m = mapping.columns

    # Read CSV metadata first
    df_lazy = pl.scan_csv(str(csv_path), ignore_errors=True)
    columns = df_lazy.columns
    
    required = ["date", "symbol", "side", "quantity"]
    missing = [k for k in required if m.get(k) not in columns]
    if missing:
        msg = f"Missing required columns in CSV per mapping: {missing}"
        logger.error(msg)
        raise ValueError(msg)
    
    # Read full CSV for chunking
    df = pl.read_csv(str(csv_path), ignore_errors=True)
    total_rows = len(df)
    
    # Deduplicate within-file by identity key (profile_id, symbol, trade_date[, time])
    seen_keys: set[tuple[int, str, date, str | None]] = set()
    all_rows_to_insert: list[dict] = []
    all_symbols: set[str] = set()
    total_errors = 0
    
    # Process in parallel chunks
    chunks = []
    for i in range(0, total_rows, chunk_size):
        chunk = df[i:min(i + chunk_size, total_rows)]
        chunks.append(chunk)
    
    logger.info(f"Processing {len(chunks)} chunks of ~{chunk_size} rows each")
    
    # Use ThreadPoolExecutor for I/O bound processing
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        process_func = partial(process_csv_chunk, mapping=mapping, profile_id=profile_id)
        
        # Submit all chunks
        future_to_chunk = {
            executor.submit(process_func, chunk, seen_keys): i 
            for i, chunk in enumerate(chunks)
        }
        
        # Collect results
        for future in as_completed(future_to_chunk):
            chunk_idx = future_to_chunk[future]
            try:
                rows, symbols, errors, new_seen_keys = future.result()
                all_rows_to_insert.extend(rows)
                all_symbols.update(symbols)
                total_errors += errors
                seen_keys.update(new_seen_keys)
                logger.debug(f"Processed chunk {chunk_idx}: {len(rows)} rows, {errors} errors")
            except Exception as e:
                logger.error(f"Failed to process chunk {chunk_idx}: {e}")
    
    # Ensure symbols exist
    symbol_dtos = [SymbolIn(symbol=s) for s in all_symbols]

    summary = {"inserted": 0, "duplicates_skipped": 0, "errors": total_errors}

    if dry_run:
        logger.info(
            f"dry_run | profile={profile_id} | rows={len(all_rows_to_insert)} | "
            f"symbols={len(all_symbols)} | errors={total_errors}"
        )
        return summary

    # Persist - batch insert for better performance
    logger.info(f"Upserting {len(symbol_dtos)} symbols")
    upsert_symbols_dto(symbol_dtos)
    
    # Insert trades in batches
    batch_size = 1000
    total_inserted = 0
    for i in range(0, len(all_rows_to_insert), batch_size):
        batch = all_rows_to_insert[i:i + batch_size]
        inserted = insert_trades_ignore_duplicates_dicts(batch)
        total_inserted += inserted
        logger.debug(f"Inserted batch {i//batch_size + 1}: {inserted} rows")
    
    summary["inserted"] = total_inserted
    summary["duplicates_skipped"] = len(all_rows_to_insert) - total_inserted
    logger.info(
        f"ingest_done | profile={profile_id} | inserted={total_inserted} | "
        f"duplicates={summary['duplicates_skipped']} | errors={total_errors}"
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
