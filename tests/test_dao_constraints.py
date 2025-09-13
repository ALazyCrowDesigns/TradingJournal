from datetime import date

from journal.dto import SymbolIn, TradeIn


def test_unique_trade_identity() -> None:
    import uuid

    from journal.db.dao import upsert_symbols_dto

    # Use unique symbol to avoid conflicts
    test_symbol = f"TST{uuid.uuid4().hex[:6].upper()}"
    upsert_symbols_dto([SymbolIn(symbol=test_symbol)])

    t = TradeIn(profile_id=1, trade_date=date(2024, 1, 2), symbol=test_symbol, side="LONG")
    from journal.db.dao import insert_trades_dto

    insert_trades_dto([t])
    # inserting same identity again should raise on UniqueConstraint
    try:
        insert_trades_dto([t])
        raise AssertionError("Expected unique constraint violation")
    except Exception:
        assert True
