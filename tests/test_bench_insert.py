import time
from datetime import date, timedelta

from journal.db.dao import insert_trades_dto, upsert_symbols_dto
from journal.dto import SymbolIn, TradeIn


def test_insert_10k_fast() -> None:
    # Clean up any existing BENCH test data from previous runs
    from journal.db.dao import session_scope
    from journal.db.models import Symbol, Trade

    with session_scope() as s:
        # Remove existing BENCH trades and symbols
        s.query(Trade).filter(Trade.symbol.like("BENCH%")).delete(synchronize_session=False)
        s.query(Symbol).filter(Symbol.symbol.like("BENCH%")).delete(synchronize_session=False)

    # Create enough symbols for unique combinations
    syms = [SymbolIn(symbol=f"BENCH{i:04d}") for i in range(100)]
    upsert_symbols_dto(syms)

    start = date(2024, 1, 1)
    rows = []
    for i in range(10000):
        # Make each trade unique by ensuring no duplicate (profile_id, symbol, trade_date)
        # combinations
        profile_id = 1
        # Each symbol gets one trade per day, spread across 100 days
        symbol_idx = i % 100
        day_offset = i // 100
        d = start + timedelta(days=day_offset)
        symbol = f"BENCH{symbol_idx:04d}"
        rows.append(TradeIn(profile_id=profile_id, trade_date=d, symbol=symbol, side="LONG"))

    t0 = time.time()
    insert_trades_dto(rows)
    elapsed = time.time() - t0
    print(f"Inserted 10k trades in {elapsed:.2f}s")
    assert elapsed < 5.0  # adjust threshold for your machine
