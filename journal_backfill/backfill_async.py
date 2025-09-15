"""Async orchestrator and CLI for backfill operations."""

import asyncio
import csv
import logging
import sys
from argparse import ArgumentParser
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .compute import compute_backfill_rows, validate_backfill_row
from .config import BackfillConfig
from .db import BackfillDatabase
from .models import BackfillRequest, BackfillRow
from .polygon_client import PolygonClient, PolygonAPIError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("backfill.log", mode="a"),
    ],
)
logger = logging.getLogger("backfill_async")


class BackfillOrchestrator:
    """Orchestrates async backfill operations with concurrency control."""
    
    def __init__(self, config: BackfillConfig) -> None:
        self.config = config
        self.db = BackfillDatabase(config)
        self._semaphore = asyncio.Semaphore(config.max_concurrent_requests)
        
    async def backfill_requests(self, requests: Iterable[BackfillRequest]) -> dict[str, Any]:
        """Backfill data for multiple symbol-date requests.
        
        Args:
            requests: Iterable of BackfillRequest objects
            
        Returns:
            Summary statistics dictionary
        """
        request_list = list(requests)
        total_requests = len(request_list)
        
        if total_requests == 0:
            logger.info("No requests to process")
            return {"total_requests": 0, "successful": 0, "failed": 0, "rows_written": 0}
        
        logger.info(f"Starting backfill for {total_requests} requests")
        
        # Ensure database tables exist
        self.db.create_tables()
        
        # Process requests concurrently
        async with PolygonClient(self.config) as client:
            tasks = [
                self._process_request_with_semaphore(client, request) 
                for request in request_list
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Separate successful results from failures
        successful_rows = []
        failed_count = 0
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Failed to process {request_list[i]}: {result}")
                failed_count += 1
            elif result is not None:
                successful_rows.append(result)
        
        # Write successful results to database in batches
        rows_written = 0
        if successful_rows:
            rows_written = self.db.batch_upsert_chunked(successful_rows)
            logger.info(f"Wrote {rows_written} rows to database")
        
        # Log summary
        successful_count = len(successful_rows)
        logger.info(
            f"Backfill complete: {successful_count}/{total_requests} successful, "
            f"{failed_count} failed, {rows_written} rows written"
        )
        
        return {
            "total_requests": total_requests,
            "successful": successful_count,
            "failed": failed_count,
            "rows_written": rows_written,
        }
    
    async def _process_request_with_semaphore(
        self, client: PolygonClient, request: BackfillRequest
    ) -> BackfillRow | None:
        """Process a single request with semaphore-controlled concurrency."""
        async with self._semaphore:
            return await self._process_request(client, request)
    
    async def _process_request(
        self, client: PolygonClient, request: BackfillRequest
    ) -> BackfillRow | None:
        """Process a single backfill request.
        
        Args:
            client: Polygon API client
            request: Backfill request to process
            
        Returns:
            BackfillRow if successful, None if failed
        """
        try:
            # Fetch data from Polygon API
            bars_30min, daily_bar = await client.fetch_symbol_data(
                request.symbol, request.trade_date
            )
            
            # Compute metrics
            row = compute_backfill_rows([
                (request.symbol, request.trade_date, bars_30min, daily_bar)
            ])[0]
            
            # Validate the computed row
            validation_issues = validate_backfill_row(row)
            if validation_issues:
                logger.warning(f"Validation issues for {request}: {validation_issues}")
                # Continue anyway - validation is for debugging
            
            logger.debug(f"Successfully processed {request}")
            return row
            
        except PolygonAPIError as e:
            logger.error(f"API error processing {request}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error processing {request}: {e}")
            return None


def parse_pairs_csv(csv_path: Path) -> list[BackfillRequest]:
    """Parse CSV file containing symbol-date pairs.
    
    Expected CSV format:
    symbol,trade_date
    AAPL,2024-01-15
    MSFT,2024-01-15
    
    Args:
        csv_path: Path to CSV file
        
    Returns:
        List of BackfillRequest objects
    """
    requests = []
    
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        
        for row_num, row in enumerate(reader, start=2):  # Start at 2 for header
            try:
                symbol = row["symbol"].strip().upper()
                trade_date_str = row["trade_date"].strip()
                
                # Parse date
                trade_date = datetime.strptime(trade_date_str, "%Y-%m-%d").date()
                
                requests.append(BackfillRequest(symbol=symbol, trade_date=trade_date))
                
            except (KeyError, ValueError) as e:
                logger.error(f"Invalid row {row_num} in CSV: {row} - {e}")
                continue
    
    logger.info(f"Parsed {len(requests)} requests from {csv_path}")
    return requests


def create_sample_pairs_csv(csv_path: Path, symbols: list[str], trade_date: date) -> None:
    """Create a sample pairs CSV file for testing.
    
    Args:
        csv_path: Path where to create the CSV file
        symbols: List of symbols to include
        trade_date: Trade date to use for all symbols
    """
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["symbol", "trade_date"])
        
        for symbol in symbols:
            writer.writerow([symbol, trade_date.isoformat()])
    
    logger.info(f"Created sample CSV with {len(symbols)} symbols at {csv_path}")


