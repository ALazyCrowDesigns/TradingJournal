from datetime import date

from journal.db.dao import (
    analytics_summary,
    insert_trades_ignore_duplicates_dicts,
    upsert_daily_prices,
    upsert_symbols_dto,
)
from journal.dto import SymbolIn, TradeIn


def test_gap_range_closechg_and_analytics_smoke() -> None:
    # First create the symbol
    upsert_symbols_dto([SymbolIn(symbol="DERI")])

    # Seed prices for 2 days
    upsert_daily_prices(
        [
            {
                "symbol": "DERI",
                "date": date(2024, 1, 1),
                "o": 10,
                "h": 12,
                "low": 9,
                "c": 11,
                "v": 1000,
            },
            {
                "symbol": "DERI",
                "date": date(2024, 1, 2),
                "o": 11,
                "h": 13,
                "low": 10,
                "c": 12,
                "v": 1100,
            },
        ]
    )
    # prev_close for 1/2 is c(1/1)=11; insert one trade on 1/2
    trade_data = TradeIn(
        profile_id=1,
        trade_date=date(2024, 1, 2),
        symbol="DERI",
        side="LONG",
        pnl=5.0,
        prev_close=11.0,
    )
    insert_trades_ignore_duplicates_dicts([trade_data.model_dump()])

    s = analytics_summary(filters={"symbol": "DERI"})
    assert s["trades"] >= 1
    assert "hit_rate" in s
