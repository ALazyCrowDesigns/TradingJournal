from datetime import date

from journal.db.dao import get_close_from_db, upsert_daily_prices, upsert_symbols
from journal.services.backfill import _prev_day


def test_prev_close_db_first() -> None:
    # Insert a symbol first (to satisfy foreign key constraint)
    upsert_symbols([{"symbol": "ZZZZ", "name": "Test Symbol"}])

    # Insert a previous day close in the DB, then set on trade day
    rows = [
        {"symbol": "ZZZZ", "date": date(2024, 1, 1), "o": 1, "h": 2, "low": 0.5, "c": 1.25, "v": 10}
    ]
    upsert_daily_prices(rows)
    pc = get_close_from_db("ZZZZ", _prev_day(date(2024, 1, 2)))
    assert pc == 1.25
