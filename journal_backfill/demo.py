"""Demonstration script for the backfill service."""

import asyncio
import os
from datetime import date, timedelta
from pathlib import Path

from .backfill_async import BackfillOrchestrator
from .config import BackfillConfig
from .models import BackfillRequest


async def demo_programmatic_usage() -> None:
    """Demonstrate programmatic usage of the backfill service."""
    print("=== Trading Journal Backfill Service Demo ===\n")
    
    # Set API key if not already set
    if not os.getenv("POLYGON_API_KEY"):
        os.environ["POLYGON_API_KEY"] = "QjD_Isd8mrkdv85s30J0r7qeGcApznGf"
        print("✓ Using provided Polygon API key")
    
    try:
        # Configure the service
        config = BackfillConfig.from_env()
        print(f"✓ Configuration loaded:")
        print(f"  - Concurrency: {config.max_concurrent_requests}")
        print(f"  - Batch size: {config.batch_size}")
        print(f"  - Database: {config.db_url}")
        
        # Create orchestrator
        orchestrator = BackfillOrchestrator(config)
        print("✓ Orchestrator created")
        
        # Define sample requests for recent trading days
        today = date.today()
        # Go back to find recent weekdays (avoid weekends)
        sample_date = today - timedelta(days=1)
        while sample_date.weekday() >= 5:  # Skip weekends
            sample_date -= timedelta(days=1)
        
        requests = [
            BackfillRequest("AAPL", sample_date),
            BackfillRequest("MSFT", sample_date),
            BackfillRequest("GOOGL", sample_date),
        ]
        
        print(f"✓ Created {len(requests)} backfill requests for {sample_date}")
        
        # Run backfill
        print("\n🚀 Starting backfill process...")
        summary = await orchestrator.backfill_requests(requests)
        
        print(f"\n✅ Backfill completed!")
        print(f"📊 Summary:")
        print(f"  - Total requests: {summary['total_requests']}")
        print(f"  - Successful: {summary['successful']}")
        print(f"  - Failed: {summary['failed']}")
        print(f"  - Rows written: {summary['rows_written']}")
        
        # Show database stats
        db_count = orchestrator.db.count_records()
        symbols_count = orchestrator.db.get_symbols_count()
        print(f"  - Total records in DB: {db_count}")
        print(f"  - Distinct symbols in DB: {symbols_count}")
        
        return summary
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        raise


def create_sample_csv() -> Path:
    """Create a sample CSV file for CLI demonstration."""
    csv_path = Path("demo_pairs.csv")
    
    # Get a recent weekday
    today = date.today()
    sample_date = today - timedelta(days=1)
    while sample_date.weekday() >= 5:  # Skip weekends
        sample_date -= timedelta(days=1)
    
    # Create CSV content
    content = "symbol,trade_date\n"
    symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA"]
    
    for symbol in symbols:
        content += f"{symbol},{sample_date.isoformat()}\n"
    
    csv_path.write_text(content, encoding="utf-8")
    print(f"✓ Created sample CSV: {csv_path}")
    print(f"  - Date: {sample_date}")
    print(f"  - Symbols: {', '.join(symbols)}")
    
    return csv_path


async def main() -> None:
    """Main demo function."""
    print("Choose demo mode:")
    print("1. Programmatic usage (recommended)")
    print("2. Create sample CSV for CLI usage")
    
    choice = input("Enter choice (1 or 2): ").strip()
    
    if choice == "1":
        await demo_programmatic_usage()
    elif choice == "2":
        csv_path = create_sample_csv()
        print(f"\n📋 Next steps:")
        print(f"1. Run: py -3.13 -m journal_backfill.backfill_async --pairs-csv {csv_path}")
        print(f"2. Check the results in trading_journal.db")
    else:
        print("Invalid choice. Please run again and choose 1 or 2.")


if __name__ == "__main__":
    asyncio.run(main())
