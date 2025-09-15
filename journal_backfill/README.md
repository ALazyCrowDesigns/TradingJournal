# Trading Journal Backfill Service

A high-performance async service for backfilling trading journal data from Polygon.io. Computes premarket/after-hours highs/lows and daily OHLC data with volume for trading analysis.

## Features

- **High Throughput**: Async HTTP with HTTP/2, connection reuse, and configurable concurrency
- **Robust Retry Logic**: Exponential backoff with jitter for handling rate limits and server errors
- **Timezone Aware**: Proper ET to UTC conversion for accurate session windows
- **Efficient Database Operations**: Batch UPSERT operations with SQLite WAL mode
- **Session-Based Metrics**: Separate premarket (04:00-09:30 ET) and after-hours (16:00-20:00 ET) calculations
- **Data Validation**: Built-in validation for computed metrics

## Data Computed

For each (symbol, trade_date) pair:

- **Premarket High/Low**: From 30-minute aggregates in [04:00, 09:30) ET
- **After-hours High/Low**: From 30-minute aggregates in [16:00, 20:00) ET  
- **Daily OHLC**: Open, high of day, low of day from 1-day aggregate
- **Daily Volume**: Total daily volume in shares (no extended-hours volume)

## Installation

### Prerequisites

- Python 3.13+ [[memory:8890629]]
- Polygon.io API key (free tier available)

### Setup

1. **Install the package**:
   ```bash
   pip install -e .
   ```

2. **Set up environment variables**:
   
   Since .env files are restricted, set the environment variable directly:
   ```bash
   # Windows PowerShell
   $env:POLYGON_API_KEY = "your_polygon_api_key_here"
   
   # Windows Command Prompt  
   set POLYGON_API_KEY=your_polygon_api_key_here
   
   # Linux/Mac
   export POLYGON_API_KEY="your_polygon_api_key_here"
   ```
   
   Or use the provided API key: `QjD_Isd8mrkdv85s30J0r7qeGcApznGf`

3. **Verify database setup**:
   ```bash
   py -3.13 -c "from journal_backfill.db import BackfillDatabase; from journal_backfill.config import BackfillConfig; db = BackfillDatabase(BackfillConfig.from_env()); db.create_tables(); print('Database ready')"
   ```

## Usage

### Command Line Interface

#### Create Sample Data
```bash
py -3.13 -m journal_backfill.backfill_async --create-sample pairs.csv
```

#### Run Backfill
```bash
py -3.13 -m journal_backfill.backfill_async --pairs-csv pairs.csv --db trading_journal.db --concurrency 12 --batch-size 300
```

#### CLI Options
- `--pairs-csv`: Path to CSV file with symbol,trade_date pairs (required)
- `--db`: Path to SQLite database file (default: trading_journal.db)
- `--concurrency`: Max concurrent requests (default: 12)
- `--batch-size`: Database batch size (default: 300)
- `--create-sample`: Create sample pairs CSV and exit
- `--log-level`: Logging level (DEBUG, INFO, WARNING, ERROR)

### CSV Format

The pairs CSV should have the following format:
```csv
symbol,trade_date
AAPL,2024-01-15
MSFT,2024-01-15
GOOGL,2024-01-16
TSLA,2024-01-16
```

### Programmatic Usage

```python
import asyncio
from datetime import date
from journal_backfill.config import BackfillConfig
from journal_backfill.backfill_async import BackfillOrchestrator
from journal_backfill.models import BackfillRequest

async def main():
    # Configure the service
    config = BackfillConfig.from_env()
    
    # Create orchestrator
    orchestrator = BackfillOrchestrator(config)
    
    # Define requests
    requests = [
        BackfillRequest("AAPL", date(2024, 1, 15)),
        BackfillRequest("MSFT", date(2024, 1, 15)),
        BackfillRequest("GOOGL", date(2024, 1, 16)),
    ]
    
    # Run backfill
    summary = await orchestrator.backfill_requests(requests)
    print(f"Backfill complete: {summary}")

# Run the async function
asyncio.run(main())
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POLYGON_API_KEY` | (required) | Your Polygon.io API key |
| `BACKFILL_CONCURRENCY` | 12 | Maximum concurrent API requests |
| `BACKFILL_BATCH_SIZE` | 300 | Database batch size for inserts |
| `BACKFILL_TIMEOUT` | 30 | HTTP request timeout in seconds |
| `BACKFILL_DB_URL` | `sqlite:///trading_journal.db` | Database connection URL |

