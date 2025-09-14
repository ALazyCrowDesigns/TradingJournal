"""
Simple CSV import service for trading journal data
Handles the specific CSV format with columns like Status, Symbol, Size, etc.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import structlog

    HAS_STRUCTLOG = True
except ImportError:
    import logging

    HAS_STRUCTLOG = False

from ..db.dao import insert_trades_ignore_duplicates_dicts, upsert_symbols_dto
from ..dto import SymbolIn, TradeIn


@dataclass
class ImportResult:
    """Result of CSV import operation"""

    total_rows: int = 0
    imported: int = 0
    updated: int = 0
    duplicates_skipped: int = 0
    errors: int = 0
    error_details: list[str] = None

    def __post_init__(self) -> None:
        if self.error_details is None:
            self.error_details = []


class CSVImportService:
    """Simple service for importing CSV trade data"""

    def __init__(self, logger=None) -> None:
        if logger:
            self._logger = logger
        elif HAS_STRUCTLOG:
            self._logger = structlog.get_logger(__name__)
        else:
            self._logger = logging.getLogger(__name__)

    def import_csv(
        self,
        csv_path: str | Path,
        profile_id: int = 1,
        progress_callback: Callable[[int, int], None] | None = None,
        dry_run: bool = False,
    ) -> ImportResult:
        """
        Import trades from CSV file

        Args:
            csv_path: Path to the CSV file
            profile_id: Profile ID for the trades (default: 1)
            progress_callback: Optional callback for progress updates (current, total)
            dry_run: If True, validate without inserting into database

        Returns:
            ImportResult with statistics about the import operation
        """
        csv_path = Path(csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        if HAS_STRUCTLOG:
            self._logger.info(
                "Starting CSV import", path=str(csv_path), profile_id=profile_id, dry_run=dry_run
            )
        else:
            self._logger.info(
                f"Starting CSV import: path={csv_path}, profile_id={profile_id}, dry_run={dry_run}"
            )

        result = ImportResult()
        trades_to_insert = []
        symbols_to_upsert = set()

        try:
            # Read and process CSV
            with open(csv_path, encoding="utf-8") as file:
                # Detect total rows for progress tracking
                total_rows = sum(1 for _ in file) - 1  # Subtract header row
                result.total_rows = total_rows

                # Reset file pointer and create CSV reader
                file.seek(0)
                reader = csv.DictReader(file)

                for row_num, row in enumerate(reader, 1):
                    try:
                        # Parse the trade row
                        trade_data = self._parse_trade_row(row, profile_id)
                        if trade_data:
                            trades_to_insert.append(trade_data)
                            symbols_to_upsert.add(trade_data["symbol"])

                        # Update progress
                        if progress_callback:
                            progress_callback(row_num, total_rows)

                    except Exception as e:
                        result.errors += 1
                        error_msg = f"Row {row_num}: {str(e)}"
                        result.error_details.append(error_msg)
                        if HAS_STRUCTLOG:
                            self._logger.warning("Row parsing error", row=row_num, error=str(e))
                        else:
                            self._logger.warning(f"Row parsing error: row={row_num}, error={e}")

            if dry_run:
                result.imported = len(trades_to_insert)
                if HAS_STRUCTLOG:
                    self._logger.info(
                        "Dry run completed",
                        would_import=result.imported,
                        errors=result.errors,
                        unique_symbols=len(symbols_to_upsert),
                    )
                else:
                    self._logger.info(
                        f"Dry run completed: would_import={result.imported}, errors={result.errors}, unique_symbols={len(symbols_to_upsert)}"
                    )
                return result

            # Insert symbols first
            if symbols_to_upsert:
                symbol_dtos = [SymbolIn(symbol=s) for s in symbols_to_upsert]
                upsert_symbols_dto(symbol_dtos)
                if HAS_STRUCTLOG:
                    self._logger.debug("Upserted symbols", count=len(symbol_dtos))
                else:
                    self._logger.debug(f"Upserted symbols: count={len(symbol_dtos)}")

            # Insert trades
            if trades_to_insert:
                inserted_count = insert_trades_ignore_duplicates_dicts(trades_to_insert)
                result.imported = inserted_count
                result.duplicates_skipped = len(trades_to_insert) - inserted_count

                if HAS_STRUCTLOG:
                    self._logger.info(
                        "CSV import completed",
                        imported=result.imported,
                        duplicates=result.duplicates_skipped,
                        errors=result.errors,
                        total_processed=len(trades_to_insert),
                    )
                else:
                    self._logger.info(
                        f"CSV import completed: imported={result.imported}, duplicates={result.duplicates_skipped}, errors={result.errors}, total_processed={len(trades_to_insert)}"
                    )

            return result

        except Exception as e:
            if HAS_STRUCTLOG:
                self._logger.error("CSV import failed", error=str(e))
            else:
                self._logger.error(f"CSV import failed: {e}")
            raise

    def _parse_trade_row(self, row: dict[str, str], profile_id: int) -> dict | None:
        """
        Parse a single CSV row into trade data

        Expected CSV columns:
        Status, Symbol, Size, Open Date, Close Date, Open Time, Close Time,
        Entry Price, Exit Price, Return $, Return %, Side, Notes, etc.
        """
        # Skip rows that don't have required data
        symbol = (row.get("Symbol", "") or "").strip().upper()
        if not symbol:
            return None

        # Parse date (format: "Sep 11, 2025")
        open_date_str = (row.get("Open Date", "") or "").strip()
        if not open_date_str:
            return None

        try:
            trade_date = datetime.strptime(open_date_str, "%b %d, %Y").date()
        except ValueError:
            # Try alternative date formats
            try:
                trade_date = datetime.strptime(open_date_str, "%Y-%m-%d").date()
            except ValueError:
                try:
                    trade_date = datetime.strptime(open_date_str, "%m/%d/%Y").date()
                except ValueError:
                    raise ValueError(f"Unable to parse date: {open_date_str}")

        # Parse side (from the Side column, should be SHORT/LONG)
        side = (row.get("Side", "") or "").strip().upper()
        if not side:
            side = "LONG"  # Default fallback

        # Parse size (handle commas and quotes: "30,000" -> 30000)
        size_str = (row.get("Size", "") or "").strip()
        size = 0
        if size_str:
            try:
                # Remove commas and quotes
                size_str = size_str.replace(",", "").replace('"', "")
                size = int(float(size_str)) if size_str else 0
            except (ValueError, TypeError):
                size = 0

        # Parse prices (handle currency format: "$1,368.49" -> 1368.49)
        def parse_currency(value: str) -> float | None:
            if not value:
                return None
            try:
                # Remove $, commas, quotes, and handle negative values
                clean_value = value.replace("$", "").replace(",", "").replace('"', "").strip()
                if clean_value.startswith("(") and clean_value.endswith(")"):
                    # Handle accounting format for negative numbers
                    clean_value = "-" + clean_value[1:-1]
                elif clean_value.startswith("-$"):
                    clean_value = clean_value[2:]  # Remove -$ prefix
                    clean_value = "-" + clean_value
                return float(clean_value) if clean_value else None
            except (ValueError, TypeError):
                return None

        # Parse percentage (handle format: "19.62%" -> 0.1962)
        def parse_percentage(value: str) -> float | None:
            if not value:
                return None
            try:
                clean_value = value.replace("%", "").replace('"', "").strip()
                if clean_value.startswith("(") and clean_value.endswith(")"):
                    # Handle accounting format for negative percentages
                    clean_value = "-" + clean_value[1:-1]
                pct_val = float(clean_value) if clean_value else None
                return pct_val / 100.0 if pct_val is not None else None
            except (ValueError, TypeError):
                return None

        entry_price = parse_currency(row.get("Entry Price", ""))
        exit_price = parse_currency(row.get("Exit Price", ""))
        pnl = parse_currency(row.get("Return $", ""))
        return_pct = parse_percentage(row.get("Return %", ""))

        # Get notes
        notes = (row.get("Notes", "") or "").strip()[:500]  # Limit to 500 chars

        # Create trade data
        trade_data = {
            "profile_id": profile_id,
            "trade_date": trade_date,
            "symbol": symbol,
            "side": side,
            "size": size,
            "entry": entry_price,
            "exit": exit_price,
            "pnl": pnl,
            "return_pct": return_pct,
            "notes": notes,
        }

        # Validate using the DTO
        try:
            trade_dto = TradeIn(**trade_data)
            return trade_dto.model_dump()
        except Exception as e:
            raise ValueError(f"Trade validation failed: {e}")
