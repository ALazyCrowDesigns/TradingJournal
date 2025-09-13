import time
from datetime import date, timedelta

from journal.db.dao import insert_trades_dto, upsert_symbols_dto
from journal.dto import SymbolIn, TradeIn


def test_insert_10k_fast() -> None:
    # Create enough symbols for unique combinations
    syms = [SymbolIn(symbol=f"BENCH{i:04d}") for i in range(100)]
    upsert_symbols_dto(syms)

    start = date(2024, 1, 1)
    rows = []
    for i in range(10000):
        # Make each trade unique by using different combinations
        profile_id = 1
        d = start + timedelta(days=i // 100)  # 100 trades per day
        symbol = f"BENCH{i % 100:04d}"  # Cycle through 100 symbols
        rows.append(TradeIn(profile_id=profile_id, trade_date=d, symbol=symbol, side="LONG"))

    t0 = time.time()
    insert_trades_dto(rows)
    elapsed = time.time() - t0
    print(f"Inserted 10k trades in {elapsed:.2f}s")
    assert elapsed < 5.0  # adjust threshold for your machine