### Session Windows (America/New_York)

- **Premarket**: 04:00 - 09:30 ET
- **Regular**: 09:30 - 16:00 ET (used for fallback only)
- **After-hours**: 16:00 - 20:00 ET

## Database Schema

The service creates a `backfill_data` table with the following schema:

```sql
CREATE TABLE IF NOT EXISTS backfill_data (
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    pre_high REAL,
    pre_low REAL,
    open_price REAL,
    hod REAL,
    lod REAL,
    ah_high REAL,
    ah_low REAL,
    day_volume INTEGER,
    PRIMARY KEY (symbol, trade_date)
);
```

## API Endpoints Used

1. **30-minute aggregates**: 
   - `GET /v2/aggs/ticker/{ticker}/range/30/minute/{fromMs}/{toMs}`
   - Covers full extended hours window (04:00-20:00 ET)

2. **Daily aggregate**:
   - `GET /v2/aggs/ticker/{ticker}/range/1/day/{YYYY-MM-DD}/{YYYY-MM-DD}`
   - Authoritative source for OHLC and volume

Both endpoints use `adjusted=false` to match trade-day prints.

## Performance

- **Concurrency**: Default 12 concurrent requests (configurable)
- **Connection Reuse**: Single HTTP/2 client with connection pooling
- **Batch Processing**: Database operations in configurable batches (default 300)
- **Retry Logic**: Exponential backoff with jitter for robust error handling
- **SQLite Optimization**: WAL mode, memory temp storage, optimized pragmas

## Error Handling

- **Rate Limiting**: Automatic retry with backoff for 429 responses
- **Server Errors**: Retry on 5xx responses with exponential backoff
- **Data Validation**: Built-in validation for computed metrics
- **Partial Failures**: Continue processing other requests if some fail
- **Comprehensive Logging**: Detailed logs for debugging and monitoring

## Logging

Logs are written to both stdout and `backfill.log` file with timestamps and structured information:

- Request processing progress
- API errors and retries
- Data validation warnings
- Performance metrics
- Summary statistics

## Examples

### Basic Backfill
```bash
# Create sample data
py -3.13 -m journal_backfill.backfill_async --create-sample test_pairs.csv

# Run backfill
py -3.13 -m journal_backfill.backfill_async --pairs-csv test_pairs.csv
```

### High Concurrency
```bash
py -3.13 -m journal_backfill.backfill_async --pairs-csv large_dataset.csv --concurrency 20 --batch-size 500
```

### Custom Database
```bash
py -3.13 -m journal_backfill.backfill_async --pairs-csv pairs.csv --db /path/to/custom.db
```

## Troubleshooting

### Common Issues

1. **API Key Not Found**
   ```
   ValueError: POLYGON_API_KEY environment variable is required
   ```
   Solution: Set the `POLYGON_API_KEY` environment variable

2. **Rate Limiting**
   ```
   PolygonAPIError: Rate limited: 429
   ```
   Solution: Reduce concurrency with `--concurrency 5` or use a paid Polygon plan

3. **Database Locked**
   ```
   sqlite3.OperationalError: database is locked
   ```
   Solution: Ensure no other processes are using the database file

4. **Import Errors**
   ```
   ModuleNotFoundError: No module named 'journal_backfill'
   ```
   Solution: Install in development mode with `pip install -e .`

### Debug Mode

Enable debug logging for detailed information:
```bash
py -3.13 -m journal_backfill.backfill_async --pairs-csv pairs.csv --log-level DEBUG
```

## License

This project is part of the Trading Journal application.