async def main_async(args: Any) -> None:
    """Main async function."""
    try:
        # Load configuration
        config = BackfillConfig.from_env()
        
        # Override config with CLI arguments
        if args.concurrency:
            config = BackfillConfig(
                **{**config.__dict__, "max_concurrent_requests": args.concurrency}
            )
        if args.batch_size:
            config = BackfillConfig(
                **{**config.__dict__, "batch_size": args.batch_size}
            )
        if args.db:
            db_url = f"sqlite:///{args.db}"
            config = BackfillConfig(
                **{**config.__dict__, "db_url": db_url}
            )
        
        # Create orchestrator
        orchestrator = BackfillOrchestrator(config)
        
        # Handle different command modes
        if args.create_sample:
            # Create sample CSV
            symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA"]
            sample_date = datetime.now().date()
            create_sample_pairs_csv(Path(args.create_sample), symbols, sample_date)
            return
        
        # Parse requests from CSV
        if not args.pairs_csv:
            raise ValueError("--pairs-csv is required (or use --create-sample)")
        
        csv_path = Path(args.pairs_csv)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        
        requests = parse_pairs_csv(csv_path)
        
        if not requests:
            logger.error("No valid requests found in CSV")
            return
        
        # Run backfill
        start_time = datetime.now()
        summary = await orchestrator.backfill_requests(requests)
        end_time = datetime.now()
        
        # Print summary
        duration = (end_time - start_time).total_seconds()
        logger.info(f"Backfill completed in {duration:.2f} seconds")
        logger.info(f"Summary: {summary}")
        
        if summary["failed"] > 0:
            sys.exit(1)  # Exit with error if any requests failed
        
    except Exception as e:
        logger.error(f"Backfill failed: {e}")
        sys.exit(1)


def main() -> None:
    """CLI entry point."""
    parser = ArgumentParser(description="Async backfill service for trading journal")
    
    parser.add_argument(
        "--pairs-csv", 
        type=str,
        help="Path to CSV file with symbol,trade_date pairs"
    )
    parser.add_argument(
        "--db", 
        type=str, 
        help="Path to SQLite database file (default: trading_journal.db)"
    )
    parser.add_argument(
        "--concurrency", 
        type=int, 
        help="Max concurrent requests (default: 12)"
    )
    parser.add_argument(
        "--batch-size", 
        type=int, 
        help="Database batch size (default: 300)"
    )
    parser.add_argument(
        "--create-sample",
        type=str,
        help="Create sample pairs CSV file at specified path and exit"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)"
    )
    
    args = parser.parse_args()
    
    # Set log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # Run async main
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
