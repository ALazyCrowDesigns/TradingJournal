"""
Service for importing trade data from CSV files
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from functools import partial
from pathlib import Path
from typing import Any

import polars as pl
import structlog

from ..dto import SymbolIn, TradeIn
from ..repositories.symbol import SymbolRepository
from ..repositories.trade import TradeRepository


@dataclass(frozen=True)
class ImportMapping:
    """CSV column mapping configuration"""

    columns: dict[str, str]
    date_formats: list[str]
    trim_symbols: bool = True
    uppercase_symbols: bool = True


@dataclass
class ImportResult:
    """Result of import operation"""

    inserted: int = 0
    duplicates_skipped: int = 0
    errors: int = 0
    error_details: list[str] = None

    def __post_init__(self) -> None:
        if self.error_details is None:
            self.error_details = []


class ImportService:
    """Service for importing trade data with progress tracking"""

    def __init__(
        self,
        trade_repository: TradeRepository,
        symbol_repository: SymbolRepository,
        logger: structlog.BoundLogger | None = None,
    ) -> None:
        self._trade_repo = trade_repository
        self._symbol_repo = symbol_repository
        self._logger = logger or structlog.get_logger()

    def load_mapping(self, mapping_path: str | Path) -> ImportMapping:
        """Load column mapping from JSON file"""
        data = json.loads(Path(mapping_path).read_text(encoding="utf-8"))
        return ImportMapping(
            columns=data["columns"],
            date_formats=data.get("date_formats", ["%Y-%m-%d"]),
            trim_symbols=bool(data.get("trim_symbols", True)),
            uppercase_symbols=bool(data.get("uppercase_symbols", True)),
        )

    def import_csv(
        self,
        csv_path: str | Path,
        profile_id: int,
        mapping: ImportMapping | str | Path,
        dry_run: bool = False,
        chunk_size: int = 5000,
        max_workers: int = 4,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ImportResult:
        """
        Import trades from CSV file

        Args:
            csv_path: Path to CSV file
            profile_id: Profile ID for trades
            mapping: ImportMapping or path to mapping JSON
            dry_run: If True, validate without inserting
            chunk_size: Number of rows per chunk
            max_workers: Number of parallel workers
            progress_callback: Callback for progress updates (current, total)
        """
        # Load mapping if path provided
        if isinstance(mapping, str | Path):
            mapping = self.load_mapping(mapping)

        # Validate CSV structure
        df_lazy = pl.scan_csv(str(csv_path), ignore_errors=True)
        columns = df_lazy.columns

        required = ["date", "symbol", "side", "quantity"]
        missing = [k for k in required if mapping.columns.get(k) not in columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        # Read full CSV
        df = pl.read_csv(str(csv_path), ignore_errors=True)
        total_rows = len(df)

        self._logger.info(
            "import_started", csv_path=str(csv_path), total_rows=total_rows, profile_id=profile_id
        )

        # Process in chunks
        result = ImportResult()
        seen_keys: set[tuple[int, str, date, str | None]] = set()
        all_trades: list[dict] = []
        all_symbols: set[str] = set()

        chunks = self._create_chunks(df, chunk_size)
        processed_rows = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            process_func = partial(
                self._process_chunk, mapping=mapping, profile_id=profile_id, seen_keys=seen_keys
            )

            future_to_chunk = {
                executor.submit(process_func, chunk): i for i, chunk in enumerate(chunks)
            }

            for future in as_completed(future_to_chunk):
                chunk_idx = future_to_chunk[future]
                try:
                    chunk_result = future.result()
                    all_trades.extend(chunk_result["trades"])
                    all_symbols.update(chunk_result["symbols"])
                    result.errors += chunk_result["errors"]
                    result.error_details.extend(chunk_result["error_details"])
                    seen_keys.update(chunk_result["seen_keys"])

                    processed_rows += len(chunks[chunk_idx])
                    if progress_callback:
                        progress_callback(processed_rows, total_rows)

                    self._logger.debug(
                        "chunk_processed",
                        chunk=chunk_idx,
                        trades=len(chunk_result["trades"]),
                        errors=chunk_result["errors"],
                    )

                except Exception as e:
                    self._logger.error("chunk_failed", chunk=chunk_idx, error=str(e))
                    result.errors += len(chunks[chunk_idx])

        if dry_run:
            result.inserted = len(all_trades)
            self._logger.info(
                "dry_run_complete", would_insert=result.inserted, errors=result.errors
            )
            return result

        # Persist data
        try:
            # Ensure symbols exist
            symbol_dtos = [SymbolIn(symbol=s) for s in all_symbols]
            self._symbol_repo.upsert_many(symbol_dtos)

            # Insert trades in batches
            batch_size = 1000
            total_inserted = 0

            for i in range(0, len(all_trades), batch_size):
                batch = all_trades[i : i + batch_size]
                inserted = self._trade_repo.insert_ignore_duplicates(batch)
                total_inserted += inserted

                if progress_callback:
                    progress_callback(total_rows + i + len(batch), total_rows + len(all_trades))

            result.inserted = total_inserted
            result.duplicates_skipped = len(all_trades) - total_inserted

            self._logger.info(
                "import_complete",
                inserted=result.inserted,
                duplicates=result.duplicates_skipped,
                errors=result.errors,
            )

        except Exception as e:
            self._logger.error("import_failed", error=str(e))
            raise

        return result

    def _create_chunks(self, df: pl.DataFrame, chunk_size: int) -> list[pl.DataFrame]:
        """Split dataframe into chunks"""
        chunks = []
        for i in range(0, len(df), chunk_size):
            chunk = df[i : min(i + chunk_size, len(df))]
            chunks.append(chunk)
        return chunks

    def _process_chunk(
        self,
        chunk_df: pl.DataFrame,
        mapping: ImportMapping,
        profile_id: int,
        seen_keys: set[tuple[int, str, date, str | None]],
    ) -> dict:
        """Process a single chunk of data"""
        _ = mapping.columns  # m was unused in this context
        trades = []
        symbols = set()
        errors = 0
        error_details = []
        local_seen_keys = seen_keys.copy()

        for row in chunk_df.iter_rows(named=True):
            try:
                # Parse and validate row
                trade_data = self._parse_trade_row(row, mapping, profile_id)

                # Check for duplicates
                identity = (
                    profile_id,
                    trade_data["symbol"],
                    trade_data["trade_date"],
                    trade_data.get("time"),
                )

                if identity in local_seen_keys:
                    continue

                local_seen_keys.add(identity)
                symbols.add(trade_data["symbol"])

                # Validate with DTO
                trade_dto = TradeIn(**trade_data)
                trades.append(trade_dto.model_dump())

            except Exception as e:
                errors += 1
                error_details.append(f"Row error: {e} | Data: {row}")
                self._logger.debug("row_parse_error", error=str(e), row=row)

        return {
            "trades": trades,
            "symbols": symbols,
            "errors": errors,
            "error_details": error_details,
            "seen_keys": local_seen_keys,
        }

    def _parse_trade_row(self, row: dict, mapping: ImportMapping, profile_id: int) -> dict:
        """Parse a single trade row"""
        m = mapping.columns

        # Symbol
        raw_symbol = row.get(m["symbol"])
        if not raw_symbol:
            raise ValueError("Empty symbol")

        symbol = self._normalize_symbol(raw_symbol, mapping)
        if not symbol:
            raise ValueError("Invalid symbol after normalization")

        # Date
        trade_date = self._parse_date(row.get(m["date"]), mapping.date_formats)
        if not trade_date:
            raise ValueError(f"Invalid date: {row.get(m['date'])}")

        # Optional time
        time_val = None
        if "time" in m and m["time"] in row:
            time_val = str(row.get(m["time"])) if row.get(m["time"]) else None

        # Numeric fields
        def to_float(x: Any) -> float | None:
            if x is None:
                return None
            try:
                return float(str(x).replace(",", ""))
            except Exception:
                return None

        # Build trade data
        return {
            "profile_id": profile_id,
            "trade_date": trade_date,
            "symbol": symbol,
            "side": str(row.get(m.get("side", ""), "") or "")[:5],
            "size": int(float(row.get(m.get("quantity", ""), 0) or 0)),
            "entry": to_float(row.get(m.get("entry", ""))),
            "exit": to_float(row.get(m.get("exit", ""))),
            "pnl": to_float(row.get(m.get("pnl", ""))),
            "return_pct": to_float(row.get(m.get("return_pct", ""))),
            "notes": str(row.get(m.get("notes", ""), "") or "")[:500],
            "time": time_val,
        }

    def _normalize_symbol(self, symbol: str, mapping: ImportMapping) -> str:
        """Normalize symbol according to mapping rules"""
        s = symbol or ""
        if mapping.trim_symbols:
            s = s.strip()
        if mapping.uppercase_symbols:
            s = s.upper()
        return s

    def _parse_date(self, value: Any, formats: list[str]) -> date | None:
        """Parse date with multiple format attempts"""
        if value is None:
            return None

        s = str(value).strip()
        for fmt in formats:
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                continue
        return None
